import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.smart_input import (
    confirm_smart_input_batch,
    confirm_smart_input_expense,
)
from app.models.expense import SplitType
from app.models.household import Household, HouseholdMember, HouseholdRole
from app.models.user import User
from app.schemas.smart_input import (
    SmartInputBatchConfirmRequest,
    SmartInputConfirmRequest,
    SmartInputParseRequest,
)
from app.services.smart_input_service import smart_input_service


@pytest.mark.asyncio
async def test_smart_input_equal_split_mapping() -> None:
    """AC 1: Il sistema mappa frasi 'diviso a metà' nel flag split_type = 'EQUAL'."""
    phrases = [
        (
            "Cena pizzeria 100€ diviso a metà",
            10000,
            "Cena pizzeria",
            "Ristoranti & Bar",
        ),
        (
            "Spesa supermercato 45,50 euro a metà",
            4550,
            "Spesa supermercato",
            "Spesa Alimentari",
        ),
        (
            "Pranzo sushi 60 eur 50/50",
            6000,
            "Pranzo sushi",
            "Ristoranti & Bar",
        ),
        (
            "Aperitivo 25 euro diviso in due",
            2500,
            "Aperitivo",
            "Ristoranti & Bar",
        ),
        (
            "Bolletta luce 80€ diviso 2",
            8000,
            "Bolletta luce",
            "Casa & Utenze",
        ),
    ]

    household_id = uuid.uuid4()
    for text, expected_amount, expected_title, expected_category in phrases:
        req = SmartInputParseRequest(text=text, household_id=household_id)
        result = await smart_input_service.parse_natural_language_expense(req)

        assert result.is_valid is True
        assert result.split_type == SplitType.EQUAL
        assert result.amount_cents == expected_amount
        assert result.title == expected_title
        assert result.category_name == expected_category
        assert result.expense_date == date.today()


@pytest.mark.asyncio
async def test_smart_input_multi_expense_batch_parsing() -> None:
    """Verifica estrazione di più spese distinte da un singolo prompt naturale."""
    household_id = uuid.uuid4()
    text = "Cena pizzeria 50€ diviso a metà e 30€ benzina ieri"
    req = SmartInputParseRequest(text=text, household_id=household_id)

    result = await smart_input_service.parse_multi_expenses(req)

    assert result.is_valid is True
    assert result.count == 2
    assert result.total_amount_cents == 8000  # 50,00€ + 30,00€

    # Spesa 1: Cena
    exp1 = result.expenses[0]
    assert exp1.title == "Cena pizzeria"
    assert exp1.amount_cents == 5000
    assert exp1.category_name == "Ristoranti & Bar"
    assert exp1.split_type == SplitType.EQUAL
    assert exp1.expense_date == date.today()

    # Spesa 2: Benzina
    exp2 = result.expenses[1]
    assert exp2.title == "Benzina"
    assert exp2.amount_cents == 3000
    assert exp2.category_name == "Trasporti"
    assert exp2.expense_date == date.today() - timedelta(days=1)


@pytest.mark.asyncio
async def test_smart_input_missing_amount_returns_managed_error() -> None:
    """AC 2: L'endpoint restituisce un errore gestito se manca l'importo."""
    household_id = uuid.uuid4()
    req = SmartInputParseRequest(
        text="Pizza con amici a metà", household_id=household_id
    )
    result = await smart_input_service.parse_natural_language_expense(req)

    assert result.is_valid is False
    assert "amount_cents" in result.missing_fields
    assert result.clarification_prompt is not None
    assert "importo" in result.clarification_prompt.lower()


@pytest.mark.asyncio
async def test_smart_input_missing_title_returns_managed_error() -> None:
    """AC 2: L'endpoint restituisce un errore gestito se manca la descrizione."""
    household_id = uuid.uuid4()
    req = SmartInputParseRequest(text="50€ diviso a metà", household_id=household_id)
    result = await smart_input_service.parse_natural_language_expense(req)

    assert result.is_valid is False
    assert "title" in result.missing_fields
    assert result.clarification_prompt is not None
    assert "descrizione" in result.clarification_prompt.lower()


@pytest.mark.asyncio
async def test_smart_input_relative_dates() -> None:
    household_id = uuid.uuid4()
    today = date.today()

    # Ieri
    req_ieri = SmartInputParseRequest(
        text="Farmacia 20 euro ieri", household_id=household_id
    )
    res_ieri = await smart_input_service.parse_natural_language_expense(req_ieri)
    assert res_ieri.is_valid is True
    assert res_ieri.expense_date == today - timedelta(days=1)
    assert res_ieri.category_name == "Salute & Farmacia"

    # L'altro ieri
    req_altro = SmartInputParseRequest(
        text="Benzina 50€ l'altro ieri", household_id=household_id
    )
    res_altro = await smart_input_service.parse_natural_language_expense(req_altro)
    assert res_altro.is_valid is True
    assert res_altro.expense_date == today - timedelta(days=2)
    assert res_altro.category_name == "Trasporti"


