"""s6_verify — guard anti-alucinación + sellado del contrato. DETERMINISTA.

Comprobaciones por requisito antes de sellar results.json:

  1. status ∈ enum del STK (garantizado por schema en s4; se re-verifica).
  2. Cada evidencia: la quote EXISTE en el chunk CITADO. Más estricto que buscar
     en el corpus entero: la cita debe estar donde el LLM dijo que estaba.
       · literal tras normalizar el ruido tipográfico del PDF (utils/text_norm):
         sin umbral, o está o no está;
       · si no es literal pero se parece (rapidfuzz partial_ratio ≥
         config.QUOTE_MIN_RATIO), el modelo parafraseó. Solo se acepta si dice lo
         MISMO: las mismas cifras y las mismas negaciones (un 96 % de parecido no
         distingue «3 to 25 MHz» de «4 to 16 MHz»). Si pasa, la cita pasa a ser el
         TEXTO DEL MANUAL con el que casó y se marca «cita_aproximada»; si no, se
         descarta como evidencia y queda marcado por qué;
       · por debajo, se descarta.
     La cita guardada es SIEMPRE texto del documento, nunca del modelo.
     La PÁGINA exacta se deriva del offset del match dentro del chunk
     (page_map de s2) — el LLM nunca escribió ubicaciones.
  2b. En modo revision (run.py --modo revision) el estado y las citas vienen de
     s5_review, que juzga cada pasaje: un solo «contradice» basta para el «no».
     Sus citas se verifican igual. Queda marcado qué cambió respecto a s4.
  3. Veredicto ≠ "open" exige ≥1 evidencia VERIFICADA; si no → degradado al
     valor open de la taxonomía (Unconfirmed/In review) + flag "demoted". Si
     todas sus citas son aproximadas, se mantiene pero con la marca
     "solo_citas_aproximadas", para que una persona lo mire antes de firmar.
  4. Cobertura: todo requisito evaluable sin veredicto → open + flag
     "sin_evaluar".

La cita final la compone EL CÓDIGO: [DOC p.N §sección] "quote" — trazabilidad
garantizada, no generada. Rationale sellado = analysis + citas verificadas.

Si el stk.json trae ground_truth por objeto (sets de prueba), imprime el
scoring contra el veredicto (mapeo yes/no/open) — no se pasa nunca a s4.

Entrada:  config.EVAL_DIR/<stem>.json + stk_json + corpus
Salida:   config.RESULTS_DIR/<stem>.json SELLADO (la frontera para s7)

Uso:  python pipeline/s6_verify.py [substring]
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from rapidfuzz import fuzz

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
from utils.text_norm import find_literal_span  # noqa: E402


_CIFRA = re.compile(r"\d+")
_NEGACION = re.compile(r"\b(?:no|not|never|cannot|neither|nor|none|without)\b|n't\b", re.IGNORECASE)


def _mismo_sentido(quote: str, tramo: str) -> str | None:
    """None si la paráfrasis conserva cifras y negaciones; si no, el motivo. Las cifras se
    comparan como multiconjunto de números; las negaciones, por recuento. No entiende el
    texto, pero caza los dos cambios que más daño hacen en una cita técnica."""
    if sorted(_CIFRA.findall(quote)) != sorted(_CIFRA.findall(tramo)):
        return f"cifras distintas: modelo {' '.join(_CIFRA.findall(quote))} / manual {' '.join(_CIFRA.findall(tramo))}"
    if len(_NEGACION.findall(quote)) != len(_NEGACION.findall(tramo)):
        return "negación distinta entre la cita del modelo y el manual"
    return None


def _a_frase(texto: str, quote: str, ini: int, fin: int, margen: int = 80) -> tuple[int, int]:
    """Ensancha el tramo de una cita aproximada: el alineamiento de rapidfuzz corta a media
    frase o a media palabra. El inicio se ancla donde empiezan las primeras palabras de la
    cita del modelo («The CRC…»), si están cerca; si no, al principio de la frase. El final,
    al final de la frase. Siempre a palabras enteras."""
    corte = re.compile(r"[.!?:;]\s|\n\s*\n")
    palabras = quote.split()
    ancla = -1
    for n in (2, 1):
        if len(palabras) >= n and len(" ".join(palabras[:n])) >= 3:
            ancla = texto.rfind(" ".join(palabras[:n]), max(0, ini - margen), ini + len(palabras[0]) + 1)
            if ancla >= 0:
                break
    previos = [m.end() for m in corte.finditer(texto, max(0, ini - margen), ini)]
    if ancla >= 0:
        ini = ancla
    elif previos:
        ini = previos[-1]
    else:
        while ini > 0 and not texto[ini - 1].isspace():
            ini -= 1
    siguiente = corte.search(texto, max(ini, fin - 1), min(len(texto), fin + margen))
    if siguiente:
        fin = siguiente.start() + 1
    else:
        while fin < len(texto) and not texto[fin].isspace():
            fin += 1
    return ini, fin


def _como_se_lee(tramo: str) -> str:
    """El tramo del PDF como lo lee una persona: palabras partidas a final de línea
    («oper-\\nating») recompuestas y el espacio en blanco colapsado. No cambia ni una letra."""
    return " ".join(re.sub(r"(\w)-[ \t]*\r?\n\s*(\w)", r"\1\2", tramo).split())


def _page_of(chunk: dict, offset: int) -> int:
    page = chunk["page_start"]
    for pm in chunk.get("page_map", []):
        if pm["offset"] <= offset:
            page = pm["page"]
    return page


def _verify_evidence(ev: dict, chunk_by_id: dict) -> tuple[dict | None, str | None]:
    """→ (evidencia verificada con página exacta, o None) + motivo de fallo."""
    chunk = chunk_by_id.get(ev.get("chunk_id"))
    if chunk is None:
        return None, f"chunk inexistente: {ev.get('chunk_id')}"
    quote = (ev.get("quote") or "").strip()
    if len(quote) < 10:
        return None, f"quote vacía/corta en {ev['chunk_id']}"
    texto = chunk["text"]
    span = find_literal_span(quote, texto)
    if span:
        ini, fin, ratio, literal = *span, 1.0, True
    else:
        aln = fuzz.partial_ratio_alignment(quote, texto)
        ratio = (aln.score if aln else 0.0) / 100.0
        if ratio < config.QUOTE_MIN_RATIO:
            return None, f"quote no encontrada en {ev['chunk_id']} (ratio {ratio:.2f})"
        distinto = _mismo_sentido(quote, texto[aln.dest_start:aln.dest_end])
        if distinto:
            return None, f"paráfrasis que cambia el sentido en {ev['chunk_id']} ({ratio:.2f}): {distinto}"
        ini, fin = _a_frase(texto, quote, aln.dest_start, aln.dest_end)
        literal = False
    out = {
        "chunk_id": chunk["chunk_id"],
        "doc": chunk["doc"],
        "section": chunk["section"],
        "page": _page_of(chunk, ini),
        "quote": _como_se_lee(texto[ini:fin]),          # el texto del manual, no el del modelo
        "match_ratio": round(ratio, 3),
        "literal": literal,
    }
    if not literal:
        out["quote_modelo"] = quote                      # lo que escribió el modelo, para auditar la diferencia
    return out, None


def _citation(ev: dict) -> str:
    sec = f" {ev['section']}" if ev["section"] else ""
    marca = " (contradice)" if ev.get("juicio") == "contradice" else ""
    return f'[{ev["doc"]} p.{ev["page"]}{sec}] "{ev["quote"]}"{marca}'


def _sellar_revision(r: dict, status_s4: str, analysis: str, chunk_by_id: dict,
                     status_names: set, open_name: str, flags: list[str]) -> tuple[str, str, list[dict]]:
    """Modo revision: el estado lo fija s5_review (un 'contradice' manda) y la evidencia son
    sus pasajes que apoyan o contradicen. Sus citas ya son literales por construcción
    (utils/citables), pero se verifican igual que las de s4: aquí no se confía en nadie."""
    status = r["status_revisado"] if r["status_revisado"] in status_names else open_name
    if status != status_s4:
        flags.append(f"revision:{status_s4}->{status}" + (" (arbitrado por el modelo grande)" if r.get("escalado") else ""))
    verified = []
    for j in r.get("juicios") or []:
        if j.get("juicio") not in ("apoya", "contradice"):
            continue
        ok, why = _verify_evidence({"chunk_id": j["chunk_id"], "quote": j.get("quote")}, chunk_by_id)
        if ok:
            ok["juicio"] = j["juicio"]
            verified.append(ok)
        else:
            flags.append(f"quote_failed:{why}")
    apoyan = sum(v["juicio"] == "apoya" for v in verified)
    contra = [v["chunk_id"] for v in verified if v["juicio"] == "contradice"]
    if contra:
        flags.append(f"contradice:{', '.join(contra)}")
    if status != status_s4:
        # el razonamiento de s4 defendía otro estado: no se deja junto a un veredicto que no sostiene
        analysis = (f"Revisión pasaje a pasaje: {apoyan} lo apoya(n) y {len(contra)} lo contradice(n). "
                    "Regla: un solo pasaje que contradiga basta para el «no».")
    return status, analysis, verified


def main() -> int:
    only = sys.argv[1] if len(sys.argv) > 1 else None
    stk_jsons = sorted(config.STK_JSON_DIR.glob("*.json"))
    if only:
        stk_jsons = [p for p in stk_jsons if only.lower() in p.stem.lower()]
    if not stk_jsons:
        print("s6: no hay stk.json que matcheen")
        return 1

    corpus = json.loads((config.CORPUS_DIR / "corpus.json").read_text(encoding="utf-8"))
    chunk_by_id = {c["chunk_id"]: c for c in corpus["chunks"]}
    config.RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    for stk_path in stk_jsons:
        stk = json.loads(stk_path.read_text(encoding="utf-8"))
        eval_path = config.EVAL_DIR / stk_path.name
        if not eval_path.is_file():
            print(f"s6: falta {eval_path.name} — ¿corrió s4?")
            return 1
        evals = {e["spec_object_id"]: e
                 for e in json.loads(eval_path.read_text(encoding="utf-8"))}
        # modo revision (run.py --modo revision): manda el juicio por pasaje de s5_review
        revision: dict = {}
        if os.environ.get("CTSM_MODO") == "revision":
            rev_path = config.REVIEW_DIR / stk_path.name
            if not rev_path.is_file():
                print(f"s6: modo revision sin {rev_path.name} — ¿corrió s5_review?")
                return 1
            revision = {r["spec_object_id"]: r
                        for r in json.loads(rev_path.read_text(encoding="utf-8"))}
        sem = stk.get("status_semantics") or {}
        open_name = sem.get("open") or config.STATUS_DEFAULT
        status_names = set(stk["status_enum_values"]) or set(config.STATUS_TAXONOMY)

        results, counts = [], {}
        evaluables = [o for o in stk["objects"] if o.get("evaluable") and o.get("text")]
        for obj in evaluables:
            oid = obj["identifier"]
            flags: list[str] = []
            e = evals.get(oid)
            if e is None:
                status, analysis, comments, verified = open_name, "", "", []
                flags.append("sin_evaluar")
            else:
                status = e["status"]
                analysis = e.get("analysis") or ""
                comments = e.get("comments") or ""
                if status not in status_names:
                    flags.append(f"status_invalido:{status}")
                    status = open_name
                verified = []
                for ev in e.get("evidence") or []:
                    ok, why = _verify_evidence(ev, chunk_by_id)
                    if ok:
                        verified.append(ok)
                        if not ok["literal"]:
                            flags.append(f"cita_aproximada:{ok['chunk_id']} ({ok['match_ratio']:.2f}): "
                                         "se muestra el texto del manual")
                    else:
                        flags.append(f"quote_failed:{why}")
                if oid in revision:
                    status, analysis, verified = _sellar_revision(
                        revision[oid], status, analysis, chunk_by_id, status_names, open_name, flags)
                if status != open_name and not verified:
                    flags.append(f"demoted:{status}->{open_name}")
                    status = open_name
                elif status != open_name and not any(v["literal"] for v in verified):
                    flags.append("solo_citas_aproximadas: revisar antes de firmar")
            rationale = analysis
            if verified:
                rationale += "\n\nEvidence:\n" + "\n".join(_citation(v) for v in verified)
            results.append({
                "spec_object_id": oid,
                "oem_req_id": obj.get("oem_req_id"),
                "status": status,
                "rationale": rationale.strip(),
                "comments": comments,
                "evidence": verified,
                "flags": flags,
            })
            counts[status] = counts.get(status, 0) + 1

        out = config.RESULTS_DIR / stk_path.name
        out.write_text(json.dumps(
            {"stk": stk_path.stem, "generated_by": "s6_verify (sellado)",
             "status_enum_values": stk["status_enum_values"], "results": results},
            ensure_ascii=False, indent=2), encoding="utf-8")
        n_flags = sum(1 for r in results if r["flags"])
        print(f"s6: {stk_path.stem} — {len(results)} sellados {counts}, "
              f"{n_flags} con flags → {out.name}")
        for r in results:
            for f in r["flags"]:
                print(f"     ⚑ {r['spec_object_id']}: {f}")

        # --- scoring opcional contra ground_truth (sets de prueba) ---
        gt_map = {"YES": sem.get("yes"), "NO": sem.get("no"), "TBD": sem.get("open")}
        scored = [(r, objs["ground_truth"]) for r in results
                  if (objs := next(o for o in evaluables
                                   if o["identifier"] == r["spec_object_id"])).get("ground_truth")]
        if scored:
            hits = sum(1 for r, gt in scored if r["status"] == gt_map.get(gt))
            print(f"s6: scoring vs ground truth: {hits}/{len(scored)}")
            for r, gt in scored:
                mark = "✓" if r["status"] == gt_map.get(gt) else "✗"
                print(f"     {mark} {r['spec_object_id']}: esperado {gt_map.get(gt)!r}, "
                      f"salió {r['status']!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
