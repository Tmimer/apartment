import os
from fastapi import APIRouter
from database import engine, db_connection_error

health_router = APIRouter(tags=["health"])


@health_router.get("/health")
@health_router.get("/healthz")
def healthcheck():
    """Lightweight public uptime endpoint for Render, UptimeRobot, etc."""
    raw_env = os.getenv("DATABASE_URL") or ""
    env_preview = raw_env[:30] if raw_env else "NOT_SET"
    db_type = "postgresql" if "postgres" in str(engine.url) else "sqlite_ephemeral"

    return {
        "status": "ok",
        "app": "Shared Apartment Hub",
        "database_type": db_type,
        "database_url_configured": bool(raw_env),
        "database_url_prefix": env_preview,
        "db_error": str(db_connection_error)
    }


@health_router.get("/health/audit-logs")
def audit_watering_logs():
    """Diagnostic check to verify database cleanliness directly in production."""
    from database import SessionLocal
    from models.plants import WateringLog
    db = SessionLocal()
    try:
        corrupted = db.query(WateringLog).filter(
            (WateringLog.raw_elapsed_hours.isnot(None) & (WateringLog.raw_elapsed_hours < 1.0)) |
            (WateringLog.effective_interval_hours.isnot(None) & (WateringLog.effective_interval_hours < 6.0))
        ).all()
        return {
            "status": "clean" if not corrupted else "corrupted_found",
            "corrupted_count": len(corrupted),
            "message": "Database is clean - no corrupted logs found." if not corrupted else f"Found {len(corrupted)} corrupted log(s)",
            "corrupted_rows": [
                {
                    "id": c.id,
                    "plant_id": c.plant_id,
                    "watered_at": c.watered_at.isoformat() if c.watered_at else None,
                    "raw_elapsed_hours": c.raw_elapsed_hours,
                    "effective_interval_hours": c.effective_interval_hours
                }
                for c in corrupted
            ]
        }
    finally:
        db.close()
