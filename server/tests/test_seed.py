from collections.abc import Generator

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.seed import seed_database
from app.models import (
    Base,
    Category,
    Expense,
    ExpenseSplit,
    Household,
    HouseholdMember,
    User,
)


@pytest.fixture(name="db_session")
def fixture_db_session() -> Generator[Session, None, None]:
    engine = create_engine("sqlite:///:memory:", echo=False)
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


def test_seed_database_success(db_session: Session) -> None:
    # 1. First execution
    counts = seed_database(db_session, reset=False)

    assert counts["users"] == 4
    assert counts["households"] == 2
    assert counts["categories"] == 14
    assert counts["expenses"] == 16
    assert counts["splits"] == 32

    # Check DB counts
    users = db_session.execute(select(User)).scalars().all()
    assert len(users) == 4

    households = db_session.execute(select(Household)).scalars().all()
    assert len(households) == 2

    members = db_session.execute(select(HouseholdMember)).scalars().all()
    assert len(members) == 4

    categories = db_session.execute(select(Category)).scalars().all()
    assert len(categories) == 14

    expenses = db_session.execute(select(Expense)).scalars().all()
    assert len(expenses) == 16


def test_seed_database_financial_balance_invariant(db_session: Session) -> None:
    seed_database(db_session, reset=False)

    expenses = db_session.execute(select(Expense)).scalars().all()
    assert len(expenses) > 0

    for expense in expenses:
        splits = (
            db_session.execute(
                select(ExpenseSplit).where(ExpenseSplit.expense_id == expense.id)
            )
            .scalars()
            .all()
        )
        assert len(splits) >= 2, f"Spesa {expense.id} ha meno di 2 quote"

        total_splits_cents = sum(s.amount_cents for s in splits)
        assert total_splits_cents == expense.amount_cents, (
            f"Sbilancio su '{expense.title}': "
            f"{total_splits_cents} != {expense.amount_cents}"
        )


def test_seed_database_idempotency_and_reset(db_session: Session) -> None:
    # First seed
    seed_database(db_session, reset=False)

    # Second seed without reset -> should detect existing data and skip
    counts_skip = seed_database(db_session, reset=False)
    assert counts_skip["users"] == 0
    assert counts_skip["expenses"] == 0

    # Seed with reset -> should clean and re-seed
    counts_reset = seed_database(db_session, reset=True)
    assert counts_reset["users"] == 4
    assert counts_reset["expenses"] == 16
