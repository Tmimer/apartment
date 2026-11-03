from database import engine
from sqlalchemy import text

def auto_migrate_schema():
    """Ensures newly added columns exist in both PostgreSQL (Supabase) and SQLite."""
    try:
        with engine.begin() as conn:
            if engine.dialect.name == "sqlite":
                # 1. meal_plans.is_double_batch
                cols = conn.execute(text("PRAGMA table_info(meal_plans);")).fetchall()
                col_names = [c[1] for c in cols]
                if "is_double_batch" not in col_names:
                    conn.execute(text("ALTER TABLE meal_plans ADD COLUMN is_double_batch BOOLEAN DEFAULT 0;"))
                    print("[+] Added column meal_plans.is_double_batch (SQLite)")

                # 2. watering_logs.watered_by
                wcols = conn.execute(text("PRAGMA table_info(watering_logs);")).fetchall()
                wcol_names = [c[1] for c in wcols]
                if "watered_by" not in wcol_names:
                    conn.execute(text("ALTER TABLE watering_logs ADD COLUMN watered_by VARCHAR(50) DEFAULT 'Tamir';"))
                    print("[+] Added column watering_logs.watered_by (SQLite)")
            else:
                # PostgreSQL (Supabase)
                conn.execute(text(
                    "ALTER TABLE meal_plans ADD COLUMN IF NOT EXISTS is_double_batch BOOLEAN DEFAULT FALSE;"
                ))
                conn.execute(text(
                    "ALTER TABLE watering_logs ADD COLUMN IF NOT EXISTS watered_by VARCHAR(50) DEFAULT 'Tamir';"
                ))
                print("[+] Verified schema columns in PostgreSQL")

            # Clean up uncompleted maintenance task attributions if any exist
            try:
                conn.execute(text("UPDATE maintenance_tasks SET last_completed_by = NULL WHERE last_completed_at IS NULL;"))
            except Exception:
                pass
    except Exception as e:
        print(f"[!] auto_migrate_schema warning: {e}")
