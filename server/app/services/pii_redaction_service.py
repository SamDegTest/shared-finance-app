import importlib
import io
import logging
import re
from typing import Any

logger = logging.getLogger("shared-finance-app.pii_redaction")

# Fallback regex per PII (Carte di credito, IBAN, CF, Telefoni, Email)
CREDIT_CARD_REGEX = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
IBAN_REGEX = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b", re.IGNORECASE)
ITALIAN_FISCAL_CODE_REGEX = re.compile(
    r"\b[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]\b", re.IGNORECASE
)
PHONE_REGEX = re.compile(r"\b(?:\+39\s?)?(?:3\d{2}[ -]?\d{6,7})\b")
EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")


class PIIRedactionService:
    """Servizio di rilevamento e oscuramento dati personali (PII)."""

    def __init__(self) -> None:
        self._analyzer: Any = None
        self._image_redactor: Any = None
        self._init_presidio_engines()

    def _init_presidio_engines(self) -> None:
        """Inizializza Microsoft Presidio se disponibile nell'ambiente."""
        try:
            mod_analyzer = importlib.import_module("presidio_analyzer")
            self._analyzer = mod_analyzer.AnalyzerEngine()
            logger.info("Presidio AnalyzerEngine inizializzato con successo.")
        except Exception as e:
            logger.warning(
                "Presidio AnalyzerEngine non disponibile, uso fallback: %s",
                e,
            )
            self._analyzer = None

        try:
            mod_redactor = importlib.import_module("presidio_image_redactor")
            self._image_redactor = mod_redactor.ImageRedactorEngine()
            logger.info("Presidio ImageRedactorEngine inizializzato.")
        except Exception as e:
            logger.warning(
                "Presidio ImageRedactorEngine non disponibile, uso fallback: %s",
                e,
            )
            self._image_redactor = None

    def is_ocr_available(self) -> bool:
        """Verifica se il motore Tesseract OCR è raggiungibile a livello OS."""
        try:
            mod_tesseract = importlib.import_module("pytesseract")
            version = mod_tesseract.get_tesseract_version()
            return version is not None
        except Exception:
            return False

    def is_nlp_model_loaded(self) -> bool:
        """Verifica se il modello spaCy / Presidio è caricato."""
        return self._analyzer is not None

    def analyze_text(self, text: str, language: str = "en") -> list[dict[str, Any]]:
        """Identifica entità sensibili nel testo (carte, codici, telefoni)."""
        if not text:
            return []

        # 1. Analisi con Microsoft Presidio se disponibile
        if self._analyzer:
            try:
                results = self._analyzer.analyze(text=text, language=language)
                return [
                    {
                        "entity_type": res.entity_type,
                        "start": res.start,
                        "end": res.end,
                        "score": res.score,
                    }
                    for res in results
                ]
            except Exception as e:
                logger.warning("Errore durante Presidio text analysis: %s", e)

        # 2. Fallback Regex deterministico
        detected: list[dict[str, Any]] = []

        for match in CREDIT_CARD_REGEX.finditer(text):
            digits = re.sub(r"\D", "", match.group())
            if 13 <= len(digits) <= 19:
                detected.append(
                    {
                        "entity_type": "CREDIT_CARD",
                        "start": match.start(),
                        "end": match.end(),
                        "score": 0.95,
                    }
                )

        for match in IBAN_REGEX.finditer(text):
            detected.append(
                {
                    "entity_type": "IBAN_CODE",
                    "start": match.start(),
                    "end": match.end(),
                    "score": 0.90,
                }
            )

        for match in ITALIAN_FISCAL_CODE_REGEX.finditer(text):
            detected.append(
                {
                    "entity_type": "IT_FISCAL_CODE",
                    "start": match.start(),
                    "end": match.end(),
                    "score": 0.99,
                }
            )

        for match in PHONE_REGEX.finditer(text):
            detected.append(
                {
                    "entity_type": "PHONE_NUMBER",
                    "start": match.start(),
                    "end": match.end(),
                    "score": 0.85,
                }
            )

        for match in EMAIL_REGEX.finditer(text):
            detected.append(
                {
                    "entity_type": "EMAIL_ADDRESS",
                    "start": match.start(),
                    "end": match.end(),
                    "score": 0.95,
                }
            )

        return detected

    def anonymize_text(self, text: str, language: str = "en") -> str:
        """Sostituisce le PII rilevate con etichette di oscuramento."""
        entities = self.analyze_text(text, language)
        if not entities:
            return text

        sorted_entities = sorted(entities, key=lambda x: x["start"], reverse=True)
        anonymized = text
        for ent in sorted_entities:
            placeholder = f"<{ent['entity_type']}>"
            anonymized = (
                anonymized[: ent["start"]] + placeholder + anonymized[ent["end"] :]
            )

        return anonymized

    def redact_receipt_image(self, image_bytes: bytes) -> bytes:
        """Applica l'oscuramento delle PII sull'immagine dello scontrino."""
        if not image_bytes:
            return image_bytes

        if self._image_redactor and self.is_ocr_available():
            try:
                mod_pil = importlib.import_module("PIL.Image")
                image = mod_pil.open(io.BytesIO(image_bytes))
                redacted_image = self._image_redactor.redact(image, fill=(0, 0, 0))

                output = io.BytesIO()
                redacted_image.save(output, format="JPEG")
                return output.getvalue()
            except Exception as e:
                logger.warning("Errore durante ImageRedactorEngine, fallback: %s", e)

        return image_bytes


pii_redaction_service = PIIRedactionService()
