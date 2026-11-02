import os
import datetime
from typing import Optional, List, Dict
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from models.meals import Meal, MealIngredient, MealPlan
from models.groceries import GroceryItem, GROCERY_CATEGORIES
from security import require_auth_api, get_active_profile

meals_router = APIRouter(prefix="/meals", tags=["meals"])

DAYS_OF_WEEK = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]


# ===================== PYDANTIC SCHEMAS =====================
class IngredientPayload(BaseModel):
    ingredient_name: str = Field(..., min_length=1)
    amount: Optional[float] = None
    unit: Optional[str] = None
    category: Optional[str] = "Produce"


class MealCreatePayload(BaseModel):
    title: str = Field(..., min_length=1)
    notes: Optional[str] = None
    prep_time_min: Optional[int] = None
    created_by: Optional[str] = None
    ingredients: List[IngredientPayload] = []


class MealPlanUpdatePayload(BaseModel):
    meal_id: Optional[int] = None
    custom_title: Optional[str] = None
    is_leftovers: bool = False
    is_double_batch: bool = False
    notes: Optional[str] = None


# ===================== STARTER RECIPES SEEDER =====================
DEFAULT_STARTER_MEALS = [
    {
        "title": "Fresh Tomato & Basil Pasta",
        "prep_time_min": 25,
        "notes": "Classic quick weeknight pasta. Cook al dente and toss with garlic, olive oil, and fresh parmesan.",
        "ingredients": [
            {"ingredient_name": "Pasta (Spaghetti or Penne)", "amount": 500.0, "unit": "g", "category": "Pantry/Dry"},
            {"ingredient_name": "Cherry Tomatoes", "amount": 400.0, "unit": "g", "category": "Produce"},
            {"ingredient_name": "Garlic", "amount": 3.0, "unit": "pcs", "category": "Produce"},
            {"ingredient_name": "Fresh Basil", "amount": 1.0, "unit": "pack", "category": "Produce"},
            {"ingredient_name": "Parmesan Cheese", "amount": 100.0, "unit": "g", "category": "Dairy/Eggs"}
        ]
    },
    {
        "title": "Shakshuka with Warm Challah",
        "prep_time_min": 30,
        "notes": "Rich spiced tomato & pepper sauce with runny poached eggs.",
        "ingredients": [
            {"ingredient_name": "Eggs", "amount": 5.0, "unit": "pcs", "category": "Dairy/Eggs"},
            {"ingredient_name": "Crushed Tomatoes", "amount": 800.0, "unit": "g", "category": "Pantry/Dry"},
            {"ingredient_name": "Red Bell Pepper", "amount": 2.0, "unit": "pcs", "category": "Produce"},
            {"ingredient_name": "Onion", "amount": 1.0, "unit": "pcs", "category": "Produce"},
            {"ingredient_name": "Challah or Sourdough", "amount": 1.0, "unit": "pcs", "category": "Bakery"}
        ]
    },
    {
        "title": "Roasted Salmon & Sweet Potato Mash",
        "prep_time_min": 35,
        "notes": "Marinate salmon fillets in olive oil, garlic, lemon, and dill. Bake at 200°C for 16 mins.",
        "ingredients": [
            {"ingredient_name": "Salmon Fillets", "amount": 2.0, "unit": "pcs", "category": "Meat/Fish"},
            {"ingredient_name": "Sweet Potatoes", "amount": 3.0, "unit": "pcs", "category": "Produce"},
            {"ingredient_name": "Broccoli", "amount": 1.0, "unit": "pcs", "category": "Produce"},
            {"ingredient_name": "Lemon", "amount": 1.0, "unit": "pcs", "category": "Produce"}
        ]
    }
]


