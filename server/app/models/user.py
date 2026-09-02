from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.expense import Expense, ExpenseSplit
    from app.models.household import HouseholdMember


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
    )
    hashed_password: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    full_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    avatar_url: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    # Relationships
    household_memberships: Mapped[list["HouseholdMember"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    expenses_paid: Mapped[list["Expense"]] = relationship(
        back_populates="paid_by",
    )
    expense_splits: Mapped[list["ExpenseSplit"]] = relationship(
        back_populates="user",
    )
