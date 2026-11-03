import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime
from database import Base


class DateSpot(Base):
    __tablename__ = "date_spots"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    category = Column(String(100), nullable=False, default="Food & Drinks")  # Food & Drinks, Coffee & Dessert, Activity, Outdoors / Trip
    location_area = Column(String(150), nullable=True)
    vibe_tags = Column(String(255), nullable=True)  # comma-separated e.g. "cozy,sweet,casual,fancy,late-night"
    status = Column(String(50), nullable=False, default="wishlist")  # wishlist | visited
    tamir_verdict = Column(String(50), nullable=True)  # loved | okay | skip | None
    mikush_verdict = Column(String(50), nullable=True)  # loved | okay | skip | None
    highlight_notes = Column(Text, nullable=True)
    added_by = Column(String(50), nullable=False, default="Tamir")
    last_visited_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class RandomizerPreset(Base):
    __tablename__ = "randomizer_presets"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    title = Column(String(150), nullable=False)
    options_json = Column(Text, nullable=False)  # JSON-encoded array of string options
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
