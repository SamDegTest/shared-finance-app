import pytest

from app.services.pii_redaction_service import pii_redaction_service


def test_presidio_text_pii_detection() -> None:
    """Smoke test: Rilevamento entità sensibili PII (carte, email, telefoni, CF)."""
    sample_text = (
        "Scontrino N. 1045 - Pagamento POS Elettronico\n"
        "Carta di Credito: 5500 0000 0000 0004\n"
        "Email cliente: mario.rossi@gmail.com\n"
        "Telefono assistenza: 333 1234567\n"
        "Codice Fiscale: RSSMRA85M01H501Z\n"
        "IBAN accredito: IT60X0542811101000000123456\n"
        "Totale: 45,50 EUR"
    )

    detected_entities = pii_redaction_service.analyze_text(sample_text)

    entity_types = {e["entity_type"] for e in detected_entities}
    assert "CREDIT_CARD" in entity_types
    assert "EMAIL_ADDRESS" in entity_types
    assert "PHONE_NUMBER" in entity_types
    assert "IT_FISCAL_CODE" in entity_types
    assert "IBAN_CODE" in entity_types


@pytest.mark.parametrize(
    "italian_phone",
    [
        "333 1234567",
        "347-8901234",
        "3201234567",
        "+39 333 1234567",
        "+393401234567",
        "0039 328 1234567",
        "02 12345678",
        "06 98765432",
        "055-123456",
        "800 123 456",
    ],
)
def test_italian_phone_numbers_detection_and_redaction(
    italian_phone: str,
) -> None:
    """Verifica il rilevamento di numeri di cellulare, fissi e numeri verdi italiani."""
    text = f"Per info contatta il {italian_phone} dal lunedi al venerdi."
    entities = pii_redaction_service.analyze_text(text)

    entity_types = {e["entity_type"] for e in entities}
    assert "PHONE_NUMBER" in entity_types

    anonymized = pii_redaction_service.anonymize_text(text)
    assert italian_phone not in anonymized
    assert "<PHONE_NUMBER>" in anonymized


def test_italian_pos_masked_receipt_redaction() -> None:
    """Verifica l'oscuramento delle carte mascherate degli scontrini POS."""
    receipt = (
        "SUPERMERCATO CONAD\n"
        "PAN: **** **** **** 4321\n"
        "Esercente: 02 87654321\n"
        "Cod. Fiscale: BNCMRC80A01H501U\n"
        "Totale EUR 32,80"
    )
    anonymized = pii_redaction_service.anonymize_text(receipt)

    assert "**** **** **** 4321" not in anonymized
    assert "02 87654321" not in anonymized
    assert "BNCMRC80A01H501U" not in anonymized
    assert "<CREDIT_CARD>" in anonymized
    assert "<PHONE_NUMBER>" in anonymized
    assert "<IT_FISCAL_CODE>" in anonymized


def test_presidio_text_anonymization() -> None:
    """Smoke test: Anonimizzazione testo con sostituzione tag di oscuramento."""
    text = "Ricevuta inviata a laura.bianchi@test.it con carta 5500-0000-0000-0004"
    anonymized = pii_redaction_service.anonymize_text(text)

    assert "laura.bianchi@test.it" not in anonymized
    assert "5500-0000-0000-0004" not in anonymized
    assert "<EMAIL_ADDRESS>" in anonymized
    assert "<CREDIT_CARD>" in anonymized


def test_tesseract_ocr_status_and_capabilities() -> None:
    """Smoke test: Verifica stato Tesseract OCR e Presidio NLP Engine."""
    ocr_available = pii_redaction_service.is_ocr_available()
    nlp_available = pii_redaction_service.is_nlp_model_loaded()

    assert isinstance(ocr_available, bool)
    assert isinstance(nlp_available, bool)


def test_receipt_image_redaction_pipeline() -> None:
    """Smoke test: Pipeline di oscuramento immagine scontrino."""
    fake_image_bytes = (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00"
        b"\xff\xdb\x00C\x00"
    )
    output_bytes = pii_redaction_service.redact_receipt_image(fake_image_bytes)

    assert output_bytes is not None
    assert len(output_bytes) > 0
