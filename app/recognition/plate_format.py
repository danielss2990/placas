"""Regras de formato das placas brasileiras.

Formatos suportados:
  * Antigo (cinza):  LLL NNNN  -> ex.: ABC1234
  * Mercosul:        LLL N L NN -> ex.: ABC1D23

O OCR frequentemente confunde caracteres parecidos (0/O, 1/I, 8/B...).
Como a posição de cada caractere define se ele deve ser letra ou número,
corrigimos as confusões de acordo com a posição.
"""
from __future__ import annotations

import re

OLD_PATTERN = re.compile(r"^[A-Z]{3}[0-9]{4}$")
MERCOSUL_PATTERN = re.compile(r"^[A-Z]{3}[0-9][A-Z][0-9]{2}$")

# Dígito lido onde deveria haver letra
DIGIT_TO_LETTER = {
    "0": "O", "1": "I", "2": "Z", "3": "B", "4": "A",
    "5": "S", "6": "G", "7": "T", "8": "B", "9": "G",
}
# Letra lida onde deveria haver dígito
LETTER_TO_DIGIT = {
    "O": "0", "Q": "0", "D": "0", "U": "0", "I": "1", "L": "1", "J": "1",
    "T": "7", "Z": "2", "S": "5", "B": "8", "G": "6", "A": "4", "E": "8",
}

PLATE_LENGTH = 7


def clean(text: str) -> str:
    """Remove tudo que não é letra/dígito e converte para maiúsculas."""
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


def classify(plate: str) -> str | None:
    """Retorna 'mercosul', 'antiga' ou None se o texto não for uma placa válida."""
    plate = clean(plate)
    if MERCOSUL_PATTERN.match(plate):
        return "mercosul"
    if OLD_PATTERN.match(plate):
        return "antiga"
    return None


def is_valid(plate: str) -> bool:
    return classify(plate) is not None


def _as_letter(ch: str) -> str:
    return ch if ch.isalpha() else DIGIT_TO_LETTER.get(ch, ch)


def _as_digit(ch: str) -> str:
    return ch if ch.isdigit() else LETTER_TO_DIGIT.get(ch, ch)


def correct(candidate: str) -> tuple[str, int]:
    """Corrige um candidato de 7 caracteres pela posição.

    Retorna (placa_corrigida, numero_de_substituicoes). Se a correção não
    produzir uma placa válida, a placa retornada não passará em ``is_valid``.
    """
    candidate = clean(candidate)
    if len(candidate) != PLATE_LENGTH:
        return candidate, PLATE_LENGTH

    chars = list(candidate)
    fixed = [_as_letter(c) for c in chars[:3]] + [_as_digit(chars[3])]
    # Posição 4: letra (Mercosul) ou dígito (antiga) — mantém o que foi lido.
    fixed.append(chars[4])
    fixed += [_as_digit(c) for c in chars[5:]]
    plate = "".join(fixed)
    changes = sum(1 for a, b in zip(chars, fixed) if a != b)
    return plate, changes


def extract_plate(text: str) -> tuple[str | None, int]:
    """Procura a melhor placa válida dentro de um texto de OCR.

    Cada linha é analisada separadamente (para não juntar "BRASIL" com a linha
    de baixo). Em cada linha, todas as janelas de 7 caracteres são testadas e
    vence a que exige menos correções; linhas com caracteres sobrando recebem
    1 ponto de penalidade. Retorna (placa, pontuacao) ou (None, 10**6).
    """
    best: tuple[str | None, int] = (None, 10**6)
    for line in re.split(r"[\n|]", (text or "").upper()):
        line = clean(line)
        if len(line) < PLATE_LENGTH:
            continue
        extra = 1 if len(line) > PLATE_LENGTH else 0
        for i in range(len(line) - PLATE_LENGTH + 1):
            plate, changes = correct(line[i:i + PLATE_LENGTH])
            if is_valid(plate) and changes + extra < best[1]:
                best = (plate, changes + extra)
    return best


def format_display(plate: str) -> str:
    """Formata para exibição: ABC-1234 (antiga) ou ABC1D23 (Mercosul)."""
    plate = clean(plate)
    if classify(plate) == "antiga":
        return f"{plate[:3]}-{plate[3:]}"
    return plate


def mercosul_to_old(plate: str) -> str:
    """Converte placa Mercosul para o padrão antigo equivalente (ABC1C34 -> ABC1234).

    A conversão oficial substitui a 2ª posição numérica por uma letra:
    0->A, 1->B, ..., 9->J.
    """
    plate = clean(plate)
    if classify(plate) != "mercosul" or plate[4] > "J":
        return plate
    return plate[:4] + str(ord(plate[4]) - ord("A")) + plate[5:]


def old_to_mercosul(plate: str) -> str:
    plate = clean(plate)
    if classify(plate) != "antiga":
        return plate
    return plate[:4] + chr(ord("A") + int(plate[4])) + plate[5:]
