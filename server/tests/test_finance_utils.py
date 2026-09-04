import ast
import random
import uuid
from decimal import Decimal
from pathlib import Path

import pytest

from app.utils.finance import (
    calculate_precise_splits,
    calculate_precise_splits_cents,
    cents_to_decimal,
    decimal_to_cents,
)


def test_cents_and_decimal_conversions() -> None:
    """Verifica la conversione bidirezionale tra centesimi interi e Decimal."""
    assert cents_to_decimal(1050) == Decimal("10.50")
    assert cents_to_decimal(0) == Decimal("0.00")
    assert cents_to_decimal(1) == Decimal("0.01")
    assert cents_to_decimal(99999) == Decimal("999.99")

    assert decimal_to_cents(Decimal("10.50")) == 1050
    assert decimal_to_cents(Decimal("0.01")) == 1
    assert decimal_to_cents(Decimal("0.00")) == 0
    assert decimal_to_cents("45.99") == 4599
    assert decimal_to_cents(25) == 2500


def test_equal_split_three_users_with_payer_remainder() -> None:
    """AC 2 & AC 3: 10.00 € divisi tra 3 utenti con resto al pagatore."""
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()
    user_c = uuid.uuid4()
    participants = [user_a, user_b, user_c]

    # Scenario 1: user_a è il pagatore
    splits_a = calculate_precise_splits(
        total_amount=Decimal("10.00"),
        participant_ids=participants,
        payer_id=user_a,
    )
    assert splits_a[user_a] == Decimal("3.34")
    assert splits_a[user_b] == Decimal("3.33")
    assert splits_a[user_c] == Decimal("3.33")
    assert sum(splits_a.values()) == Decimal("10.00")

    # Scenario 2: user_b è il pagatore
    splits_b = calculate_precise_splits(
        total_amount=Decimal("10.00"),
        participant_ids=participants,
        payer_id=user_b,
    )
    assert splits_b[user_b] == Decimal("3.34")
    assert splits_b[user_a] == Decimal("3.33")
    assert splits_b[user_c] == Decimal("3.33")
    assert sum(splits_b.values()) == Decimal("10.00")


def test_equal_split_seven_users_multiple_remainder_cents() -> None:
    """AC 3: 100.00 € divisi tra 7 utenti (10000 % 7 = 4 centesimi resto)."""
    users = [uuid.uuid4() for _ in range(7)]
    payer = users[3]

    splits = calculate_precise_splits(
        total_amount=Decimal("100.00"),
        participant_ids=users,
        payer_id=payer,
    )

    # Il pagatore e i successivi 3 ricevono 14.29 €, gli altri 3 ricevono 14.28 €
    assert splits[payer] == Decimal("14.29")
    assert sum(splits.values()) == Decimal("100.00")

    # Conteggio quote: 10000 % 7 = 4 centesimi di resto
    counts = list(splits.values())
    assert counts.count(Decimal("14.29")) == 4
    assert counts.count(Decimal("14.28")) == 3


def test_micro_amount_one_cent_among_multiple_users() -> None:
    """AC 4: Caso limite 0.01 € diviso tra 3 e tra 5 persone."""
    users = ["user_1", "user_2", "user_3"]
    payer = "user_2"

    splits = calculate_precise_splits(
        total_amount=Decimal("0.01"),
        participant_ids=users,
        payer_id=payer,
    )
    assert splits["user_2"] == Decimal("0.01")
    assert splits["user_1"] == Decimal("0.00")
    assert splits["user_3"] == Decimal("0.00")
    assert sum(splits.values()) == Decimal("0.01")


def test_micro_amount_two_cents_among_three_and_five_users() -> None:
    """AC 4: Caso limite 0.02 € diviso tra 3 e tra 5 persone."""
    users_3 = ["alice", "bob", "charlie"]
    payer_3 = "charlie"

    splits_3 = calculate_precise_splits(
        total_amount=Decimal("0.02"),
        participant_ids=users_3,
        payer_id=payer_3,
    )
    assert splits_3["charlie"] == Decimal("0.01")
    assert sum(splits_3.values()) == Decimal("0.02")

    users_5 = [f"usr_{i}" for i in range(5)]
    splits_5 = calculate_precise_splits(
        total_amount=Decimal("0.02"),
        participant_ids=users_5,
        payer_id=users_5[2],
    )
    assert splits_5[users_5[2]] == Decimal("0.01")
    assert sum(splits_5.values()) == Decimal("0.02")
    assert list(splits_5.values()).count(Decimal("0.01")) == 2
    assert list(splits_5.values()).count(Decimal("0.00")) == 3