def ensure_starter_meals(db: Session):
    """Seeds starter recipes if the meals table is empty."""
    if db.query(Meal).count() == 0:
        for m in DEFAULT_STARTER_MEALS:
            meal = Meal(
                title=m["title"],
                notes=m["notes"],
                prep_time_min=m["prep_time_min"],
                created_by="Tamir",
                created_at=datetime.datetime.utcnow()
            )
            db.add(meal)
            db.commit()
            db.refresh(meal)

            for ing in m["ingredients"]:
                db.add(MealIngredient(
                    meal_id=meal.id,
                    ingredient_name=ing["ingredient_name"],
                    amount=ing["amount"],
                    unit=ing["unit"],
                    category=ing["category"]
                ))
            db.commit()


# ===================== MEALS CRUD ENDPOINTS =====================
@meals_router.get("/api/meals", dependencies=[Depends(require_auth_api)])
def list_saved_meals(db: Session = Depends(get_db)):
    """Returns all saved meals with their structured ingredients."""
    ensure_starter_meals(db)
    meals = db.query(Meal).order_by(Meal.title.asc()).all()

    return {
        "meals": [
            {
                "id": m.id,
                "title": m.title,
                "notes": m.notes,
                "prep_time_min": m.prep_time_min,
                "created_by": m.created_by,
                "created_at": m.created_at.isoformat() if m.created_at else None,
                "ingredients": [
                    {
                        "id": ing.id,
                        "ingredient_name": ing.ingredient_name,
                        "amount": ing.amount,
                        "unit": ing.unit,
                        "category": ing.category
                    }
                    for ing in m.ingredients
                ]
            }
            for m in meals
        ]
    }


@meals_router.post("/api/meals", dependencies=[Depends(require_auth_api)])
def create_meal(payload: MealCreatePayload, request: Request, db: Session = Depends(get_db)):
    """Creates a new meal and saves its structured ingredients."""
    active_user = payload.created_by or get_active_profile(request)
    now = datetime.datetime.utcnow()

    meal = Meal(
        title=payload.title.strip(),
        notes=payload.notes.strip() if payload.notes else None,
        prep_time_min=payload.prep_time_min,
        created_by=active_user,
        created_at=now
    )
    db.add(meal)
    db.commit()
    db.refresh(meal)

    for ing in payload.ingredients:
        clean_name = ing.ingredient_name.strip()
        if clean_name:
            db.add(MealIngredient(
                meal_id=meal.id,
                ingredient_name=clean_name,
                amount=ing.amount,
                unit=ing.unit.strip() if ing.unit else None,
                category=ing.category if ing.category in GROCERY_CATEGORIES else "Produce"
            ))
    db.commit()
    db.refresh(meal)

    return {
        "status": "ok",
        "meal": {
            "id": meal.id,
            "title": meal.title,
            "notes": meal.notes,
            "prep_time_min": meal.prep_time_min,
            "created_by": meal.created_by,
            "ingredients": [
                {
                    "id": ing.id,
                    "ingredient_name": ing.ingredient_name,
                    "amount": ing.amount,
                    "unit": ing.unit,
                    "category": ing.category
                }
                for ing in meal.ingredients
            ]
        }
    }


@meals_router.put("/api/meals/{meal_id}", dependencies=[Depends(require_auth_api)])
def update_meal(meal_id: int, payload: MealCreatePayload, db: Session = Depends(get_db)):
    """Updates an existing meal and its ingredients."""
    meal = db.query(Meal).filter(Meal.id == meal_id).first()
    if not meal:
        raise HTTPException(status_code=404, detail="Meal not found")

    meal.title = payload.title.strip()
    meal.notes = payload.notes.strip() if payload.notes else None
    meal.prep_time_min = payload.prep_time_min

    # Replace ingredients
    db.query(MealIngredient).filter(MealIngredient.meal_id == meal_id).delete()
    for ing in payload.ingredients:
        clean_name = ing.ingredient_name.strip()
        if clean_name:
            db.add(MealIngredient(
                meal_id=meal.id,
                ingredient_name=clean_name,
                amount=ing.amount,
                unit=ing.unit.strip() if ing.unit else None,
                category=ing.category if ing.category in GROCERY_CATEGORIES else "Produce"
            ))
    db.commit()
    db.refresh(meal)

    return {"status": "ok", "message": f"Updated '{meal.title}'"}


