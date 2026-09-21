"""s3_retrieve — requisito → chunks candidatos del corpus. DETERMINISTA, sin API.

Por cada requisito evaluable del stk.json selecciona los chunks que s4 recibirá
como contexto:

  · Si el corpus completo cabe (config.CORPUS_MAX_CHARS): passthrough.
  · Si no: BM25 (rank-bm25) sobre tokens alfanuméricos, top-K
    (config.S3_TOP_K) por requisito. Query = texto del requisito.

La lista de candidatos ES el universo de citación de s4: el chunk_id que el
LLM puede citar se restringe por responseSchema a estos IDs. Retrieval que
falla aquí = requisito que s4 solo podrá dejar en revisión — mejor eso que
una cita inventada.

Entrada:  config.STK_JSON_DIR/<stem>.json + config.CORPUS_DIR/corpus.json
Salida:   config.EVIDENCE_DIR/<stem>.json
          [{spec_object_id, candidates: [{chunk_id, score, doc, section,
            page_start, page_end}]}]  (el texto vive en corpus.json)

Uso:  python pipeline/s3_retrieve.py [substring]
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from rank_bm25 import BM25Okapi

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402

_TOKEN = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def main() -> int:
    only = sys.argv[1] if len(sys.argv) > 1 else None
    stk_jsons = sorted(config.STK_JSON_DIR.glob("*.json"))
    if only:
        stk_jsons = [p for p in stk_jsons if only.lower() in p.stem.lower()]
    if not stk_jsons:
        print(f"s3: no hay stk.json en {config.STK_JSON_DIR} — ¿corriste s1?")
        return 1
    corpus_path = config.CORPUS_DIR / "corpus.json"
    if not corpus_path.is_file():
        print(f"s3: falta {corpus_path} — ¿corriste s2?")
        return 1

    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    chunks = corpus["chunks"]
    total_chars = sum(len(c["text"]) for c in chunks)
    # umbral según el contexto REAL del backend, no un fijo pensado para Gemini
    passthrough = total_chars <= config.corpus_max_chars()
    bm25 = None
    if not passthrough:
        bm25 = BM25Okapi([_tokens(c["text"]) for c in chunks])

    config.EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    for stk_path in stk_jsons:
        stk = json.loads(stk_path.read_text(encoding="utf-8"))
        evaluables = [o for o in stk["objects"] if o.get("evaluable") and o.get("text")]
        out = []
        for o in evaluables:
            if passthrough:
                cand = list(range(len(chunks)))
                scores = [0.0] * len(chunks)
            else:
                scores_all = bm25.get_scores(_tokens(o["text"]))
                cand = sorted(range(len(chunks)), key=lambda i: -scores_all[i])[:config.S3_TOP_K]
                scores = [float(scores_all[i]) for i in cand]
            out.append({
                "spec_object_id": o["identifier"],
                "candidates": [{
                    "chunk_id": chunks[i]["chunk_id"],
                    "score": round(s, 2),
                    "doc": chunks[i]["doc"],
                    "section": chunks[i]["section"],
                    "page_start": chunks[i]["page_start"],
                    "page_end": chunks[i]["page_end"],
                } for i, s in zip(cand, scores)],
            })
        out_path = config.EVIDENCE_DIR / stk_path.name
        out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        mode = "passthrough" if passthrough else f"BM25 top-{config.S3_TOP_K}"
        print(f"s3: {stk_path.stem} — {len(out)} requisitos × {mode} → {out_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
