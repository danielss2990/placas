"""API REST (JSON) consumida pelo app web/mobile."""
from __future__ import annotations

import base64
import binascii
from datetime import date

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import func, or_

from .models import Debt, DebtStatus, DebtType, Payment, PaymentStatus, RecognitionLog, Vehicle, db
from .recognition import classify, clean, decode_image, tesseract_available
from .recognition.plate_format import mercosul_to_old, old_to_mercosul
from .recognition.recognizer import OcrUnavailableError
from .services import payments as pay
from .services.debts import vehicle_summary

api = Blueprint("api", __name__)


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message, self.status = message, status


@api.errorhandler(ApiError)
def _api_error(err: ApiError):
    return jsonify({"error": err.message}), err.status


@api.errorhandler(pay.PaymentError)
def _payment_error(err):
    return jsonify({"error": str(err)}), 400


@api.errorhandler(404)
def _not_found(err):
    return jsonify({"error": "não encontrado"}), 404


# ------------------------------------------------------------------ helpers

def _json() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("corpo JSON inválido")
    return data


def _ref_date() -> date:
    raw = request.args.get("date")
    if not raw:
        return date.today()
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise ApiError("data inválida, use AAAA-MM-DD")


def find_vehicle(plate: str) -> Vehicle | None:
    """Busca pela placa; aceita a equivalente Mercosul/antiga (ABC1234 <-> ABC1C34)."""
    plate = clean(plate)
    options = {plate, mercosul_to_old(plate), old_to_mercosul(plate)}
    return Vehicle.query.filter(Vehicle.plate.in_(options)).first()


def _get_vehicle_or_404(plate: str) -> Vehicle:
    v = find_vehicle(plate)
    if not v:
        raise ApiError(f"veículo {clean(plate)} não cadastrado", 404)
    return v


def _get_payment_or_404(payment_id: int) -> Payment:
    p = db.session.get(Payment, payment_id)
    if not p:
        raise ApiError("pagamento não encontrado", 404)
    return p


def _parse_cents(data: dict) -> int:
    if "amount_cents" in data:
        value = data["amount_cents"]
    elif "amount" in data:
        try:
            value = round(float(str(data["amount"]).replace(",", ".")) * 100)
        except ValueError:
            raise ApiError("valor inválido")
    else:
        raise ApiError("informe amount (reais) ou amount_cents")
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ApiError("valor deve ser positivo")
    return value


# ------------------------------------------------------------------ geral

@api.get("/health")
def health():
    return jsonify({"status": "ok", "ocr_available": tesseract_available()})


@api.get("/stats")
def stats():
    pay.expire_stale_payments()
    today = date.today()
    open_q = Debt.query.filter(Debt.status == DebtStatus.ABERTO)
    received = db.session.query(func.coalesce(func.sum(Payment.total_cents), 0)) \
        .filter(Payment.status == PaymentStatus.APROVADO).scalar()
    by_method = dict(db.session.query(Payment.method, func.sum(Payment.total_cents))
                     .filter(Payment.status == PaymentStatus.APROVADO).group_by(Payment.method).all())
    return jsonify({
        "vehicles": Vehicle.query.count(),
        "open_debts": open_q.count(),
        "overdue_debts": open_q.filter(Debt.due_date < today).count(),
        "open_principal_cents": db.session.query(func.coalesce(func.sum(Debt.amount_cents), 0))
        .filter(Debt.status == DebtStatus.ABERTO).scalar(),
        "pending_payments": Payment.query.filter_by(status=PaymentStatus.PENDENTE).count(),
        "received_cents": received,
        "received_by_method": by_method,
        "recognitions": RecognitionLog.query.count(),
    })


# ------------------------------------------------------------------ reconhecimento

