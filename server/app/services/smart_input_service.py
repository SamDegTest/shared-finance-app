import re
import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category
from app.models.expense import SplitType
from app.schemas.smart_input import (
    SmartInputBatchParseResponse,
    SmartInputExtractedExpense,
    SmartInputParseRequest,
)

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "Spesa Alimentari": [
        "spesa",
        "supermercato",
        "esselunga",
        "conad",
        "coop",
        "lidl",
        "carrefour",
        "eurospin",
        "alimentari",
        "frutta",
        "verdura",
        "carne",
        "pesce",
        "latte",
        "pane",
    ],
    "Ristoranti & Bar": [
        "cena",
        "pranzo",
        "pizzeria",
        "pizza",
        "ristorante",
        "bar",
        "caffè",
        "caffe",
        "aperitivo",
        "sushi",
        "pub",
        "colazione",
        "brioche",
        "mcdonald",
        "kebab",
    ],
    "Casa & Utenze": [
        "bolletta",
        "luce",
        "gas",
        "enel",
        "acqua",
        "internet",
        "wifi",
        "affitto",
        "condominio",
        "ikea",
        "leroy merlin",
        "brico",
        "ferramenta",
        "detersivi",
    ],
    "Salute & Farmacia": [
        "farmacia",
        "medicinali",
        "medicine",
        "tachipirina",
        "ticket",
        "dottore",
        "dentista",
        "medico",
        "visita",
        "farmaco",
        "sciroppo",
    ],
    "Trasporti": [
        "benzina",
        "gasolio",
        "rifornimento",
        "carburante",
        "treno",
        "biglietto",
        "italo",
        "trenitalia",
        "metro",
        "taxi",
        "uber",
        "telepass",
        "autostrada",
        "pedaggio",
        "parcheggio",
    ],
    "Svago & Viaggi": [
        "cinema",
        "teatro",
        "concerto",
        "vacanza",
        "hotel",
        "bnb",
        "booking",
        "airbnb",
        "aereo",
        "volo",
        "netflix",
        "spotify",
        "palestra",
        "museo",
    ],
}


def _extract_amount_cents(text: str) -> tuple[int | None, str]:
    """Estrae l'importo in centesimi e rimuove la porzione di testo trovata."""
    # 1. Pattern: "34 euro e 20 centesimi"
    complex_pattern = re.search(
        r"(\d+)\s*(?:euro|euri|eur|€)\s*e\s*(\d{1,2})\s*(?:cent|centesimi)?",
        text,
        re.IGNORECASE,
    )
    if complex_pattern:
        euros = int(complex_pattern.group(1))
        cents = int(complex_pattern.group(2).ljust(2, "0"))
        amount = euros * 100 + cents
        cleaned_text = (
            text[: complex_pattern.start()] + " " + text[complex_pattern.end() :]
        )
        return amount, cleaned_text

    # 2. Pattern: "50,50 euro", "50.50 eur", "€ 100", "eur 100"
    currency_match = re.search(
        r"(\d+(?:[.,]\d{1,2})?)\s*(?:euro|euri|eur|€)\b|(?:€|eur)\s*(\d+(?:[.,]\d{1,2})?)",
        text,
        re.IGNORECASE,
    )
    if currency_match:
        val_str = (currency_match.group(1) or currency_match.group(2)).replace(",", ".")
        amount = int(Decimal(val_str) * 100)
        cleaned_text = (
            text[: currency_match.start()] + " " + text[currency_match.end() :]
        )
        return amount, cleaned_text

    # 3. Pattern con simbolo euro isolato: "100€"
    symbol_match = re.search(
        r"(\d+(?:[.,]\d{1,2})?)\s*€|€\s*(\d+(?:[.,]\d{1,2})?)",
        text,
    )
    if symbol_match:
        val_str = (symbol_match.group(1) or symbol_match.group(2)).replace(",", ".")
        amount = int(Decimal(val_str) * 100)
        cleaned_text = text[: symbol_match.start()] + " " + text[symbol_match.end() :]
        return amount, cleaned_text

    # 4. Numero isolato
    isolated_num = re.search(r"\b(\d+(?:[.,]\d{1,2})?)\b", text)
    if isolated_num:
        val_str = isolated_num.group(1).replace(",", ".")
        amount = int(Decimal(val_str) * 100)
        cleaned_text = text[: isolated_num.start()] + " " + text[isolated_num.end() :]
        return amount, cleaned_text

    return None, text


