"""Gestão de formas de pagamento.

Meios suportados: PIX, boleto, cartão de débito, cartão de crédito (parcelado)
e dinheiro. O gateway é **simulado**: cartões e dinheiro são aprovados na hora;
PIX e boleto ficam pendentes até a confirmação (endpoint que simula o webhook
do banco/PSP). Para produção, troque ``_gateway_authorize`` pela integração real
— dados de cartão nunca devem passar por este servidor (use tokenização do PSP).
"""
from __future__ import annotations

import math
import secrets
from datetime import date, timedelta
from decimal import Decimal

from flask import current_app

from ..models import Debt, DebtStatus, Payment, PaymentItem, PaymentStatus, db, utcnow
from .debts import calculate_debt

METHODS: dict[str, dict] = {
    "PIX": {
        "label": "PIX", "fee_cents": 0, "fee_percent": Decimal(0), "max_installments": 1,
        "instant_approval": False, "expires_minutes": 30,
        "description": "QR Code / copia e cola. Confirmação em segundos.",
    },
    "BOLETO": {
        "label": "Boleto bancário", "fee_cents": 250, "fee_percent": Decimal(0), "max_installments": 1,
        "instant_approval": False, "expires_minutes": 3 * 24 * 60,
        "description": "Compensação em até 3 dias úteis. Tarifa de R$ 2,50.",
    },
    "CARTAO_DEBITO": {
        "label": "Cartão de débito", "fee_cents": 0, "fee_percent": Decimal(0), "max_installments": 1,
        "instant_approval": True,
        "description": "Débito à vista, aprovação imediata.",
    },
    "CARTAO_CREDITO": {
        "label": "Cartão de crédito", "fee_cents": 0, "fee_percent": Decimal(0), "max_installments": 12,
        "interest_free_installments": 3, "installment_interest_monthly": Decimal("0.0199"),
        "instant_approval": True,
        "description": "Até 3x sem juros; de 4x a 12x com juros de 1,99% a.m.",
    },
    "DINHEIRO": {
        "label": "Dinheiro (balcão)", "fee_cents": 0, "fee_percent": Decimal(0), "max_installments": 1,
        "instant_approval": True,
        "description": "Pagamento presencial no caixa.",
    },
}


class PaymentError(ValueError):
    pass


def list_methods() -> list[dict]:
    out = []
    for key, m in METHODS.items():
        out.append({
            "id": key, "label": m["label"], "description": m["description"],
            "fee_cents": m["fee_cents"], "fee_percent": float(m["fee_percent"]),
            "max_installments": m["max_installments"],
            "interest_free_installments": m.get("interest_free_installments", m["max_installments"]),
            "installment_interest_monthly": float(m.get("installment_interest_monthly", 0)),
            "instant_approval": m["instant_approval"],
        })
    return out


def installment_plan(amount_cents: int, method: str, installments: int) -> dict:
    """Calcula tarifa, juros de parcelamento (Tabela Price) e valor das parcelas."""
    if method not in METHODS:
        raise PaymentError(f"forma de pagamento inválida: {method}")
    m = METHODS[method]
    if not 1 <= installments <= m["max_installments"]:
        raise PaymentError(f"{m['label']} permite de 1 a {m['max_installments']} parcela(s)")

    fee = m["fee_cents"] + int((Decimal(amount_cents) * m["fee_percent"]).to_integral_value())
    base = amount_cents + fee
    rate = m.get("installment_interest_monthly", Decimal(0))
    free = m.get("interest_free_installments", m["max_installments"])

    if installments <= free or rate == 0:
        installment = math.ceil(base / installments)
        total = base
    else:
        i = float(rate)
        pmt = base * i / (1 - (1 + i) ** -installments)
        installment = math.ceil(round(pmt, 6))
        total = installment * installments

    return {
        "method": method, "installments": installments, "base_cents": amount_cents,
        "fee_cents": fee, "interest_cents": total - base,
        "total_cents": total, "installment_cents": installment,
    }


def simulate_all(amount_cents: int) -> list[dict]:
    """Todas as opções de pagamento para um valor — usado na tela de checkout."""
    options = []
    for method, m in METHODS.items():
        for n in range(1, m["max_installments"] + 1):
            options.append(installment_plan(amount_cents, method, n))
    return options


# ---------------------------------------------------------------- PIX (BR Code)

def _emv(field_id: str, value: str) -> str:
    return f"{field_id}{len(value):02d}{value}"


def _crc16(payload: str) -> str:
    crc = 0xFFFF
    for byte in payload.encode("utf-8"):
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return f"{crc:04X}"


