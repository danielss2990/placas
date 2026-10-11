import pytest

from app.recognition import plate_format as pf


@pytest.mark.parametrize("plate,kind", [
    ("ABC1234", "antiga"), ("abc-1234", "antiga"), ("BRA2E19", "mercosul"),
    ("ABC12345", None), ("AB12345", None), ("1BC1234", None), ("", None),
])
def test_classify(plate, kind):
    assert pf.classify(plate) == kind


@pytest.mark.parametrize("raw,expected", [
    ("8RA2E19", "BRA2E19"),   # 8 -> B na posição de letra
    ("BRAZE19", "BRA2E19"),   # Z -> 2 na posição de dígito
    ("ABC1Z3O", "ABC1Z30"),   # O -> 0 nas posições finais
    ("A8C0OOO", "ABC0O00"),
])
def test_correct_by_position(raw, expected):
    plate, changes = pf.correct(raw)
    assert plate == expected
    assert changes >= 1
    assert pf.is_valid(plate)


def test_extract_plate_ignores_header_noise():
    plate, changes = pf.extract_plate("BRASIL\nBRA2E19\n")
    assert plate == "BRA2E19" and changes == 0


def test_extract_plate_prefers_fewer_corrections():
    plate, _ = pf.extract_plate("SAO PAULO SP ABC1234")
    assert plate == "ABC1234"


def test_extract_plate_none():
    assert pf.extract_plate("XYZ")[0] is None


def test_conversion_mercosul_old():
    assert pf.mercosul_to_old("ABC1C34") == "ABC1234"
    assert pf.old_to_mercosul("ABC1234") == "ABC1C34"
    assert pf.mercosul_to_old("ABC1Z34") == "ABC1Z34"  # sem equivalente
    assert pf.format_display("ABC1234") == "ABC-1234"
