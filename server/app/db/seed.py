import argparse
import logging
import sys
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
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

logger = logging.getLogger("shared-finance-app.seed")
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

MOCK_HASHED_PASSWORD = "$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQmG6W565v89G.mockhash"


def clean_database(session: Session) -> None:
    """Elimina i dati esistenti rispettando l'ordine di integrità referenziale."""
    logger.info("Pulizia del database in corso...")
    session.execute(delete(ExpenseSplit))
    session.execute(delete(Expense))
    session.execute(delete(Category))
    session.execute(delete(HouseholdMember))
    session.execute(delete(Household))
    session.execute(delete(User))
    session.flush()
    logger.info("Database ripulito con successo.")


def _create_users_and_households(
    session: Session,
) -> tuple[dict[str, User], dict[str, Household]]:
    """Crea utenti e nuclei familiari iniziali."""
    users = {
        "marco": User(
            email="marco.rossi@example.com",
            hashed_password=MOCK_HASHED_PASSWORD,
            full_name="Marco Rossi",
            avatar_url="https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=150",
            is_active=True,
        ),
        "laura": User(
            email="laura.verdi@example.com",
            hashed_password=MOCK_HASHED_PASSWORD,
            full_name="Laura Verdi",
            avatar_url="https://images.unsplash.com/photo-1494790108377-be9c29b29330?w=150",
            is_active=True,
        ),
        "giulia": User(
            email="giulia.bianchi@example.com",
            hashed_password=MOCK_HASHED_PASSWORD,
            full_name="Giulia Bianchi",
            avatar_url="https://images.unsplash.com/photo-1517841905240-472988babdf9?w=150",
            is_active=True,
        ),
        "matteo": User(
            email="matteo.neri@example.com",
            hashed_password=MOCK_HASHED_PASSWORD,
            full_name="Matteo Neri",
            avatar_url="https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=150",
            is_active=True,
        ),
    }
    session.add_all(list(users.values()))
    session.flush()

    households = {
        "rossi": Household(
            name="Casa Rossi-Verdi",
            currency="EUR",
            created_by_id=users["marco"].id,
        ),
        "bianchi": Household(
            name="Casa Bianchi-Neri",
            currency="EUR",
            created_by_id=users["giulia"].id,
        ),
    }
    session.add_all(list(households.values()))
    session.flush()

    members = [
        HouseholdMember(
            household_id=households["rossi"].id,
            user_id=users["marco"].id,
            role=HouseholdRole.ADMIN,
        ),
        HouseholdMember(
            household_id=households["rossi"].id,
            user_id=users["laura"].id,
            role=HouseholdRole.MEMBER,
        ),
        HouseholdMember(
            household_id=households["bianchi"].id,
            user_id=users["giulia"].id,
            role=HouseholdRole.ADMIN,
        ),
        HouseholdMember(
            household_id=households["bianchi"].id,
            user_id=users["matteo"].id,
            role=HouseholdRole.MEMBER,
        ),
    ]
    session.add_all(members)
    session.flush()

    return users, households


def _create_categories(
    session: Session, households: dict[str, Household]
) -> tuple[dict[str, Category], dict[str, Category]]:
    """Crea le categorie standard per ciascun household."""
    categories_def = [
        ("Spesa Alimentari", "shopping-cart", "#10B981"),
        ("Casa & Utenze", "home", "#3B82F6"),
        ("Ristoranti & Bar", "utensils", "#F59E0B"),
        ("Viaggi & Weekend", "plane", "#8B5CF6"),
        ("Trasporti & Auto", "car", "#06B6D4"),
        ("Salute & Farmacia", "heart-pulse", "#EF4444"),
        ("Svago & Cinema", "film", "#EC4899"),
    ]

    cats_rossi: dict[str, Category] = {}
    cats_bianchi: dict[str, Category] = {}

    for name, icon, color in categories_def:
        cr = Category(
            household_id=households["rossi"].id,
            name=name,
            icon=icon,
            color=color,
            is_system=False,
        )
        cb = Category(
            household_id=households["bianchi"].id,
            name=name,
            icon=icon,
            color=color,
            is_system=False,
        )
        session.add_all([cr, cb])
        cats_rossi[name] = cr
        cats_bianchi[name] = cb

    session.flush()
    return cats_rossi, cats_bianchi


