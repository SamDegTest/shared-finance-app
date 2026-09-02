from fastapi import APIRouter

from app.api.v1.endpoints import health, households, receipts, smart_input

api_router = APIRouter()
api_router.include_router(health.router, tags=["Health"])
api_router.include_router(
    households.router,
    prefix="/households",
    tags=["Households & Expenses"],
)
api_router.include_router(
    receipts.router,
    tags=["Receipts & Async Ingestion"],
)
api_router.include_router(
    smart_input.router,
    tags=["Smart Input & Natural Language"],
)
