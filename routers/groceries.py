import os
import datetime
from typing import Optional, List, Dict
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import desc, func

from database import get_db
from models.groceries import (
    GroceryItem, GroceryStaple, GroceryPurchaseHistory,
    GROCERY_CATEGORIES, SUPERMARKET_WALKING_ORDER, GROCERY_UNITS
)
from security import require_auth_api, get_active_profile
from seed_hebrew_items import classify_grocery_item
from services.gemini_service import (
    _canonical_alias_groups,
    classify_grocery_metadata,
    infer_grocery_category,
    normalize_item_key,
)

groceries_router = APIRouter(prefix="/groceries", tags=["groceries"])

BASELINE_STAPLE_INTERVALS = {
    "milk": 6.0,
    "eggs": 10.0,
    "sourdough bread": 5.0,
    "bread": 5.0,
    "onions": 12.0,
    "garlic": 14.0,
    "coffee beans": 21.0,
    "coffee": 21.0,
    "olive oil": 30.0,
    "butter": 14.0,
    "paper towels": 21.0,
    "dish soap": 30.0,
    "trash bags": 21.0,
    "toilet paper": 21.0,
}


# ===================== PYDANTIC SCHEMAS =====================
class GroceryItemCreate(BaseModel):
    name: str = Field(..., min_length=1)
    amount: Optional[float] = None
    unit: Optional[str] = None
    category: Optional[str] = None
    default_split: Optional[str] = None
    typical_depletion_days: Optional[int] = None
    for_member: Optional[str] = None
    added_by: Optional[str] = None


class GroceryItemUpdate(BaseModel):
    name: Optional[str] = None
    amount: Optional[float] = None
    unit: Optional[str] = None
    category: Optional[str] = None
    default_split: Optional[str] = None
    typical_depletion_days: Optional[int] = None
    for_member: Optional[str] = None
    is_checked: Optional[bool] = None


class GroceryRestorePayload(BaseModel):
    items: List[dict]


# ===================== STARTER STAPLES SEEDER =====================
DEFAULT_STAPLES = [
    {"name": "Milk", "category": "Dairy/Eggs", "default_amount": 1.0, "default_unit": "L", "icon_emoji": "🥛", "display_order": 1, "avg_interval_days": 6.0},
    {"name": "Eggs", "category": "Dairy/Eggs", "default_amount": 12.0, "default_unit": "pcs", "icon_emoji": "🥚", "display_order": 2, "avg_interval_days": 10.0},
    {"name": "Coffee Beans", "category": "Pantry/Dry", "default_amount": 1.0, "default_unit": "pack", "icon_emoji": "☕", "display_order": 3, "avg_interval_days": 21.0},
    {"name": "Onions", "category": "Produce", "default_amount": 1.0, "default_unit": "kg", "icon_emoji": "🧅", "display_order": 4, "avg_interval_days": 12.0},
    {"name": "Garlic", "category": "Produce", "default_amount": 3.0, "default_unit": "pcs", "icon_emoji": "🧄", "display_order": 5, "avg_interval_days": 14.0},
    {"name": "Olive Oil", "category": "Spices/Oils", "default_amount": 1.0, "default_unit": "L", "icon_emoji": "🫒", "display_order": 6, "avg_interval_days": 30.0},
    {"name": "Butter", "category": "Dairy/Eggs", "default_amount": 1.0, "default_unit": "pack", "icon_emoji": "🧈", "display_order": 7, "avg_interval_days": 14.0},
    {"name": "Sourdough Bread", "category": "Bakery", "default_amount": 1.0, "default_unit": "pcs", "icon_emoji": "🥖", "display_order": 8, "avg_interval_days": 5.0},
    {"name": "Paper Towels", "category": "Household", "default_amount": 1.0, "default_unit": "pack", "icon_emoji": "🧻", "display_order": 9, "avg_interval_days": 21.0},
    {"name": "Dish Soap", "category": "Household", "default_amount": 1.0, "default_unit": "pcs", "icon_emoji": "🧼", "display_order": 10, "avg_interval_days": 30.0},
]


def ensure_starter_staples(db: Session):
    """Populates initial common apartment staples if table is empty."""
    if db.query(GroceryStaple).count() == 0:
        for st in DEFAULT_STAPLES:
            db.add(GroceryStaple(**st))
        db.commit()


