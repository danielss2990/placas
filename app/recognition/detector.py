"""Localização da placa na imagem usando OpenCV.

Duas estratégias complementares geram regiões candidatas:

1. **Morfologia (black-hat + gradiente)**: realça caracteres escuros sobre fundo
   claro e une-os em blocos retangulares — robusta quando a borda da placa
   não é nítida.
2. **Contornos (Canny)**: procura quadriláteros com proporção de placa —
   funciona bem quando a moldura da placa é visível.

Cada candidato é recortado (com correção de perspectiva quando há 4 vértices)
e enviado ao OCR. O candidato cuja leitura forma uma placa válida com menos
correções vence.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

# Placa brasileira de carro: 400 x 130 mm -> proporção ~3.08.
# Motos: 200 x 170 mm -> ~1.18.
MIN_ASPECT, MAX_ASPECT = 2.0, 6.5
MOTO_MIN_ASPECT, MOTO_MAX_ASPECT = 0.9, 1.5
WORK_WIDTH = 960


@dataclass
class Candidate:
    box: tuple[int, int, int, int]          # x, y, w, h na imagem original
    image: np.ndarray                        # recorte BGR (já retificado)
    source: str                              # estratégia que gerou o candidato
    quad: np.ndarray | None = field(default=None, repr=False)


def _resize(image: np.ndarray) -> tuple[np.ndarray, float]:
    h, w = image.shape[:2]
    if w <= WORK_WIDTH:
        return image, 1.0
    scale = WORK_WIDTH / w
    return cv2.resize(image, (WORK_WIDTH, int(h * scale)), interpolation=cv2.INTER_AREA), scale


def _order_points(pts: np.ndarray) -> np.ndarray:
    pts = pts.reshape(4, 2).astype("float32")
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).ravel()
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)],
                     pts[np.argmax(s)], pts[np.argmax(d)]], dtype="float32")


def warp_quad(image: np.ndarray, quad: np.ndarray) -> np.ndarray:
    """Corrige a perspectiva de um quadrilátero para um retângulo."""
    tl, tr, br, bl = _order_points(quad)
    width = int(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl)))
    height = int(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl)))
    width, height = max(width, 1), max(height, 1)
    dst = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype="float32")
    matrix = cv2.getPerspectiveTransform(np.array([tl, tr, br, bl]), dst)
    return cv2.warpPerspective(image, matrix, (width, height))


def _aspect_ok(w: int, h: int, allow_moto: bool) -> bool:
    if h == 0:
        return False
    ar = w / h
    if MIN_ASPECT <= ar <= MAX_ASPECT:
        return True
    return allow_moto and MOTO_MIN_ASPECT <= ar <= MOTO_MAX_ASPECT


def _morphology_regions(gray: np.ndarray, allow_moto: bool) -> list[tuple[int, int, int, int]]:
    h_img, w_img = gray.shape
    rect_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (13, 5))
    regions = []
    # Black-hat realça texto escuro em fundo claro; top-hat o inverso.
    for op in (cv2.MORPH_BLACKHAT, cv2.MORPH_TOPHAT):
        hat = cv2.morphologyEx(gray, op, rect_kernel)
        grad = cv2.Sobel(hat, cv2.CV_32F, 1, 0, ksize=-1)
        grad = np.absolute(grad)
        grad = cv2.normalize(grad, None, 0, 255, cv2.NORM_MINMAX).astype("uint8")
        grad = cv2.GaussianBlur(grad, (5, 5), 0)
        grad = cv2.morphologyEx(grad, cv2.MORPH_CLOSE, rect_kernel)
        _, thresh = cv2.threshold(grad, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
        thresh = cv2.erode(thresh, None, iterations=2)
        thresh = cv2.dilate(thresh, None, iterations=2)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in sorted(contours, key=cv2.contourArea, reverse=True)[:10]:
            x, y, w, h = cv2.boundingRect(c)
            if w < w_img * 0.05 or h < 15 or not _aspect_ok(w, h, allow_moto):
                continue
            regions.append((x, y, w, h))
    return regions


def _contour_quads(gray: np.ndarray, allow_moto: bool) -> list[np.ndarray]:
    h_img, w_img = gray.shape
    blurred = cv2.bilateralFilter(gray, 11, 17, 17)
    edged = cv2.Canny(blurred, 30, 200)
    contours, _ = cv2.findContours(edged, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    quads = []
    for c in sorted(contours, key=cv2.contourArea, reverse=True)[:30]:
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        if len(approx) != 4:
            continue
        x, y, w, h = cv2.boundingRect(approx)
        if w < w_img * 0.05 or w > w_img * 0.98 or not _aspect_ok(w, h, allow_moto):
            continue
        quads.append(approx)
    return quads


def _iou(a, b) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    union = aw * ah + bw * bh - inter
    return inter / union if union else 0.0


def find_candidates(image: np.ndarray, max_candidates: int = 12, allow_moto: bool = True) -> list[Candidate]:
    """Retorna regiões candidatas a placa, da mais para a menos provável."""
    if image is None or image.size == 0:
        return []
    small, scale = _resize(image)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

    candidates: list[Candidate] = []
    boxes: list[tuple[int, int, int, int]] = []

    def add(box_small, source, quad_small=None):
        x, y, w, h = box_small
        box = tuple(int(round(v / scale)) for v in (x, y, w, h))
        if any(_iou(box, b) > 0.6 for b in boxes):
            return
        if quad_small is not None:
            quad = (quad_small.reshape(4, 2) / scale).astype("float32")
            crop = warp_quad(image, quad)
        else:
            quad = None
            # Pequena margem para não cortar caracteres das bordas
            mx, my = int(box[2] * 0.04), int(box[3] * 0.12)
            x0, y0 = max(0, box[0] - mx), max(0, box[1] - my)
            x1 = min(image.shape[1], box[0] + box[2] + mx)
            y1 = min(image.shape[0], box[1] + box[3] + my)
            crop = image[y0:y1, x0:x1]
        if crop.size == 0:
            return
        boxes.append(box)
        candidates.append(Candidate(box=box, image=crop, source=source, quad=quad))

    for quad in _contour_quads(gray, allow_moto):
        add(cv2.boundingRect(quad), "contorno", quad)
    for box in _morphology_regions(gray, allow_moto):
        add(box, "morfologia")

    return candidates[:max_candidates]


def _binarize(gray: np.ndarray) -> np.ndarray:
    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    # Tesseract prefere texto escuro em fundo claro
    if np.mean(otsu) < 127:
        otsu = cv2.bitwise_not(otsu)
    return otsu


def character_band(binary: np.ndarray) -> tuple[int, int, int, int] | None:
    """Encontra a faixa onde estão os caracteres grandes da placa.

    Remove moldura, faixa azul "BRASIL", nome da cidade e parafusos, que
    atrapalham o OCR. Retorna (x0, y0, x1, y1) ou None se não houver
    caracteres suficientes.
    """
    chars = segment_characters(binary)
    if len(chars) < 6:
        return None
    # Agrupa por altura semelhante: os 7 caracteres da placa têm a mesma altura.
    heights = np.array([h for _, _, _, h in chars])
    ref = np.median(heights)
    group = [c for c in chars if 0.75 * ref <= c[3] <= 1.3 * ref]
    if len(group) < 6:  # placa tem 7 caracteres; tolera 1 perdido/colado
        return None
    x0 = min(c[0] for c in group)
    y0 = min(c[1] for c in group)
    x1 = max(c[0] + c[2] for c in group)
    y1 = max(c[1] + c[3] for c in group)
    pad = int(ref * 0.15)
    h, w = binary.shape
    return max(0, x0 - pad), max(0, y0 - pad), min(w, x1 + pad), min(h, y1 + pad)


def preprocess_for_ocr(plate_img: np.ndarray) -> list[np.ndarray]:
    """Gera variações binarizadas do recorte para aumentar a chance de acerto do OCR."""
    gray = cv2.cvtColor(plate_img, cv2.COLOR_BGR2GRAY) if plate_img.ndim == 3 else plate_img
    target_h = 120
    h, w = gray.shape
    if h == 0 or w == 0:
        return []
    gray = cv2.resize(gray, (max(1, int(w * target_h / h)), target_h), interpolation=cv2.INTER_CUBIC)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)

    otsu = _binarize(blur)
    adaptive = cv2.adaptiveThreshold(blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                     cv2.THRESH_BINARY, 31, 10)
    variants = []
    band = character_band(otsu)
    if band:
        x0, y0, x1, y1 = band
        focused = blur[y0:y1, x0:x1]
        scale = target_h / max(1, focused.shape[0])
        focused = cv2.resize(focused, (max(1, int(focused.shape[1] * scale)), target_h),
                             interpolation=cv2.INTER_CUBIC)
        variants.append(_binarize(focused))
    variants += [otsu, adaptive, gray]
    return [cv2.copyMakeBorder(v, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255) for v in variants]


def segment_characters(binary: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Segmenta caracteres (componentes conectados) de uma placa binarizada.

    Útil para depuração e para desenhar as caixas de cada caractere na interface.
    """
    inv = cv2.bitwise_not(binary)
    n, _, stats, _ = cv2.connectedComponentsWithStats(inv, connectivity=8)
    h_img = binary.shape[0]
    chars = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if 0.3 * h_img <= h <= 0.95 * h_img and 0.1 <= w / h <= 1.2 and area > 30:
            chars.append((int(x), int(y), int(w), int(h)))
    return sorted(chars, key=lambda b: b[0])
