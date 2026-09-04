import uuid
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.models.expense import SplitType
from app.schemas.expense import SplitItemInput
from app.utils.finance import calculate_precise_splits_cents


@dataclass(frozen=True)
class CalculatedSplit:
    user_id: uuid.UUID
    amount_cents: int
    percentage: Decimal | None = None
    shares: int | None = None


def _calculate_equal_splits(
    total_amount_cents: int,
    participant_ids: list[uuid.UUID],
    payer_id: uuid.UUID | None,
) -> list[CalculatedSplit]:
    """Suddivide l'importo equamente, allocando deterministicamente il resto."""
    splits_cents = calculate_precise_splits_cents(
        total_cents=total_amount_cents,
        participant_ids=participant_ids,
        payer_id=payer_id,
    )

    results: list[CalculatedSplit] = []
    for uid in participant_ids:
        allocated = splits_cents[uid]
        pct = (
            (Decimal(allocated) / Decimal(total_amount_cents)) * Decimal("100")
        ).quantize(Decimal("0.01"))
        results.append(
            CalculatedSplit(
                user_id=uid,
                amount_cents=allocated,
                percentage=pct,
            )
        )
    return results


def _calculate_percentage_splits(
    total_amount_cents: int,
    participant_ids: list[uuid.UUID],
    custom_splits: list[SplitItemInput],
) -> list[CalculatedSplit]:
    """Calcola le quote in base a percentuali con precisione Decimal (Zero-Float)."""
    split_map = {s.user_id: s for s in custom_splits}
    missing = set(participant_ids) - set(split_map.keys())
    if missing:
        raise ValueError(f"Percentuale mancante per i partecipanti: {list(missing)}")

    total_pct = sum(
        (split_map[uid].percentage or Decimal("0")) for uid in participant_ids
    )
    if total_pct != Decimal("100.00") and total_pct != Decimal("100"):
        raise ValueError(
            "La somma delle percentuali deve essere esattamente 100% "
            f"(attuale: {total_pct}%)."
        )

    # Calcolo preliminare con aritmetica Decimal pura
    calculated: list[tuple[uuid.UUID, int, Decimal]] = []
    for uid in participant_ids:
        pct = split_map[uid].percentage or Decimal("0")
        allocated = int(
            (Decimal(total_amount_cents) * pct / Decimal("100")).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
        calculated.append((uid, allocated, pct))

    # Aggiustamento centesimi di scarto
    current_sum = sum(amt for _, amt, _ in calculated)
    diff = total_amount_cents - current_sum

    results: list[CalculatedSplit] = []
    for idx, (uid, amt, pct) in enumerate(calculated):
        # Aggiungi o sottrai la differenza al primo partecipante
        adj = diff if idx == 0 else 0
        results.append(
            CalculatedSplit(
                user_id=uid,
                amount_cents=amt + adj,
                percentage=pct,
            )
        )
    return results


def _calculate_exact_splits(
    total_amount_cents: int,
    participant_ids: list[uuid.UUID],
    custom_splits: list[SplitItemInput],
) -> list[CalculatedSplit]:
    """Valida e assegna gli importi esatti forniti dall'utente."""
    split_map = {s.user_id: s for s in custom_splits}
    missing = set(participant_ids) - set(split_map.keys())
    if missing:
        raise ValueError(f"Importo esatto mancante per i partecipanti: {list(missing)}")

    total_exact = sum((split_map[uid].amount_cents or 0) for uid in participant_ids)
    if total_exact != total_amount_cents:
        raise ValueError(
            f"La somma degli importi esatti ({total_exact} centesimi) non "
            f"coincide con il totale della spesa ({total_amount_cents} centesimi)."
        )

    results: list[CalculatedSplit] = []
    for uid in participant_ids:
        amt = split_map[uid].amount_cents or 0
        pct = ((Decimal(amt) / Decimal(total_amount_cents)) * Decimal("100")).quantize(
            Decimal("0.01")
        )
        results.append(
            CalculatedSplit(
                user_id=uid,
                amount_cents=amt,
                percentage=pct,
            )
        )
    return results


def _calculate_shares_splits(
    total_amount_cents: int,
    participant_ids: list[uuid.UUID],
    custom_splits: list[SplitItemInput],
) -> list[CalculatedSplit]:
    """Ripartisce in base a quote/pesi interi."""
    split_map = {s.user_id: s for s in custom_splits}
    missing = set(participant_ids) - set(split_map.keys())
    if missing:
        raise ValueError(f"Quote mancanti per i partecipanti: {list(missing)}")

    total_shares = sum((split_map[uid].shares or 1) for uid in participant_ids)
    if total_shares <= 0:
        raise ValueError("Il numero totale di quote deve essere maggiore di 0.")

    allocated_list: list[tuple[uuid.UUID, int, int]] = []
    for uid in participant_ids:
        sh = split_map[uid].shares or 1
        allocated = (total_amount_cents * sh) // total_shares
        allocated_list.append((uid, allocated, sh))

    remainder = total_amount_cents - sum(amt for _, amt, _ in allocated_list)

    results: list[CalculatedSplit] = []
    for idx, (uid, amt, sh) in enumerate(allocated_list):
        extra = 1 if idx < remainder else 0
        final_amt = amt + extra
        pct = (
            (Decimal(final_amt) / Decimal(total_amount_cents)) * Decimal("100")
        ).quantize(Decimal("0.01"))
        results.append(
            CalculatedSplit(
                user_id=uid,
                amount_cents=final_amt,
                percentage=pct,
                shares=sh,
            )
        )
    return results


def calculate_splits(
    total_amount_cents: int,
    split_type: SplitType,
    participant_ids: list[uuid.UUID],
    custom_splits: list[SplitItemInput] | None = None,
    payer_id: uuid.UUID | None = None,
) -> list[CalculatedSplit]:
    """Calcola le quote garantendo l'invariante sum(splits) == total."""
    if not participant_ids:
        raise ValueError("La lista dei partecipanti non può essere vuota.")
    if total_amount_cents <= 0:
        raise ValueError("L'importo totale deve essere maggiore di 0 centesimi.")

    if split_type == SplitType.EQUAL:
        results = _calculate_equal_splits(total_amount_cents, participant_ids, payer_id)
    elif split_type == SplitType.PERCENTAGE:
        if not custom_splits:
            raise ValueError(
                "Le percentuali sono richieste per la divisione PERCENTAGE."
            )
        results = _calculate_percentage_splits(
            total_amount_cents, participant_ids, custom_splits
        )
    elif split_type == SplitType.EXACT:
        if not custom_splits:
            raise ValueError(
                "Gli importi esatti sono richiesti per la divisione EXACT."
            )
        results = _calculate_exact_splits(
            total_amount_cents, participant_ids, custom_splits
        )
    elif split_type == SplitType.SHARES:
        if not custom_splits:
            raise ValueError("Le quote sono richieste per la divisione SHARES.")
        results = _calculate_shares_splits(
            total_amount_cents, participant_ids, custom_splits
        )
    else:
        raise ValueError(f"Tipo di split non supportato: {split_type}")

    # Verifica formale dell'invariante di quadratura
    total_split = sum(r.amount_cents for r in results)
    if total_split != total_amount_cents:
        raise RuntimeError(
            f"Errore quadratura: somma ({total_split}) != totale ({total_amount_cents})"
        )

    return results
