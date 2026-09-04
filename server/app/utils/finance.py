from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal

CENTS_UNIT = Decimal("0.01")


def cents_to_decimal(cents: int) -> Decimal:
    """Converte un importo intero in centesimi in Decimal quantizzato a 2 decimali."""
    return (Decimal(cents) / Decimal("100")).quantize(CENTS_UNIT)


def decimal_to_cents(amount: Decimal | str | int) -> int:
    """Converte un importo monetario in interi in centesimi (es. 10.50 -> 1050)."""
    dec_amount = Decimal(str(amount)) if not isinstance(amount, Decimal) else amount
    return int(
        (dec_amount * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )


def calculate_precise_splits_cents[T](
    total_cents: int,
    participant_ids: Sequence[T],
    payer_id: T | None = None,
) -> dict[T, int]:
    """Suddivide un importo in centesimi allocando deterministicamente il resto."""
    if not participant_ids:
        raise ValueError("La lista dei partecipanti non può essere vuota.")
    if total_cents < 0:
        raise ValueError("L'importo totale in centesimi non può essere negativo.")

    n = len(participant_ids)
    if n == 0:
        raise ValueError("La lista dei partecipanti non può essere vuota.")

    base_cents = total_cents // n
    remainder_cents = total_cents % n

    # Ordina i partecipanti posizionando per primo il pagatore originario se presente
    if payer_id is not None and payer_id in participant_ids:
        ordered_for_remainder = [payer_id] + [
            uid for uid in participant_ids if uid != payer_id
        ]
    else:
        ordered_for_remainder = list(participant_ids)

    # Identifica l'insieme di utenti che ricevono il centesimo di scarto
    recipients_of_extra = set(ordered_for_remainder[:remainder_cents])

    results: dict[T, int] = {}
    for uid in participant_ids:
        extra = 1 if uid in recipients_of_extra else 0
        results[uid] = base_cents + extra

    # Verifica formale di quadratura contabile
    total_split = sum(results.values())
    if total_split != total_cents:
        raise RuntimeError(
            f"Errore quadratura centesimi: somma calcolata ({total_split}) != "
            f"totale atteso ({total_cents})"
        )

    return results


def calculate_precise_splits[T](
    total_amount: Decimal,
    participant_ids: Sequence[T],
    payer_id: T | None = None,
) -> dict[T, Decimal]:
    """Calcola le quote monetarie spettanti garantendo sum(splits) == total_amount."""
    if not participant_ids:
        raise ValueError("La lista dei partecipanti non può essere vuota.")

    dec_amount = (
        Decimal(str(total_amount))
        if not isinstance(total_amount, Decimal)
        else total_amount
    )

    if dec_amount < Decimal("0.00"):
        raise ValueError("L'importo totale non può essere negativo.")

    target_total = dec_amount.quantize(CENTS_UNIT)
    total_cents = decimal_to_cents(target_total)

    splits_cents = calculate_precise_splits_cents(
        total_cents=total_cents,
        participant_ids=participant_ids,
        payer_id=payer_id,
    )

    splits_decimal: dict[T, Decimal] = {
        uid: cents_to_decimal(cents) for uid, cents in splits_cents.items()
    }

    # Verifica formale dell'invariante: somma delle quote == totale in ingresso
    sum_splits = sum(splits_decimal.values())
    if sum_splits != target_total:
        raise RuntimeError(
            f"Errore quadratura monetaria: somma quote ({sum_splits}) != "
            f"totale ({target_total})"
        )

    return splits_decimal
