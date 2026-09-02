from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.models import (
    Base,
    Category,
    Expense,
    ExpenseSplit,
    Household,
    HouseholdMember,
    HouseholdRole,
    SplitType,
    User,
)


@pytest.fixture(name="db_session")
def fixture_db_session() -> Session:
    # Test engine with SQLite in-memory and foreign keys enabled
    engine = create_engine("sqlite:///:memory:", echo=False)

    # Enable SQLite Foreign Key enforcement
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


def test_schema_tables_registered() -> None:
    expected_tables = {
        "users",
        "households",
        "household_members",
        "categories",
        "expenses",
        "expense_splits",
    }
    assert expected_tables.issubset(set(Base.metadata.tables.keys()))


def test_create_full_financial_flow(db_session: Session) -> None:
    # 1. Create two users
    user_a = User(
        email="partner.a@example.com",
        hashed_password="hashed_secure_pass_1",
        full_name="Partner A",
    )
    user_b = User(
        email="partner.b@example.com",
        hashed_password="hashed_secure_pass_2",
        full_name="Partner B",
    )
    db_session.add_all([user_a, user_b])
    db_session.commit()

    assert user_a.id is not None
    assert user_b.id is not None

    # 2. Create Household
    household = Household(
        name="Casa Nostra",
        currency="EUR",
        created_by_id=user_a.id,
    )
    db_session.add(household)
    db_session.commit()

    # 3. Add members
    member_a = HouseholdMember(
        household_id=household.id,
        user_id=user_a.id,
        role=HouseholdRole.ADMIN,
    )
    member_b = HouseholdMember(
        household_id=household.id,
        user_id=user_b.id,
        role=HouseholdRole.MEMBER,
    )
    db_session.add_all([member_a, member_b])
    db_session.commit()

    # 4. Create Category
    cat_groceries = Category(
        household_id=household.id,
        name="Spesa Alimentari",
        icon="shopping-cart",
        color="#10B981",
        is_system=False,
    )
    db_session.add(cat_groceries)
    db_session.commit()

    # 5. Create Expense: 100.50 EUR (10050 cents)
    expense = Expense(
        household_id=household.id,
        paid_by_id=user_a.id,
        category_id=cat_groceries.id,
        amount_cents=10050,
        currency="EUR",
        title="Spesa Settimanale Esselunga",
        expense_date=date(2026, 9, 2),
        split_type=SplitType.EQUAL,
        ocr_raw_data={"merchant": "Esselunga", "total": 100.50, "items_count": 12},
    )
    db_session.add(expense)
    db_session.commit()

    # 6. Create Expense Splits (50/50: 5025 cents each)
    split_a = ExpenseSplit(
        expense_id=expense.id,
        user_id=user_a.id,
        amount_cents=5025,
        percentage=Decimal("50.00"),
    )
    split_b = ExpenseSplit(
        expense_id=expense.id,
        user_id=user_b.id,
        amount_cents=5025,
        percentage=Decimal("50.00"),
    )
    db_session.add_all([split_a, split_b])
    db_session.commit()

    # Verify query and sum check
    splits = (
        db_session.execute(
            select(ExpenseSplit).where(ExpenseSplit.expense_id == expense.id)
        )
        .scalars()
        .all()
    )
    assert len(splits) == 2
    total_split_cents = sum(s.amount_cents for s in splits)
    assert total_split_cents == expense.amount_cents


def test_unique_household_member_constraint(db_session: Session) -> None:
    user = User(
        email="solo@example.com",
        hashed_password="pass",
        full_name="Solo User",
    )
    db_session.add(user)
    db_session.commit()

    household = Household(
        name="Solo Household",
        currency="EUR",
        created_by_id=user.id,
    )
    db_session.add(household)
    db_session.commit()

    m1 = HouseholdMember(household_id=household.id, user_id=user.id)
    db_session.add(m1)
    db_session.commit()

    # Duplicate membership should raise IntegrityError
    m2 = HouseholdMember(household_id=household.id, user_id=user.id)
    db_session.add(m2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_unique_expense_split_user_constraint(db_session: Session) -> None:
    user = User(email="test@example.com", hashed_password="pw", full_name="User")
    db_session.add(user)
    db_session.commit()

    household = Household(name="Home", currency="EUR", created_by_id=user.id)
    db_session.add(household)
    db_session.commit()

    expense = Expense(
        household_id=household.id,
        paid_by_id=user.id,
        amount_cents=2000,
        currency="EUR",
        title="Cinema",
        expense_date=date(2026, 9, 2),
    )
    db_session.add(expense)
    db_session.commit()

    s1 = ExpenseSplit(expense_id=expense.id, user_id=user.id, amount_cents=1000)
    db_session.add(s1)
    db_session.commit()

    # Duplicate split for same user on same expense
    s2 = ExpenseSplit(expense_id=expense.id, user_id=user.id, amount_cents=1000)
    db_session.add(s2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_check_constraint_expense_amount_positive(db_session: Session) -> None:
    user = User(email="neg@example.com", hashed_password="pw", full_name="User")
    db_session.add(user)
    db_session.commit()

    household = Household(name="Home", currency="EUR", created_by_id=user.id)
    db_session.add(household)
    db_session.commit()

    # Amount <= 0 should fail check constraint
    invalid_expense = Expense(
        household_id=household.id,
        paid_by_id=user.id,
        amount_cents=0,  # invalid
        currency="EUR",
        title="Free stuff",
        expense_date=date(2026, 9, 2),
    )
    db_session.add(invalid_expense)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
