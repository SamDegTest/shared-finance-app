from datetime import date

import pytest

from app.schemas.receipt import ReceiptExtractionResponse, ReceiptItem
from app.services.vision_worker import (
    MockVisionProvider,
    OpenAIVisionProvider,
    VisionWorker,
)

# ============================================================================
# 1. TEST DELLA SOGLIA DI TOLLERANZA ARITMETICA (> 0.05€)
# ============================================================================


def test_validation_warning_exact_match() -> None:
    """Quando la somma delle voci è identica al totale, nessun warning."""
    items = [
        ReceiptItem(name="Pane", amount_cents=250, quantity=1, category="Alimentari"),
        ReceiptItem(name="Latte", amount_cents=150, quantity=1, category="Alimentari"),
    ]
    resp = ReceiptExtractionResponse(
        merchant_name="Forno",
        expense_date=date(2026, 9, 2),
        total_amount_cents=400,  # 4.00 EUR
        currency="EUR",
        items=items,
    )

    assert resp.items_sum_cents == 400
    assert resp.validation_warning is False
    assert resp.validation_mismatch is False


def test_validation_warning_within_5_cents_tolerance() -> None:
    """Discrepanze entro i 5 centesimi (<= 0.05€) NON impostano warning."""
    # Caso 1: Differenza di 3 centesimi
    items_3c = [
        ReceiptItem(name="Articolo A", amount_cents=1000, quantity=1),
    ]
    resp_3c = ReceiptExtractionResponse(
        merchant_name="Negozio",
        total_amount_cents=1003,  # Diff = 3 centesimi (0.03€)
        currency="EUR",
        items=items_3c,
    )
    assert resp_3c.items_sum_cents == 1000
    assert resp_3c.validation_warning is False  # <= 0.05€ tollerato
    assert resp_3c.validation_mismatch is True

    # Caso 2: Differenza esatta di 5 centesimi (0.05€)
    resp_5c = ReceiptExtractionResponse(
        merchant_name="Negozio",
        total_amount_cents=1005,  # Diff = 5 centesimi (0.05€)
        currency="EUR",
        items=items_3c,
    )
    assert resp_5c.items_sum_cents == 1000
    assert resp_5c.validation_warning is False  # <= 0.05€ tollerato
    assert resp_5c.validation_mismatch is True


def test_validation_warning_triggers_over_5_cents_discrepancy() -> None:
    """Se la somma differisce di oltre 0.05€ (> 5 cent), warning DEVE essere True."""
    items = [
        ReceiptItem(name="Prodotto", amount_cents=1000, quantity=1, category="Casa"),
    ]

    # Caso 1: Differenza di 6 centesimi (0.06€ > 0.05€)
    resp_6c = ReceiptExtractionResponse(
        merchant_name="Store",
        total_amount_cents=1006,  # Diff = 6 centesimi
        currency="EUR",
        items=items,
    )
    assert resp_6c.items_sum_cents == 1000
    assert resp_6c.validation_warning is True  # TRIGGER ATTIVO!

    # Caso 2: Differenza di 80 centesimi (0.80€)
    resp_80c = ReceiptExtractionResponse(
        merchant_name="Brico",
        total_amount_cents=1080,  # Diff = 80 centesimi
        currency="EUR",
        items=items,
    )
    assert resp_80c.items_sum_cents == 1000
    assert resp_80c.validation_warning is True  # TRIGGER ATTIVO!


# ============================================================================
# 2. TEST ESTRAZIONE CATEGORIE E SUGGERIMENTI
# ============================================================================


def test_receipt_items_categories_and_suggestion() -> None:
    items = [
        ReceiptItem(
            name="Mele Golden 1kg",
            amount_cents=220,
            quantity=1,
            category="Alimentari",
        ),
        ReceiptItem(
            name="Aspirina C",
            amount_cents=850,
            quantity=1,
            category="Salute & Farmacia",
        ),
    ]
    resp = ReceiptExtractionResponse(
        merchant_name="Centro Commerciale",
        total_amount_cents=1070,
        currency="EUR",
        category_suggestion="Spesa Mista",
        items=items,
    )

    assert resp.category_suggestion == "Spesa Mista"
    assert resp.items[0].category == "Alimentari"
    assert resp.items[1].category == "Salute & Farmacia"
    assert resp.validation_warning is False


# ============================================================================
# 3. TEST VISION WORKER PIPELINE
# ============================================================================


@pytest.mark.asyncio
async def test_vision_worker_pipeline_with_mock_provider() -> None:
    worker = VisionWorker(MockVisionProvider())

    fake_image_bytes = b"fake_jpeg_binary_data"
    result = await worker.process_receipt_image(
        fake_image_bytes, mime_type="image/jpeg"
    )

    assert result.merchant_name == "Supermercato Esempio"
    assert result.total_amount_cents == 2540
    assert len(result.items) == 4
    assert result.category_suggestion == "Spesa Alimentari"
    assert result.confidence_score >= 0.90
    assert result.validation_warning is False


@pytest.mark.asyncio
async def test_vision_worker_empty_bytes_raises_error() -> None:
    worker = VisionWorker(MockVisionProvider())

    with pytest.raises(ValueError, match="non valida o vuota"):
        await worker.process_receipt_image(b"")


@pytest.mark.asyncio
async def test_openai_provider_missing_key_raises_error() -> None:
    provider = OpenAIVisionProvider(api_key=None)

    with pytest.raises(ValueError, match="API key non configurata"):
        await provider.extract_receipt(b"some_bytes")
