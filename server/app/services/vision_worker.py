import base64
import json
import logging
from abc import ABC, abstractmethod
from datetime import date
from typing import Any

import httpx

from app.schemas.receipt import (
    ReceiptExtractionResponse,
    ReceiptItem,
    ValidationMismatchError,
)
from app.services.pii_redaction_service import pii_redaction_service

logger = logging.getLogger("shared-finance-app.vision_worker")

VISION_SYSTEM_PROMPT = """Sei un assistente OCR finanziario esperto per scontrini.
Estrai i dati rispettando lo schema JSON:
- merchant_name: nome esercente
- expense_date: data emissione (YYYY-MM-DD)
- total_amount_cents: totale espresso in INTERI IN CENTESIMI (es. 10.50 EUR = 1050)
- currency: valuta (EUR)
- items: lista voci con name, amount_cents, quantity, category
- category_suggestion: categoria macro suggerita per l'intera spesa
- tax_amount_cents: importo IVA in centesimi se presente
- payment_method: metodo di pagamento
- confidence_score: float tra 0.0 e 1.0
"""


class GDPRSafeProcessingError(Exception):
    """Eccezione base per violazioni o errori di conformità privacy GDPR."""


class GDPRRedactionFailedError(GDPRSafeProcessingError):
    """Sollevata se la redazione fallisce per prevenire data leakage."""


class BaseVisionProvider(ABC):
    """Interfaccia astratta per provider Vision AI."""

    @abstractmethod
    async def extract_receipt(
        self,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
    ) -> ReceiptExtractionResponse:
        """Estrae i dati strutturati da un'immagine binaria di uno scontrino."""
        pass


class OpenAIVisionProvider(BaseVisionProvider):
    """Provider Vision basato su OpenAI gpt-4o-mini con Structured Outputs."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gpt-4o-mini",
    ) -> None:
        self.api_key = api_key
        self.model = model

    async def extract_receipt(
        self,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
    ) -> ReceiptExtractionResponse:
        if not self.api_key:
            raise ValueError("OpenAI API key non configurata per OpenAIVisionProvider.")

        base64_img = base64.b64encode(image_bytes).decode("utf-8")
        data_uri = f"data:{mime_type};base64,{base64_img}"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": VISION_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Estrai i dati da questo scontrino in formato "
                                "JSON conforme allo schema."
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": data_uri},
                        },
                    ],
                },
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.0,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        if not content:
            raise ValidationMismatchError(
                "Risposta vuota o priva di contenuto dall'LLM."
            )

        try:
            raw_json: dict[str, Any] = json.loads(content)
        except Exception as e:
            logger.error("JSON malformato ricevuto da Vision LLM: %s", e)
            raise ValidationMismatchError(
                f"JSON malformato ricevuto dall'LLM: {e}"
            ) from e

        try:
            return ReceiptExtractionResponse.model_validate(raw_json)
        except Exception as e:
            logger.error("Validazione schema Pydantic fallita per scontrino: %s", e)
            raise ValidationMismatchError(
                f"Lo scontrino estratto non rispetta lo schema Pydantic: {e}"
            ) from e


class MockVisionProvider(BaseVisionProvider):
    """Provider deterministico per testing e CI/CD."""

    def __init__(
        self,
        canned_response: ReceiptExtractionResponse | None = None,
    ) -> None:
        self.canned_response = canned_response
        self.last_received_image_bytes: bytes | None = None

    def set_canned_response(self, response: ReceiptExtractionResponse) -> None:
        self.canned_response = response

    async def extract_receipt(
        self,
        image_bytes: bytes,
        _mime_type: str = "image/jpeg",
    ) -> ReceiptExtractionResponse:
        if not image_bytes:
            raise ValueError("I byte dell'immagine non possono essere vuoti.")

        self.last_received_image_bytes = image_bytes

        if self.canned_response:
            return self.canned_response

        # Risposta di default standard con dati finanziari intatti
        return ReceiptExtractionResponse(
            merchant_name="Supermercato Esempio",
            expense_date=date.today(),
            total_amount_cents=2540,
            currency="EUR",
            category_suggestion="Spesa Alimentari",
            items=[
                ReceiptItem(
                    name="Latte Bio",
                    amount_cents=180,
                    quantity=2,
                    category="Alimentari",
                ),
                ReceiptItem(
                    name="Caffè Macinato",
                    amount_cents=450,
                    quantity=1,
                    category="Alimentari",
                ),
                ReceiptItem(
                    name="Detersivo Piatti",
                    amount_cents=350,
                    quantity=1,
                    category="Casa",
                ),
                ReceiptItem(
                    name="Prosciutto Crudo",
                    amount_cents=1380,
                    quantity=1,
                    category="Alimentari",
                ),
            ],
            tax_amount_cents=254,
            payment_method="Carta di Credito",
            confidence_score=0.98,
        )


class VisionWorker:
    """Worker di elaborazione e parsing immagini scontrini con privacy guard."""

    def __init__(self, provider: BaseVisionProvider | None = None) -> None:
        self.provider = provider or MockVisionProvider()

    async def process_receipt_image(
        self,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
        redact_pii: bool = True,
    ) -> ReceiptExtractionResponse:
        """Elabora l'immagine oscurando prima le PII e validando i dati estratti."""
        if not image_bytes:
            raise ValueError("Immagine ricevuta non valida o vuota.")

        # 1. Fase di Anonimizzazione Visiva PII (GDPR-Safe)
        payload_bytes = image_bytes
        if redact_pii:
            try:
                logger.info(
                    "Avvio mascheramento visivo PII su scontrino (%d bytes)...",
                    len(image_bytes),
                )
                payload_bytes = pii_redaction_service.redact_receipt_image(image_bytes)
                if not payload_bytes:
                    raise GDPRRedactionFailedError(
                        "L'immagine anonimizzata risulta vuota."
                    )
            except GDPRSafeProcessingError:
                raise
            except Exception as e:
                logger.exception("Fallimento durante la redazione PII: %s", e)
                raise GDPRRedactionFailedError(
                    f"Anonimizzazione PII fallita: {e}. Invio al Vision LLM "
                    "interrotto per protezione privacy GDPR."
                ) from e

        # 2. Inoltro esclusivo dell'immagine anonimizzata al Vision LLM
        logger.info(
            "Inoltro scontrino anonimizzato al Vision Provider (%d bytes)...",
            len(payload_bytes),
        )
        extraction = await self.provider.extract_receipt(payload_bytes, mime_type)

        logger.info(
            "Estrazione completata: '%s', totale=%d (warn=%s)",
            extraction.merchant_name,
            extraction.total_amount_cents,
            extraction.validation_warning,
        )
        return extraction
