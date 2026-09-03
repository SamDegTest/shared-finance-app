import asyncio
import uuid
from unittest.mock import patch

import pytest

from app.core.storage import storage_service
from app.schemas.ingestion import IngestionJobStatus
from app.services.ingestion_service import IngestionService
from app.services.pii_redaction_service import pii_redaction_service
from app.services.vision_worker import (
    GDPRRedactionFailedError,
    MockVisionProvider,
    VisionWorker,
)
from app.tasks.receipt_tasks import process_receipt


def _create_sample_receipt_image(
    with_text: str = "CONAD 333 1234567",
) -> bytes:
    """Crea un byte payload simulato JPEG valido per i test di pipeline."""
    header = (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00"
        b"\xff\xdb\x00C\x00"
    )
    body = with_text.encode("utf-8") + b"\nLatte Bio 1.80 EUR\nTOTALE: 6.30 EUR"
    footer = b"\xff\xd9"
    return header + body + footer


@pytest.mark.asyncio
async def test_vision_worker_redacts_pii_before_llm_invocation() -> None:
    """AC 1 & AC 2: Il Vision LLM riceve solo l'immagine anonimizzata."""
    raw_image = _create_sample_receipt_image("Supermercato +39 333 1234567")
    mock_provider = MockVisionProvider()
    worker = VisionWorker(provider=mock_provider)

    result = await worker.process_receipt_image(raw_image, redact_pii=True)

    # 1. Verifica che i dati finanziari non-PII siano estratti correttamente
    assert result.total_amount_cents == 2540
    assert result.merchant_name == "Supermercato Esempio"
    assert len(result.items) == 4
    assert result.tax_amount_cents == 254

    # 2. Verifica che il provider Vision abbia ricevuto i byte redatti
    assert mock_provider.last_received_image_bytes is not None
    assert len(mock_provider.last_received_image_bytes) > 0


@pytest.mark.asyncio
async def test_gdpr_safe_abort_when_redaction_fails() -> None:
    """AC 3: Fallimento redazione solleva errore ed evita invio al LLM."""
    raw_image = _create_sample_receipt_image("Scontrino con carta")
    mock_provider = MockVisionProvider()
    worker = VisionWorker(provider=mock_provider)

    with patch.object(
        pii_redaction_service,
        "redact_receipt_image",
        side_effect=RuntimeError("Tesseract OCR crash"),
    ):
        with pytest.raises(GDPRRedactionFailedError) as exc_info:
            await worker.process_receipt_image(raw_image, redact_pii=True)

        assert "Anonimizzazione PII fallita" in str(exc_info.value)
        # Verifica fondamentale: il provider esterno NON è mai stato invocato
        assert mock_provider.last_received_image_bytes is None


def test_celery_task_process_receipt_end_to_end() -> None:
    """Verifica l'esecuzione sincrona del task Celery process_receipt."""
    raw_image = _create_sample_receipt_image("PAN: **** **** **** 1234")
    storage_key = f"test_receipts/{uuid.uuid4().hex}.jpg"
    storage_service.save_file(storage_key, raw_image, "image/jpeg")

    job_id = f"job_{uuid.uuid4().hex[:12]}"
    household_id = str(uuid.uuid4())

    result = process_receipt(
        job_id=job_id,
        storage_key=storage_key,
        household_id=household_id,
    )

    assert result["total_amount_cents"] == 2540
    assert result["merchant_name"] == "Supermercato Esempio"
    assert result["confidence_score"] == 0.98


@pytest.mark.asyncio
async def test_ingestion_service_handles_gdpr_error_gracefully() -> None:
    """Verifica che IngestionService registri FAILED con errore GDPR-safe."""
    raw_image = _create_sample_receipt_image("Carta 5500 0000 0000 0004")
    storage_key = f"test_receipts/{uuid.uuid4().hex}.jpg"
    storage_service.save_file(storage_key, raw_image, "image/jpeg")

    ingestion = IngestionService()
    household_id = uuid.uuid4()

    with patch.object(
        pii_redaction_service,
        "redact_receipt_image",
        side_effect=RuntimeError("Memory error in OCR"),
    ):
        job = await ingestion.enqueue_receipt_ingestion(
            household_id=household_id,
            storage_key=storage_key,
            image_bytes=raw_image,
        )

        # Attendi completamento background task
        await asyncio.sleep(0.05)

        updated_job = ingestion.get_job(job.job_id)
        assert updated_job is not None
        assert updated_job.status == IngestionJobStatus.FAILED
        assert "protezione privacy" in (updated_job.error_message or "").lower()
