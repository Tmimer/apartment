import os
import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import desc, func

from database import get_db
from models.groceries import GroceryItem, GroceryStaple, GROCERY_CATEGORIES, GROCERY_UNITS
from security import require_auth_api, get_active_profile

groceries_router = APIRouter(prefix="/groceries", tags=["groceries"])


# ===================== PYDANTIC SCHEMAS =====================
class GroceryItemCreate(BaseModel):
    name: str = Field(..., min_length=1)
    amount: Optional[float] = None
    unit: Optional[str] = None
    category: Optional[str] = "Produce"
    added_by: Optional[str] = None


class GroceryItemUpdate(BaseModel):
    name: Optional[str] = None
    amount: Optional[float] = None
    unit: Optional[str] = None
    category: Optional[str] = None
    is_checked: Optional[bool] = None


class GroceryRestorePayload(BaseModel):
    items: List[dict]


# ===================== STARTER STAPLES SEEDER =====================
DEFAULT_STAPLES = [
    {"name": "Milk", "category": "Dairy/Eggs", "default_amount": 1.0, "default_unit": "L", "icon_emoji": "🥛", "display_order": 1},
    {"name": "Eggs", "category": "Dairy/Eggs", "default_amount": 12.0, "default_unit": "pcs", "icon_emoji": "🥚", "display_order": 2},
    {"name": "Coffee Beans", "category": "Pantry/Dry", "default_amount": 1.0, "default_unit": "pack", "icon_emoji": "☕", "display_order": 3},
    {"name": "Onions", "category": "Produce", "default_amount": 1.0, "default_unit": "kg", "icon_emoji": "🧅", "display_order": 4},
    {"name": "Garlic", "category": "Produce", "default_amount": 3.0, "default_unit": "pcs", "icon_emoji": "🧄", "display_order": 5},
    {"name": "Olive Oil", "category": "Pantry/Dry", "default_amount": 1.0, "default_unit": "L", "icon_emoji": "🫒", "display_order": 6},
    {"name": "Butter", "category": "Dairy/Eggs", "default_amount": 1.0, "default_unit": "pack", "icon_emoji": "🧈", "display_order": 7},
    {"name": "Sourdough Bread", "category": "Bakery", "default_amount": 1.0, "default_unit": "pcs", "icon_emoji": "🥖", "display_order": 8},
    {"name": "Paper Towels", "category": "Household", "default_amount": 1.0, "default_unit": "pack", "icon_emoji": "🧻", "display_order": 9},
    {"name": "Dish Soap", "category": "Household", "default_amount": 1.0, "default_unit": "pcs", "icon_emoji": "🧼", "display_order": 10},
]


def ensure_starter_staples(db: Session):
    """Populates initial common apartment staples if table is empty."""
    if db.query(GroceryStaple).count() == 0:
        for st in DEFAULT_STAPLES:
            db.add(GroceryStaple(**st))
        db.commit()


# ===================== UI SHELL ROUTE =====================
@groceries_router.get("")
@groceries_router.get("/")
def groceries_page(request: Request):
    """Serves the unified apartment hub with groceries tab active."""
    from plants_app import serve_hub_shell
    return serve_hub_shell(request, default_tab="groceries")


# ===================== API ENDPOINTS =====================
@groceries_router.get("/api/items", dependencies=[Depends(require_auth_api)])
def list_grocery_items(db: Session = Depends(get_db)):
    """Returns active and checked grocery items ordered by supermarket category layout."""
    ensure_starter_staples(db)

    items = (
        db.query(GroceryItem)
        .order_by(GroceryItem.is_checked.asc(), GroceryItem.created_at.desc())
        .all()
    )
    staples = db.query(GroceryStaple).order_by(GroceryStaple.display_order.asc()).all()

    # Get max updated timestamp for 4-second sync delta checks
    latest_update = db.query(func.max(GroceryItem.updated_at)).scalar()
    latest_update_str = latest_update.isoformat() if latest_update else datetime.datetime.utcnow().isoformat()

    return {
        "categories": GROCERY_CATEGORIES,
        "units": GROCERY_UNITS,
        "last_updated_at": latest_update_str,
        "items": [
            {
                "id": it.id,
                "name": it.name,
                "amount": it.amount,
                "unit": it.unit,
                "category": it.category,
                "is_checked": it.is_checked,
                "checked_at": it.checked_at.isoformat() if it.checked_at else None,
                "added_by": it.added_by,
                "created_at": it.created_at.isoformat() if it.created_at else None,
                "updated_at": it.updated_at.isoformat() if it.updated_at else None,
            }
            for it in items
        ],
        "staples": [
            {
                "id": st.id,
                "name": st.name,
                "default_amount": st.default_amount,
                "default_unit": st.default_unit,
                "category": st.category,
                "icon_emoji": st.icon_emoji,
            }
            for st in staples
        ]
    }


