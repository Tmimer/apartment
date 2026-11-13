import datetime
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime
from database import Base

GROCERY_CATEGORIES = [
    "Produce",      # 1. Produce (Fruits & Veggies)
    "Bakery",       # 2. Bakery
    "Dairy/Eggs",   # 3. Dairy & Eggs
    "Meat/Fish",    # 4. Meat & Fish
    "Pantry/Dry",   # 5. Pantry & Dry Goods
    "Spices/Oils",  # 6. Spices & Oils
    "Household",    # 7. Household & Cleaning
    "Frozen",       # 8. Frozen
]

SUPERMARKET_WALKING_ORDER = {cat: idx for idx, cat in enumerate(GROCERY_CATEGORIES)}

GROCERY_UNITS = ["g", "kg", "ml", "L", "pcs", "pack"]


class GroceryItem(Base):
    __tablename__ = "grocery_items"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(255), nullable=False, index=True)
    amount = Column(Float, nullable=True)
    unit = Column(String(30), nullable=True)  # g, kg, ml, L, pcs, pack
    category = Column(String(50), nullable=False, default="Produce")
    default_split = Column(String(30), nullable=False, default="SHARED_50_50")  # SHARED_50_50 | MIKUSH_100 | TAMIR_100
    typical_depletion_days = Column(Integer, nullable=True)
    for_member = Column(String(50), nullable=True)  # Optional tag e.g. "Mikush" for Solo Shopper mode
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
    avg_interval_days = Column(Float, nullable=True)


class GroceryPurchaseHistory(Base):
    __tablename__ = "grocery_purchase_history"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    item_name = Column(String(255), nullable=False)
    normalized_name = Column(String(255), nullable=False, index=True)
    category = Column(String(50), nullable=False, default="Pantry/Dry")
    amount = Column(Float, nullable=True)
    unit = Column(String(30), nullable=True)
    source = Column(String(30), nullable=False, default="grocery_check")  # grocery_check | receipt_scan | brain_dump
    purchased_by = Column(String(50), nullable=False, default="Tamir")
    purchased_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False, index=True)