def sort_grocery_items_walking_order(items: List[GroceryItem]) -> List[GroceryItem]:
    """Sorts unchecked items by physical Supermarket Walking Order, then checked items at the bottom."""
    return sorted(
        items,
        key=lambda it: (
            1 if it.is_checked else 0,
            SUPERMARKET_WALKING_ORDER.get(it.category or "Pantry/Dry", 99),
            -(it.created_at.timestamp() if it.created_at else 0.0),
        ),
    )


def serialize_grocery_item(it: GroceryItem) -> dict:
    return {
        "id": it.id,
        "name": it.name,
        "amount": it.amount,
        "unit": it.unit,
        "category": it.category,
        "default_split": getattr(it, "default_split", None) or "SHARED_50_50",
        "typical_depletion_days": getattr(it, "typical_depletion_days", None),
        "for_member": getattr(it, "for_member", None),
        "is_checked": it.is_checked,
        "checked_at": it.checked_at.isoformat() if it.checked_at else None,
        "added_by": it.added_by,
        "created_at": it.created_at.isoformat() if it.created_at else None,
        "updated_at": it.updated_at.isoformat() if it.updated_at else None,
    }


def record_purchase_event(
    db: Session,
    item_name: str,
    category: Optional[str] = None,
    amount: Optional[float] = None,
    unit: Optional[str] = None,
    source: str = "grocery_check",
    purchased_by: str = "Tamir",
    purchased_at: Optional[datetime.datetime] = None,
):
    """Records a purchase timestamp into grocery_purchase_history for the Depletion Radar."""
    clean_name = (item_name or "").strip()
    norm = normalize_item_key(clean_name)
    if not norm:
        return
    resolved_cat = infer_grocery_category(clean_name, category)
    db.add(GroceryPurchaseHistory(
        item_name=clean_name,
        normalized_name=norm,
        category=resolved_cat,
        amount=amount,
        unit=unit,
        source=source,
        purchased_by=purchased_by or "Tamir",
        purchased_at=purchased_at or datetime.datetime.utcnow(),
    ))


# ===================== UI SHELL ROUTE =====================
@groceries_router.get("")
@groceries_router.get("/")
def groceries_page(request: Request):
    """Serves the unified apartment hub with groceries tab active."""
    from plants_app import serve_hub_shell
    return serve_hub_shell(request, default_tab="groceries")


# ===================== API ENDPOINTS =====================
@groceries_router.get("/api/items", dependencies=[Depends(require_auth_api)])
def list_grocery_items(db: Session = Depends(get_db)):
    """Returns active and checked grocery items ordered by supermarket walking layout."""
    ensure_starter_staples(db)

    raw_items = db.query(GroceryItem).all()
    items = sort_grocery_items_walking_order(raw_items)
    staples = db.query(GroceryStaple).order_by(GroceryStaple.display_order.asc()).all()

    # Get max updated timestamp for 4-second sync delta checks
    latest_update = db.query(func.max(GroceryItem.updated_at)).scalar()
    latest_update_str = latest_update.isoformat() if latest_update else datetime.datetime.utcnow().isoformat()

    return {
        "categories": GROCERY_CATEGORIES,
        "walking_order": SUPERMARKET_WALKING_ORDER,
        "units": GROCERY_UNITS,
        "last_updated_at": latest_update_str,
        "items": [serialize_grocery_item(it) for it in items],
        "staples": [
            {
                "id": st.id,
                "name": st.name,
                "default_amount": st.default_amount,
                "default_unit": st.default_unit,
                "category": st.category,
                "icon_emoji": st.icon_emoji,
                "avg_interval_days": getattr(st, "avg_interval_days", None),
            }
            for st in staples
        ]
    }


