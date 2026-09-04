import asyncio
import logging
from typing import Any

import httpx

from app.core.celery_app import celery_app
from app.core.config import settings
from app.core.storage import storage_service
from app.schemas.receipt import ValidationMismatchError
from app.services.pii_redaction_service import pii_redaction_service
from app.services.vision_worker import (
    GDPRRedactionFailedError,
    VisionWorker,
)

logger = logging.getLogger("shared-finance-app.receipt_tasks")


@celery_app.task(  # type: ignore[untyped-decorator]
    name="process_receipt",
    bind=True,
    max_retries=3,
    default_retry_delay=2,
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    autoretry_for=(
        httpx.TimeoutException,
        httpx.NetworkError,
        httpx.ConnectTimeout,
        httpx.ReadTimeout,
        httpx.ConnectError,
    ),
)
def process_receipt(
    self: Any,
    job_id: str,
    storage_key: str,
    household_id: str,
) -> dict[str, Any]:
    """Task asincrono Celery con redazione visiva ed eliminazione sicura."""
    logger.info(
        "Avvio task Celery process_receipt: job=%s, key=%s, "
        "household=%s (tentativo=%s)",
        job_id,
        storage_key,
        household_id,
        getattr(getattr(self, "request", None), "retries", 0),
    )

    # 1. Download dell'immagine originale da S3 / Storage locale
    try:
        raw_image_bytes = storage_service.read_file(
            storage_key=storage_key,
            bucket_name=settings.S3_RAW_BUCKET_NAME,
        )
    except Exception as e:
        logger.exception("Impossibile scaricare lo scontrino da storage: %s", e)
        # Il file raw rimane nello storage per consentire retry automatici
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
        # In caso di errore PII, conserviamo per retry/investigazione
        raise GDPRRedactionFailedError(
            f"Anonimizzazione visiva fallita: {e}. Elaborazione interrotta "
            "per garantire la riservatezza dei dati dell'utente."
        ) from e

    # 3. Salvataggio immagine oscurata nel bucket shbc-redacted-receipts
    try:
        redacted_key = storage_service.save_redacted_receipt(
            storage_key=storage_key,
            data=redacted_image_bytes,
        )
        logger.info(
            "Immagine oscurata salvata nel bucket di destinazione: %s",
            redacted_key,
        )
    except Exception as e:
        logger.warning(
            "Impossibile salvare immagine oscurata in storage: %s",
            e,
        )

    # 4. Invio ESCLUSIVO dell'immagine anonimizzata al Vision LLM
    try:
        worker = VisionWorker()
        extraction = asyncio.run(
            worker.process_receipt_image(
                image_bytes=redacted_image_bytes,
                mime_type="image/jpeg",
                redact_pii=False,  # Già anonimizzata nello step precedente
            )
        )
    except (ValidationMismatchError, ValueError) as e:
        logger.error(
            "Validazione fallita per job %s (validation_mismatch): %s. "
            "Scontrino raw conservato per investigazione o inserimento manuale.",
            job_id,
            e,
        )
        raise ValidationMismatchError(f"validation_mismatch: {e}") from e
    except (httpx.TimeoutException, httpx.NetworkError) as e:
        logger.warning(
            "Timeout/errore transitorio di rete verso Vision LLM per job %s: %s. "
            "Attivazione retry Celery...",
            job_id,
            e,
        )
        raise

    # 5. Eliminazione Sicura Immediata dello Scontrino Raw (GDPR Art. 5)
    try:
        storage_service.delete_file(
            storage_key=storage_key,
            bucket_name=settings.S3_RAW_BUCKET_NAME,
        )
        logger.info(
            "Scontrino raw eliminato con successo per GDPR Art. 5: "
            "job=%s, key=%s, bucket=%s",
            job_id,
            storage_key,
            settings.S3_RAW_BUCKET_NAME,
        )
    except Exception as e:
        logger.error(
            "Avviso: eliminazione immediata scontrino raw fallita (%s): %s. "
            "La Lifecycle Policy S3 eliminerà il file orfano.",
            storage_key,
            e,
        )

    logger.info(
        "process_receipt completato per job %s (esercente: %s, tot: %d)",
        job_id,
        extraction.merchant_name,
        extraction.total_amount_cents,
    )

    return extraction.model_dump(mode="json")
