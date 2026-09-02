import uuid
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SQLEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.category import Category
    from app.models.household import Household
    from app.models.user import User


class SplitType(StrEnum):
    EQUAL = "EQUAL"
    PERCENTAGE = "PERCENTAGE"
    EXACT = "EXACT"
    SHARES = "SHARES"


class Expense(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "expenses"

    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    paid_by_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Financial Integrity: Strict integer in cents
    amount_cents: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        default="EUR",
        nullable=False,
    )
    title: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    expense_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
    )
    split_type: Mapped[SplitType] = mapped_column(
        SQLEnum(SplitType, name="expense_split_type_enum", native_enum=False),
        default=SplitType.EQUAL,
        nullable=False,
    )

    # Multimodal OCR metadata
    receipt_url: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
    )
    ocr_raw_data: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
    )

    # Relationships
    household: Mapped["Household"] = relationship(back_populates="expenses")
    paid_by: Mapped["User"] = relationship(back_populates="expenses_paid")
    category: Mapped["Category | None"] = relationship(back_populates="expenses")
    splits: Mapped[list["ExpenseSplit"]] = relationship(
        back_populates="expense",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint(
            "amount_cents > 0",
            name="ck_expense_amount_positive",
        ),
        CheckConstraint(
            "length(currency) = 3",
            name="ck_expense_currency_iso_len",
        ),
        Index("idx_expenses_household_date", "household_id", "expense_date"),
    )


class ExpenseSplit(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "expense_splits"

    expense_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("expenses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # Strict integer cents
    amount_cents: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    percentage: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2),
        nullable=True,
    )
    shares: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    # Relationships
    expense: Mapped["Expense"] = relationship(back_populates="splits")
    user: Mapped["User"] = relationship(back_populates="expense_splits")

    __table_args__ = (
        CheckConstraint(
            "amount_cents >= 0",
            name="ck_expense_split_amount_non_negative",
        ),
        UniqueConstraint(
            "expense_id",
            "user_id",
            name="uq_expense_split_user",
        ),
    )