@pytest.mark.asyncio
async def test_smart_input_acid_confirmation_endpoint(
    async_db: AsyncSession,
) -> None:
    """AC 3: Registrazione transazionale con garanzie ACID nel ledger relazionale."""
    user_a = User(
        email=f"user_a_{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="hashed_pwd_test",
        full_name="Marco Rossi",
    )
    user_b = User(
        email=f"user_b_{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="hashed_pwd_test",
        full_name="Laura Bianchi",
    )
    async_db.add_all([user_a, user_b])
    await async_db.flush()

    household = Household(
        name="Casa Test ACID",
        currency="EUR",
        created_by_id=user_a.id,
    )
    async_db.add(household)
    await async_db.flush()

    m1 = HouseholdMember(
        household_id=household.id,
        user_id=user_a.id,
        role=HouseholdRole.ADMIN,
    )
    m2 = HouseholdMember(
        household_id=household.id,
        user_id=user_b.id,
        role=HouseholdRole.MEMBER,
    )
    async_db.add_all([m1, m2])
    await async_db.commit()

    confirm_req = SmartInputConfirmRequest(
        title="Cena Trattoria",
        amount_cents=6000,
        paid_by_id=user_a.id,
        split_type=SplitType.EQUAL,
        expense_date=date.today(),
        description="Inserita tramite Smart Input",
    )

    created_expense = await confirm_smart_input_expense(
        household_id=household.id,
        payload=confirm_req,
        db=async_db,
    )

    assert created_expense.id is not None
    assert created_expense.title == "Cena Trattoria"
    assert created_expense.amount_cents == 6000
    assert len(created_expense.splits) == 2

    split_amounts = {s.user_id: s.amount_cents for s in created_expense.splits}
    assert split_amounts[user_a.id] == 3000
    assert split_amounts[user_b.id] == 3000
    assert sum(split_amounts.values()) == 6000


@pytest.mark.asyncio
async def test_smart_input_batch_acid_confirmation(
    async_db: AsyncSession,
) -> None:
    """AC 3: Conferma batch di più spese in una singola transazione atomica ACID."""
    user_a = User(
        email=f"user_batch_a_{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="hashed_pwd_test",
        full_name="Paolo Verdi",
    )
    user_b = User(
        email=f"user_batch_b_{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="hashed_pwd_test",
        full_name="Giulia Neri",
    )
    async_db.add_all([user_a, user_b])
    await async_db.flush()

    household = Household(
        name="Casa Batch Test",
        currency="EUR",
        created_by_id=user_a.id,
    )
    async_db.add(household)
    await async_db.flush()

    m1 = HouseholdMember(
        household_id=household.id,
        user_id=user_a.id,
        role=HouseholdRole.ADMIN,
    )
    m2 = HouseholdMember(
        household_id=household.id,
        user_id=user_b.id,
        role=HouseholdRole.MEMBER,
    )
    async_db.add_all([m1, m2])
    await async_db.commit()

    batch_req = SmartInputBatchConfirmRequest(
        expenses=[
            SmartInputConfirmRequest(
                title="Cena Pizzeria",
                amount_cents=5000,
                paid_by_id=user_a.id,
                split_type=SplitType.EQUAL,
            ),
            SmartInputConfirmRequest(
                title="Rifornimento Benzina",
                amount_cents=3000,
                paid_by_id=user_b.id,
                split_type=SplitType.EQUAL,
            ),
        ]
    )

    batch_res = await confirm_smart_input_batch(
        household_id=household.id,
        payload=batch_req,
        db=async_db,
    )

    assert batch_res.count == 2
    assert batch_res.total_amount_cents == 8000
    assert len(batch_res.expenses) == 2

    # Verifica split per la prima spesa (50€ -> 25€ a testa)
    exp1_splits = {s.user_id: s.amount_cents for s in batch_res.expenses[0].splits}
    assert exp1_splits[user_a.id] == 2500
    assert exp1_splits[user_b.id] == 2500

    # Verifica split per la seconda spesa (30€ -> 15€ a testa)
    exp2_splits = {s.user_id: s.amount_cents for s in batch_res.expenses[1].splits}
    assert exp2_splits[user_a.id] == 1500
    assert exp2_splits[user_b.id] == 1500
