import importlib
import io
import logging
import re
from typing import Any

logger = logging.getLogger("shared-finance-app.pii_redaction")

# Pattern PII con focus su scontrini, ricevute POS e fatture italiane
RAW_CARD_REGEX = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
MASKED_CARD_REGEX = re.compile(r"(?:\*{4}[ -]?\*{4}[ -]?\*{4}[ -]?\d{4}|\*{6,12}\d{4})")
IBAN_REGEX = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b", re.IGNORECASE)
ITALIAN_FISCAL_CODE_REGEX = re.compile(
    r"\b[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]\b", re.IGNORECASE
)
# Telefoni Italiani: Cellulari (3xx), Fissi (0xx), Numero Verde (800)
ITALIAN_PHONE_REGEX = re.compile(
    r"(?:(?:\+39|0039)[\s./-]?)?(?:(?:3[1-9]\d[\s./-]?\d{3}[\s./-]?\d{3,4})|(?:0\d{1,3}[\s./-]?\d{5,8})|(?:800[\s./-]?\d{3}[\s./-]?\d{3}))\b"
)
EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")


def _is_luhn_valid(candidate: str) -> bool:
    """Verifica il checksum di Luhn per le carte di credito."""
    digits = [int(c) for c in candidate if c.isdigit()]
    if len(digits) < 13 or len(digits) > 19:
        return False
    checksum = 0
    reverse_digits = digits[::-1]
    for i, digit in enumerate(reverse_digits):
        val = digit * 2 if i % 2 == 1 else digit
        if val > 9:
            val -= 9
        checksum += val
    return checksum % 10 == 0


def _filter_overlapping_entities(
    entities: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Filtra entità sovrapposte mantenendo quelle a priorità più elevata."""
    # Normalizza eventuali entità straniere duplicate
    normalized: list[dict[str, Any]] = []
    for ent in entities:
        item = dict(ent)
        if item.get("entity_type") == "UK_NHS":
            item["entity_type"] = "PHONE_NUMBER"
            item["score"] = 0.95
        normalized.append(item)

    # Ordina per score (decrescente), poi per lunghezza span (decrescente)
    sorted_by_priority = sorted(
        normalized,
        key=lambda x: (
            float(x.get("score", 0)),
            int(x["end"]) - int(x["start"]),
        ),
        reverse=True,
    )

    non_overlapping: list[dict[str, Any]] = []
    for candidate in sorted_by_priority:
        c_start = int(candidate["start"])
        c_end = int(candidate["end"])

        is_overlapping = any(
            max(c_start, int(existing["start"])) < min(c_end, int(existing["end"]))
            for existing in non_overlapping
        )
        if not is_overlapping:
            non_overlapping.append(candidate)

    # Restituisce ordinate per posizione decrescente per sostituzione sicura
    return sorted(non_overlapping, key=lambda x: int(x["start"]), reverse=True)


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

        detected: list[dict[str, Any]] = []

        # 1. Analisi con Microsoft Presidio se disponibile
        if self._analyzer:
            try:
                results = self._analyzer.analyze(text=text, language=language)
                for res in results:
                    detected.append(
                        {
                            "entity_type": res.entity_type,
                            "start": res.start,
                            "end": res.end,
                            "score": res.score,
                        }
                    )
            except Exception as e:
                logger.warning("Errore durante Presidio text analysis: %s", e)

        # 2. Riconoscitori dedicati per formati e scontrini italiani
        for match in RAW_CARD_REGEX.finditer(text):
            if _is_luhn_valid(match.group()):
                detected.append(
                    {
                        "entity_type": "CREDIT_CARD",
                        "start": match.start(),
                        "end": match.end(),
                        "score": 0.99,
                    }
                )

        for match in MASKED_CARD_REGEX.finditer(text):
            detected.append(
                {
                    "entity_type": "CREDIT_CARD",
                    "start": match.start(),
                    "end": match.end(),
                    "score": 0.99,
                }
            )

        for match in IBAN_REGEX.finditer(text):
            detected.append(
                {
                    "entity_type": "IBAN_CODE",
                    "start": match.start(),
                    "end": match.end(),
                    "score": 0.99,
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

        for match in ITALIAN_PHONE_REGEX.finditer(text):
            detected.append(
                {
                    "entity_type": "PHONE_NUMBER",
                    "start": match.start(),
                    "end": match.end(),
                    "score": 0.99,
                }
            )

        for match in EMAIL_REGEX.finditer(text):
            detected.append(
                {
                    "entity_type": "EMAIL_ADDRESS",
                    "start": match.start(),
                    "end": match.end(),
                    "score": 0.99,
                }
            )

        return _filter_overlapping_entities(detected)

    def anonymize_text(self, text: str, language: str = "en") -> str:
        """Sostituisce le PII rilevate con etichette di oscuramento."""
        filtered_entities = self.analyze_text(text, language)
        if not filtered_entities:
            return text

        anonymized = text
        for ent in filtered_entities:
            placeholder = f"<{ent['entity_type']}>"
            s = int(ent["start"])
            e = int(ent["end"])
            anonymized = anonymized[:s] + placeholder + anonymized[e:]

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
