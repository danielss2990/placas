import io
from datetime import date, timedelta

import cv2

from make_sample import render_scene


def _vehicle(client, plate="BRA2E19"):
    r = client.post("/api/vehicles", json={"plate": plate, "owner_name": "Teste", "model": "Carro"})
    assert r.status_code == 201, r.get_json()
    return r.get_json()


def _debt(client, plate, amount="100,00", due=None, type_="LICENCIAMENTO"):
    due = due or date.today().isoformat()
    r = client.post(f"/api/vehicles/{plate}/debts", json={"type": type_, "amount": amount, "due_date": due})
    assert r.status_code == 201, r.get_json()
    return r.get_json()


def test_health(client):
    assert client.get("/api/health").get_json()["status"] == "ok"


def test_index_and_pwa_assets(client):
    assert client.get("/").status_code == 200
    assert client.get("/manifest.webmanifest").status_code == 200
    assert client.get("/sw.js").status_code == 200


def test_vehicle_crud_and_validation(client):
    assert client.post("/api/vehicles", json={"plate": "XX12"}).status_code == 400
    _vehicle(client, "abc-1234")
    assert client.post("/api/vehicles", json={"plate": "ABC1234"}).status_code == 409
    # Busca pela equivalente Mercosul
    r = client.get("/api/vehicles/ABC1C34")
    assert r.status_code == 200 and r.get_json()["vehicle"]["plate"] == "ABC1234"
    r = client.put("/api/vehicles/ABC1234", json={"color": "Azul", "year": "2020"})
    assert r.get_json()["color"] == "Azul" and r.get_json()["year"] == 2020
    assert client.get("/api/vehicles?q=abc").get_json()[0]["plate"] == "ABC1234"
    assert client.delete("/api/vehicles/ABC1234").status_code == 204
    assert client.get("/api/vehicles/ABC1234").status_code == 404


def test_debt_summary_with_ref_date(client):
    _vehicle(client)
    _debt(client, "BRA2E19", "100,00", "2026-01-10")
    s = client.get("/api/vehicles/BRA2E19/debts?date=2026-02-14").get_json()
    assert s["total_cents"] == 11_355
    assert s["overdue_count"] == 1


def test_debt_validation(client):
    _vehicle(client)
    bad = [{"type": "XX", "amount": 1, "due_date": "2026-01-01"},
           {"type": "IPVA", "amount": "-5", "due_date": "2026-01-01"},
           {"type": "IPVA", "amount": "10", "due_date": "ontem"},
           {"type": "IPVA", "amount_cents": True, "due_date": "2026-01-01"}]
    for body in bad:
        assert client.post("/api/vehicles/BRA2E19/debts", json=body).status_code == 400


def test_pix_flow_pending_then_confirm(client):
    _vehicle(client)
    d1 = _debt(client, "BRA2E19", "50,00")
    d2 = _debt(client, "BRA2E19", "30,00")

    sim = client.post("/api/vehicles/BRA2E19/payments/simulate", json={"debt_ids": [d1["id"]]}).get_json()
    assert sim["debts_total_cents"] == 5_000
    assert {o["method"] for o in sim["options"]} >= {"PIX", "BOLETO", "CARTAO_CREDITO"}

    r = client.post("/api/vehicles/BRA2E19/payments", json={"debt_ids": [d1["id"], d2["id"]], "method": "pix"})
    assert r.status_code == 201
    p = r.get_json()
    assert p["status"] == "PENDENTE" and p["total_cents"] == 8_000 and p["pix_payload"]

    # Débito reservado não pode entrar em outro pagamento
    r = client.post("/api/vehicles/BRA2E19/payments", json={"debt_ids": [d1["id"]], "method": "PIX"})
    assert r.status_code == 400

    p = client.post(f"/api/payments/{p['id']}/confirm").get_json()
    assert p["status"] == "APROVADO"
    summary = client.get("/api/vehicles/BRA2E19/debts").get_json()
    assert summary["count"] == 0 and summary["paid_count"] == 2

    # Estorno reabre os débitos
    assert client.post(f"/api/payments/{p['id']}/refund").get_json()["status"] == "ESTORNADO"
    assert client.get("/api/vehicles/BRA2E19/debts").get_json()["count"] == 2


def test_credit_card_installments_instant_approval(client):
    _vehicle(client)
    d = _debt(client, "BRA2E19", "1000,00")
    r = client.post("/api/vehicles/BRA2E19/payments",
                    json={"debt_ids": [d["id"]], "method": "CARTAO_CREDITO", "installments": 12})
    p = r.get_json()
    assert p["status"] == "APROVADO"
    assert p["installments"] == 12 and p["interest_cents"] > 0
    assert client.get("/api/stats").get_json()["received_cents"] == p["total_cents"]
    # Débito já pago não pode ser pago de novo
    r = client.post("/api/vehicles/BRA2E19/payments", json={"debt_ids": [d["id"]], "method": "PIX"})
    assert r.status_code == 400


def test_cancel_pending_frees_debt(client):
    _vehicle(client)
    d = _debt(client, "BRA2E19")
    p = client.post("/api/vehicles/BRA2E19/payments", json={"debt_ids": [d["id"]], "method": "BOLETO"}).get_json()
    assert p["fee_cents"] == 250
    assert client.delete(f"/api/debts/{d['id']}").status_code == 400  # tem pagamento pendente
    assert client.post(f"/api/payments/{p['id']}/cancel").get_json()["status"] == "CANCELADO"
    assert client.post(f"/api/payments/{p['id']}/confirm").status_code == 400
    r = client.post("/api/vehicles/BRA2E19/payments", json={"debt_ids": [d["id"]], "method": "PIX"})
    assert r.status_code == 201


def test_payment_rejects_other_vehicle_debt(client):
    _vehicle(client, "BRA2E19")
    _vehicle(client, "ABC1234")
    d = _debt(client, "ABC1234")
    r = client.post("/api/vehicles/BRA2E19/payments", json={"debt_ids": [d["id"]], "method": "PIX"})
    assert r.status_code == 400


def test_recognize_endpoint_returns_vehicle(client):
    _vehicle(client)
    _debt(client, "BRA2E19", "10,00")
    ok, buf = cv2.imencode(".jpg", render_scene("BRA2E19"))
    r = client.post("/api/recognize", data={"image": (io.BytesIO(buf.tobytes()), "car.jpg")},
                    content_type="multipart/form-data")
    body = r.get_json()
    assert r.status_code == 200
    assert body["recognition"]["plate"] == "BRA2E19"
    assert body["vehicle"]["plate"] == "BRA2E19"
    assert body["summary"]["total_cents"] == 1_000
    assert client.get("/api/recognitions").get_json()[0]["plate"] == "BRA2E19"


def test_recognize_invalid_image(client):
    r = client.post("/api/recognize", data={"image": (io.BytesIO(b"not an image"), "x.jpg")},
                    content_type="multipart/form-data")
    assert r.status_code == 400
