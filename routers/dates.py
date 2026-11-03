import json
import random
import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from models.dates import DateSpot, RandomizerPreset
from security import require_auth_api, get_active_profile

dates_router = APIRouter(prefix="/dates", tags=["dates"])

DATE_CATEGORIES = [
    "Food & Drinks",
    "Coffee & Dessert",
    "Activity",
    "Outdoors / Trip",
    "At Home / Cozy"
]

DEFAULT_STARTER_SPOTS = [
    {
        "name": "Sunset Beach Picnic",
        "category": "Outdoors / Trip",
        "location_area": "Beach promenade",
        "vibe_tags": "romantic,breeze,wine",
        "status": "wishlist",
        "added_by": "Tamir",
        "highlight_notes": "Pack cheese, crackers, cold wine and blankets for golden hour."
    },
    {
        "name": "Artisan Gelato Walk",
        "category": "Coffee & Dessert",
        "location_area": "Downtown",
        "vibe_tags": "sweet,casual,stroll",
        "status": "visited",
        "tamir_verdict": "loved",
        "mikush_verdict": "loved",
        "added_by": "Mikush",
        "highlight_notes": "Pistachio and dark chocolate were incredible!"
    },
    {
        "name": "Neapolitan Pizza Night",
        "category": "Food & Drinks",
        "location_area": "Local center",
        "vibe_tags": "cozy,casual,wine",
        "status": "visited",
        "tamir_verdict": "loved",
        "mikush_verdict": "loved",
        "added_by": "Tamir",
        "highlight_notes": "Great sourdough crust and spicy chili oil."
    },
    {
        "name": "Cozy Coffee & Bookshop",
        "category": "Coffee & Dessert",
        "location_area": "Old town",
        "vibe_tags": "quiet,cozy,reading",
        "status": "wishlist",
        "added_by": "Mikush",
        "highlight_notes": "Cute quiet corner with oat lattes and indie books."
    }
]

DEFAULT_STARTER_PRESETS = [
    {
        "title": "Takeout Tonight",
        "options": [
            "Sushi & Edamame 🍣",
            "Neapolitan Pizza 🍕",
            "Thai Curry & Pad Thai 🍜",
            "Smash Burgers & Fries 🍔",
            "Fresh Poke Bowls 🥗",
            "Mexican Burritos & Tacos 🌮"
        ]
    },
    {
        "title": "Evening Vibe",
        "options": [
            "Cozy Movie + Fresh Popcorn 🍿",
            "Walk to Gelato & Stroll 🍨",
            "Board Game Duel 🎲",
            "Cook Dinner Together 🍳",
            "Stargazing / Balcony Drinks 🍷",
            "Massage & Chill Playlist 🕯️"
        ]
    }
]


def ensure_starter_dates(db: Session):
    """Pre-seeds starter date spots and presets if their tables are empty."""
    spot_count = db.query(func.count(DateSpot.id)).scalar()
    now = datetime.datetime.utcnow()
    if spot_count == 0:
        for s in DEFAULT_STARTER_SPOTS:
            db.add(DateSpot(
                name=s["name"],
                category=s.get("category", "Food & Drinks"),
                location_area=s.get("location_area"),
                vibe_tags=s.get("vibe_tags"),
                status=s.get("status", "wishlist"),
                tamir_verdict=s.get("tamir_verdict"),
                mikush_verdict=s.get("mikush_verdict"),
                highlight_notes=s.get("highlight_notes"),
                added_by=s.get("added_by", "Tamir"),
                last_visited_at=now if s.get("status") == "visited" else None,
                created_at=now
            ))
        db.commit()

    preset_count = db.query(func.count(RandomizerPreset.id)).scalar()
    if preset_count == 0:
        for p in DEFAULT_STARTER_PRESETS:
            db.add(RandomizerPreset(
                title=p["title"],
                options_json=json.dumps(p["options"]),
                created_at=now
            ))
        db.commit()


# ===================== PYDANTIC SCHEMAS =====================
class DateSpotCreatePayload(BaseModel):
    name: str = Field(..., min_length=1)
    category: str = "Food & Drinks"
    location_area: Optional[str] = None
    vibe_tags: Optional[str] = None
    status: str = "wishlist"
    highlight_notes: Optional[str] = None


