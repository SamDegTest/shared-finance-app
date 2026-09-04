import json
import logging
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.core.config import settings
from app.core.storage import storage_service
from app.services.vision_worker import GDPRRedactionFailedError
from app.tasks.receipt_tasks import process_receipt

LIFECYCLE_POLICY_PATH = (
    Path(__file__).parent.parent / "infra" / "s3_lifecycle_policy.json"
)


def _create_sample_receipt(text: str = "PAGAMENTO 5500 0000 0000 0004") -> bytes:
    """Crea un byte payload valido per il test."""
    header = (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00"
        b"\xff\xdb\x00C\x00"
    )
    body = text.encode("utf-8") + b"\nTOTALE: 15.00 EUR"
    footer = b"\xff\xd9"
    return header + body + footer


def test_s3_lifecycle_policy_json_is_valid_and_has_24h_expiration() -> None:
    """AC 3: Verifica che il file JSON di Lifecycle Policy imposti 1 giorno."""
    assert LIFECYCLE_POLICY_PATH.exists(), f"File non trovato: {LIFECYCLE_POLICY_PATH}"

    with LIFECYCLE_POLICY_PATH.open("r", encoding="utf-8") as f:
        policy = json.load(f)

    assert "Rules" in policy
    assert len(policy["Rules"]) >= 1

    rule = policy["Rules"][0]
    assert rule.get("Status") == "Enabled"
    assert rule.get("Expiration", {}).get("Days") == 1
    assert rule.get("NoncurrentVersionExpiration", {}).get("NoncurrentDays") == 1
    assert (
        rule.get("AbortIncompleteMultipartUpload", {}).get("DaysAfterInitiation") == 1
    )


def test_storage_service_apply_bucket_lifecycle_policy() -> None:
    """AC 3: Verifica applicazione programmatic della policy S3 tramite boto3."""
    mock_s3 = MagicMock()
    with patch.object(storage_service, "_get_s3_client", return_value=mock_s3):
        config = storage_service.apply_bucket_lifecycle_policy(
            bucket_name=settings.S3_RAW_BUCKET_NAME,
            expiration_days=1,
        )

        assert config is not None
        assert "Rules" in config
        mock_s3.put_bucket_lifecycle_configuration.assert_called_once_with(
            Bucket=settings.S3_RAW_BUCKET_NAME,
            LifecycleConfiguration=config,
        )


def test_boto3_s3_delete_object_invocation() -> None:
    """AC 1: Verifica che storage_service.delete_file invochi delete_object."""
    mock_s3 = MagicMock()
    storage_key = f"receipts/{uuid.uuid4()}/test_receipt.jpg"

    with patch.object(storage_service, "_get_s3_client", return_value=mock_s3):
        result = storage_service.delete_file(
            storage_key=storage_key,
            bucket_name=settings.S3_RAW_BUCKET_NAME,
        )

        assert result is True
        mock_s3.delete_object.assert_called_once_with(
            Bucket=settings.S3_RAW_BUCKET_NAME,
            Key=storage_key,
        )


def test_process_receipt_deletes_raw_s3_object_on_success(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """AC 1 & AC 4: Eliminazione raw receipt post-successo con log GDPR."""
    caplog.set_level(logging.INFO)

    raw_image = _create_sample_receipt()
    storage_key = f"receipts/{uuid.uuid4()}/receipt_to_delete.jpg"
    storage_service.save_file(storage_key, raw_image)

    job_id = f"job_{uuid.uuid4().hex[:8]}"
    household_id = str(uuid.uuid4())

    mock_s3 = MagicMock()

    with (
        patch.object(storage_service, "_get_s3_client", return_value=mock_s3),
        patch.object(
            storage_service,
            "save_redacted_receipt",
            wraps=storage_service.save_redacted_receipt,
        ) as spy_save_redacted,
    ):
        result = process_receipt(
            job_id=job_id,
            storage_key=storage_key,
            household_id=household_id,
        )

        # 1. Verifica estrazione avvenuta con successo
        assert result["merchant_name"] == "Supermercato Esempio"
        assert result["total_amount_cents"] == 2540

        # 2. Verifica che l'immagine oscurata sia stata salvata
        spy_save_redacted.assert_called_once()

        # 3. AC 1: Verifica che delete_object sia stato invocato su raw bucket
        mock_s3.delete_object.assert_called_once_with(
            Bucket=settings.S3_RAW_BUCKET_NAME,
            Key=storage_key,
        )

        # 4. AC 4: Verifica log di audit GDPR senza leakage PII
        log_records = [rec.message for rec in caplog.records]
        assert any("eliminato con successo per GDPR Art. 5" in m for m in log_records)
        assert any(settings.S3_RAW_BUCKET_NAME in m for m in log_records)
        assert not any("5500 0000 0000 0004" in m for m in log_records)


def test_process_receipt_preserves_raw_object_when_processing_fails() -> None:
    """AC 2: In caso di errore, il file raw non viene cancellato per retry."""
    raw_image = _create_sample_receipt()
    storage_key = f"receipts/{uuid.uuid4()}/receipt_retry.jpg"
    storage_service.save_file(storage_key, raw_image)

    job_id = f"job_{uuid.uuid4().hex[:8]}"
    household_id = str(uuid.uuid4())

    mock_s3 = MagicMock()

    # Simula crash improvviso del modulo OCR / redazione
    with (
        patch.object(storage_service, "_get_s3_client", return_value=mock_s3),
        patch(
            "app.tasks.receipt_tasks.pii_redaction_service.redact_receipt_image",
            side_effect=RuntimeError("OCR Worker crash"),
        ),
        patch.object(
            storage_service, "delete_file", wraps=storage_service.delete_file
        ) as spy_delete,
    ):
        with pytest.raises(GDPRRedactionFailedError):
            process_receipt(
                job_id=job_id,
                storage_key=storage_key,
                household_id=household_id,
            )

        # AC 2: delete_file e delete_object NON devono essere stati chiamati
        spy_delete.assert_not_called()
        mock_s3.delete_object.assert_not_called()

        # Il file raw è ancora presente nello storage per retry
        assert storage_service.file_exists(storage_key) is True
