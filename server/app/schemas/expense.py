import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.expense import SplitType


class SplitItemInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: uuid.UUID
    amount_cents: int | None = Field(default=None, ge=0)
    percentage: Decimal | None = Field(default=None, ge=Decimal("0"), le=Decimal("100"))
    shares: int | None = Field(default=None, ge=1)


class ExpenseCreateRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    title: str = Field(min_length=1, max_length=150)
    amount_cents: int = Field(gt=0, description="Importo totale in centesimi interi")
    paid_by_id: uuid.UUID
    category_id: uuid.UUID | None = None
    expense_date: date = Field(default_factory=date.today)
    split_type: SplitType = SplitType.EQUAL
    splits: list[SplitItemInput] | None = None
    description: str | None = None
    receipt_url: str | None = None
    ocr_raw_data: dict[str, Any] | None = None


class ExpenseSplitResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: uuid.UUID
    user_id: uuid.UUID
    amount_cents: int
    percentage: Decimal | None = None
    shares: int | None = None


class ExpenseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: uuid.UUID
    household_id: uuid.UUID
    paid_by_id: uuid.UUID
    category_id: uuid.UUID | None
    amount_cents: int
    currency: str
    title: str
    description: str | None
    expense_date: date
    split_type: SplitType
    receipt_url: str | None
    ocr_raw_data: dict[str, Any] | None
    splits: list[ExpenseSplitResponse]
    created_at: datetime