def test_payer_not_in_participants_list() -> None:
    """AC 2: Pagatore esterno al gruppo dei partecipanti."""
    participants = ["member_1", "member_2", "member_3"]
    external_payer = "external_boss"

    splits = calculate_precise_splits(
        total_amount=Decimal("10.00"),
        participant_ids=participants,
        payer_id=external_payer,
    )
    assert sum(splits.values()) == Decimal("10.00")
    assert max(splits.values()) - min(splits.values()) == Decimal("0.01")


def test_zero_total_amount() -> None:
    """AC 4: Importo a 0.00 €."""
    users = ["u1", "u2", "u3"]
    splits = calculate_precise_splits(
        total_amount=Decimal("0.00"),
        participant_ids=users,
    )
    assert all(v == Decimal("0.00") for v in splits.values())
    assert sum(splits.values()) == Decimal("0.00")


def test_validation_errors() -> None:
    """Verifica eccezioni su input non validi."""
    with pytest.raises(ValueError, match="non può essere vuota"):
        calculate_precise_splits(
            total_amount=Decimal("10.00"),
            participant_ids=[],
        )

    with pytest.raises(ValueError, match="non può essere negativo"):
        calculate_precise_splits(
            total_amount=Decimal("-5.00"),
            participant_ids=["u1", "u2"],
        )

    with pytest.raises(ValueError, match="non può essere vuota"):
        calculate_precise_splits_cents(
            total_cents=1000,
            participant_ids=[],
        )

    with pytest.raises(ValueError, match="non può essere negativo"):
        calculate_precise_splits_cents(
            total_cents=-50,
            participant_ids=["u1", "u2"],
        )


def test_monte_carlo_invariant_hundreds_of_random_splits() -> None:
    """AC 3: Proprietà invariante su centinaia di permutazioni casuali."""
    rng = random.Random(42)

    for _ in range(200):
        # Importo casuale da 0.01 a 5000.00
        cents = rng.randint(1, 500000)
        total_dec = cents_to_decimal(cents)

        num_users = rng.randint(1, 20)
        users = [f"user_{i}" for i in range(num_users)]
        payer = rng.choice(users) if rng.random() > 0.1 else None

        splits = calculate_precise_splits(
            total_amount=total_dec,
            participant_ids=users,
            payer_id=payer,
        )

        # Invariante 1: somma quote == totale
        assert sum(splits.values()) == total_dec, (
            f"Fallita quadratura su {total_dec} con {num_users} utenti!"
        )

        # Invariante 2: scarto massimo tra qualsiasi coppia di quote è <= 0.01
        diff = max(splits.values()) - min(splits.values())
        assert diff <= Decimal("0.01")


def test_zero_float_ast_certification() -> None:
    """AC 5: Certificazione AST anti-float in finance e split_calculator."""
    files_to_check = [
        Path(__file__).parent.parent / "app" / "utils" / "finance.py",
        Path(__file__).parent.parent / "app" / "services" / "split_calculator.py",
    ]

    for file_path in files_to_check:
        assert file_path.exists(), f"File non trovato: {file_path}"
        code = file_path.read_text(encoding="utf-8")
        tree = ast.parse(code, filename=str(file_path))

        for node in ast.walk(tree):
            # Controlla chiamate a float(...)
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == "float":
                    pytest.fail(
                        f"Rilevata chiamata float() proibita in {file_path.name} "
                        f"alla riga {node.lineno}!"
                    )
            # Controlla letterali float (es. 10.5 invece di Decimal/int)
            elif isinstance(node, ast.Constant) and isinstance(node.value, float):
                pytest.fail(
                    f"Rilevato letterale float ({node.value}) in {file_path.name} "
                    f"alla riga {node.lineno}!"
                )
