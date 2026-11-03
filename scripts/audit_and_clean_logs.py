import os
import sys

# Ensure repository root is in python path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from database import engine, SessionLocal, get_configured_engine
from models.plants import Plant, WateringLog
from routers.plants import recompute_plant_intervals, normalize_utc


def audit_and_clean_logs(custom_db_url: str = None):
    # Support explicit DATABASE_URL parameter or environment variable
    db_url = custom_db_url or os.getenv("DATABASE_URL")
    if db_url:
        print(f"[*] Connecting to database specified by DATABASE_URL ({db_url[:28]}...)...")
        active_engine = get_configured_engine(db_url)
        from sqlalchemy.orm import sessionmaker
        Session = sessionmaker(autocommit=False, autoflush=False, bind=active_engine)
        db = Session()
    else:
        print(f"[*] Using application configured database engine ({engine.url})...")
        db = SessionLocal()

    try:
        # 1. Query watering_logs for any rows where raw_elapsed_hours < 1.0 or effective_interval_hours < 6.0
        corrupted_logs = (
            db.query(WateringLog)
            .filter(
                (WateringLog.raw_elapsed_hours.isnot(None) & (WateringLog.raw_elapsed_hours < 1.0)) |
                (WateringLog.effective_interval_hours.isnot(None) & (WateringLog.effective_interval_hours < 6.0))
            )
            .order_by(WateringLog.plant_id.asc(), WateringLog.watered_at.asc(), WateringLog.id.asc())
            .all()
        )

        # 2. If zero corrupted rows are found
        if not corrupted_logs:
            print("Database is clean - no corrupted logs found.")
            return 0

        # 3. If corrupted rows exist: print and clean
        print(f"[!] Found {len(corrupted_logs)} corrupted watering log(s):")
        affected_plant_ids = set()
        deleted_count = 0
        recalculated_count = 0

        for log in corrupted_logs:
            watered_str = log.watered_at.isoformat() if log.watered_at else "Unknown"
            print(
                f"  -> Offending row: ID={log.id}, plant_id={log.plant_id}, "
                f"watered_at={watered_str}, raw_elapsed_hours={log.raw_elapsed_hours}, "
                f"effective_interval_hours={log.effective_interval_hours}"
            )
            affected_plant_ids.add(log.plant_id)

            # If raw_elapsed_hours < 1.0, it is a duplicate rapid-fire log (< 60 mins from prior log)
            if log.raw_elapsed_hours is not None and log.raw_elapsed_hours < 1.0:
                print(f"     [Action] Deleting duplicate rapid-fire log ID={log.id} ({log.raw_elapsed_hours}h from previous log)")
                db.delete(log)
                deleted_count += 1
            else:
                recalculated_count += 1

        db.commit()

        # Recalculate effective_interval_hours for all affected plants against true prior logs
        for plant_id in sorted(affected_plant_ids):
            recompute_plant_intervals(plant_id, db)

        db.commit()

        # Final verification query
        remaining = (
            db.query(WateringLog)
            .filter(
                (WateringLog.raw_elapsed_hours.isnot(None) & (WateringLog.raw_elapsed_hours < 1.0)) |
                (WateringLog.effective_interval_hours.isnot(None) & (WateringLog.effective_interval_hours < 6.0))
            )
            .count()
        )

        total_cleaned = deleted_count + recalculated_count
        print(f"[+] Audit complete: Cleaned {total_cleaned} row(s) (Deleted duplicate rapid logs: {deleted_count}, Recalculated: {recalculated_count}).")
        print(f"[+] Remaining corrupted logs: {remaining}")
        return total_cleaned

    finally:
        db.close()


if __name__ == "__main__":
    audit_and_clean_logs()
