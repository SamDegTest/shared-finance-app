import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_async_db
from app.models import Expense, ExpenseSplit, Household, HouseholdMember
from app.schemas.expense import ExpenseResponse
from app.schemas.smart_input import (
    SmartInputBatchConfirmRequest,
    SmartInputBatchConfirmResponse,
    SmartInputBatchParseResponse,
    SmartInputConfirmRequest,
    SmartInputParseRequest,
)
from app.services.smart_input_service import smart_input_service
from app.services.split_calculator import calculate_splits

router = APIRouter()

AsyncDb = Annotated[AsyncSession, Depends(get_async_db)]


@router.post(
    "/households/{household_id}/smart-input/parse",
    response_model=SmartInputBatchParseResponse,
    summary="Parsing Spese Singole o Multiple da Linguaggio Naturale",
    description=(
        "Estrae una o più spese da una frase naturale "
        "(es. 'Cena 50€ a metà e 30€ benzina ieri')."
    ),
)
async def parse_smart_input(
    household_id: uuid.UUID,
    payload: SmartInputParseRequest,
    db: AsyncDb,
) -> SmartInputBatchParseResponse:
    if payload.household_id != household_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Household ID nel body non corrisponde all'URL.",
        )

    # Verifica esistenza household
    hh_res = await db.execute(select(Household).where(Household.id == household_id))
    if not hh_res.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Household con id '{household_id}' non trovato.",
        )

    result = await smart_input_service.parse_multi_expenses(request=payload, db=db)

    if not result.is_valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": result.clarification_prompt,
                "missing_fields": result.missing_fields,
                "expenses": [e.model_dump(mode="json") for e in result.expenses],
            },
        )

    return result


@router.post(
    "/households/{household_id}/smart-input/confirm",
    response_model=ExpenseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Conferma Singola Spesa Smart Input",
    description="Registra la spesa estratta con garanzie ACID.",
)
async def confirm_smart_input_expense(
    household_id: uuid.UUID,
    payload: SmartInputConfirmRequest,
    db: AsyncDb,
) -> ExpenseResponse:
    # 1. Verifica household
    hh_res = await db.execute(select(Household).where(Household.id == household_id))
    household = hh_res.scalar_one_or_none()
    if not household:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Household con id '{household_id}' non trovato.",
        )

    # 2. Recupero partecipanti household
    members_res = await db.execute(
        select(HouseholdMember.user_id).where(
            HouseholdMember.household_id == household_id
        )
    )
    participant_ids = [row[0] for row in members_res.all()]
    if not participant_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nessun membro presente nel nucleo.",
        )

    # 3. Calcolo quote
    try:
        calculated_splits = calculate_splits(
            total_amount_cents=payload.amount_cents,
            split_type=payload.split_type,
            participant_ids=participant_ids,
            payer_id=payload.paid_by_id,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e

    # 4. Registrazione Transazionale ACID
    expense = Expense(
        household_id=household_id,
        paid_by_id=payload.paid_by_id,
        category_id=payload.category_id,
        amount_cents=payload.amount_cents,
        currency=household.currency,
        title=payload.title,
        description=payload.description,
        expense_date=payload.expense_date,
        split_type=payload.split_type,
    )
    db.add(expense)
    await db.flush()

    for s in calculated_splits:
        db.add(
            ExpenseSplit(
                expense_id=expense.id,
                user_id=s.user_id,
                amount_cents=s.amount_cents,
                percentage=s.percentage,
                shares=s.shares,
            )
        )

    await db.commit()

    # Ricarica con splits per risposta
    stmt = (
        select(Expense)
        .options(selectinload(Expense.splits))
        .where(Expense.id == expense.id)
    )
    res = await db.execute(stmt)
    created_expense = res.scalar_one()

    return ExpenseResponse.model_validate(created_expense)


@router.post(
    "/households/{household_id}/smart-input/confirm-batch",
    response_model=SmartInputBatchConfirmResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Conferma Batch Multi-Spesa in Transazione Atomica ACID",
    description=(
        "Registra tutte le spese estratte in una singola transazione atomica."
    ),
)
async def confirm_smart_input_batch(
    household_id: uuid.UUID,
    payload: SmartInputBatchConfirmRequest,
    db: AsyncDb,
) -> SmartInputBatchConfirmResponse:
    # 1. Verifica household
    hh_res = await db.execute(select(Household).where(Household.id == household_id))
    household = hh_res.scalar_one_or_none()
    if not household:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Household con id '{household_id}' non trovato.",
        )

    # 2. Recupero partecipanti household
    members_res = await db.execute(
        select(HouseholdMember.user_id).where(
            HouseholdMember.household_id == household_id
        )
    )
    participant_ids = [row[0] for row in members_res.all()]
    if not participant_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nessun membro presente nel nucleo.",
        )

    created_expenses: list[Expense] = []

    # 3. Transazione Unica Atomica per tutte le spese
    for exp_item in payload.expenses:
        calculated_splits = calculate_splits(
            total_amount_cents=exp_item.amount_cents,
            split_type=exp_item.split_type,
            participant_ids=participant_ids,
            payer_id=exp_item.paid_by_id,
        )

        expense = Expense(
            household_id=household_id,
            paid_by_id=exp_item.paid_by_id,
            category_id=exp_item.category_id,
            amount_cents=exp_item.amount_cents,
            currency=household.currency,
            title=exp_item.title,
            description=exp_item.description,
            expense_date=exp_item.expense_date,
            split_type=exp_item.split_type,
        )
        db.add(expense)
        await db.flush()

        for s in calculated_splits:
            db.add(
                ExpenseSplit(
                    expense_id=expense.id,
                    user_id=s.user_id,
                    amount_cents=s.amount_cents,
                    percentage=s.percentage,
                    shares=s.shares,
                )
            )

        created_expenses.append(expense)

    await db.commit()

    # Ricarica tutte le spese create con i relativi split
    response_items: list[ExpenseResponse] = []
    for exp in created_expenses:
        stmt = (
            select(Expense)
            .options(selectinload(Expense.splits))
            .where(Expense.id == exp.id)
        )
        res = await db.execute(stmt)
        response_items.append(ExpenseResponse.model_validate(res.scalar_one()))

    total_cents = sum(e.amount_cents for e in response_items)

    return SmartInputBatchConfirmResponse(
        expenses=response_items,
        total_amount_cents=total_cents,
        count=len(response_items),
    )