def pix_payload(key: str, name: str, city: str, amount_cents: int, txid: str) -> str:
    """Gera o 'PIX copia e cola' (BR Code estático, padrão EMV do Banco Central)."""
    account = _emv("00", "br.gov.bcb.pix") + _emv("01", key)
    payload = (
        _emv("00", "01")
        + _emv("26", account)
        + _emv("52", "0000")
        + _emv("53", "986")
        + _emv("54", f"{amount_cents / 100:.2f}")
        + _emv("58", "BR")
        + _emv("59", name[:25])
        + _emv("60", city[:15])
        + _emv("62", _emv("05", txid[:25]))
        + "6304"
    )
    return payload + _crc16(payload)


# ------------------------------------------------------------------ operações

def _gateway_authorize(payment: Payment) -> bool:
    """Ponto de integração com o adquirente/PSP. Simulado: sempre aprova."""
    return True


def expire_stale_payments() -> int:
    now = utcnow()
    stale = Payment.query.filter(Payment.status == PaymentStatus.PENDENTE,
                                 Payment.expires_at.isnot(None), Payment.expires_at < now).all()
    for p in stale:
        p.status = PaymentStatus.CANCELADO
    if stale:
        db.session.commit()
    return len(stale)


def create_payment(vehicle, debt_ids: list[int], method: str, installments: int = 1,
                   payer_name: str | None = None, ref_date: date | None = None) -> Payment:
    expire_stale_payments()
    ref_date = ref_date or date.today()
    if not debt_ids:
        raise PaymentError("selecione ao menos um débito")

    debts = Debt.query.filter(Debt.id.in_(debt_ids), Debt.vehicle_id == vehicle.id).all()
    if len(debts) != len(set(debt_ids)):
        raise PaymentError("débito não encontrado para este veículo")
    for d in debts:
        if d.status != DebtStatus.ABERTO:
            raise PaymentError(f"débito {d.id} não está em aberto")
        pending = d.pending_payment()
        if pending:
            raise PaymentError(f"débito {d.id} já está no pagamento pendente #{pending.id}")

    calcs = [calculate_debt(d, ref_date) for d in debts]
    debts_total = sum(c.total_cents for c in calcs)
    plan = installment_plan(debts_total, method, installments)

    payment = Payment(
        vehicle_id=vehicle.id, method=method, status=PaymentStatus.PENDENTE,
        debts_total_cents=debts_total, fee_cents=plan["fee_cents"],
        interest_cents=plan["interest_cents"], total_cents=plan["total_cents"],
        installments=installments, installment_cents=plan["installment_cents"],
        reference=secrets.token_hex(8).upper(), payer_name=payer_name, calc_date=ref_date,
    )
    for d, c in zip(debts, calcs):
        payment.items.append(PaymentItem(
            debt=d, principal_cents=c.principal_cents, late_fee_cents=c.late_fee_cents,
            interest_cents=c.interest_cents, discount_cents=c.discount_cents,
            total_cents=c.total_cents,
        ))

    m = METHODS[method]
    if "expires_minutes" in m:
        payment.expires_at = utcnow() + timedelta(minutes=m["expires_minutes"])
    if method == "PIX":
        cfg = current_app.config
        payment.pix_payload = pix_payload(cfg["PIX_KEY"], cfg["PIX_MERCHANT_NAME"],
                                          cfg["PIX_MERCHANT_CITY"], payment.total_cents,
                                          payment.reference)

    db.session.add(payment)
    db.session.flush()
    if m["instant_approval"]:
        if not _gateway_authorize(payment):
            payment.status = PaymentStatus.CANCELADO
            db.session.commit()
            raise PaymentError("pagamento recusado pela operadora")
        _approve(payment)
    db.session.commit()
    return payment


def _approve(payment: Payment) -> None:
    now = utcnow()
    payment.status = PaymentStatus.APROVADO
    payment.confirmed_at = now
    payment.expires_at = None
    for item in payment.items:
        item.debt.status = DebtStatus.PAGO
        item.debt.paid_at = now
        item.debt.paid_amount_cents = item.total_cents


def confirm_payment(payment: Payment) -> Payment:
    """Confirma um PIX/boleto (simula o retorno/webhook do banco)."""
    expire_stale_payments()
    if payment.status != PaymentStatus.PENDENTE:
        raise PaymentError(f"pagamento está {payment.status}, não pode ser confirmado")
    _approve(payment)
    db.session.commit()
    return payment


def cancel_payment(payment: Payment) -> Payment:
    if payment.status != PaymentStatus.PENDENTE:
        raise PaymentError("apenas pagamentos pendentes podem ser cancelados")
    payment.status = PaymentStatus.CANCELADO
    db.session.commit()
    return payment


def refund_payment(payment: Payment) -> Payment:
    """Estorna um pagamento aprovado e reabre os débitos."""
    if payment.status != PaymentStatus.APROVADO:
        raise PaymentError("apenas pagamentos aprovados podem ser estornados")
    payment.status = PaymentStatus.ESTORNADO
    for item in payment.items:
        item.debt.status = DebtStatus.ABERTO
        item.debt.paid_at = None
        item.debt.paid_amount_cents = None
    db.session.commit()
    return payment
