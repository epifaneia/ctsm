"""citables — trocea un chunk en unidades numeradas que el modelo puede CITAR.

Razón de ser: hoy el modelo escribe la cita a mano y la parafrasea. El proyecto
ya resolvió ese problema una vez — no escribe el chunk_id, lo elige de una lista
cerrada — y esto extiende la misma idea a la cita: el modelo devuelve ÍNDICES y
el código copia el texto del original. Una cita así es literal por construcción;
no hay nada que verificar después.

El troceo tiene que respetar la notación técnica: partir "8.5 V" o "Fig. 3" en
dos unidades produciría citas mutiladas. Por eso solo se corta en un final de
frase cuando lo que sigue empieza de verdad algo nuevo (mayúscula, viñeta,
dígito de enumeración), y nunca entre dígitos.

Cada unidad conserva su offset dentro del chunk, que es lo que permite derivar
la página exacta con el page_map de s2.
"""
from __future__ import annotations

import re

# Corte de frase: tras . ! ? o :  seguidos de espacio, SOLO si lo siguiente
# arranca algo nuevo. El lookbehind evita cortar "8.5" o "v1.2".
_CORTE = re.compile(r"(?<=[.!?:])\s+(?=[A-Z(\[•●○▪])")
# Salto de línea que precede a una viñeta o a un numeral de lista.
_VINETA = re.compile(r"\n\s*(?=[•●○▪▫⁃-]|\d+[.)]\s)")
_MIN = 15   # por debajo de esto no es una unidad citable, se pega a la anterior


def trocear(texto: str) -> list[dict]:
    """→ [{'i': índice, 'texto': str, 'offset': int}] sobre el texto ORIGINAL."""
    cortes = {0, len(texto)}
    for rx in (_CORTE, _VINETA):
        for m in rx.finditer(texto):
            cortes.add(m.end() if rx is _VINETA else m.start() + len(m.group(0)))
    puntos = sorted(cortes)

    crudas: list[tuple[int, str]] = []
    for a, b in zip(puntos, puntos[1:]):
        frag = texto[a:b]
        if frag.strip():
            crudas.append((a, frag))

    # pega los fragmentos demasiado cortos al anterior (encabezados sueltos,
    # restos de tabla) para no llenar el prompt de ruido numerado
    unidades: list[dict] = []
    for off, frag in crudas:
        limpio = frag.strip()
        if unidades and len(limpio) < _MIN:
            ini = unidades[-1]["offset"]
            unidades[-1]["texto"] = texto[ini:off + len(frag)].strip()
            continue
        unidades.append({"i": len(unidades), "texto": limpio, "offset": off})

    for n, u in enumerate(unidades):
        u["i"] = n
    return unidades


def reconstruir(texto: str, unidades: list[dict], indices: list[int]) -> tuple[str, int] | None:
    """Compone la cita a partir de índices. → (cita literal, offset) o None.

    Los índices se ordenan y deduplican; si son contiguos se devuelve el tramo
    exacto del original (con su puntuación y espaciado), y si no, las unidades
    unidas por un espacio. En ambos casos el texto sale del documento, no del
    modelo.
    """
    val = sorted({i for i in indices if isinstance(i, int) and 0 <= i < len(unidades)})
    if not val:
        return None
    if val == list(range(val[0], val[-1] + 1)):
        ini = unidades[val[0]]["offset"]
        ult = unidades[val[-1]]
        fin = ult["offset"] + len(ult["texto"])
        # el offset de la unidad apunta al inicio del fragmento sin recortar,
        # así que se reajusta al primer carácter no blanco
        while ini < len(texto) and texto[ini].isspace():
            ini += 1
        return texto[ini:fin].strip(), ini
    return " ".join(unidades[i]["texto"] for i in val), unidades[val[0]]["offset"]
