from datetime import date

from app.models import Debt, DebtType
from app.services.debts import calculate_debt, months_late


def make(amount=10_000, due=date(2026, 1, 10), type_=DebtType.LICENCIAMENTO):
    return Debt(id=1, type=type_, description="x", amount_cents=amount, due_date=due)


def test_months_late():
    due = date(2026, 1, 10)
    assert months_late(due, date(2026, 1, 10)) == 0
    assert months_late(due, date(2026, 1, 11)) == 1
    assert months_late(due, date(2026, 2, 10)) == 1
    assert months_late(due, date(2026, 2, 11)) == 2
    assert months_late(date(2026, 1, 31), date(2026, 2, 28)) == 1


def test_on_due_date_no_charges():
    c = calculate_debt(make(), date(2026, 1, 10))
    assert (c.days_late, c.late_fee_cents, c.interest_cents, c.total_cents) == (0, 0, 0, 10_000)


def test_overdue_late_fee_and_interest():
    c = calculate_debt(make(), date(2026, 2, 14))  # 35 dias, 2 meses
    assert c.days_late == 35
    assert c.late_fee_cents == 1_155   # 0,33% x 35 = 11,55%
    assert c.interest_cents == 200     # 1% x 2 meses
    assert c.total_cents == 11_355


def test_late_fee_capped_at_20_percent():
    c = calculate_debt(make(), date(2026, 6, 10))
    assert c.late_fee_cents == 2_000
    assert c.interest_cents == 500  # 5 meses


def test_on_time_discount_for_fines():
    c = calculate_debt(make(type_=DebtType.MULTA), date(2026, 1, 5))
    assert c.discount_cents == 2_000
    assert c.total_cents == 8_000


def test_no_discount_when_overdue():
    c = calculate_debt(make(type_=DebtType.MULTA), date(2026, 1, 11))
    assert c.discount_cents == 0
    assert c.total_cents == 10_000 + 33 + 100


def test_rounding_half_up():
    c = calculate_debt(make(amount=13_016), date(2026, 1, 20))  # 10 dias
    assert c.late_fee_cents == 430  # 13016 * 0.033 = 429.528
    assert c.interest_cents == 130  # 130.16
