import os
import time
import threading
from contextlib import asynccontextmanager
from typing import Optional
from fastapi import FastAPI, Request, Response, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from database import engine, SessionLocal, Base
from models import (
    Plant, WateringLog, PushSubscription, AppConfig,
    GroceryItem, GroceryStaple,
    Meal, MealIngredient, MealPlan, FridgeItem,
    MaintenanceTask, ApartmentStatusNote,
    DateSpot, RandomizerPreset
)
from security import is_authenticated, COOKIE_NAME
from routers import (
    auth_router, health_router, plants_router,
    groceries_router, meals_router, maintenance_router,
    status_note_router, dates_router
)
from routers.plants import init_plant_db, check_and_notify_due_plants
from migrations import auto_migrate_schema

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# ===================== BACKGROUND WORKER =====================
def background_notification_worker():
    """Background daemon thread checking for due plants every 30 minutes."""
    while True:
        try:
            db = SessionLocal()
            check_and_notify_due_plants(db)
            db.close()
        except Exception as e:
            print(f"[!] Notification worker background exception: {e}")
        time.sleep(1800)


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    # Initialize all SQLAlchemy tables (Plants, Groceries, Meals, Maintenance, Status Note, Dates)
    try:
        Base.metadata.create_all(bind=engine)
    except Exception as e:
        print(f"[!] Warning during Base metadata create_all: {e}")

    auto_migrate_schema()
    init_plant_db()
    worker = threading.Thread(target=background_notification_worker, daemon=True)
    worker.start()
    yield


app = FastAPI(
    title="Shared Apartment Hub",
    description="Apartment Hub with Plants, Groceries, Meals, Maintenance, Dates, and Status for Tamir & Mikush",
    lifespan=app_lifespan
)

# CORS setup for mobile web views
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===================== AUTHENTICATION GATE MIDDLEWARE =====================
PUBLIC_PATHS = [
    "/health",
    "/healthz",
    "/health/audit-logs",
    "/login",
    "/api/auth/login",
    "/api/auth/status",
    "/manifest.json",
    "/sw.js",
    "/icon.svg",
    "/icon-192.png",
    "/icon-512.png",
    "/favicon.ico",
    "/plants/manifest.json",
    "/plants/sw.js",
    "/plants/icon.svg",
    "/plants/icon-192.png",
    "/plants/icon-512.png",
    "/plants/favicon.ico",
]


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path

    # Allow public endpoints unconditionally
    if path in PUBLIC_PATHS or path.startswith("/static/"):
        return await call_next(request)

    # Check authentication cookie
    authed = is_authenticated(request)

    if not authed:
        # If API request, return 401 Unauthorized
        if path.startswith("/api/") or "/api/" in path:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Apartment passcode required. Please log in.", "auth_required": True}
            )

        # For browser navigation, redirect to login page with next query param
        next_url = str(request.url.path)
        if request.url.query:
            next_url += f"?{request.url.query}"
        return RedirectResponse(url=f"/login?next={next_url}", status_code=status.HTTP_302_FOUND)

    return await call_next(request)


# ===================== MOUNT APPLICATION ROUTERS =====================
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(plants_router)
app.include_router(groceries_router)
app.include_router(meals_router)
app.include_router(maintenance_router)
app.include_router(status_note_router)
app.include_router(dates_router)


# ===================== ROOT & SHELL SERVING =====================
def serve_hub_shell(request: Request, default_tab: str = "plants"):
    """Renders the master unified mobile shell with default active tab."""
    hub_file = os.path.join(BASE_DIR, "templates", "hub.html")
    if not os.path.exists(hub_file):
        # Fallback to direct plants_index.html if template missing
        return FileResponse(os.path.join(BASE_DIR, "plants_index.html"))

    with open(hub_file, "r", encoding="utf-8") as f:
        html = f.read()

    return HTMLResponse(content=html)


@app.get("/", response_class=HTMLResponse)
def root_index(request: Request):
    """Serves the unified Apartment Hub shell."""
    return serve_hub_shell(request, default_tab="plants")


@app.get("/plants", response_class=HTMLResponse)
def plants_view(request: Request):
    """Serves the unified Apartment Hub shell focused on Plants tab."""
    return serve_hub_shell(request, default_tab="plants")


@app.get("/groceries", response_class=HTMLResponse)
def groceries_view(request: Request):
    """Serves the unified Apartment Hub shell focused on Groceries tab."""
    return serve_hub_shell(request, default_tab="groceries")


@app.get("/shop", response_class=HTMLResponse)
def shop_view(request: Request):
    """Serves the unified Apartment Hub shell focused on Groceries (Shop) tab."""
    return serve_hub_shell(request, default_tab="groceries")


@app.get("/meals", response_class=HTMLResponse)
def meals_view(request: Request):
    """Serves the unified Apartment Hub shell focused on Meals tab."""
    return serve_hub_shell(request, default_tab="meals")


@app.get("/maintenance", response_class=HTMLResponse)
def maintenance_view(request: Request):
    """Serves the unified Apartment Hub shell focused on Maintenance tab."""
    return serve_hub_shell(request, default_tab="maintenance")


@app.get("/tasks", response_class=HTMLResponse)
def tasks_view(request: Request):
    """Serves the unified Apartment Hub shell focused on Maintenance (Tasks) tab."""
    return serve_hub_shell(request, default_tab="maintenance")


@app.get("/dates", response_class=HTMLResponse)
def dates_view(request: Request):
    """Serves the unified Apartment Hub shell focused on Dates tab."""
    return serve_hub_shell(request, default_tab="dates")


@app.get("/manifest.json")
def serve_root_manifest():
    response = FileResponse(os.path.join(BASE_DIR, "manifest.json"), media_type="application/manifest+json")
    response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/sw.js")
def serve_root_sw():
    response = FileResponse(os.path.join(BASE_DIR, "sw.js"), media_type="application/javascript")
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


@app.get("/icon.svg")
def serve_root_icon_svg():
    response = FileResponse(os.path.join(BASE_DIR, "icon.svg"), media_type="image/svg+xml")
    response.headers["Cache-Control"] = "public, max-age=86400"
    return response


@app.get("/icon-192.png")
def serve_root_icon_192():
    return FileResponse(os.path.join(BASE_DIR, "icon-192.png"), media_type="image/png")


@app.get("/icon-512.png")
def serve_root_icon_512():
    return FileResponse(os.path.join(BASE_DIR, "icon-512.png"), media_type="image/png")


@app.get("/favicon.ico")
def serve_root_favicon():
    return FileResponse(os.path.join(BASE_DIR, "icon-192.png"), media_type="image/png")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    print(f"[*] Starting Shared Apartment Hub on 0.0.0.0:{port}...")
    uvicorn.run("plants_app:app", host="0.0.0.0", port=port, log_level="info")
