import base64
import json
import logging
from abc import ABC, abstractmethod
from datetime import date
from typing import Any

import httpx

from app.schemas.receipt import ReceiptExtractionResponse, ReceiptItem

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

        content = data["choices"][0]["message"]["content"]
        raw_json: dict[str, Any] = json.loads(content)

        return ReceiptExtractionResponse.model_validate(raw_json)


class MockVisionProvider(BaseVisionProvider):
    """Provider deterministico per testing e CI/CD."""

    def __init__(
        self,
        canned_response: ReceiptExtractionResponse | None = None,
    ) -> None:
        self.canned_response = canned_response

    def set_canned_response(self, response: ReceiptExtractionResponse) -> None:
        self.canned_response = response

    async def extract_receipt(
        self,
        image_bytes: bytes,
        _mime_type: str = "image/jpeg",
    ) -> ReceiptExtractionResponse:
        if not image_bytes:
            raise ValueError("I byte dell'immagine non possono essere vuoti.")

        if self.canned_response:
            return self.canned_response

        # Risposta di default standard
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
    """Worker di elaborazione e parsing immagini scontrini."""

    def __init__(self, provider: BaseVisionProvider | None = None) -> None:
        self.provider = provider or MockVisionProvider()

    async def process_receipt_image(
        self,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
    ) -> ReceiptExtractionResponse:
        """Elabora l'immagine e restituisce i dati estratti con validazione."""
        if not image_bytes:
            raise ValueError("Immagine ricevuta non valida o vuota.")

        logger.info(
            "Avvio elaborazione scontrino (%d bytes, mime: %s)...",
            len(image_bytes),
            mime_type,
        )
        extraction = await self.provider.extract_receipt(image_bytes, mime_type)

        logger.info(
            "Completato: '%s', tot=%d (warn=%s, mism=%s)",
            extraction.merchant_name,
            extraction.total_amount_cents,
            extraction.validation_warning,
            extraction.validation_mismatch,
        )
        return extraction
