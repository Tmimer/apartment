import datetime
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime
from database import Base

GROCERY_CATEGORIES = [
    "Produce",
    "Bakery",
    "Meat/Fish",
    "Dairy/Eggs",
    "Pantry/Dry",
    "Frozen",
    "Household"
]

GROCERY_UNITS = ["g", "kg", "ml", "L", "pcs", "pack"]


class GroceryItem(Base):
    __tablename__ = "grocery_items"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(255), nullable=False, index=True)
    amount = Column(Float, nullable=True)
    unit = Column(String(30), nullable=True)  # g, kg, ml, L, pcs, pack
    category = Column(String(50), nullable=False, default="Produce")
    is_checked = Column(Boolean, nullable=False, default=False, index=True)
    checked_at = Column(DateTime, nullable=True)
    added_by = Column(String(50), nullable=False, default="Tamir")
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class GroceryStaple(Base):
    __tablename__ = "grocery_staples"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(255), nullable=False, unique=True)
    default_amount = Column(Float, nullable=True)
    default_unit = Column(String(30), nullable=True)
    category = Column(String(50), nullable=False, default="Pantry/Dry")
    icon_emoji = Column(String(10), nullable=True)
    display_order = Column(Integer, default=0)
