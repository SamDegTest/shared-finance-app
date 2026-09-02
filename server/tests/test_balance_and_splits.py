import time
import uuid
from collections.abc import AsyncGenerator, Generator
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import get_async_db
from app.db.seed import seed_database
from app.main import app
from app.models import (
    Base,
    Household,
    HouseholdMember,
    HouseholdRole,
    SplitType,
    User,
)
from app.schemas.expense import SplitItemInput
from app.services.balance_service import _compute_settlements
from app.services.split_calculator import calculate_splits


@pytest.fixture(name="db_session")
def fixture_db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys = ON;")

    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest_asyncio.fixture(name="async_session")
async def fixture_async_session() -> AsyncGenerator[AsyncSession, None]:
    test_async_engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async with test_async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session_factory = async_sessionmaker(
        bind=test_async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with async_session_factory() as session:
        yield session

    async with test_async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await test_async_engine.dispose()


# ============================================================================
# 1. UNIT TESTS - SPLIT CALCULATOR ENGINE
# ============================================================================


def test_split_calculator_equal_even() -> None:
    u1, u2 = uuid.uuid4(), uuid.uuid4()
    splits = calculate_splits(
        total_amount_cents=10000,  # 100.00 EUR
        split_type=SplitType.EQUAL,
        participant_ids=[u1, u2],
    )
    assert len(splits) == 2
    assert splits[0].amount_cents == 5000
    assert splits[1].amount_cents == 5000
    assert sum(s.amount_cents for s in splits) == 10000


def test_split_calculator_equal_odd_cents_remainder() -> None:
    u1, u2 = uuid.uuid4(), uuid.uuid4()
    # 10.01 EUR (1001 cents) between 2 people -> 501 and 500 cents
    splits = calculate_splits(
        total_amount_cents=1001,
        split_type=SplitType.EQUAL,
        participant_ids=[u1, u2],
        payer_id=u1,
    )
    assert len(splits) == 2
    assert splits[0].amount_cents == 501
    assert splits[1].amount_cents == 500
    assert sum(s.amount_cents for s in splits) == 1001


def test_split_calculator_equal_three_participants_remainder() -> None:
    u1, u2, u3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    # 10.00 EUR (1000 cents) between 3 people -> 334, 333, 333 cents
    splits = calculate_splits(
        total_amount_cents=1000,
        split_type=SplitType.EQUAL,
        participant_ids=[u1, u2, u3],
    )
    assert len(splits) == 3
    assert [s.amount_cents for s in splits] == [334, 333, 333]
    assert sum(s.amount_cents for s in splits) == 1000


def test_split_calculator_percentage() -> None:
    u1, u2 = uuid.uuid4(), uuid.uuid4()
    custom = [
        SplitItemInput(user_id=u1, percentage=Decimal("60.00")),
        SplitItemInput(user_id=u2, percentage=Decimal("40.00")),
    ]
    splits = calculate_splits(
        total_amount_cents=15000,  # 150.00 EUR
        split_type=SplitType.PERCENTAGE,
        participant_ids=[u1, u2],
        custom_splits=custom,
    )
    assert len(splits) == 2
    assert splits[0].amount_cents == 9000
    assert splits[1].amount_cents == 6000
    assert sum(s.amount_cents for s in splits) == 15000


def test_split_calculator_percentage_invalid_sum() -> None:
    u1, u2 = uuid.uuid4(), uuid.uuid4()
    custom = [
        SplitItemInput(user_id=u1, percentage=Decimal("50.00")),
        SplitItemInput(user_id=u2, percentage=Decimal("40.00")),
    ]
    with pytest.raises(ValueError, match="100%"):
        calculate_splits(
            total_amount_cents=10000,
            split_type=SplitType.PERCENTAGE,
            participant_ids=[u1, u2],
            custom_splits=custom,
        )


def test_split_calculator_exact() -> None:
    u1, u2 = uuid.uuid4(), uuid.uuid4()
    custom = [
        SplitItemInput(user_id=u1, amount_cents=7500),
        SplitItemInput(user_id=u2, amount_cents=2500),
    ]
    splits = calculate_splits(
        total_amount_cents=10000,
        split_type=SplitType.EXACT,
        participant_ids=[u1, u2],
        custom_splits=custom,
    )
    assert len(splits) == 2
    assert splits[0].amount_cents == 7500
    assert splits[1].amount_cents == 2500
    assert sum(s.amount_cents for s in splits) == 10000


def test_split_calculator_exact_mismatch() -> None:
    u1, u2 = uuid.uuid4(), uuid.uuid4()
    custom = [
        SplitItemInput(user_id=u1, amount_cents=7000),
        SplitItemInput(user_id=u2, amount_cents=2000),
    ]
    with pytest.raises(ValueError, match="non coincide"):
        calculate_splits(
            total_amount_cents=10000,
            split_type=SplitType.EXACT,
            participant_ids=[u1, u2],
            custom_splits=custom,
        )


# ============================================================================
# 2. CORE BUSINESS RULE - 50/50 RECIPROCAL DEBT
# ============================================================================


def test_acceptance_criteria_100_euro_50_50_debt() -> None:
    """AC: Se A spende 100€ split 50/50, il debito di B verso A aumenta di 50€."""
    user_a_id = uuid.uuid4()
    user_b_id = uuid.uuid4()

    members_map = {user_a_id: "Partner A", user_b_id: "Partner B"}

    # Spesa da 100.00 EUR (10000 centesimi) pagata da A
    # Quota A = 5000 centesimi, Quota B = 5000 centesimi
    net_balances = {
        user_a_id: 10000 - 5000,  # +5000 centesimi (creditore)
        user_b_id: 0 - 5000,  # -5000 centesimi (debitore)
    }

    settlements = _compute_settlements(members_map, net_balances)

    assert len(settlements) == 1
    transfer = settlements[0]
    assert transfer.from_user_id == user_b_id
    assert transfer.from_user_name == "Partner B"
    assert transfer.to_user_id == user_a_id
    assert transfer.to_user_name == "Partner A"
    assert transfer.amount_cents == 5000  # 50.00 EUR


# ============================================================================
# 3. ENDPOINT INTEGRATION & PERFORMANCE BENCHMARK (< 80ms)
# ============================================================================


@pytest.mark.asyncio
async def test_api_balance_endpoint_and_performance(
    async_session: AsyncSession,
) -> None:
    # 1. Popola il DB usando la sessione sincrona interna per il seeder
    await async_session.run_sync(seed_database)

    # 2. Recupera l'household generato
    res = await async_session.execute(select(Household))
    household = res.scalars().first()
    assert household is not None
    hh_id = household.id

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield async_session

    app.dependency_overrides[get_async_db] = override_get_db

    with TestClient(app) as client:
        start_time = time.perf_counter()
        response = client.get(f"/api/v1/households/{hh_id}/balance")
        elapsed_ms = (time.perf_counter() - start_time) * 1000

        assert response.status_code == 200
        data = response.json()

        assert data["household_id"] == str(hh_id)
        assert data["total_expenses_cents"] > 0
        assert len(data["members"]) == 2
        assert len(data["settlements"]) >= 1

        # Verifica benchmark di performance: < 80ms
        assert elapsed_ms < 80.0, f"Latenza ({elapsed_ms:.2f}ms) superiore a 80ms!"

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_create_expense_with_auto_split(
    async_session: AsyncSession,
) -> None:
    u1 = User(email="user1@example.com", hashed_password="pw", full_name="Marco")
    u2 = User(email="user2@example.com", hashed_password="pw", full_name="Laura")
    async_session.add_all([u1, u2])
    await async_session.flush()

    hh = Household(name="Casa", currency="EUR", created_by_id=u1.id)
    async_session.add(hh)
    await async_session.flush()

    m1 = HouseholdMember(household_id=hh.id, user_id=u1.id, role=HouseholdRole.ADMIN)
    m2 = HouseholdMember(household_id=hh.id, user_id=u2.id, role=HouseholdRole.MEMBER)
    async_session.add_all([m1, m2])
    await async_session.commit()

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield async_session

    app.dependency_overrides[get_async_db] = override_get_db

    with TestClient(app) as client:
        payload = {
            "title": "Spesa Supermercato 100 Euro",
            "amount_cents": 10000,
            "paid_by_id": str(u1.id),
            "expense_date": str(date.today()),
            "split_type": "EQUAL",
        }
        res = client.post(f"/api/v1/households/{hh.id}/expenses", json=payload)
        assert res.status_code == 201
        exp_data = res.json()
        assert exp_data["title"] == "Spesa Supermercato 100 Euro"
        assert exp_data["amount_cents"] == 10000
        assert len(exp_data["splits"]) == 2
        assert exp_data["splits"][0]["amount_cents"] == 5000
        assert exp_data["splits"][1]["amount_cents"] == 5000

        # Verifica bilancio subito dopo
        bal_res = client.get(f"/api/v1/households/{hh.id}/balance")
        assert bal_res.status_code == 200
        bal_data = bal_res.json()
        assert len(bal_data["settlements"]) == 1
        assert bal_data["settlements"][0]["amount_cents"] == 5000
        assert bal_data["settlements"][0]["from_user_id"] == str(u2.id)
        assert bal_data["settlements"][0]["to_user_id"] == str(u1.id)

    app.dependency_overrides.clear()