class DateSpotReviewPayload(BaseModel):
    verdict: Optional[str] = None  # "loved", "okay", "skip", or None
    highlight_notes: Optional[str] = None


class RandomizerPresetCreatePayload(BaseModel):
    title: str = Field(..., min_length=1)
    options: List[str] = Field(..., min_items=2)


def format_spot_dict(s: DateSpot) -> dict:
    is_mutual_love = (s.tamir_verdict == "loved" and s.mikush_verdict == "loved")
    return {
        "id": s.id,
        "name": s.name,
        "category": s.category,
        "location_area": s.location_area,
        "vibe_tags": [tag.strip() for tag in (s.vibe_tags or "").split(",") if tag.strip()],
        "raw_vibe_tags": s.vibe_tags,
        "status": s.status,
        "tamir_verdict": s.tamir_verdict,
        "mikush_verdict": s.mikush_verdict,
        "is_mutual_love": is_mutual_love,
        "highlight_notes": s.highlight_notes,
        "added_by": s.added_by,
        "last_visited_at": s.last_visited_at.isoformat() if s.last_visited_at else None,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


# ===================== SPOTS ENDPOINTS =====================
@dates_router.get("/api/spots", dependencies=[Depends(require_auth_api)])
def get_date_spots(
    status: Optional[str] = Query("all"),
    category: Optional[str] = Query("all"),
    db: Session = Depends(get_db)
):
    """Returns date vault spots with optional status and category filtering."""
    ensure_starter_dates(db)
    query = db.query(DateSpot)

    if status and status.lower() != "all":
        query = query.filter(DateSpot.status == status.lower())

    if category and category.lower() != "all":
        query = query.filter(func.lower(DateSpot.category) == category.lower())

    spots = query.order_by(
        DateSpot.status.asc(),  # 'visited' vs 'wishlist'
        DateSpot.created_at.desc()
    ).all()

    return [format_spot_dict(s) for s in spots]


@dates_router.post("/api/spots", dependencies=[Depends(require_auth_api)])
def create_date_spot(payload: DateSpotCreatePayload, request: Request, db: Session = Depends(get_db)):
    """Creates a new spot in the Date Vault."""
    active_user = get_active_profile(request)
    now = datetime.datetime.utcnow()
    is_visited = (payload.status == "visited")

    new_spot = DateSpot(
        name=payload.name.strip(),
        category=payload.category.strip() if payload.category else "Food & Drinks",
        location_area=payload.location_area.strip() if payload.location_area else None,
        vibe_tags=payload.vibe_tags.strip() if payload.vibe_tags else None,
        status="visited" if is_visited else "wishlist",
        highlight_notes=payload.highlight_notes.strip() if payload.highlight_notes else None,
        added_by=active_user,
        last_visited_at=now if is_visited else None,
        created_at=now
    )
    db.add(new_spot)
    db.commit()
    db.refresh(new_spot)

    return {"status": "ok", "spot": format_spot_dict(new_spot)}


@dates_router.post("/api/spots/{spot_id}/review", dependencies=[Depends(require_auth_api)])
def review_date_spot(
    spot_id: int,
    payload: DateSpotReviewPayload,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Updates the reviewer's verdict for a date spot.
    CRITICAL: Only updates the active user's rating (Tamir or Mikush) and preserves the other partner's rating!
    """
    spot = db.query(DateSpot).filter(DateSpot.id == spot_id).first()
    if not spot:
        raise HTTPException(status_code=404, detail="Date spot not found")

    active_user = get_active_profile(request)
    now = datetime.datetime.utcnow()

    # Update only the active user's field
    if active_user.lower() == "mikush":
        spot.mikush_verdict = payload.verdict
    else:
        spot.tamir_verdict = payload.verdict

    # Mark as visited when reviewed
    spot.status = "visited"
    spot.last_visited_at = now

    if payload.highlight_notes:
        spot.highlight_notes = payload.highlight_notes.strip()

    db.commit()
    db.refresh(spot)

    return {
        "status": "ok",
        "message": f"Updated review by {active_user}",
        "spot": format_spot_dict(spot)
    }


@dates_router.delete("/api/spots/{spot_id}", dependencies=[Depends(require_auth_api)])
def delete_date_spot(spot_id: int, db: Session = Depends(get_db)):
    """Deletes a date spot."""
    spot = db.query(DateSpot).filter(DateSpot.id == spot_id).first()
    if not spot:
        raise HTTPException(status_code=404, detail="Date spot not found")

    db.delete(spot)
    db.commit()
    return {"status": "ok", "message": f"Deleted '{spot.name}'"}


# ===================== DATE SPINNER ENDPOINT =====================
@dates_router.get("/api/spin", dependencies=[Depends(require_auth_api)])
def spin_date_spot(
    mode: str = Query("new", pattern="^(new|favorite)$"),
    category: Optional[str] = Query(None),
    exclude_id: Optional[int] = Query(None),
    db: Session = Depends(get_db)
):
    """
    Weighted randomizer for date night decision:
    - mode='new': Picks from wishlist spots.
    - mode='favorite': Picks from visited favorites, giving 2x weight to spots both loved!
    Supports optional category filtering and exclude_id (for veto reroll).
    """
    ensure_starter_dates(db)
    query = db.query(DateSpot)

    if category and category.lower() != "all":
        query = query.filter(func.lower(DateSpot.category) == category.lower())

    if exclude_id:
        query = query.filter(DateSpot.id != exclude_id)

    if mode == "favorite":
        # Candidates that are visited and at least one person liked
        all_candidates = query.filter(DateSpot.status == "visited").all()
        # Filter to spots that someone enjoyed (loved or okay)
        candidates = [
            s for s in all_candidates
            if (s.tamir_verdict in ("loved", "okay") or s.mikush_verdict in ("loved", "okay"))
        ]
        # If no rated favorites match, fall back to all visited spots in category
        if not candidates:
            candidates = all_candidates
    else:
        # 'new' mode: Wishlist spots
        candidates = query.filter(DateSpot.status == "wishlist").all()
        # If wishlist is empty, fall back to any spots
        if not candidates:
            candidates = query.all()

    if not candidates:
        return {
            "status": "empty",
            "spot": None,
            "message": "No matching date spots found! Add some to the vault first."
        }

    # Calculate weights: Mutual love spots get 2x weight in favorite mode
    weights = []
    for s in candidates:
        w = 1.0
        if mode == "favorite" and (s.tamir_verdict == "loved" and s.mikush_verdict == "loved"):
            w = 2.0
        weights.append(w)

    chosen = random.choices(candidates, weights=weights, k=1)[0]

    return {
        "status": "ok",
        "spot": format_spot_dict(chosen),
        "total_candidates": len(candidates)
    }


# ===================== RANDOMIZER PRESETS ENDPOINTS =====================
@dates_router.get("/api/presets", dependencies=[Depends(require_auth_api)])
def get_randomizer_presets(db: Session = Depends(get_db)):
    """Returns all decision wheel presets."""
    ensure_starter_dates(db)
    presets = db.query(RandomizerPreset).order_by(RandomizerPreset.created_at.asc()).all()
    res = []
    for p in presets:
        try:
            options = json.loads(p.options_json)
        except Exception:
            options = []
        res.append({
            "id": p.id,
            "title": p.title,
            "options": options,
            "created_at": p.created_at.isoformat() if p.created_at else None
        })
    return res


@dates_router.post("/api/presets", dependencies=[Depends(require_auth_api)])
def create_randomizer_preset(payload: RandomizerPresetCreatePayload, db: Session = Depends(get_db)):
    """Creates a custom decision wheel preset."""
    clean_options = [opt.strip() for opt in payload.options if opt.strip()]
    if len(clean_options) < 2:
        raise HTTPException(status_code=400, detail="A decision wheel must have at least 2 options")

    preset = RandomizerPreset(
        title=payload.title.strip(),
        options_json=json.dumps(clean_options),
        created_at=datetime.datetime.utcnow()
    )
    db.add(preset)
    db.commit()
    db.refresh(preset)

    return {
        "status": "ok",
        "preset": {
            "id": preset.id,
            "title": preset.title,
            "options": clean_options
        }
    }


@dates_router.delete("/api/presets/{preset_id}", dependencies=[Depends(require_auth_api)])
def delete_randomizer_preset(preset_id: int, db: Session = Depends(get_db)):
    """Deletes a custom decision wheel preset."""
    preset = db.query(RandomizerPreset).filter(RandomizerPreset.id == preset_id).first()
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")

    db.delete(preset)
    db.commit()
    return {"status": "ok", "message": f"Deleted preset '{preset.title}'"}