def _extract_split_type(text: str) -> tuple[SplitType, str]:
    """Riconosce e mappa le frasi di ripartizione."""
    lower = text.lower()

    # Mappatura 50/50 (EQUAL)
    equal_patterns = [
        r"\bdivis[oa]\s+a\s+met[àa]\b",
        r"\ba\s+met[àa]\b",
        r"\b50\s*/\s*50\b",
        r"\b50\s*-\s*50\b",
        r"\bdivis[oa]\s+in\s+due\b",
        r"\bdivis[oa]\s+2\b",
        r"\bmet[àa]\s+per\s+uno\b",
        r"\bdivis[oa]\s+equamente\b",
        r"\bequ[oa]\b",
    ]
    for pattern in equal_patterns:
        match = re.search(pattern, lower)
        if match:
            cleaned = text[: match.start()] + " " + text[match.end() :]
            return SplitType.EQUAL, cleaned

    # Mappatura 100% solo pagatore (EXACT)
    exact_patterns = [
        r"\bpago\s+tutto\s+io\b",
        r"\bsolo\s+mi[ao]\b",
        r"\b100%\s+io\b",
        r"\btutto\s+io\b",
    ]
    for pattern in exact_patterns:
        match = re.search(pattern, lower)
        if match:
            cleaned = text[: match.start()] + " " + text[match.end() :]
            return SplitType.EXACT, cleaned

    # Default: EQUAL per spese di coppia
    return SplitType.EQUAL, text


def _extract_relative_date(text: str) -> tuple[date, str]:
    """Riconosce espressioni di data relativa come 'ieri', 'l'altro ieri', 'oggi'."""
    today = date.today()
    lower = text.lower()

    if re.search(r"\bl['\s]?altro\s*ieri\b", lower):
        match = re.search(r"\bl['\s]?altro\s*ieri\b", lower)
        assert match is not None
        cleaned = text[: match.start()] + " " + text[match.end() :]
        return today - timedelta(days=2), cleaned

    if re.search(r"\bieri\b", lower):
        match = re.search(r"\bieri\b", lower)
        assert match is not None
        cleaned = text[: match.start()] + " " + text[match.end() :]
        return today - timedelta(days=1), cleaned

    if re.search(r"\boggi\b", lower):
        match = re.search(r"\boggi\b", lower)
        assert match is not None
        cleaned = text[: match.start()] + " " + text[match.end() :]
        return today, cleaned

    return today, text


def _extract_category_name(text: str) -> str | None:
    """Inferisce la categoria in base alle parole chiave contenute nel testo."""
    lower = text.lower()
    for category_name, keywords in CATEGORY_KEYWORDS.items():
        if any(re.search(rf"\b{kw}\b", lower) for kw in keywords):
            return category_name
    return None


def _split_into_expense_clauses(text: str) -> list[str]:
    """Divide un testo multi-spesa in clausole distinte."""
    if "\n" in text:
        return [line.strip() for line in text.split("\n") if line.strip()]
    if ";" in text:
        return [part.strip() for part in text.split(";") if part.strip()]

    # Controlla se sono presenti 2 o più importi distinti
    currency_occurrences = list(
        re.finditer(
            r"(\d+(?:[.,]\d{1,2})?)\s*(?:euro|euri|eur|€)\b|(?:€|eur)\s*(\d+(?:[.,]\d{1,2})?)|\b\d+(?:[.,]\d{1,2})?\s*€",
            text,
            re.IGNORECASE,
        )
    )

    if len(currency_occurrences) <= 1:
        return [text]

    # Suddivisione connettivi multi-spesa
    split_regex = r"\b(?:e\s+poi|e\s+anche|inoltre|in\s+più|\+)\b|,\s*(?=[a-zA-Z0-9€])"
    raw_parts = [p.strip() for p in re.split(split_regex, text) if p.strip()]
    if len(raw_parts) > 1:
        return raw_parts

    and_split = [p.strip() for p in re.split(r"\s+\be\b\s+", text) if p.strip()]
    if len(and_split) > 1:
        return and_split

    return [text]


