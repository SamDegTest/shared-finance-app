import json
import logging
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.core.celery_app import celery_app
from app.core.config import settings
from app.core.storage import storage_service
from app.schemas.ingestion import IngestionJobStatus
from app.schemas.receipt import (
    ReceiptExtractionResponse,
    ReceiptItem,
    ValidationMismatchError,
)
from app.services.ingestion_service import IngestionService
from app.services.vision_worker import (
    OpenAIVisionProvider,
    VisionWorker,
)
from app.tasks.receipt_tasks import process_receipt


def _create_dummy_image_bytes() -> bytes:
    """Restituisce un payload JPEG minimo valido per i test."""
    header = (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00"
        b"\xff\xdb\x00C\x00"
    )
    body = b"DUMMY_RECEIPT_TEXT\nTOTALE 10.00 EUR"
    footer = b"\xff\xd9"
    return header + body + footer


# ==============================================================================
# 1. TEST MOCK S3 CALLS & S3 ERROR BOUNDARIES
# ==============================================================================


def test_process_receipt_handles_s3_read_failure_and_preserves_state() -> None:
    """AC 1: Fallimento download S3 solleva RuntimeError e non procede."""
    storage_key = f"receipts/{uuid.uuid4()}/missing_receipt.jpg"
    job_id = f"job_{uuid.uuid4().hex[:8]}"
    household_id = str(uuid.uuid4())

    with (
        patch.object(
            storage_service,
            "read_file",
            side_effect=RuntimeError("S3 Bucket timeout o 404 Not Found"),
        ),
        pytest.raises(RuntimeError, match="Errore lettura storage"),
    ):
        process_receipt(
            job_id=job_id,
            storage_key=storage_key,
            household_id=household_id,
        )


