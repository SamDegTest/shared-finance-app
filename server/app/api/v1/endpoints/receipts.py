import uuid
from typing import Annotated

from fastapi import (
    APIRouter,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)

from app.core.storage import storage_service
from app.schemas.ingestion import (
    IngestionJobResponse,
    IngestReceiptRequest,
    PresignedUploadResponse,
)
from app.services.ingestion_service import ingestion_service

router = APIRouter()


# ============================================================================
# 1. GENERAZIONE PRESIGNED URL & UPLOAD DIRETTO (< 2s)
# ============================================================================


@router.post(
    "/households/{household_id}/receipts/upload-url",
    response_model=PresignedUploadResponse,
    summary="Generazione URL Pre-firmato per Upload Ricevuta",
    description=(
        "Genera un URL sicuro pre-firmato (valido 15 minuti) per consentire "
        "alla PWA l'upload diretto sullo storage."
    ),
)
async def generate_upload_url(
    household_id: uuid.UUID,
    file_extension: Annotated[str, Query(description="Estensione file")] = "jpg",
) -> PresignedUploadResponse:
    upload_url, storage_key = storage_service.generate_presigned_upload_url(
        household_id=household_id, file_extension=file_extension
    )
    return PresignedUploadResponse(
        upload_url=upload_url,
        storage_key=storage_key,
        expires_in_seconds=900,
        http_method="PUT",
    )


@router.post(
    "/households/{household_id}/receipts/upload",
    response_model=IngestionJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload Immagine Ricevuta & Auto-Ingestion Asincrona",
    description=(
        "Riceve l'immagine dello scontrino via multipart (< 2s), la salva "
        "nello storage isolato e avvia l'ingestion in background."
    ),
)
async def upload_and_ingest_receipt(
    household_id: uuid.UUID,
    file: Annotated[UploadFile, File(description="File immagine ricevuta")],
) -> IngestionJobResponse:
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nome file non valido.",
        )

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File vuoto o corrotto.",
        )

    ext = file.filename.split(".")[-1] if "." in file.filename else "jpg"
    storage_key = storage_service.generate_storage_key(household_id, ext)

    # Salvataggio veloce nello storage
    storage_service.save_file(
        storage_key, file_bytes, file.content_type or "image/jpeg"
    )

    # Accodamento asincrono immediato
    return await ingestion_service.enqueue_receipt_ingestion(
        household_id=household_id,
        storage_key=storage_key,
        image_bytes=file_bytes,
    )


@router.post(
    "/households/{household_id}/receipts/ingest",
    response_model=IngestionJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Avvio Ingestion Asincrona da Storage Key",
    description=(
        "Accoda l'elaborazione Vision OCR per un'immagine già caricata "
        "tramite presigned URL."
    ),
)
async def ingest_receipt_from_storage(
    household_id: uuid.UUID,
    payload: IngestReceiptRequest,
) -> IngestionJobResponse:
    if not storage_service.file_exists(payload.storage_key):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(f"File non trovato per la storage key: {payload.storage_key}"),
        )

    return await ingestion_service.enqueue_receipt_ingestion(
        household_id=household_id,
        storage_key=payload.storage_key,
    )


# ============================================================================
# 2. POLLING STATO JOB & RISULTATI VISION
# ============================================================================


@router.get(
    "/receipts/jobs/{job_id}",
    response_model=IngestionJobResponse,
    summary="Polling Stato Job di Ingestion",
    description=(
        "Restituisce lo stato attuale del job (PENDING, PROCESSING, "
        "COMPLETED, FAILED) e i dati estratti."
    ),
)
async def get_ingestion_job_status(job_id: str) -> IngestionJobResponse:
    job = ingestion_service.get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job con ID '{job_id}' non trovato.",
        )
    return job


# ============================================================================
# 3. ENDPOINTS STORAGE PRESIGNED LOCALE (SIMULAZIONE S3)
# ============================================================================


@router.put(
    "/storage/upload",
    summary="Upload Binario Pre-firmato",
    description="Endpoint di destinazione per upload con verifica firma HMAC.",
)
async def handle_presigned_upload(
    key: Annotated[str, Query()],
    expires: Annotated[int, Query()],
    signature: Annotated[str, Query()],
    request: Request,
) -> dict[str, str]:
    if not storage_service.validate_presigned_token(key, expires, signature):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Firma URL pre-firmato non valida o scaduta.",
        )

    body = await request.body()
    if not body:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Payload binario vuoto.",
        )

    storage_service.save_file(key, body)
    return {"status": "success", "storage_key": key}


@router.get(
    "/storage/download",
    summary="Download Binario Pre-firmato",
    description="Endpoint per il recupero protetto delle immagini.",
)
async def handle_presigned_download(
    key: Annotated[str, Query()],
    expires: Annotated[int, Query()],
    signature: Annotated[str, Query()],
) -> Response:
    if not storage_service.validate_presigned_token(key, expires, signature):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Firma URL pre-firmato non valida o scaduta.",
        )

    try:
        data = storage_service.read_file(key)
        return Response(content=data, media_type="image/jpeg")
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