@groceries_router.get("/api/sync", dependencies=[Depends(require_auth_api)])
def sync_groceries(since: Optional[str] = Query(None), db: Session = Depends(get_db)):
    """Ultra-lightweight endpoint for 4-second visibility polling."""
    latest_update = db.query(func.max(GroceryItem.updated_at)).scalar()
    count = db.query(GroceryItem).count()

    if not latest_update:
        return {"changed": False, "count": 0, "last_updated_at": None}

    latest_iso = latest_update.isoformat()

    # Compare ISO strings
    if since and since.strip() == latest_iso:
        return {"changed": False, "last_updated_at": latest_iso, "count": count}

    # If state changed, return full fresh items list in supermarket walking order
    items = sort_grocery_items_walking_order(db.query(GroceryItem).all())

    return {
        "changed": True,
        "last_updated_at": latest_iso,
        "count": len(items),
        "items": [serialize_grocery_item(it) for it in items]
    }


@groceries_router.post("/api/items", dependencies=[Depends(require_auth_api)])
def add_grocery_item(payload: GroceryItemCreate, request: Request, db: Session = Depends(get_db)):
    """Adds a new item to the shared list (auto-classified by supermarket aisle), or reactivates existing checked item."""
    clean_name = payload.name.strip()
    if not clean_name:
        raise HTTPException(status_code=400, detail="Item name is required")

    active_user = payload.added_by or get_active_profile(request)
    now = datetime.datetime.utcnow()
    meta = classify_grocery_metadata(
        clean_name,
        explicit_category=payload.category,
        explicit_split=payload.default_split,
    )
    resolved_category = meta["category"]
    resolved_split = meta["default_split"]
    resolved_days = (
        payload.typical_depletion_days
        if payload.typical_depletion_days is not None
        else meta["typical_depletion_days"]
    )

    # Check if this exact item is already on list checked off
    existing_checked = (
        db.query(GroceryItem)
        .filter(func.lower(GroceryItem.name) == clean_name.lower(), GroceryItem.is_checked == True)
        .first()
    )

    if existing_checked:
        existing_checked.is_checked = False
        existing_checked.checked_at = None
        existing_checked.added_by = active_user
        existing_checked.updated_at = now
        existing_checked.category = resolved_category
        existing_checked.default_split = resolved_split
        existing_checked.typical_depletion_days = resolved_days
        if payload.amount is not None:
            existing_checked.amount = payload.amount
        if payload.unit is not None:
            existing_checked.unit = payload.unit
        if payload.for_member is not None:
            existing_checked.for_member = payload.for_member
        db.commit()
        db.refresh(existing_checked)
        item = existing_checked
    else:
        item = GroceryItem(
            name=clean_name,
            amount=payload.amount,
            unit=payload.unit,
            category=resolved_category,
            default_split=resolved_split,
            typical_depletion_days=resolved_days,
            for_member=payload.for_member,
            is_checked=False,
            added_by=active_user,
            created_at=now,
            updated_at=now
        )
        db.add(item)
        db.commit()
        db.refresh(item)

    return {
        "status": "ok",
        "item": serialize_grocery_item(item)
    }


