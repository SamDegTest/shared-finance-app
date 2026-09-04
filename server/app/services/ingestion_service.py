import asyncio
import logging
import time
import uuid
from datetime import UTC, datetime

from app.core.storage import storage_service
from app.schemas.ingestion import IngestionJobResponse, IngestionJobStatus
from app.schemas.receipt import ValidationMismatchError
from app.services.vision_worker import (
    GDPRRedactionFailedError,
    VisionWorker,
)

logger = logging.getLogger("shared-finance-app.ingestion_service")


class IngestionService:
    """Servizio per la gestione asincrona dei job di ingestion e OCR ricevute."""

    def __init__(self, vision_worker: VisionWorker | None = None) -> None:
        self.vision_worker = vision_worker or VisionWorker()
        self._jobs_store: dict[str, IngestionJobResponse] = {}
        self._background_tasks: set[asyncio.Task[None]] = set()

    def get_job(self, job_id: str) -> IngestionJobResponse | None:
        """Recupera lo stato attuale del job dal database/store."""
        return self._jobs_store.get(job_id)

    async def _process_job_task(
        self,
        job_id: str,
        storage_key: str,
        image_bytes: bytes | None,
    ) -> None:
        """Esegue il task in background per non bloccare l'API Gateway."""
        job = self._jobs_store.get(job_id)
        if not job:
            logger.error("Job %s non trovato.", job_id)
            return

        start_time = time.perf_counter()
        job.status = IngestionJobStatus.PROCESSING
        self._jobs_store[job_id] = job

        try:
            # 1. Recupero byte immagine dallo storage se non già in memoria
            data_bytes = image_bytes or storage_service.read_file(storage_key)

            # 2. Invocazione del Vision Worker con redazione visiva PII (GDPR-Safe)
            extraction_result = await self.vision_worker.process_receipt_image(
                data_bytes,
                mime_type="image/jpeg",
                redact_pii=True,
            )

            # 3. Aggiornamento stato completato
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            job.status = IngestionJobStatus.COMPLETED
            job.completed_at = datetime.now(UTC)
            job.processing_time_ms = elapsed_ms
            job.result = extraction_result
            self._jobs_store[job_id] = job

            logger.info(
                "Job %s completato con successo in %.2f ms.",
                job_id,
                elapsed_ms,
            )

        except GDPRRedactionFailedError as e:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.error(
                "Elaborazione scontrino %s bloccata per sicurezza GDPR: %s",
                job_id,
                e,
            )
            job.status = IngestionJobStatus.FAILED
            job.completed_at = datetime.now(UTC)
            job.processing_time_ms = elapsed_ms
            job.error_message = (
                "Elaborazione interrotta per protezione privacy: "
                "impossibile anonimizzare le informazioni personali."
            )
            self._jobs_store[job_id] = job

        except ValidationMismatchError as e:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.error(
                "Elaborazione scontrino %s fallita per validation_mismatch: %s",
                job_id,
                e,
            )
            job.status = IngestionJobStatus.FAILED
            job.completed_at = datetime.now(UTC)
            job.processing_time_ms = elapsed_ms
            job.error_message = f"validation_mismatch: {e}"
            self._jobs_store[job_id] = job

        except Exception as e:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.exception("Errore elaborazione job %s: %s", job_id, e)
            job.status = IngestionJobStatus.FAILED
            job.completed_at = datetime.now(UTC)
            job.processing_time_ms = elapsed_ms
            job.error_message = str(e)
            self._jobs_store[job_id] = job

    async def enqueue_receipt_ingestion(
        self,
        household_id: uuid.UUID,
        storage_key: str,
        image_bytes: bytes | None = None,
    ) -> IngestionJobResponse:
        """Accoda l'elaborazione dello scontrino e restituisce il job_id."""
        job_id = f"job_{uuid.uuid4().hex[:16]}"
        job = IngestionJobResponse(
            job_id=job_id,
            household_id=household_id,
            status=IngestionJobStatus.PENDING,
            created_at=datetime.now(UTC),
        )
        self._jobs_store[job_id] = job

        # Avvio task in background asincrono e salvataggio reference per GC
        task = asyncio.create_task(
            self._process_job_task(job_id, storage_key, image_bytes)
        )
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

        logger.info(
            "Job di ingestion %s accodato (household: %s).",
            job_id,
            household_id,
        )
        return job


ingestion_service = IngestionService()
