import os
import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from models.meals import Meal, MealIngredient, MealPlan
from security import require_auth_api

meals_router = APIRouter(prefix="/meals", tags=["meals"])

DAYS_OF_WEEK = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]


@meals_router.get("")
@meals_router.get("/")
def meals_page(request: Request):
    """Serves the unified apartment hub with meals tab active."""
    from plants_app import serve_hub_shell
    return serve_hub_shell(request, default_tab="meals")


@meals_router.get("/api/plan", dependencies=[Depends(require_auth_api)])
def get_weekly_plan(db: Session = Depends(get_db)):
    """Returns the weekly planner entries and saved meals."""
    meals = db.query(Meal).order_by(Meal.title.asc()).all()
    plans = db.query(MealPlan).all()

    plan_by_day = {day: None for day in DAYS_OF_WEEK}
    for p in plans:
        if p.day_of_week in plan_by_day:
            plan_by_day[p.day_of_week] = {
                "id": p.id,
                "meal_id": p.meal_id,
                "meal_title": p.meal.title if p.meal else p.custom_title,
                "custom_title": p.custom_title,
                "is_leftovers": p.is_leftovers,
                "notes": p.notes
            }

    return {
        "days": DAYS_OF_WEEK,
        "weekly_plan": plan_by_day,
        "saved_meals_count": len(meals)
    }
