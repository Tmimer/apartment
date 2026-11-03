import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from models.maintenance import MaintenanceTask
from security import require_auth_api, get_active_profile

maintenance_router = APIRouter(prefix="/maintenance", tags=["maintenance"])

# ===================== PRE-SEEDED DEFAULT TASKS =====================
DEFAULT_MAINTENANCE_TASKS = [
    {
        "title": "Wash Bedsheets",
        "category": "Bedroom",
        "interval_days": 10,
        "notes": "Strip bed, wash pillowcases and duvet cover at 60°C."
    },
    {
        "title": "Descale Kettle / Coffee",
        "category": "Kitchen",
        "interval_days": 30,
        "notes": "Run white vinegar or citric acid cycle and rinse twice."
    },
    {
        "title": "Clean Washing Machine Filter",
        "category": "Bathroom",
        "interval_days": 45,
        "notes": "Drain front bottom catch, rinse mesh filter, and clean rubber door seal."
    },
    {
        "title": "Clean AC Mesh Filters",
        "category": "Living Room",
        "interval_days": 60,
        "notes": "Pop open front AC unit covers, rinse plastic dust filters under shower, dry thoroughly."
    },
    {
        "title": "Pantry & Dry Goods Check",
        "category": "Kitchen",
        "interval_days": 30,
        "notes": "Check for open pasta/flour bugs, expired canned goods, wipe shelves."
    }
]


def ensure_starter_tasks(db: Session):
    """Pre-seeds default tasks if the maintenance_tasks table is empty, and cleans up empty attributions."""
    count = db.query(func.count(MaintenanceTask.id)).scalar()
    now = datetime.datetime.utcnow()
    if count == 0:
        for t in DEFAULT_MAINTENANCE_TASKS:
            task = MaintenanceTask(
                title=t["title"],
                category=t["category"],
                interval_days=t["interval_days"],
                notes=t.get("notes"),
                last_completed_at=None,
                last_completed_by=None,
                created_at=now
            )
            db.add(task)
        db.commit()


def cleanup_default_attributions(db: Session):
    """Safe startup cleanup: any task without a legitimate last_completed_at must have last_completed_by=None."""
    try:
        tasks = db.query(MaintenanceTask).filter(MaintenanceTask.last_completed_at == None).all()
        for t in tasks:
            if t.last_completed_by is not None:
                t.last_completed_by = None
        db.commit()
    except Exception as e:
        print(f"[!] Warning during maintenance task cleanup: {e}")


# ===================== PYDANTIC SCHEMAS =====================
class MaintenanceTaskCreatePayload(BaseModel):
    title: str = Field(..., min_length=1)
    category: Optional[str] = "General"
    interval_days: int = Field(..., ge=1, le=365)
    notes: Optional[str] = None


class MaintenanceTaskUpdatePayload(BaseModel):
    title: Optional[str] = None
    category: Optional[str] = None
    interval_days: Optional[int] = Field(None, ge=1, le=365)
    notes: Optional[str] = None