def _get_rossi_expense_defs(
    users: dict[str, User], cats: dict[str, Category]
) -> list[dict[str, Any]]:
    """Definizioni delle spese per Casa Rossi."""
    return [
        {
            "days_ago": 1,
            "payer": users["marco"],
            "cat": cats["Spesa Alimentari"],
            "title": "Spesa Esselunga",
            "cents": 8460,
            "split": (4230, 4230),
            "split_type": SplitType.EQUAL,
            "ocr": {
                "merchant": "Esselunga S.p.A.",
                "total": 84.60,
                "confidence": 0.98,
                "items": [
                    {"name": "Pasta De Cecco 500g", "price": 1.49, "qty": 3},
                    {"name": "Passata Mutti", "price": 1.29, "qty": 4},
                    {"name": "Latte Fresco Bio", "price": 1.79, "qty": 2},
                    {"name": "Parmigiano Reggiano 24m", "price": 8.90, "qty": 1},
                    {"name": "Petto di Pollo 600g", "price": 7.45, "qty": 1},
                ],
            },
        },
        {
            "days_ago": 3,
            "payer": users["laura"],
            "cat": cats["Ristoranti & Bar"],
            "title": "Cena Pizzeria da Michele",
            "cents": 4600,
            "split": (2300, 2300),
            "split_type": SplitType.EQUAL,
            "ocr": {
                "merchant": "Pizzeria Da Michele",
                "total": 46.00,
                "confidence": 0.95,
                "items": [
                    {"name": "Pizza Margherita", "price": 8.50, "qty": 2},
                    {"name": "Birra Artigianale 0.5L", "price": 6.00, "qty": 2},
                    {"name": "Dolce del Giorno", "price": 5.50, "qty": 2},
                    {"name": "Coperto", "price": 3.00, "qty": 2},
                ],
            },
        },
        {
            "days_ago": 6,
            "payer": users["marco"],
            "cat": cats["Casa & Utenze"],
            "title": "Bolletta Luce Enel Energia",
            "cents": 11840,
            "split": (5920, 5920),
            "split_type": SplitType.EQUAL,
            "ocr": None,
        },
        {
            "days_ago": 9,
            "payer": users["laura"],
            "cat": cats["Spesa Alimentari"],
            "title": "Spesa Settimanale Conad",
            "cents": 6250,
            "split": (3750, 2500),  # 60% Marco, 40% Laura
            "split_type": SplitType.PERCENTAGE,
            "ocr": {
                "merchant": "Conad Superstore",
                "total": 62.50,
                "confidence": 0.96,
            },
        },
        {
            "days_ago": 12,
            "payer": users["marco"],
            "cat": cats["Trasporti & Auto"],
            "title": "Rifornimento Benzina Eni Station",
            "cents": 7000,
            "split": (3500, 3500),
            "split_type": SplitType.EQUAL,
            "ocr": None,
        },
        {
            "days_ago": 16,
            "payer": users["laura"],
            "cat": cats["Salute & Farmacia"],
            "title": "Farmacia Comunale - Medicinali",
            "cents": 2840,
            "split": (1420, 1420),
            "split_type": SplitType.EQUAL,
            "ocr": {
                "merchant": "Farmacia Comunale",
                "total": 28.40,
                "confidence": 0.99,
            },
        },
        {
            "days_ago": 20,
            "payer": users["marco"],
            "cat": cats["Svago & Cinema"],
            "title": "Biglietti Cinema The Space + Popcorn",
            "cents": 2600,
            "split": (1300, 1300),
            "split_type": SplitType.EQUAL,
            "ocr": None,
        },
        {
            "days_ago": 25,
            "payer": users["laura"],
            "cat": cats["Casa & Utenze"],
            "title": "Abbonamento Internet Fibra Fastweb",
            "cents": 2995,
            "split": (1500, 1495),
            "split_type": SplitType.EXACT,
            "ocr": None,
        },
        {
            "days_ago": 32,
            "payer": users["marco"],
            "cat": cats["Viaggi & Weekend"],
            "title": "Soggiorno B&B Weekend Firenze",
            "cents": 22000,
            "split": (11000, 11000),
            "split_type": SplitType.EQUAL,
            "ocr": None,
        },
        {
            "days_ago": 38,
            "payer": users["laura"],
            "cat": cats["Trasporti & Auto"],
            "title": "Biglietti Treno Trenitalia A/R Firenze",
            "cents": 9200,
            "split": (4600, 4600),
            "split_type": SplitType.EQUAL,
            "ocr": None,
        },
        {
            "days_ago": 45,
            "payer": users["marco"],
            "cat": cats["Spesa Alimentari"],
            "title": "Spesa Bio NaturaSì",
            "cents": 4180,
            "split": (2090, 2090),
            "split_type": SplitType.EQUAL,
            "ocr": None,
        },
        {
            "days_ago": 52,
            "payer": users["laura"],
            "cat": cats["Ristoranti & Bar"],
            "title": "Pranzo Domenicale Osteria del Borgo",
            "cents": 6800,
            "split": (3400, 3400),
            "split_type": SplitType.EQUAL,
            "ocr": None,
        },
    ]


