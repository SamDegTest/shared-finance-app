import uuid

from pydantic import BaseModel, ConfigDict


class MemberBalanceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    user_id: uuid.UUID
    full_name: str
    total_paid_cents: int
    total_owed_cents: int
    net_balance_cents: int


class DebtTransferResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    from_user_id: uuid.UUID
    from_user_name: str
    to_user_id: uuid.UUID
    to_user_name: str
    amount_cents: int


class HouseholdBalanceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    household_id: uuid.UUID
    currency: str
    total_expenses_cents: int
    members: list[MemberBalanceResponse]
    settlements: list[DebtTransferResponse]
