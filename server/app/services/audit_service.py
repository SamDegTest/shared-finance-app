import asyncio
import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.utils.privacy import anonymize_ip_address, sanitize_audit_details

logger = logging.getLogger("shared-finance-app.audit")


class AuditService:
    """Servizio asincrono per audit logging conforme ad Art. 30/32 GDPR."""

    def __init__(self) -> None:
        self._background_tasks: set[asyncio.Task[None]] = set()
        self.session_factory: Any = AsyncSessionLocal

    async def log_event(
        self,
        session: AsyncSession,
        *,
        action: str,
        resource_type: str,
        user_id: uuid.UUID | None = None,
        household_id: uuid.UUID | None = None,
        resource_id: str | None = None,
        ip_address: str | None = None,
        status: str = "SUCCESS",
        details: dict[str, Any] | None = None,
    ) -> AuditLog:
        """Registra un evento di audit all'interno della sessione fornita."""
        masked_ip = anonymize_ip_address(ip_address)
        clean_details = sanitize_audit_details(details)

        audit_record = AuditLog(
            user_id=user_id,
            household_id=household_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            ip_address_masked=masked_ip,
            status=status,
            details=clean_details,
        )

        session.add(audit_record)
        await session.commit()
        await session.refresh(audit_record)

        logger.info(
            "Audit registrato: action=%s, res=%s:%s, status=%s, user=%s",
            action,
            resource_type,
            resource_id,
            status,
            user_id,
        )
        return audit_record

    async def record_audit_log_async(
        self,
        *,
        action: str,
        resource_type: str,
        user_id: uuid.UUID | None = None,
        household_id: uuid.UUID | None = None,
        resource_id: str | None = None,
        ip_address: str | None = None,
        status: str = "SUCCESS",
        details: dict[str, Any] | None = None,
    ) -> None:
        """Registra un evento di audit aprendo una sessione DB isolata."""
        if not self.session_factory:
            return

        try:
            async with self.session_factory() as session:
                await self.log_event(
                    session=session,
                    action=action,
                    resource_type=resource_type,
                    user_id=user_id,
                    household_id=household_id,
                    resource_id=resource_id,
                    ip_address=ip_address,
                    status=status,
                    details=details,
                )
        except Exception as e:
            logger.debug(
                "Impossibile registrare log di audit in background (%s): %s",
                action,
                e,
            )

    def enqueue_audit_log(
        self,
        *,
        action: str,
        resource_type: str,
        user_id: uuid.UUID | None = None,
        household_id: uuid.UUID | None = None,
        resource_id: str | None = None,
        ip_address: str | None = None,
        status: str = "SUCCESS",
        details: dict[str, Any] | None = None,
    ) -> None:
        """Accoda in background la registrazione dell'evento (0 ms overhead)."""
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(
                self.record_audit_log_async(
                    action=action,
                    resource_type=resource_type,
                    user_id=user_id,
                    household_id=household_id,
                    resource_id=resource_id,
                    ip_address=ip_address,
                    status=status,
                    details=details,
                )
            )
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
        except RuntimeError:
            logger.warning(
                "Nessun event loop in esecuzione per enqueue_audit_log (%s)",
                action,
            )


audit_service = AuditService()
