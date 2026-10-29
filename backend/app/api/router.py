from fastapi import APIRouter

from app.api.endpoints.corporate_actions import router as corporate_actions_router
from app.api.endpoints.health import router as health_router
from app.api.endpoints.instruments import router as instruments_router
from app.api.endpoints.market_data import router as market_data_router
from app.api.endpoints.providers import router as providers_router
from app.api.endpoints.share_counts import router as share_counts_router

api_router = APIRouter()

# Include all modular routers
api_router.include_router(health_router)
api_router.include_router(providers_router)
api_router.include_router(instruments_router)
api_router.include_router(market_data_router)
api_router.include_router(corporate_actions_router)
api_router.include_router(share_counts_router)
