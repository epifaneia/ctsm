"""text_norm — normalización tipográfica para verificar citas LITERALES.

El problema: un PDF no entrega el texto como lo lee un humano. Mete saltos de
línea a mitad de frase, parte palabras con guiones, usa comillas tipográficas,
viñetas y espacios dobles. Comparar una cita carácter a carácter contra ese
texto rechaza citas perfectamente válidas: medido sobre las 550 citas de las dos
corridas, solo el 46% coincide en crudo, frente al 91,8% tras limpiar ese ruido.

De ahí la regla: **literal sí, pero sobre texto normalizado**. Sin umbrales de
similitud — un porcentaje de parecido no mide equivalencia técnica, y donde peor
falla es en las cifras: "entre 5 y 8.5" y "entre 5 y 11" se parecen en un 95% y
significan lo contrario frente a un requisito que exija "> 10".

La parte delicada: la página de la cita se deriva del OFFSET del match dentro del
chunk. Si la normalización colapsa espacios, los offsets se desplazan y la página
sale mal. Por eso `normalize` devuelve además un mapa índice→posición original,
y `find_literal` traduce el match de vuelta al texto de partida.
"""
from __future__ import annotations

import unicodedata

# Caracteres que aportan ruido y no significado en una cita técnica.
_INVISIBLES = {
    "­",  # soft hyphen
    "​", "‌", "‍",  # zero-width
    "﻿",  # BOM
}
# Viñetas y marcadores de lista: el modelo suele omitirlos o cambiarlos.
_VINETAS = set("•●○▪▫◦‣⁃")
# Familias de signos que los PDF usan indistintamente.
_COMILLAS = {"‘": "'", "’": "'", "‚": "'", "‛": "'",
             "“": '"', "”": '"', "„": '"', "‟": '"',
             "«": '"', "»": '"', "′": "'", "″": '"'}
_GUIONES = {"‐": "-", "‑": "-", "‒": "-", "–": "-",
            "—": "-", "―": "-", "−": "-"}


def normalize(text: str) -> tuple[str, list[int]]:
    """→ (texto normalizado, mapa posición_normalizada → posición_original).

    Minúsculas, sin invisibles ni viñetas, comillas y guiones unificados,
    guiones de partición de línea reabsorbidos y todo el whitespace colapsado
    a un único espacio.
    """
    out: list[str] = []
    idx: list[int] = []
    i, n = 0, len(text)
    espacio_pendiente = False

    while i < n:
        c = text[i]

        # guion de partición: "confiden-\ncial" → "confidencial"
        if c == "-" and i + 1 < n:
            j = i + 1
            while j < n and text[j] in " \t\r":
                j += 1
            if j < n and text[j] == "\n":
                j += 1
                while j < n and text[j] in " \t\r":
                    j += 1
                i = j
                espacio_pendiente = False
                continue

        if c in _INVISIBLES or c in _VINETAS:
            i += 1
            continue

        if c.isspace():
            espacio_pendiente = True
            i += 1
            continue

        if espacio_pendiente and out:
            out.append(" ")
            idx.append(i)
            espacio_pendiente = False
        elif espacio_pendiente:
            espacio_pendiente = False

        c = _COMILLAS.get(c, _GUIONES.get(c, c))
        # NFKD + descarte de diacríticos combinantes: ligaduras y acentos fuera
        for d in unicodedata.normalize("NFKD", c):
            if unicodedata.combining(d):
                continue
            out.append(d.lower())
            idx.append(i)
        i += 1

    return "".join(out), idx


def find_literal(quote: str, texto: str) -> int | None:
    """Posición en `texto` (offset ORIGINAL) donde empieza `quote`, o None.

    Literal estricto tras normalizar: no hay umbral que ajustar. O está, o no.
    """
    q, _ = normalize(quote)
    t, mapa = normalize(texto)
    if not q:
        return None
    pos = t.find(q)
    if pos < 0:
        return None
    return mapa[pos] if pos < len(mapa) else None


def is_literal(quote: str, texto: str) -> bool:
    return find_literal(quote, texto) is not None
