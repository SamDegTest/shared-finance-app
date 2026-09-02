from datetime import date

from app.ai.spike_receipt_vision import execute_receipt_extraction_spike
from app.schemas.receipt import ReceiptExtractionResponse, ReceiptItem


def test_receipt_extraction_nominal_exact_match() -> None:
    # 84.60 EUR = 8460 cents, 3 items summing to 8460
    items = [
        ReceiptItem(name="Pasta", amount_cents=447, quantity=1),
        ReceiptItem(name="Passata", amount_cents=516, quantity=1),
        ReceiptItem(name="Carne", amount_cents=7497, quantity=1),
    ]
    response = ReceiptExtractionResponse(
        merchant_name="Esselunga",
        expense_date=date(2026, 9, 1),
        total_amount_cents=8460,
        currency="EUR",
        items=items,
        tax_amount_cents=846,
        confidence_score=0.98,
    )

    assert response.merchant_name == "Esselunga"
    assert response.total_amount_cents == 8460
    assert response.items_sum_cents == 8460
    assert response.validation_mismatch is False


def test_receipt_extraction_triggers_validation_mismatch_on_discrepancy() -> None:
    # Declared total: 4200 cents (42.00 EUR)
    # Extracted items sum: 1500 + 1200 + 1420 = 4120 cents (41.20 EUR)
    items = [
        ReceiptItem(name="Cacciaviti", amount_cents=1500, quantity=1),
        ReceiptItem(name="Lampadine", amount_cents=1200, quantity=1),
        ReceiptItem(name="Colla", amount_cents=1420, quantity=1),
    ]
    response = ReceiptExtractionResponse(
        merchant_name="Brico Center",
        expense_date=date(2026, 8, 20),
        total_amount_cents=4200,
        currency="EUR",
        items=items,
        confidence_score=0.75,
    )

    assert response.total_amount_cents == 4200
    assert response.items_sum_cents == 4120
    assert response.validation_mismatch is True  # Discrepanza rilevata


def test_receipt_extraction_empty_items_fallback() -> None:
    response = ReceiptExtractionResponse(
        merchant_name="Parcheggio",
        expense_date=date(2026, 9, 2),
        total_amount_cents=1500,
        currency="EUR",
        items=[],
        confidence_score=0.80,
    )

    assert response.total_amount_cents == 1500
    assert response.items_sum_cents == 1500
    assert response.validation_mismatch is False


def test_execute_spike_dataset_all_five_receipts() -> None:
    results = execute_receipt_extraction_spike()
    assert len(results) == 5

    # Scontrino 1 (Esselunga nominale) -> Match
    assert results[0].merchant_name == "Esselunga S.p.A."
    assert results[0].validation_mismatch is False

    # Scontrino 2 (Pizzeria) -> Match
    assert results[1].merchant_name == "Antica Pizzeria Da Michele"
    assert results[1].validation_mismatch is False

    # Scontrino 3 (Farmacia) -> Match
    assert results[2].merchant_name == "Farmacia San Giorgio"
    assert results[2].validation_mismatch is False

    # Scontrino 4 (Brico con discrepanza) -> validation_mismatch = True
    assert results[3].merchant_name == "Brico Center"
    assert results[3].validation_mismatch is True
    assert results[3].total_amount_cents == 4200
    assert results[3].items_sum_cents == 4120

    # Scontrino 5 (Bar micro) -> Match
    assert results[4].merchant_name == "Bar Centrale"
    assert results[4].validation_mismatch is False
