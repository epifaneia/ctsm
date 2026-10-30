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


def find_literal_span(quote: str, texto: str) -> tuple[int, int] | None:
    """(inicio, fin) en `texto` (offsets ORIGINALES) del tramo que es `quote`, o None.

    Literal estricto tras normalizar: no hay umbral que ajustar. O está, o no.
    `texto[inicio:fin]` es el texto del documento tal cual, con sus saltos de línea.

    El tramo tiene que empezar y acabar en límite de palabra: «200 mA» no está
    dentro de «1200 mA», ni «40 °C» dentro de «-40 °C», ni «3» dentro de «3,5».
    """
    q, _ = normalize(quote)
    t, mapa = normalize(texto)
    if not q:
        return None
    pos = t.find(q)
    while pos >= 0:
        if _en_limite(t, pos, pos + len(q)):
            return mapa[pos], mapa[pos + len(q) - 1] + 1
        pos = t.find(q, pos + 1)
    return None


def _en_limite(t: str, ini: int, fin: int) -> bool:
    """El tramo t[ini:fin] no corta una palabra ni una cifra (con su signo o sus decimales)."""
    antes = t[ini - 1] if ini > 0 else ""
    despues = t[fin] if fin < len(t) else ""
    if antes.isalnum() and t[ini].isalnum():
        return False
    if despues.isalnum() and t[fin - 1].isalnum():
        return False
    # un signo pegado a la cifra es parte de ella; un guion pegado a otra palabra o cifra es un
    # rango o un compuesto («9-16 V», «2.0-to-3.6 V»)
    previo = t[ini - 2] if ini > 1 else ""
    if t[ini].isdigit() and antes and antes in "-−+" and not previo.isalnum():
        return False
    if t[ini].isdigit() and antes and antes in ".," and previo.isdigit():
        return False
    if t[fin - 1].isdigit() and despues in ".," and fin + 1 < len(t) and t[fin + 1].isdigit():
        return False
    return True


def find_literal(quote: str, texto: str) -> int | None:
    """Posición en `texto` (offset ORIGINAL) donde empieza `quote`, o None."""
    span = find_literal_span(quote, texto)
    return span[0] if span else None


def is_literal(quote: str, texto: str) -> bool:
    return find_literal(quote, texto) is not None