@groceries_router.get("/api/sync", dependencies=[Depends(require_auth_api)])
def sync_groceries(since: Optional[str] = Query(None), db: Session = Depends(get_db)):
    """Ultra-lightweight endpoint for 4-second visibility polling."""
    latest_update = db.query(func.max(GroceryItem.updated_at)).scalar()
    count = db.query(GroceryItem).count()

    if not latest_update:
        return {"changed": False, "count": 0, "last_updated_at": None}

    latest_iso = latest_update.isoformat()

    # Compare ISO strings
    if since and since.strip() == latest_iso:
        return {"changed": False, "last_updated_at": latest_iso, "count": count}

    # If state changed, return full fresh items list
    items = (
        db.query(GroceryItem)
        .order_by(GroceryItem.is_checked.asc(), GroceryItem.created_at.desc())
        .all()
    )

    return {
        "changed": True,
        "last_updated_at": latest_iso,
        "count": len(items),
        "items": [
            {
                "id": it.id,
                "name": it.name,
                "amount": it.amount,
                "unit": it.unit,
                "category": it.category,
                "is_checked": it.is_checked,
                "checked_at": it.checked_at.isoformat() if it.checked_at else None,
                "added_by": it.added_by,
                "created_at": it.created_at.isoformat() if it.created_at else None,
                "updated_at": it.updated_at.isoformat() if it.updated_at else None,
            }
            for it in items
        ]
    }


@groceries_router.post("/api/items", dependencies=[Depends(require_auth_api)])
def add_grocery_item(payload: GroceryItemCreate, request: Request, db: Session = Depends(get_db)):
    """Adds a new item to the shared list, or reactivates existing checked item."""
    clean_name = payload.name.strip()
    if not clean_name:
        raise HTTPException(status_code=400, detail="Item name is required")

    active_user = payload.added_by or get_active_profile(request)
    now = datetime.datetime.utcnow()

    # Check if this exact item is already on list checked off
    existing_checked = (
        db.query(GroceryItem)
        .filter(func.lower(GroceryItem.name) == clean_name.lower(), GroceryItem.is_checked == True)
        .first()
    )

    if existing_checked:
        existing_checked.is_checked = False
        existing_checked.checked_at = None
        existing_checked.added_by = active_user
        existing_checked.updated_at = now
        if payload.amount is not None:
            existing_checked.amount = payload.amount
        if payload.unit is not None:
            existing_checked.unit = payload.unit
        if payload.category:
            existing_checked.category = payload.category
        db.commit()
        db.refresh(existing_checked)
        item = existing_checked
    else:
        item = GroceryItem(
            name=clean_name,
            amount=payload.amount,
            unit=payload.unit,
            category=payload.category if payload.category in GROCERY_CATEGORIES else "Produce",
            is_checked=False,
            added_by=active_user,
            created_at=now,
            updated_at=now
        )
        db.add(item)
        db.commit()
        db.refresh(item)

    return {
        "status": "ok",
        "item": {
            "id": item.id,
            "name": item.name,
            "amount": item.amount,
            "unit": item.unit,
            "category": item.category,
            "is_checked": item.is_checked,
            "added_by": item.added_by,
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        }
    }


