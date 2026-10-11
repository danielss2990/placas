"""Pipeline completo de reconhecimento: imagem -> placa.

    imagem -> candidatos (OpenCV) -> pré-processamento -> OCR -> correção por posição

O motor de OCR padrão é o Tesseract (via pytesseract). Qualquer função
``Callable[[np.ndarray], str]`` pode ser injetada em ``PlateRecognizer`` para
trocar o motor (ex.: EasyOCR, um modelo próprio, ou um stub nos testes).
"""
from __future__ import annotations

import base64
import shutil
from dataclasses import dataclass, asdict
from typing import Callable

import cv2
import numpy as np

from . import plate_format
from .detector import find_candidates, preprocess_for_ocr

OcrEngine = Callable[[np.ndarray], str]

WHITELIST = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


class OcrUnavailableError(RuntimeError):
    pass


def tesseract_available() -> bool:
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        return False
    return shutil.which("tesseract") is not None


def tesseract_engine(image: np.ndarray) -> str:
    """OCR com Tesseract. Lê como linha única (psm 7) e bloco (psm 6)."""
    try:
        import pytesseract
    except ImportError as exc:  # pragma: no cover - depende do ambiente
        raise OcrUnavailableError("pytesseract não instalado") from exc
    if shutil.which("tesseract") is None:
        raise OcrUnavailableError("binário 'tesseract' não encontrado no PATH")
    texts = []
    for psm in (7, 6):
        config = f"--oem 3 --psm {psm} -c tessedit_char_whitelist={WHITELIST}"
        texts.append(pytesseract.image_to_string(image, config=config))
    return "\n".join(texts)


@dataclass
class RecognitionResult:
    plate: str | None
    plate_type: str | None
    confidence: float
    raw_text: str
    box: tuple[int, int, int, int] | None
    source: str | None
    crop_png_base64: str | None = None
    annotated_png_base64: str | None = None

    def to_dict(self) -> dict:
        data = asdict(self)
        data["display"] = plate_format.format_display(self.plate) if self.plate else None
        return data


def _encode_png(image: np.ndarray) -> str:
    ok, buf = cv2.imencode(".png", image)
    return base64.b64encode(buf.tobytes()).decode("ascii") if ok else ""


def _score(changes: int, raw: str) -> float:
    """Confiança heurística: penaliza correções e lixo extra no texto lido."""
    noise = max(0, len(plate_format.clean(raw)) - plate_format.PLATE_LENGTH)
    return round(max(0.05, 1.0 - 0.15 * changes - 0.01 * noise), 2)


class PlateRecognizer:
    def __init__(self, ocr_engine: OcrEngine | None = None):
        self.ocr_engine = ocr_engine or tesseract_engine

    def _read(self, crop: np.ndarray) -> tuple[str | None, int, str]:
        best_plate, best_changes, texts = None, 10**6, []
        for variant in preprocess_for_ocr(crop):
            text = self.ocr_engine(variant)
            texts.append(text.strip())
            plate, changes = plate_format.extract_plate(text)
            if plate and changes < best_changes:
                best_plate, best_changes = plate, changes
                if changes == 0:
                    break
        return best_plate, best_changes, " | ".join(t for t in texts if t)

    def recognize(self, image: np.ndarray, with_images: bool = True) -> RecognitionResult:
        if image is None or image.size == 0:
            raise ValueError("imagem inválida")

        candidates = find_candidates(image)
        best: RecognitionResult | None = None
        best_changes = 10**6
        raw_texts = []

        for cand in candidates:
            plate, changes, raw = self._read(cand.image)
            raw_texts.append(raw)
            if plate and changes < best_changes:
                best_changes = changes
                best = RecognitionResult(
                    plate=plate, plate_type=plate_format.classify(plate),
                    confidence=_score(changes, raw), raw_text=raw,
                    box=cand.box, source=cand.source,
                    crop_png_base64=_encode_png(cand.image) if with_images else None,
                )
                if changes == 0:
                    break

        # A foto pode já ser um recorte da placa: tenta a imagem inteira também.
        if best_changes > 0:
            plate, changes, raw = self._read(image)
            raw_texts.append(raw)
            if plate and changes < best_changes:
                h, w = image.shape[:2]
                best = RecognitionResult(
                    plate=plate, plate_type=plate_format.classify(plate),
                    confidence=round(_score(changes, raw) * 0.9, 2), raw_text=raw,
                    box=(0, 0, w, h), source="imagem_inteira",
                    crop_png_base64=_encode_png(image) if with_images else None,
                )

        if best is None:
            return RecognitionResult(None, None, 0.0, " | ".join(t for t in raw_texts if t), None, None)

        if with_images and best.box:
            annotated = image.copy()
            x, y, w, h = best.box
            thickness = max(2, image.shape[1] // 300)
            cv2.rectangle(annotated, (x, y), (x + w, y + h), (0, 200, 0), thickness)
            cv2.putText(annotated, best.plate, (x, max(20, y - 10)), cv2.FONT_HERSHEY_SIMPLEX,
                        max(0.6, image.shape[1] / 900), (0, 200, 0), thickness)
            best.annotated_png_base64 = _encode_png(annotated)
        return best


def decode_image(data: bytes) -> np.ndarray:
    arr = np.frombuffer(data, dtype=np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("não foi possível decodificar a imagem enviada")
    return image