@groceries_router.patch("/api/items/{item_id}", dependencies=[Depends(require_auth_api)])
def update_grocery_item(item_id: int, payload: GroceryItemUpdate, request: Request, db: Session = Depends(get_db)):
    """Edits, checks off, or unchecks a grocery item (recording purchase timestamps for Depletion Radar)."""
    item = db.query(GroceryItem).filter(GroceryItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    now = datetime.datetime.utcnow()
    was_checked = bool(item.is_checked)
    item.updated_at = now

    if payload.name is not None:
        item.name = payload.name.strip()
        if payload.typical_depletion_days is None:
            item.typical_depletion_days = classify_grocery_item(item.name)["typical_depletion_days"]
    if payload.amount is not None:
        item.amount = payload.amount
    if payload.unit is not None:
        item.unit = payload.unit.strip() if payload.unit else None
    if payload.category is not None:
        if payload.category in GROCERY_CATEGORIES:
            item.category = payload.category
    if payload.default_split in ("SHARED_50_50", "MIKUSH_100", "TAMIR_100"):
        item.default_split = payload.default_split
    if payload.typical_depletion_days is not None:
        item.typical_depletion_days = payload.typical_depletion_days
    if payload.for_member is not None:
        item.for_member = payload.for_member.strip() if payload.for_member else None

    if payload.is_checked is not None:
        item.is_checked = payload.is_checked
        item.checked_at = now if payload.is_checked else None
        if payload.is_checked and not was_checked:
            active_user = get_active_profile(request)
            record_purchase_event(
                db=db,
                item_name=item.name,
                category=item.category,
                amount=item.amount,
                unit=item.unit,
                source="grocery_check",
                purchased_by=active_user,
                purchased_at=now,
            )

    db.commit()
    db.refresh(item)

    return {
        "status": "ok",
        "item": serialize_grocery_item(item)
    }


@groceries_router.delete("/api/items/{item_id}", dependencies=[Depends(require_auth_api)])
def delete_grocery_item(item_id: int, db: Session = Depends(get_db)):
    """Deletes an item, returning backup details for client-side 5-second undo."""
    item = db.query(GroceryItem).filter(GroceryItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    deleted_copy = {
        "name": item.name,
        "amount": item.amount,
        "unit": item.unit,
        "category": item.category,
        "is_checked": item.is_checked,
        "added_by": item.added_by,
        "created_at": item.created_at.isoformat() if item.created_at else None
    }

    db.delete(item)
    db.commit()

    return {
        "status": "ok",
        "message": f"Deleted '{item.name}'",
        "deleted_item": deleted_copy
    }


@groceries_router.post("/api/clear-checked", dependencies=[Depends(require_auth_api)])
def clear_checked_items(db: Session = Depends(get_db)):
    """Clears all checked items from list, returning backup for 5-second undo."""
    checked_items = db.query(GroceryItem).filter(GroceryItem.is_checked == True).all()
    if not checked_items:
        return {"status": "ok", "cleared_count": 0, "cleared_items": []}

    backup = [
        {
            "name": it.name,
            "amount": it.amount,
            "unit": it.unit,
            "category": it.category,
            "is_checked": it.is_checked,
            "added_by": it.added_by,
            "created_at": it.created_at.isoformat() if it.created_at else None
        }
        for it in checked_items
    ]

    for it in checked_items:
        db.delete(it)
    db.commit()

    return {
        "status": "ok",
        "cleared_count": len(backup),
        "cleared_items": backup
    }


@groceries_router.post("/api/restore", dependencies=[Depends(require_auth_api)])
def restore_grocery_items(payload: GroceryRestorePayload, db: Session = Depends(get_db)):
    """Restores previously deleted or cleared items when user taps Toast Undo."""
    now = datetime.datetime.utcnow()
    restored_count = 0

    for it in payload.items:
        new_item = GroceryItem(
            name=it.get("name", "Item"),
            amount=it.get("amount"),
            unit=it.get("unit"),
            category=it.get("category", "Produce"),
            is_checked=it.get("is_checked", False),
            added_by=it.get("added_by", "Tamir"),
            created_at=now,
            updated_at=now
        )
        db.add(new_item)
        restored_count += 1

    db.commit()
    return {"status": "ok", "restored_count": restored_count}


@groceries_router.get("/api/autocomplete", dependencies=[Depends(require_auth_api)])
def grocery_autocomplete(q: str = Query("", min_length=1), db: Session = Depends(get_db)):
    """Returns suggestions from past items matching search query."""
    search = f"%{q.strip().lower()}%"
    rows = (
        db.query(GroceryItem.name, GroceryItem.category, GroceryItem.unit)
        .filter(func.lower(GroceryItem.name).like(search))
        .distinct()
        .limit(8)
        .all()
    )

    return {
        "suggestions": [
            {"name": r[0], "category": r[1], "unit": r[2]}
            for r in rows
        ]
    }


@groceries_router.get("/api/depletion-radar", dependencies=[Depends(require_auth_api)])
def get_depletion_radar(
    threshold: float = Query(0.80, ge=0.1, le=2.0),
    db: Session = Depends(get_db),
):
    """
    Computes the rolling average repurchase interval per staple from checked-off grocery items
    and scanned receipts, surfacing items that have passed 80% of their typical cycle.
    """
    ensure_starter_staples(db)
    now = datetime.datetime.utcnow()

    # Active unchecked items (including bilingual aliases) are already on the list -> don't nag
    active_unchecked = db.query(GroceryItem).filter(GroceryItem.is_checked == False).all()
    active_norm_names = set()
    for it in active_unchecked:
        if it.name:
            active_norm_names.add(normalize_item_key(it.name))
            active_norm_names.update(_canonical_alias_groups(it.name))

    # Baseline intervals from GroceryStaple + known household staples
    staples = db.query(GroceryStaple).all()
    staple_baselines: Dict[str, dict] = {}
    for st in staples:
        norm = normalize_item_key(st.name)
        baseline = st.avg_interval_days or BASELINE_STAPLE_INTERVALS.get(norm)
        staple_baselines[norm] = {
            "name": st.name,
            "category": st.category,
            "default_amount": st.default_amount,
            "default_unit": st.default_unit,
            "icon_emoji": st.icon_emoji,
            "baseline_days": baseline,
        }

    # Fetch all purchase events chronologically
    history_rows = (
        db.query(GroceryPurchaseHistory)
        .order_by(GroceryPurchaseHistory.purchased_at.asc())
        .all()
    )

    grouped: Dict[str, List[GroceryPurchaseHistory]] = {}
    for row in history_rows:
        norm = row.normalized_name or normalize_item_key(row.item_name)
        if not norm:
            continue
        grouped.setdefault(norm, []).append(row)

    radar_items = []
    for norm, events in grouped.items():
        if norm in active_norm_names:
            continue

        # Deduplicate near-simultaneous events (< 6 hours apart) so double-taps don't distort cycles
        deduped: List[GroceryPurchaseHistory] = []
        for ev in events:
            if not deduped:
                deduped.append(ev)
            else:
                gap_hours = (ev.purchased_at - deduped[-1].purchased_at).total_seconds() / 3600.0
                if gap_hours >= 6.0:
                    deduped.append(ev)

        last_ev = deduped[-1]
        days_since_last = max(0.0, (now - last_ev.purchased_at).total_seconds() / 86400.0)

        avg_interval: Optional[float] = None
        prior_source = "history"
        if len(deduped) >= 2:
            intervals = [
                (deduped[i].purchased_at - deduped[i - 1].purchased_at).total_seconds() / 86400.0
                for i in range(1, len(deduped))
            ]
            # Rolling average over the most recent 5 purchase intervals
            recent_intervals = [iv for iv in intervals[-5:] if iv >= 0.25]
            if recent_intervals:
                avg_interval = round(sum(recent_intervals) / len(recent_intervals), 1)

        if avg_interval is None:
            if norm in staple_baselines and staple_baselines[norm]["baseline_days"]:
                avg_interval = float(staple_baselines[norm]["baseline_days"])
                prior_source = "staple"
            elif norm in BASELINE_STAPLE_INTERVALS:
                avg_interval = float(BASELINE_STAPLE_INTERVALS[norm])
                prior_source = "staple"
            else:
                # Day-1 Depletion Radar prior seeded from seed_hebrew_items.py
                seed_prior = classify_grocery_item(last_ev.item_name)
                if seed_prior and seed_prior.get("typical_depletion_days"):
                    avg_interval = float(seed_prior["typical_depletion_days"])
                    prior_source = "seed_dictionary"

        if not avg_interval or avg_interval <= 0:
            continue

        cycle_ratio = days_since_last / avg_interval
        if cycle_ratio >= threshold:
            st_meta = staple_baselines.get(norm, {})
            cycle_pct = int(round(cycle_ratio * 100))
            item_meta = classify_grocery_metadata(last_ev.item_name, explicit_category=st_meta.get("category") or last_ev.category)
            radar_items.append({
                "normalized_name": norm,
                "name": st_meta.get("name") or last_ev.item_name,
                "category": item_meta["category"],
                "default_split": item_meta["default_split"],
                "default_amount": st_meta.get("default_amount") or last_ev.amount,
                "default_unit": st_meta.get("default_unit") or last_ev.unit,
                "icon_emoji": st_meta.get("icon_emoji") or "⚡",
                "avg_interval_days": avg_interval,
                "prior_source": prior_source,
                "days_since_last": round(days_since_last, 1),
                "cycle_pct": cycle_pct,
                "purchase_count": len(deduped),
                "last_purchased_at": last_ev.purchased_at.isoformat(),
                "status_label": f"{round(days_since_last, 1)}d since last (~{avg_interval}d cycle · {cycle_pct}%)",
            })

    radar_items.sort(key=lambda x: (-x["cycle_pct"], x["name"].lower()))
    return {"radar_items": radar_items, "threshold_pct": int(round(threshold * 100))}