def test_process_receipt_handles_s3_save_redacted_warning_and_continues(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """AC 1: Fallimento salvataggio immagine oscurata non blocca il flusso."""
    caplog.set_level(logging.WARNING)

    raw_bytes = _create_dummy_image_bytes()
    storage_key = f"receipts/{uuid.uuid4()}/receipt_warn.jpg"
    storage_service.save_file(storage_key, raw_bytes)

    job_id = f"job_{uuid.uuid4().hex[:8]}"
    household_id = str(uuid.uuid4())

    mock_s3 = MagicMock()

    with (
        patch.object(storage_service, "_get_s3_client", return_value=mock_s3),
        patch.object(
            storage_service,
            "save_redacted_receipt",
            side_effect=Exception("S3 Destination Bucket permissions error"),
        ),
    ):
        result = process_receipt(
            job_id=job_id,
            storage_key=storage_key,
            household_id=household_id,
        )

        assert result["merchant_name"] == "Supermercato Esempio"
        assert result["total_amount_cents"] == 2540
        assert any(
            "Impossibile salvare immagine oscurata in storage" in rec.message
            for rec in caplog.records
        )


def test_process_receipt_handles_s3_delete_failure_with_lifecycle_fallback_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """AC 1: Fallimento delete raw post-successo logga fallback per Lifecycle."""
    caplog.set_level(logging.ERROR)

    raw_bytes = _create_dummy_image_bytes()
    storage_key = f"receipts/{uuid.uuid4()}/receipt_del_fail.jpg"
    storage_service.save_file(storage_key, raw_bytes)

    job_id = f"job_{uuid.uuid4().hex[:8]}"
    household_id = str(uuid.uuid4())

    with patch.object(
        storage_service,
        "delete_file",
        side_effect=RuntimeError("S3 Access Denied on delete"),
    ):
        result = process_receipt(
            job_id=job_id,
            storage_key=storage_key,
            household_id=household_id,
        )

        # L'estrazione deve comunque avere successo
        assert result["total_amount_cents"] == 2540
        assert any(
            "eliminazione immediata scontrino raw fallita" in rec.message
            for rec in caplog.records
        )
        assert any("Lifecycle Policy S3" in rec.message for rec in caplog.records)


# ==============================================================================
# 2. TEST RISPOSTE LLM NON VALIDE / MALFORMATE (VALIDATION_MISMATCH)
# ==============================================================================


@pytest.mark.asyncio
async def test_openai_vision_provider_malformed_json_raises_validation_mismatch() -> (
    None
):
    """AC 2: Risposta non-JSON da OpenAI solleva ValidationMismatchError."""
    provider = OpenAIVisionProvider(api_key="test-mock-key")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": "Questo non è un JSON valido {{{",
                }
            }
        ]
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        with pytest.raises(ValidationMismatchError, match="JSON malformato"):
            await provider.extract_receipt(_create_dummy_image_bytes())


@pytest.mark.asyncio
async def test_openai_vision_provider_schema_violation_raises_validation_mismatch() -> (
    None
):
    """AC 2: Risposta JSON con tipi o campi invalidi solleva ValidationMismatchError."""
    provider = OpenAIVisionProvider(api_key="test-mock-key")

    # Payload non conforme (total_amount_cents negativo e merchant_name assente)
    invalid_schema_content = json.dumps(
        {
            "merchant_name": "",  # min_length=1 violato
            "total_amount_cents": -500,  # gt=0 violato
            "currency": "EUR",
        }
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": invalid_schema_content}}]
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        with pytest.raises(
            ValidationMismatchError, match="non rispetta lo schema Pydantic"
        ):
            await provider.extract_receipt(_create_dummy_image_bytes())


def test_process_receipt_validation_mismatch_fails_and_preserves_raw_s3_file() -> None:
    """AC 2: Validation mismatch blocca task, solleva errore e preserva raw S3."""
    raw_bytes = _create_dummy_image_bytes()
    storage_key = f"receipts/{uuid.uuid4()}/receipt_mismatch.jpg"
    storage_service.save_file(storage_key, raw_bytes)

    job_id = f"job_{uuid.uuid4().hex[:8]}"
    household_id = str(uuid.uuid4())

    mock_s3 = MagicMock()

    with (
        patch.object(storage_service, "_get_s3_client", return_value=mock_s3),
        patch(
            "app.tasks.receipt_tasks.VisionWorker.process_receipt_image",
            side_effect=ValidationMismatchError(
                "Somma voci incompatibile e schema corrotto"
            ),
        ),
        patch.object(
            storage_service, "delete_file", wraps=storage_service.delete_file
        ) as spy_delete,
        pytest.raises(ValidationMismatchError, match="validation_mismatch"),
    ):
        process_receipt(
            job_id=job_id,
            storage_key=storage_key,
            household_id=household_id,
        )

        # AC 2: Il file raw NON deve essere cancellato in caso di errore di validazione
        spy_delete.assert_not_called()
        mock_s3.delete_object.assert_not_called()
        assert storage_service.file_exists(storage_key) is True


@pytest.mark.asyncio
async def test_ingestion_service_transitions_to_failed_on_validation_mismatch() -> None:
    """AC 2: IngestionService imposta lo stato su FAILED con validation_mismatch."""
    mock_worker = MagicMock(spec=VisionWorker)
    mock_worker.process_receipt_image = AsyncMock(
        side_effect=ValidationMismatchError("Campi obbligatori mancanti")
    )

    service = IngestionService(vision_worker=mock_worker)
    household_id = uuid.uuid4()
    storage_key = "receipts/test/mismatch_job.jpg"

    job = await service.enqueue_receipt_ingestion(
        household_id=household_id,
        storage_key=storage_key,
        image_bytes=_create_dummy_image_bytes(),
    )

    # Attendi completamento background task
    await service._process_job_task(
        job_id=job.job_id,
        storage_key=storage_key,
        image_bytes=_create_dummy_image_bytes(),
    )

    updated_job = service.get_job(job.job_id)
    assert updated_job is not None
    assert updated_job.status == IngestionJobStatus.FAILED
    assert updated_job.completed_at is not None
    assert updated_job.error_message is not None
    assert "validation_mismatch" in updated_job.error_message


# ==============================================================================
# 3. TEST CELERY ASYNC RETRY & EXPONENTIAL BACKOFF ON LLM TIMEOUTS
# ==============================================================================


def test_celery_task_retry_configuration_attributes() -> None:
    """AC 3: Parametri di configurazione retry e backoff del task Celery."""
    assert getattr(process_receipt, "max_retries", None) == 3
    assert getattr(process_receipt, "retry_backoff", False) is True
    assert getattr(process_receipt, "retry_backoff_max", None) == 300
    assert getattr(process_receipt, "retry_jitter", False) is True

    autoretry_tuple = getattr(process_receipt, "autoretry_for", ())
    assert httpx.TimeoutException in autoretry_tuple
    assert httpx.NetworkError in autoretry_tuple
    assert httpx.ConnectTimeout in autoretry_tuple
    assert httpx.ReadTimeout in autoretry_tuple


def test_celery_task_retries_on_llm_timeout_and_succeeds_on_second_attempt() -> None:
    """AC 3: Retry automatico su timeout con successo al 2° tentativo."""
    raw_bytes = _create_dummy_image_bytes()
    storage_key = f"receipts/{uuid.uuid4()}/receipt_retry_ok.jpg"
    storage_service.save_file(storage_key, raw_bytes)

    job_id = f"job_{uuid.uuid4().hex[:8]}"
    household_id = str(uuid.uuid4())

    call_count = 0

    async def mock_extract(*_args: Any, **_kwargs: Any) -> ReceiptExtractionResponse:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise httpx.ReadTimeout("Timeout transitorio API Vision LLM")
        return ReceiptExtractionResponse(
            merchant_name="Farmacia Centrale",
            total_amount_cents=1890,
            currency="EUR",
            items=[ReceiptItem(name="Sciroppo", amount_cents=1890, quantity=1)],
        )

    # Configura Celery in modalità eager per eseguire i retry in-process offline
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = False
    celery_app.conf.result_backend = "cache+memory://"

    mock_s3 = MagicMock()

    with (
        patch.object(storage_service, "_get_s3_client", return_value=mock_s3),
        patch(
            "app.tasks.receipt_tasks.VisionWorker.process_receipt_image",
            side_effect=mock_extract,
        ),
        patch.object(
            storage_service, "delete_file", wraps=storage_service.delete_file
        ) as spy_delete,
    ):
        async_res = process_receipt.apply(args=[job_id, storage_key, household_id])
        result = async_res.get()

        # 1. Chiamata 2 volte (1 fallimento + 1 retry riuscito)
        assert call_count == 2

        # 2. Risultato finale estratto con successo
        assert result["merchant_name"] == "Farmacia Centrale"
        assert result["total_amount_cents"] == 1890

        # 3. Pulizia scontrino raw al termine con successo (GDPR Art. 5)
        spy_delete.assert_called_once_with(
            storage_key=storage_key,
            bucket_name=settings.S3_RAW_BUCKET_NAME,
        )


def test_celery_task_retries_exhausted_preserves_raw_s3_receipt() -> None:
    """AC 3 & AC 4: Esaurimento 3 tentativi fallisce task e preserva scontrino raw."""
    raw_bytes = _create_dummy_image_bytes()
    storage_key = f"receipts/{uuid.uuid4()}/receipt_retry_exhausted.jpg"
    storage_service.save_file(storage_key, raw_bytes)

    job_id = f"job_{uuid.uuid4().hex[:8]}"
    household_id = str(uuid.uuid4())

    call_count = 0

    async def mock_extract_always_timeout(
        *_args: Any, **_kwargs: Any
    ) -> ReceiptExtractionResponse:
        nonlocal call_count
        call_count += 1
        raise httpx.ConnectTimeout("Vision LLM unreachable timeout")

    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = False
    celery_app.conf.result_backend = "cache+memory://"

    mock_s3 = MagicMock()

    with (
        patch.object(storage_service, "_get_s3_client", return_value=mock_s3),
        patch(
            "app.tasks.receipt_tasks.VisionWorker.process_receipt_image",
            side_effect=mock_extract_always_timeout,
        ),
        patch.object(
            storage_service, "delete_file", wraps=storage_service.delete_file
        ) as spy_delete,
    ):
        async_res = process_receipt.apply(args=[job_id, storage_key, household_id])

        assert async_res.status == "FAILURE"
        with pytest.raises(httpx.ConnectTimeout):
            async_res.get()

        # 1 iniziale + 3 retries = 4 chiamate complessive
        assert call_count == 4

        # Il file raw NON deve essere stato eliminato
        spy_delete.assert_not_called()
        mock_s3.delete_object.assert_not_called()
        assert storage_service.file_exists(storage_key) is True


# ==============================================================================
# 4. TEST 100% OFFLINE EXECUTION & CI COMPATIBILITY
# ==============================================================================


def test_test_suite_runs_completely_offline_without_real_credentials() -> None:
    """AC 4: Esecuzione completamente offline senza credenziali reali."""
    assert settings.S3_RAW_BUCKET_NAME is not None
    assert settings.S3_REDACTED_BUCKET_NAME is not None
    assert settings.VISION_MODEL == "gpt-4o-mini"
    assert settings.OPENAI_API_KEY is None
