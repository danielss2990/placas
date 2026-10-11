import pytest

from app.services import payments as pay


def test_crc16_ccitt_false():
    assert pay._crc16("123456789") == "29B1"


def test_pix_payload_structure():
    payload = pay.pix_payload("chave@exemplo.com", "LOJA TESTE", "SAO PAULO", 12_345, "REF123")
    assert payload.startswith("000201")
    assert "br.gov.bcb.pix" in payload
    assert "5406123.45" in payload
    assert payload[-8:-4] == "6304"
    assert pay._crc16(payload[:-4]) == payload[-4:]


def test_plan_pix_no_fee():
    p = pay.installment_plan(10_000, "PIX", 1)
    assert p["total_cents"] == 10_000 and p["fee_cents"] == 0


def test_plan_boleto_fee():
    p = pay.installment_plan(10_000, "BOLETO", 1)
    assert p["fee_cents"] == 250 and p["total_cents"] == 10_250


def test_plan_credit_interest_free():
    p = pay.installment_plan(10_000, "CARTAO_CREDITO", 3)
    assert p["interest_cents"] == 0
    assert p["installment_cents"] == 3_334
    assert p["total_cents"] == 10_000


def test_plan_credit_with_interest_price_table():
    p = pay.installment_plan(100_000, "CARTAO_CREDITO", 12)
    # PMT(1,99%, 12, 1000) = 94,5015 -> arredondado para cima: 94,51
    assert p["installment_cents"] == 9_451
    assert p["total_cents"] == 9_451 * 12
    assert p["interest_cents"] == 9_451 * 12 - 100_000


@pytest.mark.parametrize("method,n", [("PIX", 2), ("CARTAO_CREDITO", 13), ("CARTAO_CREDITO", 0), ("FOO", 1)])
def test_plan_invalid(method, n):
    with pytest.raises(pay.PaymentError):
        pay.installment_plan(10_000, method, n)