@api.post("/recognize")
def recognize():
    """Recebe uma imagem (multipart 'image' ou JSON {'image': base64/dataURL})."""
    if "image" in request.files:
        data = request.files["image"].read()
    else:
        payload = request.get_json(silent=True) or {}
        b64 = payload.get("image")
        if not b64:
            raise ApiError("envie a imagem no campo 'image'")
        if "," in b64 and b64.startswith("data:"):
            b64 = b64.split(",", 1)[1]
        try:
            data = base64.b64decode(b64, validate=False)
        except (binascii.Error, ValueError):
            raise ApiError("imagem base64 inválida")
    try:
        image = decode_image(data)
    except ValueError as exc:
        raise ApiError(str(exc))

    recognizer = current_app.extensions["plate_recognizer"]
    try:
        result = recognizer.recognize(image)
    except OcrUnavailableError as exc:
        raise ApiError(f"OCR indisponível: {exc}", 503)

    db.session.add(RecognitionLog(plate=result.plate, confidence=result.confidence,
                                  source=result.source, raw_text=result.raw_text[:500]))
    db.session.commit()

    body = {"recognition": result.to_dict(), "vehicle": None, "summary": None}
    if result.plate:
        v = find_vehicle(result.plate)
        if v:
            body["vehicle"] = v.to_dict()
            body["summary"] = vehicle_summary(v)
    return jsonify(body)


@api.get("/recognitions")
def recognitions():
    logs = RecognitionLog.query.order_by(RecognitionLog.created_at.desc()).limit(50).all()
    return jsonify([l.to_dict() for l in logs])


# ------------------------------------------------------------------ veículos

@api.get("/vehicles")
def list_vehicles():
    q = clean(request.args.get("q", ""))
    query = Vehicle.query
    if q:
        name = request.args.get("q", "").strip()
        query = query.filter(or_(Vehicle.plate.contains(q), Vehicle.owner_name.ilike(f"%{name}%")))
    vehicles = query.order_by(Vehicle.plate).limit(200).all()
    out = []
    for v in vehicles:
        d = v.to_dict()
        s = vehicle_summary(v)
        d.update(open_debts=s["count"], total_cents=s["total_cents"], overdue_count=s["overdue_count"])
        out.append(d)
    return jsonify(out)


@api.post("/vehicles")
def create_vehicle():
    data = _json()
    plate = clean(data.get("plate", ""))
    if not classify(plate):
        raise ApiError("placa inválida (formatos aceitos: ABC1234 ou ABC1D23)")
    if find_vehicle(plate):
        raise ApiError("veículo já cadastrado", 409)
    v = Vehicle(plate=plate, plate_type=classify(plate))
    _apply_vehicle_fields(v, data)
    db.session.add(v)
    db.session.commit()
    return jsonify(v.to_dict()), 201


def _apply_vehicle_fields(v: Vehicle, data: dict) -> None:
    for field in ("owner_name", "owner_document", "model", "color"):
        if field in data:
            setattr(v, field, (data[field] or "").strip() or None)
    if "year" in data:
        try:
            v.year = int(data["year"]) if data["year"] not in (None, "") else None
        except (TypeError, ValueError):
            raise ApiError("ano inválido")


@api.get("/vehicles/<plate>")
def get_vehicle(plate):
    v = _get_vehicle_or_404(plate)
    return jsonify({"vehicle": v.to_dict(), "summary": vehicle_summary(v, _ref_date()),
                    "history": [d.to_dict() for d in v.debts if d.status != DebtStatus.ABERTO]})


@api.put("/vehicles/<plate>")
def update_vehicle(plate):
    v = _get_vehicle_or_404(plate)
    _apply_vehicle_fields(v, _json())
    db.session.commit()
    return jsonify(v.to_dict())


@api.delete("/vehicles/<plate>")
def delete_vehicle(plate):
    v = _get_vehicle_or_404(plate)
    if any(p.status in (PaymentStatus.APROVADO, PaymentStatus.PENDENTE) for p in v.payments):
        raise ApiError("veículo possui pagamentos registrados e não pode ser excluído", 409)
    db.session.delete(v)
    db.session.commit()
    return "", 204


# ------------------------------------------------------------------ débitos

@api.get("/debt-types")
def debt_types():
    return jsonify(DebtType.ALL)


