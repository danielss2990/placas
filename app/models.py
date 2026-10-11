"""Modelos de dados. Valores monetários são armazenados em centavos (inteiros)."""
from __future__ import annotations

from datetime import date, datetime, timezone

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class DebtType:
    IPVA = "IPVA"
    LICENCIAMENTO = "LICENCIAMENTO"
    MULTA = "MULTA"
    ESTACIONAMENTO = "ESTACIONAMENTO"
    PEDAGIO = "PEDAGIO"
    OUTROS = "OUTROS"

    ALL = [IPVA, LICENCIAMENTO, MULTA, ESTACIONAMENTO, PEDAGIO, OUTROS]


class DebtStatus:
    ABERTO = "ABERTO"
    PAGO = "PAGO"
    CANCELADO = "CANCELADO"


class PaymentStatus:
    PENDENTE = "PENDENTE"
    APROVADO = "APROVADO"
    CANCELADO = "CANCELADO"
    ESTORNADO = "ESTORNADO"


class Vehicle(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    plate = db.Column(db.String(7), unique=True, nullable=False, index=True)
    plate_type = db.Column(db.String(10))
    owner_name = db.Column(db.String(120))
    owner_document = db.Column(db.String(20))
    model = db.Column(db.String(80))
    color = db.Column(db.String(30))
    year = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=utcnow)

    debts = db.relationship("Debt", back_populates="vehicle", cascade="all, delete-orphan",
                            order_by="Debt.due_date")
    payments = db.relationship("Payment", back_populates="vehicle", cascade="all, delete-orphan",
                               order_by="Payment.created_at.desc()")

    def to_dict(self) -> dict:
        from .recognition import format_display
        return {
            "id": self.id, "plate": self.plate, "display": format_display(self.plate),
            "plate_type": self.plate_type, "owner_name": self.owner_name,
            "owner_document": self.owner_document, "model": self.model,
            "color": self.color, "year": self.year,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Debt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey("vehicle.id"), nullable=False, index=True)
    type = db.Column(db.String(20), nullable=False)
    description = db.Column(db.String(200))
    amount_cents = db.Column(db.Integer, nullable=False)
    due_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(12), default=DebtStatus.ABERTO, nullable=False)
    paid_at = db.Column(db.DateTime)
    paid_amount_cents = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=utcnow)

    vehicle = db.relationship("Vehicle", back_populates="debts")
    items = db.relationship("PaymentItem", back_populates="debt")

    def pending_payment(self) -> "Payment | None":
        for item in self.items:
            if item.payment.status == PaymentStatus.PENDENTE:
                return item.payment
        return None

    def to_dict(self) -> dict:
        pending = self.pending_payment()
        return {
            "id": self.id, "vehicle_id": self.vehicle_id, "type": self.type,
            "description": self.description, "amount_cents": self.amount_cents,
            "due_date": self.due_date.isoformat(), "status": self.status,
            "paid_at": self.paid_at.isoformat() if self.paid_at else None,
            "paid_amount_cents": self.paid_amount_cents,
            "pending_payment_id": pending.id if pending else None,
        }


class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey("vehicle.id"), nullable=False, index=True)
    method = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(12), default=PaymentStatus.PENDENTE, nullable=False)
    debts_total_cents = db.Column(db.Integer, nullable=False)   # débitos atualizados
    fee_cents = db.Column(db.Integer, default=0, nullable=False)  # tarifa do meio de pagamento
    interest_cents = db.Column(db.Integer, default=0, nullable=False)  # juros do parcelamento
    total_cents = db.Column(db.Integer, nullable=False)
    installments = db.Column(db.Integer, default=1, nullable=False)
    installment_cents = db.Column(db.Integer, nullable=False)
    reference = db.Column(db.String(40), unique=True)
    pix_payload = db.Column(db.Text)
    payer_name = db.Column(db.String(120))
    calc_date = db.Column(db.Date, nullable=False, default=date.today)
    expires_at = db.Column(db.DateTime)
    confirmed_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=utcnow)

    vehicle = db.relationship("Vehicle", back_populates="payments")
    items = db.relationship("PaymentItem", back_populates="payment", cascade="all, delete-orphan")

    def to_dict(self) -> dict:
        from .services.payments import METHODS
        return {
            "id": self.id, "vehicle_id": self.vehicle_id,
            "plate": self.vehicle.plate if self.vehicle else None,
            "method": self.method, "method_label": METHODS.get(self.method, {}).get("label", self.method),
            "status": self.status, "debts_total_cents": self.debts_total_cents,
            "fee_cents": self.fee_cents, "interest_cents": self.interest_cents,
            "total_cents": self.total_cents, "installments": self.installments,
            "installment_cents": self.installment_cents, "reference": self.reference,
            "pix_payload": self.pix_payload, "payer_name": self.payer_name,
            "calc_date": self.calc_date.isoformat() if self.calc_date else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "confirmed_at": self.confirmed_at.isoformat() if self.confirmed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "items": [i.to_dict() for i in self.items],
        }


class PaymentItem(db.Model):
    """Débito incluído num pagamento, com o valor calculado no momento da emissão."""
    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(db.Integer, db.ForeignKey("payment.id"), nullable=False, index=True)
    debt_id = db.Column(db.Integer, db.ForeignKey("debt.id"), nullable=False, index=True)
    principal_cents = db.Column(db.Integer, nullable=False)
    late_fee_cents = db.Column(db.Integer, default=0, nullable=False)
    interest_cents = db.Column(db.Integer, default=0, nullable=False)
    discount_cents = db.Column(db.Integer, default=0, nullable=False)
    total_cents = db.Column(db.Integer, nullable=False)

    payment = db.relationship("Payment", back_populates="items")
    debt = db.relationship("Debt", back_populates="items")

    def to_dict(self) -> dict:
        return {
            "debt_id": self.debt_id,
            "type": self.debt.type if self.debt else None,
            "description": self.debt.description if self.debt else None,
            "principal_cents": self.principal_cents, "late_fee_cents": self.late_fee_cents,
            "interest_cents": self.interest_cents, "discount_cents": self.discount_cents,
            "total_cents": self.total_cents,
        }


class RecognitionLog(db.Model):
    """Histórico de leituras de placas."""
    id = db.Column(db.Integer, primary_key=True)
    plate = db.Column(db.String(7), index=True)
    confidence = db.Column(db.Float)
    source = db.Column(db.String(20))
    raw_text = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "plate": self.plate, "confidence": self.confidence,
            "source": self.source, "created_at": self.created_at.isoformat() if self.created_at else None,
        }
