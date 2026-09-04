import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.models.base import Base, UUIDPrimaryKeyMixin


class AuditActionType(StrEnum):
    """Tipologie di azioni tracciabili per flussi sensibili."""

    READ_RECEIPT = "READ_RECEIPT"
    UPLOAD_RECEIPT = "UPLOAD_RECEIPT"
    DELETE_RECEIPT = "DELETE_RECEIPT"
    CREATE_EXPENSE = "CREATE_EXPENSE"
    UPDATE_EXPENSE = "UPDATE_EXPENSE"
    DELETE_EXPENSE = "DELETE_EXPENSE"
    READ_EXPENSE = "READ_EXPENSE"
    READ_SETTLEMENT = "READ_SETTLEMENT"
    EXPORT_FINANCIAL_REPORT = "EXPORT_FINANCIAL_REPORT"
    READ_HOUSEHOLD = "READ_HOUSEHOLD"
    UPDATE_HOUSEHOLD = "UPDATE_HOUSEHOLD"
    AUTH_LOGIN = "AUTH_LOGIN"
    AUTH_LOGOUT = "AUTH_LOGOUT"


class AuditLog(Base, UUIDPrimaryKeyMixin):
    """Registro elettronico di audit per conformità Art. 30/32 GDPR."""

    __tablename__ = "audit_logs"

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid().with_variant(PG_UUID(as_uuid=True), "postgresql"),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    household_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid().with_variant(PG_UUID(as_uuid=True), "postgresql"),
        ForeignKey("households.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    action: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )

    resource_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )

    resource_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        index=True,
    )

    ip_address_masked: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="SUCCESS",
    )

    details: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    __table_args__ = (
        Index(
            "ix_audit_logs_household_created",
            "household_id",
            "created_at",
        ),
        Index(
            "ix_audit_logs_action_created",
            "action",
            "created_at",
        ),
    )