@meals_router.delete("/api/meals/{meal_id}", dependencies=[Depends(require_auth_api)])
def delete_meal(meal_id: int, db: Session = Depends(get_db)):
    """Deletes a saved meal and cascades delete to its ingredients."""
    meal = db.query(Meal).filter(Meal.id == meal_id).first()
    if not meal:
        raise HTTPException(status_code=404, detail="Meal not found")

    title = meal.title
    db.delete(meal)
    db.commit()
    return {"status": "ok", "message": f"Deleted meal '{title}'"}


# ===================== WEEKLY PLANNER ENDPOINTS =====================
@meals_router.get("/api/plan", dependencies=[Depends(require_auth_api)])
def get_weekly_plan(db: Session = Depends(get_db)):
    """Returns the 7-day schedule with assigned meals."""
    ensure_starter_meals(db)
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
                "is_double_batch": getattr(p, "is_double_batch", False),
                "notes": p.notes,
                "prep_time_min": p.meal.prep_time_min if p.meal else None,
                "ingredients_count": len(p.meal.ingredients) if p.meal else 0
            }

    return {
        "days": DAYS_OF_WEEK,
        "weekly_plan": plan_by_day,
        "saved_meals_count": len(meals)
    }


@meals_router.put("/api/plan/{day_of_week}", dependencies=[Depends(require_auth_api)])
def set_day_meal(day_of_week: str, payload: MealPlanUpdatePayload, db: Session = Depends(get_db)):
    """Assigns or updates a meal for a specific day of the week."""
    if day_of_week not in DAYS_OF_WEEK:
        raise HTTPException(status_code=400, detail="Invalid day of week")

    now = datetime.datetime.utcnow()
    plan_entry = db.query(MealPlan).filter(MealPlan.day_of_week == day_of_week).first()

    if not plan_entry:
        plan_entry = MealPlan(
            day_of_week=day_of_week,
            meal_id=payload.meal_id,
            custom_title=payload.custom_title.strip() if payload.custom_title else None,
            is_leftovers=payload.is_leftovers,
            is_double_batch=payload.is_double_batch,
            notes=payload.notes.strip() if payload.notes else None,
            updated_at=now
        )
        db.add(plan_entry)
    else:
        plan_entry.meal_id = payload.meal_id
        plan_entry.custom_title = payload.custom_title.strip() if payload.custom_title else None
        plan_entry.is_leftovers = payload.is_leftovers
        plan_entry.is_double_batch = payload.is_double_batch
        plan_entry.notes = payload.notes.strip() if payload.notes else None
        plan_entry.updated_at = now

    db.commit()
    db.refresh(plan_entry)

    return {
        "status": "ok",
        "message": f"Updated dinner for {day_of_week}",
        "entry": {
            "day": plan_entry.day_of_week,
            "meal_id": plan_entry.meal_id,
            "is_leftovers": plan_entry.is_leftovers,
            "is_double_batch": getattr(plan_entry, "is_double_batch", False)
        }
    }


@meals_router.delete("/api/plan/{day_of_week}", dependencies=[Depends(require_auth_api)])
def clear_day_meal(day_of_week: str, db: Session = Depends(get_db)):
    """Clears the assigned meal for a specific day."""
    plan_entry = db.query(MealPlan).filter(MealPlan.day_of_week == day_of_week).first()
    if plan_entry:
        db.delete(plan_entry)
        db.commit()
    return {"status": "ok", "message": f"Cleared dinner for {day_of_week}"}


