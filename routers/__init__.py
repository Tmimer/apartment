from routers.auth import auth_router
from routers.health import health_router
from routers.plants import plants_router
from routers.groceries import groceries_router
from routers.meals import meals_router
from routers.maintenance import maintenance_router
from routers.status_note import status_note_router
from routers.dates import dates_router

__all__ = [
    "auth_router",
    "health_router",
    "plants_router",
    "groceries_router",
    "meals_router",
    "maintenance_router",
    "status_note_router",
    "dates_router",
]
