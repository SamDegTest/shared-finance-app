import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.models.expense import SplitType
from app.schemas.expense import ExpenseResponse


class SmartInputParseRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str = Field(
        min_length=1,
        max_length=1000,
        description="Testo in linguaggio naturale (singola o multi-spesa)",
    )
    household_id: uuid.UUID
    default_payer_id: uuid.UUID | None = None


class SmartInputExtractedExpense(BaseModel):
    model_config = ConfigDict(frozen=True)

    title: str | None = None
    amount_cents: int | None = Field(default=None, gt=0)
    currency: str = "EUR"
    expense_date: date = Field(default_factory=date.today)
    category_name: str | None = None
    category_id: uuid.UUID | None = None
    split_type: SplitType = SplitType.EQUAL
    paid_by_id: uuid.UUID | None = None
    confidence_score: float = 1.0
    is_valid: bool = True
    missing_fields: list[str] = Field(default_factory=list)
    clarification_prompt: str | None = None


class SmartInputBatchParseResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    expenses: list[SmartInputExtractedExpense]
    total_amount_cents: int
    count: int
    is_valid: bool
    missing_fields: list[str] = Field(default_factory=list)
    clarification_prompt: str | None = None


class SmartInputConfirmRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    title: str = Field(min_length=1, max_length=150)
    amount_cents: int = Field(gt=0, description="Importo totale in centesimi interi")
    paid_by_id: uuid.UUID
    category_id: uuid.UUID | None = None
    expense_date: date = Field(default_factory=date.today)
    split_type: SplitType = SplitType.EQUAL
    description: str | None = None


class SmartInputBatchConfirmRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    expenses: list[SmartInputConfirmRequest] = Field(
        min_length=1,
        description="Lista di spese da registrare atomicamente in batch",
    )


class SmartInputBatchConfirmResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    expenses: list[ExpenseResponse]
    total_amount_cents: int
    count: int
