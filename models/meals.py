import datetime
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from database import Base


class Meal(Base):
    __tablename__ = "meals"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    title = Column(String(255), nullable=False)
    notes = Column(Text, nullable=True)
    prep_time_min = Column(Integer, nullable=True)
    created_by = Column(String(50), nullable=False, default="Tamir")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    ingredients = relationship(
        "MealIngredient",
        back_populates="meal",
        cascade="all, delete-orphan",
        order_by="MealIngredient.id.asc()"
    )
    meal_plans = relationship("MealPlan", back_populates="meal")


class MealIngredient(Base):
    __tablename__ = "meal_ingredients"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    meal_id = Column(Integer, ForeignKey("meals.id", ondelete="CASCADE"), nullable=False, index=True)
    ingredient_name = Column(String(255), nullable=False)
    amount = Column(Float, nullable=True)
    unit = Column(String(30), nullable=True)
    category = Column(String(50), nullable=False, default="Produce")

    meal = relationship("Meal", back_populates="ingredients")


class MealPlan(Base):
    __tablename__ = "meal_plans"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    day_of_week = Column(String(20), nullable=False, index=True)  # Sunday, Monday, etc.
    meal_id = Column(Integer, ForeignKey("meals.id", ondelete="SET NULL"), nullable=True)
    custom_title = Column(String(255), nullable=True)
    is_leftovers = Column(Boolean, nullable=False, default=False)
    notes = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    meal = relationship("Meal", back_populates="meal_plans")
