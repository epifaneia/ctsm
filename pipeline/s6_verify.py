"""s6_verify — guard anti-alucinación + sellado del contrato. DETERMINISTA.

Comprobaciones por requisito antes de sellar results.json:

  1. status ∈ enum del STK (garantizado por schema en s4; se re-verifica).
  2. Cada evidencia: la quote EXISTE en el chunk CITADO (rapidfuzz
     partial_ratio ≥ config.QUOTE_MIN_RATIO). Más estricto que buscar en el
     corpus entero: la cita debe estar donde el LLM dijo que estaba.
     La PÁGINA exacta se deriva del offset del match dentro del chunk
     (page_map de s2) — el LLM nunca escribió ubicaciones.
  3. Veredicto ≠ "open" exige ≥1 evidencia VERIFICADA; si no → degradado al
     valor open de la taxonomía (Unconfirmed/In review) + flag "demoted".
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
import sys
from pathlib import Path

from rapidfuzz import fuzz

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402


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
    aln = fuzz.partial_ratio_alignment(quote, chunk["text"])
    ratio = (aln.score if aln else 0.0) / 100.0
    if ratio < config.QUOTE_MIN_RATIO:
        return None, f"quote no encontrada en {ev['chunk_id']} (ratio {ratio:.2f})"
    return {
        "chunk_id": chunk["chunk_id"],
        "doc": chunk["doc"],
        "section": chunk["section"],
        "page": _page_of(chunk, aln.dest_start),
        "quote": quote,
        "match_ratio": round(ratio, 3),
    }, None


def _citation(ev: dict) -> str:
    sec = f" {ev['section']}" if ev["section"] else ""
    return f'[{ev["doc"]} p.{ev["page"]}{sec}] "{ev["quote"]}"'


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
                    else:
                        flags.append(f"quote_failed:{why}")
                if status != open_name and not verified:
                    flags.append(f"demoted:{status}->{open_name}")
                    status = open_name
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
