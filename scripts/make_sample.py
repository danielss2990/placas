"""Gera imagens sintéticas de veículos com placa para testes e demonstração.

Uso: python scripts/make_sample.py ABC1D23 saida.jpg
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]


def _font(size: int):
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def render_plate(text: str, width: int = 400, height: int = 130) -> np.ndarray:
    """Desenha uma placa no estilo Mercosul (faixa azul + texto preto)."""
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, width - 1, height - 1], outline="black", width=4)
    draw.rectangle([4, 4, width - 5, 28], fill=(0, 51, 153))
    draw.text((width // 2, 16), "BRASIL", fill="white", font=_font(16), anchor="mm")
    draw.text((width // 2, 80), text, fill="black", font=_font(66), anchor="mm")
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def render_scene(text: str, seed: int = 0, size=(1280, 720)) -> np.ndarray:
    """Coloca a placa em um 'carro' simples, com fundo e ruído."""
    rng = np.random.default_rng(seed)
    w, h = size
    scene = np.full((h, w, 3), (90, 100, 110), np.uint8)
    cv2.rectangle(scene, (0, int(h * 0.75)), (w, h), (60, 60, 60), -1)              # asfalto
    cv2.rectangle(scene, (int(w * .2), int(h * .25)), (int(w * .8), int(h * .8)), (30, 30, 150), -1)  # carro
    cv2.rectangle(scene, (int(w * .27), int(h * .3)), (int(w * .73), int(h * .45)), (40, 40, 40), -1)  # vidro
    plate = render_plate(text)
    ph, pw = plate.shape[:2]
    x, y = (w - pw) // 2, int(h * .55)
    scene[y:y + ph, x:x + pw] = plate
    noise = rng.normal(0, 6, scene.shape).astype(np.int16)
    return np.clip(scene.astype(np.int16) + noise, 0, 255).astype(np.uint8)


if __name__ == "__main__":
    plate = sys.argv[1] if len(sys.argv) > 1 else "BRA2E19"
    out = sys.argv[2] if len(sys.argv) > 2 else f"{plate}.jpg"
    cv2.imwrite(out, render_scene(plate))
    print(f"imagem gerada: {out}")
