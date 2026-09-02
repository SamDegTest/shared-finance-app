import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Expense, ExpenseSplit, Household, HouseholdMember, User
from app.schemas.household import (
    DebtTransferResponse,
    HouseholdBalanceResponse,
    MemberBalanceResponse,
)

if TYPE_CHECKING:
    from collections.abc import Sequence


def _compute_settlements(
    members_map: dict[uuid.UUID, str],
    net_balances: dict[uuid.UUID, int],
) -> list[DebtTransferResponse]:
    """Algoritmo greedy a due puntatori per risolvere i debiti reciproci."""
    # Lista creditori (net_balance > 0) e debitori (net_balance < 0)
    creditors: list[list[Any]] = [
        [uid, net_balances[uid]] for uid in net_balances if net_balances[uid] > 0
    ]
    debtors: list[list[Any]] = [
        [uid, -net_balances[uid]] for uid in net_balances if net_balances[uid] < 0
    ]

    settlements: list[DebtTransferResponse] = []
    c_idx = 0
    d_idx = 0

    while c_idx < len(creditors) and d_idx < len(debtors):
        creditor_id, credit_rem = creditors[c_idx]
        debtor_id, debt_rem = debtors[d_idx]

        settle_amt = min(credit_rem, debt_rem)
        if settle_amt > 0:
            settlements.append(
                DebtTransferResponse(
                    from_user_id=debtor_id,
                    from_user_name=members_map.get(debtor_id, "Utente"),
                    to_user_id=creditor_id,
                    to_user_name=members_map.get(creditor_id, "Utente"),
                    amount_cents=settle_amt,
                )
            )

        creditors[c_idx][1] -= settle_amt
        debtors[d_idx][1] -= settle_amt

        if creditors[c_idx][1] == 0:
            c_idx += 1
        if debtors[d_idx][1] == 0:
            d_idx += 1

    return settlements


async def calculate_household_balance(
    session: AsyncSession,
    household_id: uuid.UUID,
) -> HouseholdBalanceResponse:
    """Calcola il bilancio contabile e i debiti reciproci per un nucleo."""
    # 1. Recupera household e membri
    hh_stmt = select(Household).where(Household.id == household_id)
    hh_res = await session.execute(hh_stmt)
    household = hh_res.scalar_one_or_none()
    if not household:
        raise ValueError(f"Household con id '{household_id}' non trovato.")

    # 2. Recupera utenti membri del gruppo
    members_stmt = (
        select(User)
        .join(HouseholdMember, HouseholdMember.user_id == User.id)
        .where(HouseholdMember.household_id == household_id)
    )
    members_res = await session.execute(members_stmt)
    members: Sequence[User] = members_res.scalars().all()
    members_map = {m.id: m.full_name for m in members}

    # 3. Aggregazione importi pagati per utente
    paid_stmt = (
        select(
            Expense.paid_by_id,
            func.coalesce(func.sum(Expense.amount_cents), 0).label("total_paid"),
        )
        .where(Expense.household_id == household_id)
        .group_by(Expense.paid_by_id)
    )
    paid_res = await session.execute(paid_stmt)
    paid_map = {row[0]: int(row[1]) for row in paid_res.all()}

    # 4. Aggregazione quote di debito per utente
    owed_stmt = (
        select(
            ExpenseSplit.user_id,
            func.coalesce(func.sum(ExpenseSplit.amount_cents), 0).label("total_owed"),
        )
        .join(Expense, ExpenseSplit.expense_id == Expense.id)
        .where(Expense.household_id == household_id)
        .group_by(ExpenseSplit.user_id)
    )
    owed_res = await session.execute(owed_stmt)
    owed_map = {row[0]: int(row[1]) for row in owed_res.all()}

    # 5. Costruzione risposte per membro
    members_balance_response: list[MemberBalanceResponse] = []
    net_balances: dict[uuid.UUID, int] = {}
    total_expenses = 0

    for m in members:
        paid = paid_map.get(m.id, 0)
        owed = owed_map.get(m.id, 0)
        net = paid - owed
        net_balances[m.id] = net
        total_expenses += paid

        members_balance_response.append(
            MemberBalanceResponse(
                user_id=m.id,
                full_name=m.full_name,
                total_paid_cents=paid,
                total_owed_cents=owed,
                net_balance_cents=net,
            )
        )

    # 6. Calcolo trasferimenti di debito
    settlements = _compute_settlements(members_map, net_balances)

    return HouseholdBalanceResponse(
        household_id=household.id,
        currency=household.currency,
        total_expenses_cents=total_expenses,
        members=members_balance_response,
        settlements=settlements,
    )
