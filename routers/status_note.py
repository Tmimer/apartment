import datetime
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from database import get_db
from models.status import ApartmentStatusNote
from security import require_auth_api, get_active_profile

status_note_router = APIRouter(prefix="/api/status-note", tags=["status-note"])

DEFAULT_NOTE = "Welcome home! Tap here to leave a note for each other 💌"


class NoteUpdatePayload(BaseModel):
    message: str = Field(..., min_length=1, max_length=500)


def format_time_ago(dt: datetime.datetime) -> str:
    if not dt:
        return "recently"
    now = datetime.datetime.utcnow()
    diff = now - dt
    total_seconds = int(diff.total_seconds())
    if total_seconds < 60:
        return "just now"
    minutes = total_seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"


@status_note_router.get("", dependencies=[Depends(require_auth_api)])
def get_status_note(db: Session = Depends(get_db)):
    note = db.query(ApartmentStatusNote).order_by(ApartmentStatusNote.id.desc()).first()
    if not note:
        now = datetime.datetime.utcnow()
        note = ApartmentStatusNote(message=DEFAULT_NOTE, author="Apartment", updated_at=now)
        db.add(note)
        db.commit()
        db.refresh(note)

    return {
        "id": note.id,
        "message": note.message,
        "author": note.author,
        "updated_at": note.updated_at.isoformat() if note.updated_at else None,
        "time_ago": format_time_ago(note.updated_at)
    }


@status_note_router.post("", dependencies=[Depends(require_auth_api)])
def update_status_note(payload: NoteUpdatePayload, request: Request, db: Session = Depends(get_db)):
    active_user = get_active_profile(request)
    now = datetime.datetime.utcnow()
    note = db.query(ApartmentStatusNote).order_by(ApartmentStatusNote.id.desc()).first()
    clean_msg = payload.message.strip()
    if not clean_msg:
        raise HTTPException(status_code=400, detail="Note cannot be empty")

    if not note:
        note = ApartmentStatusNote(message=clean_msg, author=active_user, updated_at=now)
        db.add(note)
    else:
        note.message = clean_msg
        note.author = active_user
        note.updated_at = now

    db.commit()
    db.refresh(note)

    return {
        "status": "ok",
        "message": f"Updated fridge note by {active_user}!",
        "note": {
            "id": note.id,
            "message": note.message,
            "author": note.author,
            "updated_at": note.updated_at.isoformat() if note.updated_at else None,
            "time_ago": "just now"
        }
    }
