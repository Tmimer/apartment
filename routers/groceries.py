import os
import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import desc

from database import get_db
from models.groceries import GroceryItem, GroceryStaple, GROCERY_CATEGORIES, GROCERY_UNITS
from security import require_auth_api, is_authenticated

groceries_router = APIRouter(prefix="/groceries", tags=["groceries"])


class GroceryItemCreate(BaseModel):
    name: str = Field(..., min_length=1)
    amount: Optional[float] = None
    unit: Optional[str] = None
    category: Optional[str] = "Produce"
    added_by: Optional[str] = "Tamir"


class GroceryItemUpdate(BaseModel):
    name: Optional[str] = None
    amount: Optional[float] = None
    unit: Optional[str] = None
    category: Optional[str] = None
    is_checked: Optional[bool] = None


@groceries_router.get("")
@groceries_router.get("/")
def groceries_page(request: Request):
    """Serves the unified apartment hub with groceries tab active."""
    from plants_app import serve_hub_shell
    return serve_hub_shell(request, default_tab="groceries")


@groceries_router.get("/api/items", dependencies=[Depends(require_auth_api)])
def list_grocery_items(db: Session = Depends(get_db)):
    """Returns active and checked grocery items ordered by supermarket category layout."""
    items = (
        db.query(GroceryItem)
        .order_by(GroceryItem.is_checked.asc(), GroceryItem.created_at.desc())
        .all()
    )
    staples = db.query(GroceryStaple).order_by(GroceryStaple.display_order.asc()).all()

    return {
        "categories": GROCERY_CATEGORIES,
        "units": GROCERY_UNITS,
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
