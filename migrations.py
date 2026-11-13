from database import engine, Base
from sqlalchemy import text


def _ensure_column(conn, table_name: str, col_name: str, sqlite_def: str, pg_def: str):
    """Idempotently adds a column to an existing table across SQLite and PostgreSQL."""
    if engine.dialect.name == "sqlite":
        cols = conn.execute(text(f"PRAGMA table_info({table_name});")).fetchall()
        col_names = [c[1] for c in cols]
        if col_names and col_name not in col_names:
            conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {sqlite_def};"))
            print(f"[+] Added column {table_name}.{col_name} (SQLite)")
    else:
        conn.execute(text(
            f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {col_name} {pg_def};"
        ))


def auto_migrate_schema():
    """Ensures all tables & newly added columns exist in both PostgreSQL (Supabase) and SQLite."""
    try:
        # Ensure all registered SQLAlchemy models/tables exist (safe no-op for existing tables)
        import models  # noqa: F401
        Base.metadata.create_all(bind=engine)
    except Exception as e:
        print(f"[!] auto_migrate_schema create_all note: {e}")

    try:
        with engine.begin() as conn:
            # 1. Existing upgrades
            _ensure_column(conn, "meal_plans", "is_double_batch", "BOOLEAN DEFAULT 0", "BOOLEAN DEFAULT FALSE")
            _ensure_column(conn, "watering_logs", "watered_by", "VARCHAR(50) DEFAULT 'Tamir'", "VARCHAR(50) DEFAULT 'Tamir'")

            # 2. Zero-Entry Suite upgrades on existing grocery tables
            _ensure_column(conn, "grocery_items", "for_member", "VARCHAR(50) DEFAULT NULL", "VARCHAR(50) DEFAULT NULL")
            _ensure_column(conn, "grocery_items", "default_split", "VARCHAR(30) DEFAULT 'SHARED_50_50'", "VARCHAR(30) DEFAULT 'SHARED_50_50'")
            _ensure_column(conn, "grocery_items", "typical_depletion_days", "INTEGER DEFAULT NULL", "INTEGER DEFAULT NULL")
            _ensure_column(conn, "grocery_staples", "avg_interval_days", "FLOAT DEFAULT NULL", "DOUBLE PRECISION DEFAULT NULL")

            # Update Olive Oil staple to Spices/Oils aisle if still under Pantry/Dry
            try:
                conn.execute(text(
                    "UPDATE grocery_staples SET category = 'Spices/Oils' "
                    "WHERE LOWER(name) = 'olive oil' AND category = 'Pantry/Dry';"
                ))
            except Exception:
                pass

            # Clean up uncompleted maintenance task attributions if any exist
            try:
                conn.execute(text("UPDATE maintenance_tasks SET last_completed_by = NULL WHERE last_completed_at IS NULL;"))
            except Exception:
                pass
    except Exception as e:
        print(f"[!] auto_migrate_schema warning: {e}")

    # Backfill grocery_purchase_history from existing checked items if history table is empty
    try:
        from database import SessionLocal
        from models.groceries import GroceryItem, GroceryPurchaseHistory
        db = SessionLocal()
        try:
            if db.query(GroceryPurchaseHistory).count() == 0:
                checked_items = (
                    db.query(GroceryItem)
                    .filter(GroceryItem.is_checked == True, GroceryItem.checked_at != None)
                    .all()
                )
                for it in checked_items:
                    norm = (it.name or "").strip().lower()
                    if norm:
                        db.add(GroceryPurchaseHistory(
                            item_name=it.name.strip(),
                            normalized_name=norm,
                            category=it.category or "Pantry/Dry",
                            amount=it.amount,
                            unit=it.unit,
                            source="grocery_check",
                            purchased_by=it.added_by or "Tamir",
                            purchased_at=it.checked_at
                        ))
                if checked_items:
                    db.commit()
                    print(f"[+] Backfilled {len(checked_items)} purchase history records for Depletion Radar")
        finally:
            db.close()
    except Exception as e:
        print(f"[!] auto_migrate_schema purchase history backfill note: {e}")

    # Startup repair check for corrupted watering logs (self-comparison / near-zero elapsed time)
    try:
        from database import SessionLocal
        from routers.plants import repair_corrupted_watering_logs
        db = SessionLocal()
        try:
            repair_corrupted_watering_logs(db)
        finally:
            db.close()
    except Exception as e:
        print(f"[!] auto_migrate_schema plant repair note: {e}")
