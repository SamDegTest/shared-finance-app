import base64
import hashlib
import hmac
import time
import uuid
from pathlib import Path

from app.core.config import settings


class StorageService:
    """Gestore sicuro dello storage delle ricevute con URL pre-firmati."""

    def __init__(self) -> None:
        self.provider = settings.STORAGE_PROVIDER
        self.signing_secret = settings.STORAGE_SIGNING_SECRET.encode("utf-8")
        self.local_dir = Path(settings.STORAGE_LOCAL_DIR)
        self.local_dir.mkdir(parents=True, exist_ok=True)

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
        _content_type: str = "image/jpeg",
    ) -> str:
        """Salva i byte del file nello storage isolato."""
        file_path = self.local_dir / storage_key
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with file_path.open("wb") as f:
            f.write(data)
        return str(file_path)

    def read_file(self, storage_key: str) -> bytes:
        """Legge i byte del file dallo storage."""
        file_path = self.local_dir / storage_key
        if not file_path.exists():
            raise FileNotFoundError(
                f"File di storage non trovato per la chiave: {storage_key}"
            )
        with file_path.open("rb") as f:
            return f.read()

    def file_exists(self, storage_key: str) -> bool:
        """Verifica se il file è presente nello storage."""
        file_path = self.local_dir / storage_key
        return file_path.exists()


storage_service = StorageService()
