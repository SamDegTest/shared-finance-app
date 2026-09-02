import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_async_db
from app.models import Expense, ExpenseSplit, Household, HouseholdMember
from app.schemas.expense import ExpenseCreateRequest, ExpenseResponse
from app.schemas.household import HouseholdBalanceResponse
from app.services.balance_service import calculate_household_balance
from app.services.split_calculator import calculate_splits

router = APIRouter()

AsyncDb = Annotated[AsyncSession, Depends(get_async_db)]


@router.get(
    "/{household_id}/balance",
    response_model=HouseholdBalanceResponse,
    summary="Calcolo Bilancio e Debiti Reciproci",
    description=(
        "Restituisce i saldi netti di ciascun membro e la risoluzione minima "
        "dei debiti reciproci per la coppia."
    ),
)
async def get_household_balance(
    household_id: uuid.UUID,
    db: AsyncDb,
) -> HouseholdBalanceResponse:
    try:
        return await calculate_household_balance(db, household_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e


@router.post(
    "/{household_id}/expenses",
    response_model=ExpenseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrazione Spesa con Ripartizione Automatica",
    description=(
        "Crea una nuova spesa nel nucleo, calcola automaticamente gli split "
        "secondo la tipologia scelta e li persiste in transazione."
    ),
)
async def create_expense(
    household_id: uuid.UUID,
    payload: ExpenseCreateRequest,
    db: AsyncDb,
) -> ExpenseResponse:
    # 1. Verifica esistenza household
    hh_res = await db.execute(select(Household).where(Household.id == household_id))
    household = hh_res.scalar_one_or_none()
    if not household:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Household con id '{household_id}' non trovato.",
        )

    # 2. Recupera i membri del nucleo per determinare i partecipanti di default
    members_res = await db.execute(
        select(HouseholdMember.user_id).where(
            HouseholdMember.household_id == household_id
        )
    )
    household_member_ids = [row[0] for row in members_res.all()]
    if not household_member_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Il nucleo non ha membri registrati a cui imputare la spesa.",
        )

    # Se non specificati split custom, partecipano tutti i membri
    if payload.splits:
        participant_ids = [s.user_id for s in payload.splits]
    else:
        participant_ids = household_member_ids

    # 3. Calcolo quote tramite Split Engine
    try:
        calculated_splits = calculate_splits(
            total_amount_cents=payload.amount_cents,
            split_type=payload.split_type,
            participant_ids=participant_ids,
            custom_splits=payload.splits,
            payer_id=payload.paid_by_id,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        ) from e

    # 4. Creazione spesa e quote
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
        receipt_url=payload.receipt_url,
        ocr_raw_data=payload.ocr_raw_data,
    )
    db.add(expense)
    await db.flush()

    for s in calculated_splits:
        split_record = ExpenseSplit(
            expense_id=expense.id,
            user_id=s.user_id,
            amount_cents=s.amount_cents,
            percentage=s.percentage,
            shares=s.shares,
        )
        db.add(split_record)

    await db.commit()

    # Ricarica con la relazione splits
    stmt = (
        select(Expense)
        .options(selectinload(Expense.splits))
        .where(Expense.id == expense.id)
    )
    res = await db.execute(stmt)
    created_expense = res.scalar_one()

    return ExpenseResponse.model_validate(created_expense)


@router.get(
    "/{household_id}/expenses",
    response_model=list[ExpenseResponse],
    summary="Lista Spese del Nucleo",
    description=(
        "Restituisce la lista cronologica paginata delle spese registrate "
        "per un nucleo familiare."
    ),
)
async def list_expenses(
    household_id: uuid.UUID,
    db: AsyncDb,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[ExpenseResponse]:
    stmt = (
        select(Expense)
        .options(selectinload(Expense.splits))
        .where(Expense.household_id == household_id)
        .order_by(desc(Expense.expense_date), desc(Expense.created_at))
        .offset(skip)
        .limit(limit)
    )
    res = await db.execute(stmt)
    expenses = res.scalars().all()
    return [ExpenseResponse.model_validate(e) for e in expenses]
