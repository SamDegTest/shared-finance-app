import base64
import hashlib
import hmac
import importlib
import logging
import time
import uuid
from pathlib import Path
from typing import Any

from app.core.config import settings

logger = logging.getLogger("shared-finance-app.storage")


class StorageService:
    """Gestore sicuro dello storage delle ricevute con conformità GDPR Art. 5."""

    def __init__(self) -> None:
        self.provider = settings.STORAGE_PROVIDER
        self.raw_bucket = settings.S3_RAW_BUCKET_NAME
        self.redacted_bucket = settings.S3_REDACTED_BUCKET_NAME
        self.signing_secret = settings.STORAGE_SIGNING_SECRET.encode("utf-8")
        self.local_dir = Path(settings.STORAGE_LOCAL_DIR)
        self.local_dir.mkdir(parents=True, exist_ok=True)
        self._s3_client: Any = None

    def _get_s3_client(self) -> Any:
        """Restituisce o inizializza il client boto3 S3."""
        if self._s3_client is None:
            try:
                boto3 = importlib.import_module("boto3")
                client_kwargs: dict[str, Any] = {
                    "service_name": "s3",
                    "region_name": settings.S3_REGION,
                }
                if settings.S3_ENDPOINT_URL:
                    client_kwargs["endpoint_url"] = settings.S3_ENDPOINT_URL
                if settings.S3_ACCESS_KEY and settings.S3_SECRET_KEY:
                    client_kwargs["aws_access_key_id"] = settings.S3_ACCESS_KEY
                    client_kwargs["aws_secret_access_key"] = settings.S3_SECRET_KEY

                self._s3_client = boto3.client(**client_kwargs)
                logger.info("Client S3 boto3 inizializzato con successo.")
            except Exception as e:
                logger.warning("Impossibile inizializzare client boto3 S3: %s", e)
                self._s3_client = None
        return self._s3_client

    def _generate_hmac_signature(self, storage_key: str, expires_at: int) -> str:
        msg = f"{storage_key}:{expires_at}".encode()
        sig = hmac.new(self.signing_secret, msg, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(sig).decode("utf-8")

    def validate_presigned_token(
        self, storage_key: str, expires_at: int, signature: str
    ) -> bool:
        """Verifica la validità temporale e crittografica della firma HMAC."""
        current_ts = int(time.time())
        if current_ts > expires_at:
            return False

        expected_sig = self._generate_hmac_signature(storage_key, expires_at)
        return hmac.compare_digest(expected_sig, signature)

    def generate_storage_key(
        self, household_id: uuid.UUID, file_extension: str = "jpg"
    ) -> str:
        """Genera una chiave di storage isolata per tenant household_id."""
        clean_ext = file_extension.lstrip(".").lower()
        file_id = uuid.uuid4()
        return f"receipts/{household_id}/{file_id}.{clean_ext}"

    def generate_presigned_upload_url(
        self,
        household_id: uuid.UUID,
        file_extension: str = "jpg",
        expires_in: int | None = None,
    ) -> tuple[str, str]:
        """Genera un URL pre-firmato per upload diretto da client."""
        expiration = expires_in or settings.PRESIGNED_URL_EXPIRATION_SECONDS
        storage_key = self.generate_storage_key(household_id, file_extension)
        expires_at = int(time.time()) + expiration

        sig = self._generate_hmac_signature(storage_key, expires_at)
        upload_url = (
            f"/api/v1/storage/upload?key={storage_key}"
            f"&expires={expires_at}&signature={sig}"
        )
        return upload_url, storage_key

    def generate_presigned_download_url(
        self,
        storage_key: str,
        expires_in: int | None = None,
    ) -> str:
        """Genera un URL pre-firmato per scaricare una ricevuta."""
        expiration = expires_in or settings.PRESIGNED_URL_EXPIRATION_SECONDS
        expires_at = int(time.time()) + expiration
        sig = self._generate_hmac_signature(storage_key, expires_at)
        return (
            f"/api/v1/storage/download?key={storage_key}"
            f"&expires={expires_at}&signature={sig}"
        )

    def save_file(
        self,
        storage_key: str,
        data: bytes,
        content_type: str = "image/jpeg",
        bucket_name: str | None = None,
    ) -> str:
        """Salva i byte del file nello storage isolato (S3 o locale)."""
        bucket = bucket_name or self.raw_bucket

        if self.provider in ("s3", "minio"):
            client = self._get_s3_client()
            if client:
                client.put_object(
                    Bucket=bucket,
                    Key=storage_key,
                    Body=data,
                    ContentType=content_type,
                )

        file_path = self.local_dir / storage_key
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with file_path.open("wb") as f:
            f.write(data)
        return str(file_path)

    def save_redacted_receipt(
        self,
        storage_key: str,
        data: bytes,
        content_type: str = "image/jpeg",
    ) -> str:
        """Salva l'immagine anonimizzata nel bucket shbc-redacted-receipts."""
        redacted_key = (
            storage_key.replace("receipts/", "redacted/")
            if "receipts/" in storage_key
            else f"redacted/{storage_key}"
        )
        self.save_file(
            storage_key=redacted_key,
            data=data,
            content_type=content_type,
            bucket_name=self.redacted_bucket,
        )
        logger.info(
            "Scontrino anonimizzato salvato con successo: bucket=%s, key=%s",
            self.redacted_bucket,
            redacted_key,
        )
        return redacted_key

    def read_file(
        self,
        storage_key: str,
        bucket_name: str | None = None,
    ) -> bytes:
        """Legge i byte del file dallo storage."""
        bucket = bucket_name or self.raw_bucket

        if self.provider in ("s3", "minio"):
            client = self._get_s3_client()
            if client:
                try:
                    resp = client.get_object(Bucket=bucket, Key=storage_key)
                    return resp["Body"].read()  # type: ignore[no-any-return]
                except Exception as e:
                    logger.warning(
                        "Lettura da S3 fallita (%s), tentativo fallback locale: %s",
                        storage_key,
                        e,
                    )

        file_path = self.local_dir / storage_key
        if not file_path.exists():
            raise FileNotFoundError(
                f"File di storage non trovato per la chiave: {storage_key}"
            )
        with file_path.open("rb") as f:
            return f.read()

    def file_exists(
        self,
        storage_key: str,
        bucket_name: str | None = None,
    ) -> bool:
        """Verifica se il file è presente nello storage."""
        bucket = bucket_name or self.raw_bucket

        if self.provider in ("s3", "minio"):
            client = self._get_s3_client()
            if client:
                try:
                    client.head_object(Bucket=bucket, Key=storage_key)
                    return True
                except Exception:
                    pass

        file_path = self.local_dir / storage_key
        return file_path.exists()

    def delete_file(
        self,
        storage_key: str,
        bucket_name: str | None = None,
    ) -> bool:
        """Elimina permanentemente un oggetto da S3/Storage (GDPR Art. 5)."""
        bucket = bucket_name or self.raw_bucket
        deleted_s3 = False

        client = self._get_s3_client()
        if client:
            try:
                client.delete_object(Bucket=bucket, Key=storage_key)
                deleted_s3 = True
                logger.info(
                    "Eliminato oggetto da S3 per conformità Art. 5 GDPR: "
                    "bucket=%s, key=%s",
                    bucket,
                    storage_key,
                )
            except Exception as e:
                logger.warning(
                    "Errore durante eliminazione oggetto da S3 (%s/%s): %s",
                    bucket,
                    storage_key,
                    e,
                )

        file_path = self.local_dir / storage_key
        if file_path.exists():
            try:
                file_path.unlink()
                logger.info(
                    "Eliminato file locale per conformità Art. 5 GDPR: key=%s",
                    storage_key,
                )
            except Exception as e:
                logger.warning(
                    "Errore durante unlink file locale (%s): %s",
                    storage_key,
                    e,
                )

        return deleted_s3 or not file_path.exists()

    def apply_bucket_lifecycle_policy(
        self,
        bucket_name: str | None = None,
        expiration_days: int = 1,
    ) -> dict[str, Any]:
        """Applica la Lifecycle Policy di retention su S3 (es. 24h per raw bucket)."""
        bucket = bucket_name or self.raw_bucket
        lifecycle_config: dict[str, Any] = {
            "Rules": [
                {
                    "ID": f"{bucket}-24h-storage-limitation",
                    "Status": "Enabled",
                    "Filter": {"Prefix": ""},
                    "Expiration": {"Days": expiration_days},
                    "NoncurrentVersionExpiration": {"NoncurrentDays": expiration_days},
                    "AbortIncompleteMultipartUpload": {
                        "DaysAfterInitiation": expiration_days
                    },
                }
            ]
        }

        client = self._get_s3_client()
        if client:
            client.put_bucket_lifecycle_configuration(
                Bucket=bucket,
                LifecycleConfiguration=lifecycle_config,
            )
            logger.info(
                "Applicata S3 Lifecycle Policy con successo: bucket=%s, retention=%dgg",
                bucket,
                expiration_days,
            )

        return lifecycle_config


storage_service = StorageService()