# ===================== API ENDPOINTS =====================
@maintenance_router.get("/api/tasks", dependencies=[Depends(require_auth_api)])
def get_maintenance_tasks(db: Session = Depends(get_db)):
    """
    Returns all maintenance tasks with safe urgency status:
    - Never completed tasks show days_elapsed since creation (or 0) without fake attribution.
    - Completed tasks show days_elapsed since last_completed_at.
    - Sorted with overdue and due soon tasks first.
    """
    ensure_starter_tasks(db)
    cleanup_default_attributions(db)
    tasks = db.query(MaintenanceTask).all()
    now = datetime.datetime.utcnow()

    task_list = []
    for t in tasks:
        is_completed = t.last_completed_at is not None
        interval = max(1, t.interval_days)

        if is_completed:
            reference_date = t.last_completed_at
            days_elapsed = max(0, (now - reference_date).days)
            progress_pct = min(100, round((days_elapsed / interval) * 100))
            if days_elapsed >= interval:
                urgency = "OVERDUE"
                sort_score = 300 + (days_elapsed - interval)
            elif progress_pct >= 75:
                urgency = "DUE_SOON"
                sort_score = 200 + progress_pct
            else:
                urgency = "GOOD"
                sort_score = progress_pct
            days_remaining = interval - days_elapsed
        else:
            # Never completed yet - safe math without crash
            created_ref = t.created_at or now
            days_elapsed = max(0, (now - created_ref).days)
            progress_pct = min(100, round((days_elapsed / interval) * 100))
            if days_elapsed >= interval:
                urgency = "OVERDUE"
                sort_score = 280 + days_elapsed
            elif progress_pct >= 60:
                urgency = "DUE_SOON"
                sort_score = 180 + progress_pct
            else:
                urgency = "GOOD"
                sort_score = progress_pct
            days_remaining = max(0, interval - days_elapsed)

        task_list.append({
            "id": t.id,
            "title": t.title,
            "category": t.category,
            "interval_days": t.interval_days,
            "last_completed_at": t.last_completed_at.isoformat() if t.last_completed_at else None,
            "last_completed_by": t.last_completed_by if is_completed else None,
            "is_completed": is_completed,
            "notes": t.notes,
            "days_elapsed": days_elapsed,
            "days_remaining": days_remaining,
            "progress_pct": progress_pct,
            "urgency": urgency,
            "_sort_score": sort_score
        })

    # Sort descending by urgency score (overdue first)
    task_list.sort(key=lambda x: x["_sort_score"], reverse=True)
    for item in task_list:
        del item["_sort_score"]

    return {
        "tasks": task_list,
        "total": len(task_list),
        "overdue_count": sum(1 for t in task_list if t["urgency"] == "OVERDUE"),
        "due_soon_count": sum(1 for t in task_list if t["urgency"] == "DUE_SOON")
    }


@maintenance_router.post("/api/complete/{task_id}", dependencies=[Depends(require_auth_api)])
def complete_maintenance_task(task_id: int, request: Request, db: Session = Depends(get_db)):
    """Marks a task as completed now with the active user profile."""
    task = db.query(MaintenanceTask).filter(MaintenanceTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Maintenance task not found")

    active_user = get_active_profile(request)
    now = datetime.datetime.utcnow()

    task.last_completed_at = now
    task.last_completed_by = active_user
    db.commit()
    db.refresh(task)

    return {
        "status": "ok",
        "message": f"'{task.title}' marked as completed by {active_user}!",
        "task": {
            "id": task.id,
            "title": task.title,
            "last_completed_at": task.last_completed_at.isoformat(),
            "last_completed_by": task.last_completed_by
        }
    }


@maintenance_router.post("/api/reset/{task_id}", dependencies=[Depends(require_auth_api)])
def reset_maintenance_task(task_id: int, db: Session = Depends(get_db)):
    """Resets a task back to uncompleted state (last_completed_at=None, last_completed_by=None)."""
    task = db.query(MaintenanceTask).filter(MaintenanceTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Maintenance task not found")

    task.last_completed_at = None
    task.last_completed_by = None
    db.commit()
    db.refresh(task)

    return {
        "status": "ok",
        "message": f"Reset '{task.title}' to not completed yet",
        "task": {
            "id": task.id,
            "title": task.title,
            "last_completed_at": None,
            "last_completed_by": None
        }
    }


@maintenance_router.post("/api/tasks", dependencies=[Depends(require_auth_api)])
def create_maintenance_task(payload: MaintenanceTaskCreatePayload, db: Session = Depends(get_db)):
    """Creates a new recurring maintenance task with uncompleted initial state."""
    now = datetime.datetime.utcnow()
    new_task = MaintenanceTask(
        title=payload.title.strip(),
        category=payload.category.strip() if payload.category else "General",
        interval_days=payload.interval_days,
        notes=payload.notes.strip() if payload.notes else None,
        last_completed_at=None,
        last_completed_by=None,
        created_at=now
    )
    db.add(new_task)
    db.commit()
    db.refresh(new_task)

    return {
        "status": "ok",
        "message": f"Added maintenance task '{new_task.title}'",
        "task_id": new_task.id
    }


@maintenance_router.delete("/api/tasks/{task_id}", dependencies=[Depends(require_auth_api)])
def delete_maintenance_task(task_id: int, db: Session = Depends(get_db)):
    """Deletes a maintenance task."""
    task = db.query(MaintenanceTask).filter(MaintenanceTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Maintenance task not found")

    title = task.title
    db.delete(task)
    db.commit()

    return {"status": "ok", "message": f"Deleted task '{title}'"}
