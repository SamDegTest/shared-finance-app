import asyncio
import logging
from typing import Any

from app.core.celery_app import celery_app
from app.core.storage import storage_service
from app.services.pii_redaction_service import pii_redaction_service
from app.services.vision_worker import (
    GDPRRedactionFailedError,
    VisionWorker,
)

logger = logging.getLogger("shared-finance-app.receipt_tasks")


@celery_app.task(name="process_receipt")  # type: ignore[untyped-decorator]
def process_receipt(
    job_id: str,
    storage_key: str,
    household_id: str,
) -> dict[str, Any]:
    """Task asincrono Celery per scontrini con redazione visiva PII."""
    logger.info(
        "Avvio task Celery process_receipt: job=%s, key=%s, household=%s",
        job_id,
        storage_key,
        household_id,
    )

    # 1. Download dell'immagine originale da S3 / Storage locale
    try:
        raw_image_bytes = storage_service.read_file(storage_key)
    except Exception as e:
        logger.exception("Impossibile scaricare lo scontrino da storage: %s", e)
        raise RuntimeError(
            f"Errore lettura storage per la chiave '{storage_key}': {e}"
        ) from e

    # 2. Redazione Visiva PII locale con Presidio ImageRedactor & Pillow
    try:
        logger.info(
            "Applicazione mascheramento visivo PII su scontrino %s...",
            storage_key,
        )
        redacted_image_bytes = pii_redaction_service.redact_receipt_image(
            raw_image_bytes
        )
        if not redacted_image_bytes:
            raise GDPRRedactionFailedError("L'immagine anonimizzata risulta vuota.")
    except Exception as e:
        logger.critical(
            "Fallimento redazione visiva PII per job %s: %s. "
            "Invio al Vision LLM abortito per sicurezza GDPR.",
            job_id,
            e,
        )
        raise GDPRRedactionFailedError(
            f"Anonimizzazione visiva fallita: {e}. Elaborazione interrotta "
            "per garantire la riservatezza dei dati dell'utente."
        ) from e

    # 3. Invio ESCLUSIVO dell'immagine anonimizzata al Vision LLM
    worker = VisionWorker()

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    extraction = loop.run_until_complete(
        worker.process_receipt_image(
            image_bytes=redacted_image_bytes,
            mime_type="image/jpeg",
            redact_pii=False,  # Già anonimizzata nello step precedente
        )
    )

    logger.info(
        "Task process_receipt completato per job %s (esercente: %s, tot: %d)",
        job_id,
        extraction.merchant_name,
        extraction.total_amount_cents,
    )

    return extraction.model_dump(mode="json")
