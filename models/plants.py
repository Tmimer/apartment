import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from database import Base


class Plant(Base):
    __tablename__ = "plants"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String, nullable=False)
    species_or_type = Column(String, nullable=True)
    location_group = Column(String, nullable=True)
    pot_size_liters = Column(Float, nullable=True)
    growth_stage = Column(String, nullable=True)
    initial_interval_hours = Column(Float, nullable=False, default=168.0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_notified_at = Column(DateTime, nullable=True)

    watering_logs = relationship(
        "WateringLog",
        back_populates="plant",
        cascade="all, delete-orphan",
        order_by="WateringLog.watered_at.desc()"
    )


class WateringLog(Base):
    __tablename__ = "watering_logs"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    plant_id = Column(Integer, ForeignKey("plants.id", ondelete="CASCADE"), nullable=False, index=True)
    watered_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    soil_state = Column(String, nullable=False)  # "damp" | "ideal" | "bone_dry"
    raw_elapsed_hours = Column(Float, nullable=True)
    effective_interval_hours = Column(Float, nullable=True)
    notes = Column(String, nullable=True)
    watered_by = Column(String(50), nullable=True, default="Tamir")

    plant = relationship("Plant", back_populates="watering_logs")


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    endpoint = Column(String, unique=True, index=True, nullable=False)
    p256dh = Column(String, nullable=False)
    auth = Column(String, nullable=False)
    user_agent = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True)


class AppConfig(Base):
    __tablename__ = "app_config"

    key = Column(String, primary_key=True, index=True)
    value = Column(String, nullable=False)
