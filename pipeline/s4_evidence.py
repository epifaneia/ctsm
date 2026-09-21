"""s4_evidence — evidencia candidata al Rationale, SIN modelo. DETERMINISTA.

Cambio de paradigma respecto a la v1: el sistema NO dictamina.

En un contexto donde la revisión humana es obligatoria, un veredicto automático
no ahorra ese trabajo — solo añade riesgo, y uno particular: un dictamen
plausible con una cita real al lado invita a aceptarlo sin comprobar. Aquí el
sistema hace lo que sabe hacer con garantías —localizar la evidencia y anclarla
a su página— y deja el juicio al ingeniero, que es quien firma.

Por cada requisito escribe en el Rationale los pasajes candidatos que recuperó
s3, cada uno con su documento, página y sección, recortados al fragmento que de
verdad guarda relación con el requisito. El estado queda en el valor abierto de
la taxonomía del propio ReqIF: no es un veredicto negativo, es una petición de
revisión.

Ninguna llamada a modelo. Todo el paso es código: la corrida completa tarda
segundos en lugar de horas, y el resultado es reproducible bit a bit.

Selección del extracto: cada pasaje se trocea en unidades citables
(utils.citables) y se puntúa cada unidad por los términos del requisito que
contiene, ponderando los términos largos —los técnicos— sobre los vacíos. Se
toma la mejor y se extiende a sus vecinas contiguas mientras quepa en el
presupuesto de caracteres, de modo que el extracto sea continuo y literal.

Entrada:  stk_json (s1) + evidence (s3) + corpus (s2)
Salida:   config.RESULTS_DIR/<stem>.json   — mismo contrato que s6, para que s7
          funcione sin cambio alguno

Uso:  python pipeline/s4_evidence.py [substring]
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
from utils.citables import reconstruir, trocear  # noqa: E402

# Presupuesto de caracteres por cita. Con 10 pasajes salen ~4.000 caracteres de
# Rationale por requisito: legible en Polarion y suficiente para decidir si
# merece la pena abrir el PDF por la página indicada.
EXTRACTO_CHARS = int(os.environ.get("CTSM_EXTRACTO_CHARS", "420"))

_PALABRA = re.compile(r"[A-Za-z0-9_]{3,}")


def _terminos(texto: str) -> set[str]:
    """Términos del requisito que sirven para puntuar un pasaje."""
    return {w.lower() for w in _PALABRA.findall(texto or "")}


def _factor_prosa(unidad: str) -> float:
    """Penaliza el texto que no es prosa: etiquetas sueltas de un diagrama.

    Los diagramas de estos manuales son dibujos vectoriales, así que sus
    etiquetas se extraen como texto plano y forman bloques del tipo
    'ICUM_AESB0IDAT / BCI / AES core / BCO' repetidos varias veces. Contienen
    términos técnicos —así que puntúan alto— pero no dicen nada: como cita ante
    un revisor son ruido puro.

    Dos señales bastan para reconocerlos: mucha repetición de los mismos
    tokens, y líneas muy cortas (el pie de cada caja del dibujo).
    """
    tokens = _PALABRA.findall(unidad.lower())
    if len(tokens) < 6:
        return 1.0
    unicidad = len(set(tokens)) / len(tokens)
    lineas = [ln.strip() for ln in unidad.splitlines() if ln.strip()]
    cortas = sum(1 for ln in lineas if len(ln) < 25) / max(1, len(lineas))
    factor = 1.0
    if unicidad < 0.55:                 # el mismo vocabulario una y otra vez
        factor *= 0.25
    if len(lineas) >= 4 and cortas > 0.6:   # una pila de etiquetas sueltas
        factor *= 0.35
    return factor


def _puntuar(unidad: str, terminos: set[str]) -> float:
    """Términos del requisito presentes en la unidad, ponderados por longitud.

    Un identificador de registro pesa más que un artículo: 'icum_trngc0' aporta
    mucha más señal que 'the', y así el extracto se centra en lo técnico. El
    resultado se corrige por la calidad del texto, para que un bloque de
    etiquetas de figura no desplace a una frase que sí explica algo.
    """
    presentes = _terminos(unidad) & terminos
    return sum(len(t) for t in presentes) * _factor_prosa(unidad)


def extracto(chunk: dict, terminos: set[str], presupuesto: int) -> tuple[str, int] | None:
    """→ (texto literal del pasaje, offset dentro del chunk) o None."""
    unidades = trocear(chunk["text"])
    if not unidades:
        return None
    puntos = [_puntuar(u["texto"], terminos) for u in unidades]
    mejor = max(range(len(unidades)), key=lambda i: puntos[i])

    # extiende a las vecinas contiguas, escogiendo cada vez el lado que más aporta
    ini = fin = mejor
    largo = len(unidades[mejor]["texto"])
    while largo < presupuesto:
        izq = puntos[ini - 1] if ini > 0 else -1
        der = puntos[fin + 1] if fin + 1 < len(unidades) else -1
        if izq < 0 and der < 0:
            break
        if der >= izq:
            if largo + len(unidades[fin + 1]["texto"]) > presupuesto * 1.4:
                break
            fin += 1
            largo += len(unidades[fin]["texto"])
        else:
            if largo + len(unidades[ini - 1]["texto"]) > presupuesto * 1.4:
                break
            ini -= 1
            largo += len(unidades[ini]["texto"])
    return reconstruir(chunk["text"], unidades, list(range(ini, fin + 1)))


def _pagina(chunk: dict, offset: int) -> int:
    pagina = chunk["page_start"]
    for pm in chunk.get("page_map", []):
        if pm["offset"] <= offset:
            pagina = pm["page"]
    return pagina


def _cita(ev: dict) -> str:
    sec = f" {ev['section']}" if ev.get("section") else ""
    return f'[{ev["doc"]} p.{ev["page"]}{sec}] "{ev["quote"]}"'


CABECERA = ("Evidencia candidata localizada automáticamente en la documentación del "
            "proveedor. El sistema NO emite veredicto: los pasajes siguientes son los "
            "que guardan mayor relación con el requisito, ordenados por afinidad, para "
            "que sea el ingeniero quien determine el cumplimiento.")

SIN_EVIDENCIA = ("No se ha localizado en la documentación disponible ningún pasaje "
                 "relacionado con este requisito. Puede significar que la documentación "
                 "no cubre este punto, o que falta el manual correspondiente.")

COMENTARIO = ("Pendiente de revisión por ingeniería. La evidencia candidata se adjunta "
              "en el campo Rationale con su documento, página y sección.")


def main() -> int:
    only = sys.argv[1] if len(sys.argv) > 1 else None
    corpus = json.loads((config.CORPUS_DIR / "corpus.json").read_text(encoding="utf-8"))
    chunk_by_id = {c["chunk_id"]: c for c in corpus["chunks"]}

    stk_jsons = sorted(config.STK_JSON_DIR.glob("*.json"))
    if only:
        stk_jsons = [p for p in stk_jsons if only.lower() in p.stem.lower()]
    if not stk_jsons:
        print("s4: no hay stk.json que matcheen")
        return 1

    config.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    for stk_path in stk_jsons:
        stk = json.loads(stk_path.read_text(encoding="utf-8"))
        ev_path = config.EVIDENCE_DIR / stk_path.name
        if not ev_path.is_file():
            print(f"s4: falta {ev_path.name} — ¿corrió s3?")
            return 1
        candidatos = {e["spec_object_id"]: [c["chunk_id"] for c in e["candidates"]]
                      for e in json.loads(ev_path.read_text(encoding="utf-8"))}
        sem = stk.get("status_semantics") or {}
        abierto = sem.get("open") or config.STATUS_DEFAULT

        resultados, con_ev, total_citas = [], 0, 0
        for obj in stk["objects"]:
            if not obj.get("evaluable") or not obj.get("text"):
                continue
            oid = obj["identifier"]
            terminos = _terminos(obj["text"])
            evidencias = []
            for cid in candidatos.get(oid, []):
                ch = chunk_by_id.get(cid)
                if ch is None:
                    continue
                comp = extracto(ch, terminos, EXTRACTO_CHARS)
                if comp is None:
                    continue
                texto, off = comp
                evidencias.append({
                    "chunk_id": cid, "doc": ch["doc"], "section": ch.get("section", ""),
                    "page": _pagina(ch, off), "quote": texto, "match_ratio": 1.0,
                })
            total_citas += len(evidencias)
            con_ev += bool(evidencias)
            if evidencias:
                rationale = CABECERA + "\n\nEvidence:\n" + "\n".join(
                    _cita(e) for e in evidencias)
                comentario = COMENTARIO
            else:
                rationale = SIN_EVIDENCIA
                comentario = ("No se ha localizado documentación relacionada con este "
                              "requisito en los manuales analizados.")
            resultados.append({
                "spec_object_id": oid,
                "oem_req_id": obj.get("oem_req_id"),
                "status": abierto,
                "rationale": rationale,
                "comments": comentario,
                "evidence": evidencias,
                "flags": [],
            })

        salida = config.RESULTS_DIR / stk_path.name
        salida.write_text(json.dumps({
            "stk": stk_path.stem,
            "generated_by": "s4_evidence (sin modelo — evidencia candidata)",
            "status_enum_values": stk["status_enum_values"],
            "results": resultados,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        chars = sum(len(r["rationale"]) for r in resultados)
        print(f"s4: {stk_path.stem[:44]}")
        print(f"    {len(resultados)} requisitos | {con_ev} con evidencia | "
              f"{total_citas} citas | {chars:,} chars de rationale")
        print(f"    → {salida.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
