from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from app.core.config import settings

router = APIRouter()


class HealthCheckResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str
    environment: str
    version: str


@router.get(
    "/health",
    response_model=HealthCheckResponse,
    summary="Health Check",
    description="Restituisce lo stato operativo del servizio e la versione corrente.",
)
def get_health() -> HealthCheckResponse:
    return HealthCheckResponse(
        status="ok",
        environment=settings.ENVIRONMENT,
        version=settings.VERSION,
    )
