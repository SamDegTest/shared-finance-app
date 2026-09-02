import io
import time
import uuid

from fastapi.testclient import TestClient

from app.core.storage import storage_service
from app.main import app
from app.schemas.ingestion import IngestionJobStatus


def test_storage_presigned_url_generation_and_validation() -> None:
    household_id = uuid.uuid4()
    upload_url, storage_key = storage_service.generate_presigned_upload_url(
        household_id=household_id, file_extension="jpg", expires_in=900
    )

    assert "receipts/" in storage_key
    assert str(household_id) in storage_key
    assert "signature=" in upload_url
    assert "expires=" in upload_url

    # Verifica download URL
    download_url = storage_service.generate_presigned_download_url(
        storage_key=storage_key, expires_in=900
    )
    assert "signature=" in download_url

    # Verifica validazione HMAC
    expires_at = int(time.time()) + 900
    sig = storage_service._generate_hmac_signature(storage_key, expires_at)
    assert (
        storage_service.validate_presigned_token(storage_key, expires_at, sig) is True
    )

    # Verifica rifiuto con firma manomessa
    assert (
        storage_service.validate_presigned_token(
            storage_key, expires_at, "fake_tampered_sig"
        )
        is False
    )

    # Verifica rifiuto con scadenza passata
    past_timestamp = int(time.time()) - 100
    assert (
        storage_service.validate_presigned_token(storage_key, past_timestamp, sig)
        is False
    )


def test_api_generate_upload_url() -> None:
    household_id = uuid.uuid4()
    with TestClient(app) as client:
        res = client.post(
            f"/api/v1/households/{household_id}/receipts/upload-url?file_extension=png"
        )
        assert res.status_code == 200
        data = res.json()
        assert "upload_url" in data
        assert "storage_key" in data
        assert data["expires_in_seconds"] == 900
        assert data["http_method"] == "PUT"
        assert str(household_id) in data["storage_key"]
        assert data["storage_key"].endswith(".png")


def test_api_receipt_upload_benchmark_and_async_job_queue() -> None:
    """AC: Upload completato entro 2s, restituzione job_id per polling."""
    household_id = uuid.uuid4()

    fake_image_content = b"RI_TEST_IMAGE_BYTES_FOR_RECEIPT_1234567890"
    file_payload = {
        "file": (
            "scontrino_spesa.jpg",
            io.BytesIO(fake_image_content),
            "image/jpeg",
        )
    }

    with TestClient(app) as client:
        # 1. Benchmark Latenza Upload (< 2 secondi)
        start_t = time.perf_counter()
        res = client.post(
            f"/api/v1/households/{household_id}/receipts/upload",
            files=file_payload,
        )
        elapsed_seconds = time.perf_counter() - start_t

        assert res.status_code == 202
        assert elapsed_seconds < 2.0, (
            f"Latenza upload ({elapsed_seconds:.3f}s) superiore a 2.0s!"
        )

        job_data = res.json()
        assert "job_id" in job_data
        job_id = job_data["job_id"]
        assert job_data["household_id"] == str(household_id)
        assert job_data["status"] in ["PENDING", "PROCESSING", "COMPLETED"]

        # 2. Polling stato job finché non diventa COMPLETED
        max_attempts = 30
        completed = False
        final_job_data = {}

        for _ in range(max_attempts):
            poll_res = client.get(f"/api/v1/receipts/jobs/{job_id}")
            assert poll_res.status_code == 200
            final_job_data = poll_res.json()
            if final_job_data["status"] == IngestionJobStatus.COMPLETED.value:
                completed = True
                break
            time.sleep(0.05)

        assert completed is True, f"Il job {job_id} non è stato completato."
        assert final_job_data["result"] is not None
        assert final_job_data["result"]["total_amount_cents"] > 0
        assert len(final_job_data["result"]["items"]) > 0
        assert final_job_data["processing_time_ms"] is not None


def test_api_ingest_from_storage_key() -> None:
    household_id = uuid.uuid4()

    storage_key = storage_service.generate_storage_key(household_id, "jpg")
    storage_service.save_file(storage_key, b"RAW_RECEIPT_BINARY_DATA")

    with TestClient(app) as client:
        payload = {"storage_key": storage_key}
        res = client.post(
            f"/api/v1/households/{household_id}/receipts/ingest",
            json=payload,
        )
        assert res.status_code == 202
        data = res.json()
        assert "job_id" in data
        assert data["household_id"] == str(household_id)


def test_api_job_not_found_returns_404() -> None:
    with TestClient(app) as client:
        res = client.get("/api/v1/receipts/jobs/job_inexistent_12345")
        assert res.status_code == 404
        assert "non trovato" in res.json()["detail"]