class SmartInputService:
    """Servizio per l'elaborazione del linguaggio naturale e parsing multi-spesa."""

    async def parse_single_clause(
        self,
        text: str,
        household_id: uuid.UUID,
        default_payer_id: uuid.UUID | None,
        db: AsyncSession | None = None,
    ) -> SmartInputExtractedExpense:
        raw_text = text.strip()
        remaining_text = raw_text

        # 1. Estrazione Data
        expense_date, remaining_text = _extract_relative_date(remaining_text)

        # 2. Estrazione Tipo di Split
        split_type, remaining_text = _extract_split_type(remaining_text)

        # 3. Estrazione Importo in Centesimi
        amount_cents, remaining_text = _extract_amount_cents(remaining_text)

        # 4. Inferenza Categoria Semantica
        category_name = _extract_category_name(raw_text)

        # 5. Pulizia e Normalizzazione Titolo
        cleaned_title = re.sub(r"[\s\-_,;.]+", " ", remaining_text).strip()
        cleaned_title = re.sub(
            r"^(?:per|con|da|in|a|di)\s+", "", cleaned_title, flags=re.IGNORECASE
        ).strip()
        title = cleaned_title.capitalize() if cleaned_title else None

        # 6. Risoluzione Category ID da Database
        category_id = None
        if db and category_name:
            stmt = select(Category.id).where(
                Category.household_id == household_id,
                Category.name.ilike(f"%{category_name}%"),
            )
            res = await db.execute(stmt)
            category_id = res.scalar_one_or_none()

        # 7. Validazione Campi Obbligatori
        missing_fields: list[str] = []
        clarification_prompt = None

        if amount_cents is None or amount_cents <= 0:
            missing_fields.append("amount_cents")
            clarification_prompt = "Specifica l'importo della spesa (es. 50€)"

        if not title or len(title) < 2:
            missing_fields.append("title")
            clarification_prompt = (
                "Specifica una descrizione per la spesa (es. Cena pizzeria)"
            )

        is_valid = len(missing_fields) == 0

        return SmartInputExtractedExpense(
            title=title,
            amount_cents=amount_cents,
            currency="EUR",
            expense_date=expense_date,
            category_name=category_name,
            category_id=category_id,
            split_type=split_type,
            paid_by_id=default_payer_id,
            confidence_score=0.98 if is_valid else 0.50,
            is_valid=is_valid,
            missing_fields=missing_fields,
            clarification_prompt=clarification_prompt,
        )

    async def parse_natural_language_expense(
        self,
        request: SmartInputParseRequest,
        db: AsyncSession | None = None,
    ) -> SmartInputExtractedExpense:
        """Compatibilità per parsing di singola spesa."""
        return await self.parse_single_clause(
            text=request.text,
            household_id=request.household_id,
            default_payer_id=request.default_payer_id,
            db=db,
        )

    async def parse_multi_expenses(
        self,
        request: SmartInputParseRequest,
        db: AsyncSession | None = None,
    ) -> SmartInputBatchParseResponse:
        """Esegue il parsing batch di una o più spese in un unico prompt."""
        clauses = _split_into_expense_clauses(request.text)
        extracted_list: list[SmartInputExtractedExpense] = []

        for clause in clauses:
            if not clause.strip():
                continue
            parsed = await self.parse_single_clause(
                text=clause,
                household_id=request.household_id,
                default_payer_id=request.default_payer_id,
                db=db,
            )
            extracted_list.append(parsed)

        total_cents = sum(e.amount_cents for e in extracted_list if e.amount_cents)
        is_all_valid = len(extracted_list) > 0 and all(
            e.is_valid for e in extracted_list
        )

        all_missing: list[str] = []
        for e in extracted_list:
            all_missing.extend(e.missing_fields)

        prompt = (
            None if is_all_valid else "Alcune spese richiedono importo o descrizione."
        )

        return SmartInputBatchParseResponse(
            expenses=extracted_list,
            total_amount_cents=total_cents,
            count=len(extracted_list),
            is_valid=is_all_valid,
            missing_fields=list(set(all_missing)),
            clarification_prompt=prompt,
        )


smart_input_service = SmartInputService()
