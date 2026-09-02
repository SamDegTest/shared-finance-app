import uuid
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SQLEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.category import Category
    from app.models.expense import Expense
    from app.models.user import User


class HouseholdRole(StrEnum):
    ADMIN = "admin"
    MEMBER = "member"


class Household(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "households"

    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        default="EUR",
        nullable=False,
    )
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # Relationships
    creator: Mapped["User"] = relationship()
    members: Mapped[list["HouseholdMember"]] = relationship(
        back_populates="household",
        cascade="all, delete-orphan",
    )
    categories: Mapped[list["Category"]] = relationship(
        back_populates="household",
        cascade="all, delete-orphan",
    )
    expenses: Mapped[list["Expense"]] = relationship(
        back_populates="household",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint(
            "length(currency) = 3",
            name="ck_household_currency_iso_len",
        ),
    )


class HouseholdMember(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "household_members"

    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[HouseholdRole] = mapped_column(
        SQLEnum(HouseholdRole, name="household_role_enum", native_enum=False),
        default=HouseholdRole.MEMBER,
        nullable=False,
    )

    # Relationships
    household: Mapped["Household"] = relationship(back_populates="members")
    user: Mapped["User"] = relationship(back_populates="household_memberships")

    __table_args__ = (
        UniqueConstraint("household_id", "user_id", name="uq_household_member"),
    )