# ===================== ONE-TAP GROCERY EXPORT WITH INGREDIENT AGGREGATION =====================
@meals_router.post("/api/export-to-groceries", dependencies=[Depends(require_auth_api)])
def export_week_ingredients_to_groceries(request: Request, db: Session = Depends(get_db)):
    """Aggregates all ingredients from the week's meal plan and exports them to Groceries.
    
    Rules:
    - Normalizes ingredient_name (lowercase, trimmed)
    - Sums amounts where unit matches (e.g., onion 2 pcs + onion 1 pcs = onion 3 pcs)
    - If units differ (e.g. g vs pcs), keeps both quantities visible without overwriting
    - Merges with existing unchecked grocery items
    """
    active_user = get_active_profile(request)
    now = datetime.datetime.utcnow()

    # 1. Fetch weekly plan entries that have meals assigned
    plans = (
        db.query(MealPlan)
        .filter(MealPlan.meal_id != None)
        .all()
    )

    if not plans:
        raise HTTPException(
            status_code=400,
            detail="No saved meals assigned in this week's plan yet! Assign meals to days first."
        )

    # 2. Collect and aggregate ingredients
    # Key: (normalized_name, normalized_unit)
    # Value: { "display_name": str, "amount": float, "unit": str, "category": str }
    aggregated: Dict[tuple, dict] = {}

    for plan in plans:
        if not plan.meal:
            continue

        # If day is marked as leftovers from another night, skip ingredients to prevent duplicate buying
        if plan.is_leftovers:
            continue

        # 2x batch multiplier: doubles ingredient quantities when cooking a double batch
        multiplier = 2.0 if getattr(plan, "is_double_batch", False) else 1.0

        for ing in plan.meal.ingredients:
            raw_name = (ing.ingredient_name or "").strip()
            if not raw_name:
                continue

            norm_name = raw_name.lower()
            raw_unit = (ing.unit or "").strip()
            norm_unit = raw_unit.lower()

            item_amount = (float(ing.amount) * multiplier) if ing.amount is not None else None

            key = (norm_name, norm_unit)

            if key not in aggregated:
                aggregated[key] = {
                    "name": raw_name.capitalize(),
                    "amount": item_amount,
                    "unit": raw_unit if raw_unit else None,
                    "category": ing.category or "Produce"
                }
            else:
                # Sum amounts where unit matches
                if item_amount is not None:
                    curr_amt = aggregated[key]["amount"] or 0.0
                    aggregated[key]["amount"] = round(curr_amt + item_amount, 2)

    if not aggregated:
        raise HTTPException(
            status_code=400,
            detail="The assigned meals do not have any ingredients listed."
        )

    # 3. Export into grocery_items table (merge with existing or create fresh)
    added_count = 0
    updated_count = 0

    for (norm_name, norm_unit), item_data in aggregated.items():
        # Check if an unchecked item with same normalized name and unit already exists
        existing_item = (
            db.query(GroceryItem)
            .filter(
                func.lower(GroceryItem.name) == norm_name,
                GroceryItem.is_checked == False
            )
            .all()
        )

        # Match by unit
        matched = None
        for ex in existing_item:
            ex_unit = (ex.unit or "").strip().lower()
            if ex_unit == norm_unit:
                matched = ex
                break

        if matched:
            # Merge quantity
            if item_data["amount"] is not None:
                matched.amount = round((matched.amount or 0.0) + item_data["amount"], 2)
            matched.updated_at = now
            matched.added_by = active_user
            updated_count += 1
        else:
            # Create new grocery item
            new_groc = GroceryItem(
                name=item_data["name"],
                amount=item_data["amount"],
                unit=item_data["unit"],
                category=item_data["category"],
                is_checked=False,
                added_by=active_user,
                created_at=now,
                updated_at=now
            )
            db.add(new_groc)
            added_count += 1

    db.commit()

    return {
        "status": "ok",
        "message": f"Exported {len(aggregated)} ingredient(s) to Grocery List! ({added_count} new, {updated_count} merged)",
        "exported_count": len(aggregated),
        "new_items_count": added_count,
        "updated_items_count": updated_count,
        "aggregated_items": list(aggregated.values())
    }
