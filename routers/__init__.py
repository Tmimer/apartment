from routers.auth import auth_router
from routers.health import health_router
from routers.plants import plants_router
from routers.groceries import groceries_router
from routers.meals import meals_router

__all__ = [
    "auth_router",
    "health_router",
    "plants_router",
    "groceries_router",
    "meals_router"
]
