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
