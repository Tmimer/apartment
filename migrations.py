from database import engine
from sqlalchemy import text

def auto_migrate_schema():
    """Ensures newly added columns exist in both PostgreSQL (Supabase) and SQLite."""
    try:
        with engine.begin() as conn:
            # Check meal_plans table for is_double_batch column
            if engine.dialect.name == "sqlite":
                cols = conn.execute(text("PRAGMA table_info(meal_plans);")).fetchall()
                col_names = [c[1] for c in cols]
                if "is_double_batch" not in col_names:
                    conn.execute(text("ALTER TABLE meal_plans ADD COLUMN is_double_batch BOOLEAN DEFAULT 0;"))
                    print("[+] Added column meal_plans.is_double_batch (SQLite)")
            else:
                # PostgreSQL (Supabase)
                conn.execute(text(
                    "ALTER TABLE meal_plans ADD COLUMN IF NOT EXISTS is_double_batch BOOLEAN DEFAULT FALSE;"
                ))
                print("[+] Verified column meal_plans.is_double_batch (PostgreSQL)")
    except Exception as e:
        print(f"[!] auto_migrate_schema warning: {e}")