@api.get("/vehicles/<plate>/debts")
def vehicle_debts(plate):
    v = _get_vehicle_or_404(plate)
    return jsonify(vehicle_summary(v, _ref_date()))


@api.post("/vehicles/<plate>/debts")
def create_debt(plate):
    v = _get_vehicle_or_404(plate)
    data = _json()
    dtype = (data.get("type") or "").upper()
    if dtype not in DebtType.ALL:
        raise ApiError(f"tipo inválido; use um de {', '.join(DebtType.ALL)}")
    try:
        due = date.fromisoformat(data.get("due_date", ""))
    except ValueError:
        raise ApiError("vencimento inválido, use AAAA-MM-DD")
    debt = Debt(vehicle=v, type=dtype, description=(data.get("description") or "").strip() or None,
                amount_cents=_parse_cents(data), due_date=due)
    db.session.add(debt)
    db.session.commit()
    return jsonify(debt.to_dict()), 201


@api.delete("/debts/<int:debt_id>")
def cancel_debt(debt_id):
    debt = db.session.get(Debt, debt_id)
    if not debt:
        raise ApiError("débito não encontrado", 404)
    if debt.status != DebtStatus.ABERTO:
        raise ApiError("apenas débitos em aberto podem ser cancelados")
    if debt.pending_payment():
        raise ApiError("débito possui pagamento pendente; cancele o pagamento antes")
    debt.status = DebtStatus.CANCELADO
    db.session.commit()
    return jsonify(debt.to_dict())


# ------------------------------------------------------------------ pagamentos

@api.get("/payment-methods")
def payment_methods():
    return jsonify(pay.list_methods())


@api.post("/vehicles/<plate>/payments/simulate")
def simulate_payment(plate):
    """Simula todas as formas de pagamento para os débitos selecionados."""
    v = _get_vehicle_or_404(plate)
    data = _json()
    ids = set(data.get("debt_ids") or [])
    summary = vehicle_summary(v, _ref_date())
    selected = [d for d in summary["debts"] if d["debt_id"] in ids] if ids else summary["debts"]
    total = sum(d["total_cents"] for d in selected)
    return jsonify({"debts_total_cents": total, "debt_ids": [d["debt_id"] for d in selected],
                    "options": pay.simulate_all(total) if total else []})


@api.post("/vehicles/<plate>/payments")
def create_payment(plate):
    v = _get_vehicle_or_404(plate)
    data = _json()
    try:
        installments = int(data.get("installments", 1))
    except (TypeError, ValueError):
        raise ApiError("número de parcelas inválido")
    payment = pay.create_payment(v, list(data.get("debt_ids") or []), (data.get("method") or "").upper(),
                                 installments, payer_name=data.get("payer_name"))
    return jsonify(payment.to_dict()), 201


@api.get("/payments")
def list_payments():
    pay.expire_stale_payments()
    query = Payment.query
    if status := request.args.get("status"):
        query = query.filter(Payment.status == status.upper())
    if plate := request.args.get("plate"):
        v = find_vehicle(plate)
        query = query.filter(Payment.vehicle_id == (v.id if v else -1))
    payments = query.order_by(Payment.created_at.desc()).limit(200).all()
    return jsonify([p.to_dict() for p in payments])


@api.get("/payments/<int:payment_id>")
def get_payment(payment_id):
    pay.expire_stale_payments()
    return jsonify(_get_payment_or_404(payment_id).to_dict())


@api.post("/payments/<int:payment_id>/confirm")
def confirm_payment(payment_id):
    return jsonify(pay.confirm_payment(_get_payment_or_404(payment_id)).to_dict())


@api.post("/payments/<int:payment_id>/cancel")
def cancel_payment(payment_id):
    return jsonify(pay.cancel_payment(_get_payment_or_404(payment_id)).to_dict())


@api.post("/payments/<int:payment_id>/refund")
def refund_payment(payment_id):
    return jsonify(pay.refund_payment(_get_payment_or_404(payment_id)).to_dict())