@groceries_router.patch("/api/items/{item_id}", dependencies=[Depends(require_auth_api)])
def update_grocery_item(item_id: int, payload: GroceryItemUpdate, db: Session = Depends(get_db)):
    """Edits, checks off, or unchecks a grocery item."""
    item = db.query(GroceryItem).filter(GroceryItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    now = datetime.datetime.utcnow()
    item.updated_at = now

    if payload.name is not None:
        item.name = payload.name.strip()
    if payload.amount is not None:
        item.amount = payload.amount
    if payload.unit is not None:
        item.unit = payload.unit.strip() if payload.unit else None
    if payload.category is not None:
        if payload.category in GROCERY_CATEGORIES:
            item.category = payload.category

    if payload.is_checked is not None:
        item.is_checked = payload.is_checked
        item.checked_at = now if payload.is_checked else None

    db.commit()
    db.refresh(item)

    return {
        "status": "ok",
        "item": {
            "id": item.id,
            "name": item.name,
            "amount": item.amount,
            "unit": item.unit,
            "category": item.category,
            "is_checked": item.is_checked,
            "checked_at": item.checked_at.isoformat() if item.checked_at else None,
            "added_by": item.added_by,
            "updated_at": item.updated_at.isoformat() if item.updated_at else None
        }
    }


@groceries_router.delete("/api/items/{item_id}", dependencies=[Depends(require_auth_api)])
def delete_grocery_item(item_id: int, db: Session = Depends(get_db)):
    """Deletes an item, returning backup details for client-side 5-second undo."""
    item = db.query(GroceryItem).filter(GroceryItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    deleted_copy = {
        "name": item.name,
        "amount": item.amount,
        "unit": item.unit,
        "category": item.category,
        "is_checked": item.is_checked,
        "added_by": item.added_by,
        "created_at": item.created_at.isoformat() if item.created_at else None
    }

    db.delete(item)
    db.commit()

    return {
        "status": "ok",
        "message": f"Deleted '{item.name}'",
        "deleted_item": deleted_copy
    }


@groceries_router.post("/api/clear-checked", dependencies=[Depends(require_auth_api)])
def clear_checked_items(db: Session = Depends(get_db)):
    """Clears all checked items from list, returning backup for 5-second undo."""
    checked_items = db.query(GroceryItem).filter(GroceryItem.is_checked == True).all()
    if not checked_items:
        return {"status": "ok", "cleared_count": 0, "cleared_items": []}

    backup = [
        {
            "name": it.name,
            "amount": it.amount,
            "unit": it.unit,
            "category": it.category,
            "is_checked": it.is_checked,
            "added_by": it.added_by,
            "created_at": it.created_at.isoformat() if it.created_at else None
        }
        for it in checked_items
    ]

    for it in checked_items:
        db.delete(it)
    db.commit()

    return {
        "status": "ok",
        "cleared_count": len(backup),
        "cleared_items": backup
    }


@groceries_router.post("/api/restore", dependencies=[Depends(require_auth_api)])
def restore_grocery_items(payload: GroceryRestorePayload, db: Session = Depends(get_db)):
    """Restores previously deleted or cleared items when user taps Toast Undo."""
    now = datetime.datetime.utcnow()
    restored_count = 0

    for it in payload.items:
        new_item = GroceryItem(
            name=it.get("name", "Item"),
            amount=it.get("amount"),
            unit=it.get("unit"),
            category=it.get("category", "Produce"),
            is_checked=it.get("is_checked", False),
            added_by=it.get("added_by", "Tamir"),
            created_at=now,
            updated_at=now
        )
        db.add(new_item)
        restored_count += 1

    db.commit()
    return {"status": "ok", "restored_count": restored_count}


@groceries_router.get("/api/autocomplete", dependencies=[Depends(require_auth_api)])
def grocery_autocomplete(q: str = Query("", min_length=1), db: Session = Depends(get_db)):
    """Returns suggestions from past items matching search query."""
    search = f"%{q.strip().lower()}%"
    rows = (
        db.query(GroceryItem.name, GroceryItem.category, GroceryItem.unit)
        .filter(func.lower(GroceryItem.name).like(search))
        .distinct()
        .limit(8)
        .all()
    )

    return {
        "suggestions": [
            {"name": r[0], "category": r[1], "unit": r[2]}
            for r in rows
        ]
    }
