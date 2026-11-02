import os
from typing import Optional
from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

db_connection_error = None


def get_configured_engine(raw_url: Optional[str] = None):
    global db_connection_error
    url = (raw_url or os.getenv("DATABASE_URL") or "").strip()
    if url:
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+psycopg2://", 1)
        elif url.startswith("postgresql://") and not url.startswith("postgresql+"):
            url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
        try:
            connect_args = {"connect_timeout": 10} if "postgresql" in url else {}
            eng = create_engine(url, pool_pre_ping=True, connect_args=connect_args)
            return eng
        except Exception as e:
            db_connection_error = str(e)
            print(f"[!] Failed to configure PostgreSQL engine: {e}")

    # Fallback to local SQLite database
    sqlite_path = os.path.join(BASE_DIR, "plants_tracker.db")
    fallback_url = f"sqlite:///{sqlite_path}"
    eng = create_engine(fallback_url, connect_args={"check_same_thread": False})

    @event.listens_for(eng, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.close()

    return eng


engine = get_configured_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