def _get_bianchi_expense_defs(
    users: dict[str, User], cats: dict[str, Category]
) -> list[dict[str, Any]]:
    """Definizioni delle spese per Casa Bianchi."""
    return [
        {
            "days_ago": 2,
            "payer": users["giulia"],
            "cat": cats["Spesa Alimentari"],
            "title": "Spesa IperCoop",
            "cents": 7450,
            "split": (3725, 3725),
            "split_type": SplitType.EQUAL,
            "ocr": {
                "merchant": "Coop Alleanza 3.0",
                "total": 74.50,
                "confidence": 0.97,
            },
        },
        {
            "days_ago": 5,
            "payer": users["matteo"],
            "cat": cats["Ristoranti & Bar"],
            "title": "Cena Sushi All You Can Eat",
            "cents": 5800,
            "split": (2900, 2900),
            "split_type": SplitType.EQUAL,
            "ocr": None,
        },
        {
            "days_ago": 14,
            "payer": users["giulia"],
            "cat": cats["Casa & Utenze"],
            "title": "Bolletta Gas A2A",
            "cents": 8900,
            "split": (4450, 4450),
            "split_type": SplitType.EQUAL,
            "ocr": None,
        },
        {
            "days_ago": 28,
            "payer": users["matteo"],
            "cat": cats["Svago & Cinema"],
            "title": "Abbonamento Coppia Palestra FitActive",
            "cents": 7980,
            "split": (3990, 3990),
            "split_type": SplitType.EQUAL,
            "ocr": None,
        },
    ]


def _insert_expenses(
    session: Session,
    household: Household,
    expenses_raw: list[dict[str, Any]],
    partners: tuple[User, User],
    *,
    reference_date: date,
) -> tuple[int, int]:
    """Inserisce le spese e i relativi split con validazione di quadratura."""
    user_a, user_b = partners
    exp_count = 0
    split_count = 0

    for item in expenses_raw:
        exp = Expense(
            household_id=household.id,
            paid_by_id=item["payer"].id,
            category_id=item["cat"].id,
            amount_cents=item["cents"],
            currency="EUR",
            title=item["title"],
            expense_date=reference_date - timedelta(days=item["days_ago"]),
            split_type=item["split_type"],
            receipt_url="https://storage.example.com/receipts/mock_receipt.jpg"
            if item["ocr"]
            else None,
            ocr_raw_data=item["ocr"],
        )
        session.add(exp)
        session.flush()
        exp_count += 1

        split_a_cents, split_b_cents = item["split"]
        assert split_a_cents + split_b_cents == item["cents"]

        pct_a = Decimal(f"{(split_a_cents / item['cents']) * 100:.2f}")
        pct_b = Decimal(f"{(split_b_cents / item['cents']) * 100:.2f}")

        split_a = ExpenseSplit(
            expense_id=exp.id,
            user_id=user_a.id,
            amount_cents=split_a_cents,
            percentage=pct_a,
        )
        split_b = ExpenseSplit(
            expense_id=exp.id,
            user_id=user_b.id,
            amount_cents=split_b_cents,
            percentage=pct_b,
        )
        session.add_all([split_a, split_b])
        split_count += 2

    return exp_count, split_count


def seed_database(session: Session, reset: bool = False) -> dict[str, int]:
    """Popola il database con utenti, household, categorie e spese realistiche."""
    if reset:
        clean_database(session)
    else:
        existing = session.execute(select(User).limit(1)).scalar_one_or_none()
        if existing:
            logger.info(
                "Dati già presenti nel database. Usa il flag --reset per sovrascrivere."
            )
            return {"users": 0, "households": 0, "expenses": 0, "splits": 0}

    logger.info("Inizio seeding dati di mock per shared-finance-app...")
    users, households = _create_users_and_households(session)
    cats_rossi, cats_bianchi = _create_categories(session, households)

    today = date.today()
    rossi_defs = _get_rossi_expense_defs(users, cats_rossi)
    exp_r, split_r = _insert_expenses(
        session,
        households["rossi"],
        rossi_defs,
        (users["marco"], users["laura"]),
        reference_date=today,
    )

    bianchi_defs = _get_bianchi_expense_defs(users, cats_bianchi)
    exp_b, split_b = _insert_expenses(
        session,
        households["bianchi"],
        bianchi_defs,
        (users["giulia"], users["matteo"]),
        reference_date=today,
    )

    session.commit()
    total_exp = exp_r + exp_b
    total_split = split_r + split_b

    logger.info(
        "Seeding completato: %d utenti, %d household, %d spese, %d split.",
        len(users),
        len(households),
        total_exp,
        total_split,
    )

    return {
        "users": len(users),
        "households": len(households),
        "categories": len(cats_rossi) + len(cats_bianchi),
        "expenses": total_exp,
        "splits": total_split,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Popola il database di shared-finance-app con dati di mock."
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Elimina tutti i dati esistenti prima del seeding.",
    )
    args = parser.parse_args()

    engine = create_engine(settings.sync_database_uri, echo=False)
    Base.metadata.create_all(engine)

    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as session:
        try:
            seed_database(session, reset=args.reset)
        except Exception as e:
            session.rollback()
            logger.error("Errore durante il seeding: %s", e)
            sys.exit(1)


if __name__ == "__main__":
    main()
