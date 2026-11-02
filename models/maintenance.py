import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text
from database import Base


class MaintenanceTask(Base):
    __tablename__ = "maintenance_tasks"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    title = Column(String(255), nullable=False)
    category = Column(String(100), nullable=False, default="General")
    interval_days = Column(Integer, nullable=False, default=30)
    last_completed_at = Column(DateTime, nullable=True)
    last_completed_by = Column(String(50), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
