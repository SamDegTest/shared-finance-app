import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.receipt import ReceiptExtractionResponse


class IngestionJobStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class PresignedUploadResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    upload_url: str = Field(description="URL pre-firmato temporaneo per upload diretto")
    storage_key: str = Field(description="Key di storage isolata per household")
    expires_in_seconds: int = Field(description="Secondi di validità dell'URL")
    http_method: str = Field(default="PUT", description="Metodo HTTP")


class IngestReceiptRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    storage_key: str = Field(
        min_length=5,
        description="Storage key ottenuta dall'upload presigned",
    )


class IngestionJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: str
    household_id: uuid.UUID
    status: IngestionJobStatus
    created_at: datetime
    completed_at: datetime | None = None
    processing_time_ms: float | None = None
    result: ReceiptExtractionResponse | None = None
    error_message: str | None = None
