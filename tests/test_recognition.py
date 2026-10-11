"""Testes do pipeline OpenCV + Tesseract em imagens sintéticas.

São ignorados automaticamente se o Tesseract não estiver instalado.
"""
import cv2
import numpy as np
import pytest

from app.recognition import PlateRecognizer, tesseract_available
from app.recognition.detector import find_candidates
from make_sample import render_plate, render_scene

needs_tesseract = pytest.mark.skipif(not tesseract_available(), reason="Tesseract não instalado")


def test_detector_finds_plate_region():
    scene = render_scene("BRA2E19")
    cands = find_candidates(scene)
    assert cands
    # A placa foi desenhada centralizada em y = 55% da altura
    x, y, w, h = cands[0].box
    assert abs((x + w / 2) - scene.shape[1] / 2) < 40
    assert 2.0 < w / h < 4.5


@needs_tesseract
@pytest.mark.parametrize("plate", ["BRA2E19", "ABC1234", "RIO4F56", "QWE9H87"])
def test_recognize_synthetic_scene(plate):
    result = PlateRecognizer().recognize(render_scene(plate, seed=1))
    assert result.plate == plate
    assert result.confidence > 0.5


@needs_tesseract
def test_recognize_with_perspective():
    scene = render_scene("PLC3A45", seed=2)
    h, w = scene.shape[:2]
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = np.float32([[40, 30], [w - 10, 0], [w - 60, h], [0, h - 20]])
    warped = cv2.warpPerspective(scene, cv2.getPerspectiveTransform(src, dst), (w, h),
                                 borderValue=(90, 100, 110))
    assert PlateRecognizer().recognize(warped).plate == "PLC3A45"


@needs_tesseract
def test_recognize_cropped_plate_only():
    plate_img = render_plate("XYZ1234")
    assert PlateRecognizer().recognize(plate_img).plate == "XYZ1234"


@needs_tesseract
def test_no_plate_in_blank_image():
    blank = np.full((480, 640, 3), 128, np.uint8)
    assert PlateRecognizer().recognize(blank).plate is None
