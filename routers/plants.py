import os
import json
import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import text
from pywebpush import webpush, WebPushException
from py_vapid import Vapid
import py_vapid.utils
from cryptography.hazmat.primitives import serialization

from database import engine, SessionLocal, Base, get_db
from models.plants import Plant, WateringLog, PushSubscription, AppConfig
from security import is_authenticated, get_active_profile

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ===================== DATABASE HELPER & INTERVAL ENGINE =====================
def get_utc_now() -> datetime.datetime:
    """Returns current UTC time as naive datetime for consistent DB storage and comparisons."""
    return datetime.datetime.utcnow()


def normalize_utc(dt: Optional[datetime.datetime]) -> Optional[datetime.datetime]:
    """Ensures datetime is naive UTC across all database engines and payload types."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return dt


def recompute_plant_intervals(plant_id: int, db: Session):
    """
    Recomputes raw_elapsed_hours and effective_interval_hours for all logs of a plant.
    Guards against near-zero interval poisoning, double-taps (< 6h), and enforces a 12h floor.
    """
    plant = db.query(Plant).filter(Plant.id == plant_id).first()
    default_interval = float(plant.initial_interval_hours) if (plant and plant.initial_interval_hours) else 72.0
    default_interval = max(12.0, default_interval)

    logs = (
        db.query(WateringLog)
        .filter(WateringLog.plant_id == plant_id)
        .order_by(WateringLog.watered_at.asc(), WateringLog.id.asc())
        .all()
    )
    prev_log = None
    last_valid_effective = default_interval

    for log in logs:
        if prev_log is None:
            log.raw_elapsed_hours = None
            log.effective_interval_hours = None
        else:
            prev_watered = normalize_utc(prev_log.watered_at)
            curr_watered = normalize_utc(log.watered_at)
            diff_hours = (curr_watered - prev_watered).total_seconds() / 3600.0
            diff_hours = max(0.0, diff_hours)
            log.raw_elapsed_hours = round(diff_hours, 2)

            state = (log.soil_state or "ideal").lower().strip()
            if state == "damp":
                mult = 1.20
            elif state == "bone_dry":
                mult = 0.80
            else:
                mult = 1.00

            # Guard against accidental double-taps or rapid logs (< 6.0 hours elapsed):
            # Do NOT use tiny elapsed time to poison intervals. Inherit previous valid interval.
            if diff_hours < 6.0:
                log.effective_interval_hours = round(last_valid_effective, 2)
            else:
                computed = max(12.0, diff_hours * mult)
                log.effective_interval_hours = round(computed, 2)
                last_valid_effective = log.effective_interval_hours
        prev_log = log
    db.commit()


def repair_corrupted_watering_logs(db: Session) -> int:
    """
    Scans for and repairs any corrupted watering_logs where raw_elapsed_hours < 1.0
    or effective_interval_hours < 6.0 (caused by self-comparison or double-taps).
    Deletes rapid-fire duplicates (< 1.0h) and recalculates intervals for all affected plants.
    """
    corrupted_logs = (
        db.query(WateringLog)
        .filter(
            (WateringLog.raw_elapsed_hours.isnot(None) & (WateringLog.raw_elapsed_hours < 1.0)) |
            (WateringLog.effective_interval_hours.isnot(None) & (WateringLog.effective_interval_hours < 6.0))
        )
        .all()
    )

    if not corrupted_logs:
        return 0

    affected_plant_ids = set()
    cleaned = 0
    for log in corrupted_logs:
        affected_plant_ids.add(log.plant_id)
        if log.raw_elapsed_hours is not None and log.raw_elapsed_hours < 1.0:
            db.delete(log)
            cleaned += 1
        else:
            cleaned += 1

    db.commit()

    for pid in affected_plant_ids:
        recompute_plant_intervals(pid, db)

    db.commit()
    print(f"[+] Successfully repaired and cleaned {cleaned} corrupted watering log(s) across {len(affected_plant_ids)} plant(s)")
    return cleaned

    if repaired_count > 0:
        print(f"[+] Successfully repaired corrupted watering logs across {repaired_count} plant(s)")
    return repaired_count


def init_plant_db():
    """Initializes tables, safe column migration, starter plants and VAPID keys."""
    try:
        Base.metadata.create_all(bind=engine)
        # Safe migration check: ensure last_notified_at column exists
        try:
            with engine.connect() as conn:
                dialect = engine.dialect.name
                if dialect == "postgresql":
                    conn.execute(text("ALTER TABLE plants ADD COLUMN IF NOT EXISTS last_notified_at TIMESTAMP;"))
                else:
                    try:
                        conn.execute(text("ALTER TABLE plants ADD COLUMN last_notified_at TIMESTAMP;"))
                    except Exception:
                        pass
                conn.commit()
        except Exception as e:
            print(f"[!] Migration check note: {e}")

        print("[+] Database tables initialized successfully")
    except Exception as e:
        print(f"[!] Database metadata initialization note: {e}")

    db = SessionLocal()
    try:
        get_or_create_vapid(db)

        count = db.query(Plant).count()
        if count == 0:
            now = datetime.datetime.utcnow()
            p1 = Plant(
                name="Strawberries (Mother)",
                species_or_type="Fragaria × ananassa",
                location_group="Terrace / Home",
                pot_size_liters=5.0,
                growth_stage="Runner / Stolon",
                initial_interval_hours=54.0,
                created_at=now - datetime.timedelta(days=14)
            )
            p2 = Plant(
                name="Monstera Deliciosa",
                species_or_type="Swiss Cheese Plant",
                location_group="Apartment",
                pot_size_liters=9.0,
                growth_stage="Vegetative",
                initial_interval_hours=168.0,
                created_at=now - datetime.timedelta(days=30)
            )
            p3 = Plant(
                name="Coleus Cutting",
                species_or_type="Plectranthus scutellarioides",
                location_group="Grow Light Zone",
                pot_size_liters=0.8,
                growth_stage="Propagating / Rooting",
                initial_interval_hours=48.0,
                created_at=now - datetime.timedelta(days=10)
            )
            db.add_all([p1, p2, p3])
            db.commit()

            l1 = WateringLog(plant_id=p1.id, watered_at=now - datetime.timedelta(days=10), soil_state="ideal")
            l2 = WateringLog(plant_id=p1.id, watered_at=now - datetime.timedelta(days=7), soil_state="ideal")
            l3 = WateringLog(plant_id=p1.id, watered_at=now - datetime.timedelta(days=4, hours=12), soil_state="ideal")
            l4 = WateringLog(plant_id=p1.id, watered_at=now - datetime.timedelta(days=2, hours=12), soil_state="damp", notes="Lots of runners")
            l5 = WateringLog(plant_id=p1.id, watered_at=now - datetime.timedelta(hours=18), soil_state="ideal", notes="Kelp feed")

            m1 = WateringLog(plant_id=p2.id, watered_at=now - datetime.timedelta(days=22), soil_state="ideal")
            m2 = WateringLog(plant_id=p2.id, watered_at=now - datetime.timedelta(days=14), soil_state="ideal")
            m3 = WateringLog(plant_id=p2.id, watered_at=now - datetime.timedelta(days=6), soil_state="damp")

            c1 = WateringLog(plant_id=p3.id, watered_at=now - datetime.timedelta(days=8), soil_state="ideal")
            c2 = WateringLog(plant_id=p3.id, watered_at=now - datetime.timedelta(days=5), soil_state="ideal")
            c3 = WateringLog(plant_id=p3.id, watered_at=now - datetime.timedelta(days=2), soil_state="bone_dry")

            db.add_all([l1, l2, l3, l4, l5, m1, m2, m3, c1, c2, c3])
            db.commit()

            recompute_plant_intervals(p1.id, db)
            recompute_plant_intervals(p2.id, db)
            recompute_plant_intervals(p3.id, db)
            print("[+] Seeded initial starter plants successfully")

        # Run startup check & repair on any corrupted watering logs
        repair_corrupted_watering_logs(db)
    except Exception as e:
        print(f"[!] Warning during starter seed or repair: {e}")
        db.rollback()
    finally:
        db.close()


# ===================== METRIC CALCULATION ENGINE =====================
def calculate_plant_metrics(plant: Plant, now: Optional[datetime.datetime] = None) -> dict:
    now = normalize_utc(now) or get_utc_now()

    # 1. Explicitly sort all logs chronologically (ASC: oldest first, newest last)
    # Never rely on default DB or ORM order.
    raw_logs = list(plant.watering_logs or [])
    sorted_logs_asc = sorted(
        raw_logs,
        key=lambda l: (normalize_utc(l.watered_at) or datetime.datetime.min, l.id or 0)
    )

    # 2. Extract valid positive intervals from chronological logs
    intervals = [
        max(12.0, float(l.effective_interval_hours))
        for l in sorted_logs_asc
        if l.effective_interval_hours is not None and l.effective_interval_hours > 0
    ]

    initial_interval = max(12.0, float(plant.initial_interval_hours or 72.0))

    if not intervals:
        baseline_interval_hours = initial_interval
    else:
        last_10 = intervals[-10:]  # 10 most recent intervals
        baseline_interval_hours = round(sum(last_10) / len(last_10), 2)
    baseline_interval_hours = max(12.0, baseline_interval_hours)

    if len(intervals) >= 3:
        # intervals[-1] is most recent, intervals[-2] is 2nd most recent, etc.
        recent_interval_hours = round(
            0.50 * intervals[-1] + 0.30 * intervals[-2] + 0.20 * intervals[-3],
            2
        )
    elif len(intervals) == 2:
        recent_interval_hours = round(
            0.625 * intervals[-1] + 0.375 * intervals[-2],
            2
        )
    elif len(intervals) == 1:
        recent_interval_hours = round(intervals[-1], 2)
    else:
        recent_interval_hours = None

    if recent_interval_hours is not None:
        recent_interval_hours = max(12.0, recent_interval_hours)

    if len(intervals) >= 3 and baseline_interval_hours > 0 and recent_interval_hours is not None:
        delta = ((baseline_interval_hours - recent_interval_hours) / baseline_interval_hours) * 100.0
        drinking_speed_delta_pct = round(delta, 1)
    else:
        drinking_speed_delta_pct = 0.0

    if drinking_speed_delta_pct >= 15.0:
        trend_badge = f"▲ Drinking {int(round(drinking_speed_delta_pct))}% Faster"
        trend_class = "faster"
    elif drinking_speed_delta_pct <= -15.0:
        trend_badge = f"▼ Drinking {int(round(abs(drinking_speed_delta_pct)))}% Slower"
        trend_class = "slower"
    else:
        trend_badge = "Steady Pace"
        trend_class = "steady"

    predicted_interval_hours = (
        recent_interval_hours if recent_interval_hours is not None else baseline_interval_hours
    )
    predicted_interval_hours = max(12.0, predicted_interval_hours)

    # 3. Guaranteed latest log is the last element of sorted_logs_asc
    if sorted_logs_asc:
        latest_log = sorted_logs_asc[-1]
        last_watered_at = normalize_utc(latest_log.watered_at)
        last_soil_state = latest_log.soil_state
    else:
        last_watered_at = normalize_utc(plant.created_at) or now
        last_soil_state = None

    next_due_at = last_watered_at + datetime.timedelta(hours=predicted_interval_hours)
    hours_remaining = round((next_due_at - now).total_seconds() / 3600.0, 1)
    hours_since_watered = round(max(0.0, (now - last_watered_at).total_seconds() / 3600.0), 1)

    if hours_remaining <= 0:
        urgency_status = "OVERDUE"
    elif hours_remaining <= 18:
        urgency_status = "DUE_TODAY"
    else:
        urgency_status = "GOOD"

    if predicted_interval_hours > 0:
        dry_down_pct = min(100.0, max(0.0, round((hours_since_watered / predicted_interval_hours) * 100.0, 1)))
    else:
        dry_down_pct = 100.0

    predicted_days = round(predicted_interval_hours / 24.0, 1)
    if urgency_status == "OVERDUE":
        overdue_hrs = int(round(abs(hours_remaining)))
        due_text = "Overdue right now" if overdue_hrs == 0 else f"Overdue by {overdue_hrs}h (Cycle: {predicted_days}d)"
    elif urgency_status == "DUE_TODAY":
        hrs = max(0, int(round(hours_remaining)))
        due_text = f"Due today in {hrs}h (Every {predicted_days} days)"
    else:
        hrs = int(round(hours_remaining))
        due_text = f"Due in {hrs}h (Every {predicted_days} days)"

    return {
        "id": plant.id,
        "name": plant.name,
        "species_or_type": plant.species_or_type,
        "location_group": plant.location_group,
        "pot_size_liters": plant.pot_size_liters,
        "growth_stage": plant.growth_stage,
        "initial_interval_hours": plant.initial_interval_hours,
        "created_at": plant.created_at.isoformat() if plant.created_at else None,
        "last_watered_at": last_watered_at.isoformat() if last_watered_at else None,
        "last_soil_state": last_soil_state,
        "next_due_at": next_due_at.isoformat() if next_due_at else None,
        "hours_remaining": hours_remaining,
        "hours_since_watered": hours_since_watered,
        "baseline_interval_hours": baseline_interval_hours,
        "recent_interval_hours": recent_interval_hours,
        "predicted_interval_hours": round(predicted_interval_hours, 1),
        "predicted_interval_days": predicted_days,
        "drinking_speed_delta_pct": drinking_speed_delta_pct,
        "trend_badge": trend_badge,
        "trend_class": trend_class,
        "urgency_status": urgency_status,
        "dry_down_pct": dry_down_pct,
        "due_text": due_text,
        "logs_count": len(sorted_logs_asc)
    }


# ===================== VAPID & NOTIFICATION ENGINE =====================
def get_or_create_vapid(db: Session):
    """Retrieves or creates permanent VAPID keys from the database."""
    pub_row = db.query(AppConfig).filter(AppConfig.key == "vapid_public_b64").first()
    priv_row = db.query(AppConfig).filter(AppConfig.key == "vapid_private_pem").first()
    if pub_row and priv_row:
        try:
            v = Vapid.from_pem(priv_row.value.encode("utf-8"))
            return pub_row.value, v
        except Exception as e:
            print(f"[!] Error loading existing VAPID key: {e}")

    # Generate fresh VAPID keypair
    v = Vapid()
    v.generate_keys()
    raw_pub = v.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    b64_pub = py_vapid.utils.b64urlencode(raw_pub)
    pem_priv = v.private_pem().decode("utf-8")

    if not pub_row:
        pub_row = AppConfig(key="vapid_public_b64", value=b64_pub)
        db.add(pub_row)
    else:
        pub_row.value = b64_pub

    if not priv_row:
        priv_row = AppConfig(key="vapid_private_pem", value=pem_priv)
        db.add(priv_row)
    else:
        priv_row.value = pem_priv

    db.commit()
    return b64_pub, v


def send_push_notification(sub: PushSubscription, title: str, body: str, url: str = "/plants", db: Session = None) -> bool:
    """Dispatches a web push notification to a registered device."""
    if db is None:
        return False
    try:
        _, vapid_obj = get_or_create_vapid(db)
        subscription_info = {
            "endpoint": sub.endpoint,
            "keys": {
                "p256dh": sub.p256dh,
                "auth": sub.auth
            }
        }
        payload = json.dumps({
            "title": title,
            "body": body,
            "url": url
        })
        webpush(
            subscription_info=subscription_info,
            data=payload,
            vapid_private_key=vapid_obj,
            vapid_claims={"sub": "mailto:tmimer@plants.app"},
            ttl=86400
        )
        sub.last_used_at = datetime.datetime.utcnow()
        db.commit()
        return True
    except WebPushException as ex:
        print(f"[!] WebPushException: {ex}")
        if ex.response is not None and ex.response.status_code in (404, 410):
            print(f"[-] Pruning expired push subscription {sub.endpoint[:35]}...")
            db.delete(sub)
            db.commit()
        return False
    except Exception as e:
        print(f"[!] Error sending push: {e}")
        return False


def check_and_notify_due_plants(db: Session) -> dict:
    """Checks for plants due/overdue for watering and alerts registered devices."""
    subs = db.query(PushSubscription).all()
    if not subs:
        return {"status": "no_subscribers", "due_count": 0, "sent": 0}

    now = datetime.datetime.utcnow()
    plants = db.query(Plant).all()
    due_plants = []

    for p in plants:
        m = calculate_plant_metrics(p, now=now)
        urgency = m["urgency_status"]
        if urgency in ("OVERDUE", "DUE_TODAY"):
            if not p.last_notified_at or (now - p.last_notified_at).total_seconds() > 16 * 3600:
                due_plants.append((p, m))

    if not due_plants:
        return {"status": "all_hydrated", "due_count": 0, "sent": 0}

    if len(due_plants) == 1:
        p, m = due_plants[0]
        if m["urgency_status"] == "OVERDUE":
            overdue_hrs = max(1, int(round(abs(m['hours_remaining']))))
            title = f"🥀 {p.name} is Overdue!"
            body = f"{p.name} is dry and overdue by {overdue_hrs}h. Tap to log watering."
        else:
            hrs = max(0, int(round(m['hours_remaining'])))
            title = f"💧 Time to water {p.name}"
            body = f"{p.name} is due today in {hrs}h. Tap to log watering."
    else:
        names = [p.name for p, _ in due_plants[:2]]
        extra = len(due_plants) - len(names)
        title = f"💧 {len(due_plants)} Plants Need Water Today!"
        body = f"{', '.join(names)}" + (f" and {extra} more" if extra > 0 else "") + " are ready for a drink."

    sent_count = 0
    for sub in subs:
        if send_push_notification(sub, title=title, body=body, url="/plants", db=db):
            sent_count += 1

    for p, _ in due_plants:
        p.last_notified_at = now
    db.commit()

    return {"status": "sent", "due_count": len(due_plants), "sent": sent_count}


# ===================== PYDANTIC SCHEMAS =====================
class PlantCreate(BaseModel):
    name: str = Field(..., min_length=1)
    species_or_type: Optional[str] = None
    location_group: Optional[str] = "Apartment"
    pot_size_liters: Optional[float] = None
    growth_stage: Optional[str] = "Vegetative"
    initial_interval_hours: Optional[float] = 72.0


class PlantUpdate(BaseModel):
    name: Optional[str] = None
    species_or_type: Optional[str] = None
    location_group: Optional[str] = None
    pot_size_liters: Optional[float] = None
    growth_stage: Optional[str] = None
    initial_interval_hours: Optional[float] = None


class WaterLogCreate(BaseModel):
    soil_state: str = Field(..., pattern="^(damp|ideal|bone_dry)$")
    notes: Optional[str] = None
    watered_at: Optional[datetime.datetime] = None


class WaterLogUpdate(BaseModel):
    soil_state: Optional[str] = Field(None, pattern="^(damp|ideal|bone_dry)$")
    notes: Optional[str] = None
    watered_at: Optional[datetime.datetime] = None


class PushSubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscriptionCreate(BaseModel):
    endpoint: str
    keys: PushSubscriptionKeys
    user_agent: Optional[str] = None


class PushUnsubscribe(BaseModel):
    endpoint: str


# ===================== FASTAPI ROUTER =====================
plants_router = APIRouter(prefix="/plants", tags=["plants"])


def _serve_sw_response():
    response = FileResponse(
        os.path.join(BASE_DIR, "sw.js"),
        media_type="application/javascript"
    )
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


def _serve_manifest_response():
    response = FileResponse(
        os.path.join(BASE_DIR, "manifest.json"),
        media_type="application/manifest+json"
    )
    response.headers["Cache-Control"] = "no-cache"
    return response


@plants_router.get("")
@plants_router.get("/")
def serve_plants_ui(request: Request):
    """Serves the unified apartment hub shell on /plants."""
    hub_file = os.path.join(BASE_DIR, "templates", "hub.html")
    if os.path.exists(hub_file):
        from fastapi.responses import HTMLResponse
        with open(hub_file, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    html_file = os.path.join(BASE_DIR, "plants_index.html")
    if not os.path.exists(html_file):
        raise HTTPException(status_code=404, detail="plants_index.html not found")
    return FileResponse(html_file)


@plants_router.get("/manifest.json")
def serve_manifest():
    return _serve_manifest_response()


@plants_router.get("/sw.js")
def serve_sw():
    return _serve_sw_response()


@plants_router.get("/icon-192.png")
def serve_icon_192():
    return FileResponse(os.path.join(BASE_DIR, "icon-192.png"), media_type="image/png")


@plants_router.get("/icon-512.png")
def serve_icon_512():
    return FileResponse(os.path.join(BASE_DIR, "icon-512.png"), media_type="image/png")


@plants_router.get("/icon.svg")
def serve_icon_svg():
    response = FileResponse(os.path.join(BASE_DIR, "icon.svg"), media_type="image/svg+xml")
    response.headers["Cache-Control"] = "public, max-age=86400"
    return response


@plants_router.get("/api/list")
def list_plants(db: Session = Depends(get_db)):
    """Returns all plants with computed drinking velocity metrics and summary counts."""
    now = datetime.datetime.utcnow()
    plants = db.query(Plant).all()

    plant_items = [calculate_plant_metrics(p, now=now) for p in plants]

    urgency_ranks = {"OVERDUE": 0, "DUE_TODAY": 1, "GOOD": 2}
    plant_items.sort(key=lambda x: (urgency_ranks.get(x["urgency_status"], 3), x["hours_remaining"]))

    overdue_count = sum(1 for p in plant_items if p["urgency_status"] == "OVERDUE")
    due_today_count = sum(1 for p in plant_items if p["urgency_status"] == "DUE_TODAY")
    good_count = sum(1 for p in plant_items if p["urgency_status"] == "GOOD")

    db_locations = [p.location_group for p in plants if p.location_group]
    all_locations = ["All"]
    for loc in ["Apartment", "Terrace / Home", "Grow Light Zone"]:
        if loc not in all_locations:
            all_locations.append(loc)
    for loc in db_locations:
        if loc and loc not in all_locations:
            all_locations.append(loc)

    return {
        "summary": {
            "total": len(plant_items),
            "overdue": overdue_count,
            "due_today": due_today_count,
            "good": good_count
        },
        "locations": all_locations,
        "plants": plant_items
    }


@plants_router.post("/api/plants")
def create_plant(payload: PlantCreate, db: Session = Depends(get_db)):
    plant = Plant(
        name=payload.name.strip(),
        species_or_type=payload.species_or_type.strip() if payload.species_or_type else None,
        location_group=payload.location_group.strip() if payload.location_group else "Apartment",
        pot_size_liters=payload.pot_size_liters,
        growth_stage=payload.growth_stage or "Vegetative",
        initial_interval_hours=payload.initial_interval_hours or 72.0,
        created_at=datetime.datetime.utcnow()
    )
    db.add(plant)
    db.commit()
    db.refresh(plant)
    return calculate_plant_metrics(plant)


@plants_router.get("/api/plants/{plant_id}")
def get_plant_details(plant_id: int, db: Session = Depends(get_db)):
    plant = db.query(Plant).filter(Plant.id == plant_id).first()
    if not plant:
        raise HTTPException(status_code=404, detail="Plant not found")

    metrics = calculate_plant_metrics(plant)

    sorted_logs_desc = sorted(
        plant.watering_logs or [],
        key=lambda l: (normalize_utc(l.watered_at) or datetime.datetime.min, l.id or 0),
        reverse=True
    )
    sorted_logs_asc = list(reversed(sorted_logs_desc))

    logs_data = []
    for log in sorted_logs_desc:
        watered_dt = normalize_utc(log.watered_at)
        logs_data.append({
            "id": log.id,
            "watered_at": watered_dt.isoformat() if watered_dt else None,
            "soil_state": log.soil_state,
            "raw_elapsed_hours": log.raw_elapsed_hours,
            "raw_elapsed_days": round(log.raw_elapsed_hours / 24.0, 1) if log.raw_elapsed_hours else None,
            "effective_interval_hours": log.effective_interval_hours,
            "effective_interval_days": round(log.effective_interval_hours / 24.0, 1) if log.effective_interval_hours else None,
            "notes": log.notes,
            "watered_by": getattr(log, 'watered_by', None) or "Tamir"
        })

    chart_points = [
        {
            "id": log.id,
            "watered_at": normalize_utc(log.watered_at).strftime("%b %d"),
            "effective_hours": log.effective_interval_hours,
            "effective_days": round(log.effective_interval_hours / 24.0, 1) if log.effective_interval_hours else 0,
            "soil_state": log.soil_state
        }
        for log in sorted_logs_asc
        if log.effective_interval_hours is not None
    ]

    return {
        "plant": metrics,
        "logs": logs_data,
        "sparkline": chart_points
    }


@plants_router.patch("/api/plants/{plant_id}")
def update_plant(plant_id: int, payload: PlantUpdate, db: Session = Depends(get_db)):
    plant = db.query(Plant).filter(Plant.id == plant_id).first()
    if not plant:
        raise HTTPException(status_code=404, detail="Plant not found")

    if payload.name is not None:
        plant.name = payload.name.strip()
    if payload.species_or_type is not None:
        plant.species_or_type = payload.species_or_type.strip()
    if payload.location_group is not None:
        plant.location_group = payload.location_group.strip()
    if payload.pot_size_liters is not None:
        plant.pot_size_liters = payload.pot_size_liters
    if payload.growth_stage is not None:
        plant.growth_stage = payload.growth_stage
    if payload.initial_interval_hours is not None:
        plant.initial_interval_hours = payload.initial_interval_hours

    db.commit()
    db.refresh(plant)
    return calculate_plant_metrics(plant)


@plants_router.delete("/api/plants/{plant_id}")
def delete_plant(plant_id: int, db: Session = Depends(get_db)):
    plant = db.query(Plant).filter(Plant.id == plant_id).first()
    if not plant:
        raise HTTPException(status_code=404, detail="Plant not found")
    db.delete(plant)
    db.commit()
    return {"status": "ok", "message": f"Plant '{plant.name}' deleted"}


@plants_router.post("/api/water/{plant_id}")
def water_plant(plant_id: int, payload: WaterLogCreate, request: Request, db: Session = Depends(get_db)):
    plant = db.query(Plant).filter(Plant.id == plant_id).first()
    if not plant:
        raise HTTPException(status_code=404, detail="Plant not found")

    active_user = get_active_profile(request)
    watered_at = normalize_utc(payload.watered_at) if payload.watered_at else get_utc_now()

    # Query previous_log BEFORE inserting the new log (prevents self-comparison)
    previous_log = (
        db.query(WateringLog)
        .filter(WateringLog.plant_id == plant_id)
        .order_by(WateringLog.watered_at.desc(), WateringLog.id.desc())
        .first()
    )

    initial_interval = max(12.0, float(plant.initial_interval_hours or 72.0))
    state = payload.soil_state.lower().strip()
    mult = 1.20 if state == "damp" else (0.80 if state == "bone_dry" else 1.00)

    if previous_log:
        prev_watered = normalize_utc(previous_log.watered_at)
        diff_hours = max(0.0, (watered_at - prev_watered).total_seconds() / 3600.0)
        raw_elapsed = round(diff_hours, 2)
        if diff_hours < 6.0:
            # Rapid log / double-tap protection: inherit previous valid effective interval
            prev_eff = previous_log.effective_interval_hours
            effective_interval = round(float(prev_eff) if (prev_eff and prev_eff >= 12.0) else initial_interval, 2)
        else:
            effective_interval = round(max(12.0, diff_hours * mult), 2)
    else:
        raw_elapsed = None
        effective_interval = None

    new_log = WateringLog(
        plant_id=plant_id,
        watered_at=watered_at,
        soil_state=state,
        raw_elapsed_hours=raw_elapsed,
        effective_interval_hours=effective_interval,
        notes=payload.notes.strip() if payload.notes else None,
        watered_by=active_user
    )
    db.add(new_log)
    plant.last_notified_at = None
    db.commit()

    recompute_plant_intervals(plant_id, db)
    db.refresh(plant)

    return {
        "status": "ok",
        "message": f"Logged watering for {plant.name}",
        "plant": calculate_plant_metrics(plant)
    }


@plants_router.put("/api/logs/{log_id}")
def edit_watering_log(log_id: int, payload: WaterLogUpdate, db: Session = Depends(get_db)):
    log = db.query(WateringLog).filter(WateringLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="Log entry not found")

    if payload.soil_state is not None:
        log.soil_state = payload.soil_state.lower().strip()
    if payload.notes is not None:
        log.notes = payload.notes.strip()
    if payload.watered_at is not None:
        log.watered_at = normalize_utc(payload.watered_at)

    db.commit()
    recompute_plant_intervals(log.plant_id, db)

    plant = db.query(Plant).filter(Plant.id == log.plant_id).first()
    return {
        "status": "ok",
        "message": "Watering log updated",
        "plant": calculate_plant_metrics(plant) if plant else None
    }


@plants_router.delete("/api/logs/{log_id}")
def delete_watering_log(log_id: int, db: Session = Depends(get_db)):
    log = db.query(WateringLog).filter(WateringLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="Log entry not found")

    plant_id = log.plant_id
    db.delete(log)
    db.commit()

    recompute_plant_intervals(plant_id, db)
    plant = db.query(Plant).filter(Plant.id == plant_id).first()
    return {
        "status": "ok",
        "message": "Watering log deleted",
        "plant": calculate_plant_metrics(plant) if plant else None
    }


# ===================== NOTIFICATION ROUTES =====================
@plants_router.get("/api/notifications/vapid-public-key")
def get_vapid_public_key(db: Session = Depends(get_db)):
    """Returns the application VAPID public key for browser push subscription."""
    pub_key, _ = get_or_create_vapid(db)
    return {"public_key": pub_key}


@plants_router.post("/api/notifications/subscribe")
def subscribe_notifications(payload: PushSubscriptionCreate, db: Session = Depends(get_db)):
    """Registers a mobile device / browser for watering alerts."""
    sub = db.query(PushSubscription).filter(PushSubscription.endpoint == payload.endpoint).first()
    if not sub:
        sub = PushSubscription(
            endpoint=payload.endpoint,
            p256dh=payload.keys.p256dh,
            auth=payload.keys.auth,
            user_agent=payload.user_agent,
            created_at=datetime.datetime.utcnow()
        )
        db.add(sub)
    else:
        sub.p256dh = payload.keys.p256dh
        sub.auth = payload.keys.auth
        if payload.user_agent:
            sub.user_agent = payload.user_agent

    db.commit()
    return {"status": "ok", "message": "Device registered for watering reminders"}


@plants_router.post("/api/notifications/unsubscribe")
def unsubscribe_notifications(payload: PushUnsubscribe, db: Session = Depends(get_db)):
    """Unregisters a device from notifications."""
    sub = db.query(PushSubscription).filter(PushSubscription.endpoint == payload.endpoint).first()
    if sub:
        db.delete(sub)
        db.commit()
    return {"status": "ok", "message": "Device unregistered"}


@plants_router.post("/api/notifications/test")
def test_notification(db: Session = Depends(get_db)):
    """Dispatches an instant test push notification to verify phone reception."""
    subs = db.query(PushSubscription).all()
    if not subs:
        raise HTTPException(
            status_code=400,
            detail="No devices registered for notifications yet. Tap 'Turn On Phone Reminders' first!"
        )

    title = "🌿 Tmimer's Plants Alert Test"
    body = "Watering reminders are active! You will receive alerts when your plants are due."
    sent = 0
    for s in subs:
        if send_push_notification(s, title=title, body=body, url="/plants", db=db):
            sent += 1

    return {"status": "ok", "message": f"Test alert dispatched to {sent} device(s)!"}


@plants_router.get("/api/notifications/status")
def notification_status(db: Session = Depends(get_db)):
    """Returns subscription count and notification readiness."""
    count = db.query(PushSubscription).count()
    return {
        "active_devices": count,
        "enabled": count > 0
    }
