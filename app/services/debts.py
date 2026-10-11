"""Cálculo do débito atualizado de cada veículo.

Regras padrão (todas configuráveis via ``DebtRules``):

* **Multa de mora**: 0,33% ao dia de atraso, limitada a 20% do principal.
* **Juros de mora**: 1% ao mês ou fração de atraso, juros simples sobre o principal.
* **Desconto por pagamento em dia**: aplicado somente até o vencimento,
  por tipo de débito (ex.: 20% para multas de trânsito, 3% para IPVA à vista).

Todos os valores são inteiros em centavos; o arredondamento é feito com
ROUND_HALF_UP a cada componente, como em guias de recolhimento.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from ..models import Debt, DebtStatus, DebtType


@dataclass(frozen=True)
class DebtRules:
    late_fee_daily: Decimal = Decimal("0.0033")
    late_fee_cap: Decimal = Decimal("0.20")
    interest_monthly: Decimal = Decimal("0.01")
    on_time_discount: dict = field(default_factory=lambda: {
        DebtType.MULTA: Decimal("0.20"),
        DebtType.IPVA: Decimal("0.03"),
    })
    # Tipos sobre os quais não incidem encargos de atraso (ex.: tarifas privadas).
    no_charges_types: frozenset = frozenset()


DEFAULT_RULES = DebtRules()


def _cents(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def months_late(due: date, ref: date) -> int:
    """Meses ou fração de atraso (1 dia de atraso = 1 mês)."""
    if ref <= due:
        return 0
    months = (ref.year - due.year) * 12 + (ref.month - due.month)
    if ref.day > due.day:
        months += 1
    return max(months, 1)


@dataclass
class DebtCalculation:
    debt_id: int | None
    type: str
    description: str | None
    due_date: str
    principal_cents: int
    days_late: int
    months_late: int
    late_fee_cents: int
    interest_cents: int
    discount_cents: int
    total_cents: int

    def to_dict(self) -> dict:
        return asdict(self)


def calculate_debt(debt: Debt, ref_date: date | None = None, rules: DebtRules = DEFAULT_RULES) -> DebtCalculation:
    ref_date = ref_date or date.today()
    principal = Decimal(debt.amount_cents)
    days = max(0, (ref_date - debt.due_date).days)
    months = months_late(debt.due_date, ref_date)

    late_fee = interest = discount = Decimal(0)
    if days > 0 and debt.type not in rules.no_charges_types:
        late_fee = principal * min(rules.late_fee_daily * days, rules.late_fee_cap)
        interest = principal * rules.interest_monthly * months
    elif days == 0:
        discount = principal * rules.on_time_discount.get(debt.type, Decimal(0))

    late_fee_c, interest_c, discount_c = _cents(late_fee), _cents(interest), _cents(discount)
    total = debt.amount_cents + late_fee_c + interest_c - discount_c
    return DebtCalculation(
        debt_id=debt.id, type=debt.type, description=debt.description,
        due_date=debt.due_date.isoformat(), principal_cents=debt.amount_cents,
        days_late=days, months_late=months, late_fee_cents=late_fee_c,
        interest_cents=interest_c, discount_cents=discount_c, total_cents=total,
    )


def vehicle_summary(vehicle, ref_date: date | None = None, rules: DebtRules = DEFAULT_RULES) -> dict:
    """Resumo consolidado dos débitos em aberto de um veículo."""
    ref_date = ref_date or date.today()
    open_debts = [d for d in vehicle.debts if d.status == DebtStatus.ABERTO]
    calcs = []
    for d in open_debts:
        c = calculate_debt(d, ref_date, rules).to_dict()
        pending = d.pending_payment()
        c["pending_payment_id"] = pending.id if pending else None
        calcs.append(c)

    def total(key):
        return sum(c[key] for c in calcs)

    by_type: dict[str, int] = {}
    for c in calcs:
        by_type[c["type"]] = by_type.get(c["type"], 0) + c["total_cents"]

    return {
        "ref_date": ref_date.isoformat(),
        "debts": calcs,
        "count": len(calcs),
        "overdue_count": sum(1 for c in calcs if c["days_late"] > 0),
        "principal_cents": total("principal_cents"),
        "late_fee_cents": total("late_fee_cents"),
        "interest_cents": total("interest_cents"),
        "discount_cents": total("discount_cents"),
        "total_cents": total("total_cents"),
        "by_type": by_type,
        "paid_count": sum(1 for d in vehicle.debts if d.status == DebtStatus.PAGO),
    }
