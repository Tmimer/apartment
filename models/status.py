import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime
from database import Base


class ApartmentStatusNote(Base):
    __tablename__ = "apartment_status_notes"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    message = Column(Text, nullable=False)
    author = Column(String(50), nullable=False, default="Tamir")
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
