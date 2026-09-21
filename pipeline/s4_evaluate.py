"""s4_evaluate — CASO DE USO 1: Status + trazabilidad. LLM (gasta API).

UNA llamada Gemini POR REQUISITO con responseSchema estricto y dinámico:

  · status   — enum con los valores REALES del STK (stk.json), no texto libre.
  · evidence — [{chunk_id, quote}] donde chunk_id es un ENUM restringido a los
               candidatos que s3 recuperó para ESE requisito: el LLM no puede
               citar una ubicación que no le hayamos dado (trazabilidad
               garantizada, no generada). La página/sección la deriva s6 de
               los metadatos del chunk — el LLM nunca escribe ubicaciones.
  · analysis — razonamiento del veredicto (2-4 frases, inglés de auditoría).
  · comments — mensaje corto al OEM.

Regla de oro (prompts/evaluar_status.txt): ante evidencia insuficiente → el
valor "open" de la taxonomía (p.ej. Unconfirmed), jamás inventar un compliant.
La quote se verifica en s6 contra el chunk citado (rapidfuzz): paráfrasis = flag.

Entrada:  stk_json + evidence (s3) + corpus (s2)
Salida:   config.EVAL_DIR/<stem>.json  (crudo, sin verificar — s6 sella)

Uso:  python pipeline/s4_evaluate.py [substring]
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
from clients import gemini, ollama  # noqa: E402


def _status_rules(sem: dict, names: list[str]) -> str:
    desc = {
        "yes":  "the documentation explicitly supports the requirement.",
        "no":   "the documentation contradicts the requirement or the capability "
                "is not available on the product.",
        "open": "evidence is insufficient, the topic is outside the documentation's "
                "scope, or it is an application/design decision. THIS IS THE DEFAULT "
                "whenever you are not certain.",
    }
    lines = []
    for role in ("yes", "no", "open"):
        if sem.get(role):
            lines.append(f'· "{sem[role]}" — {desc[role]}')
    for n in names:                      # valores sin rol asignado, por si acaso
        if n not in sem.values():
            lines.append(f'· "{n}"')
    return "\n".join(lines)


def _schema(status_names: list[str], chunk_ids: list[str]) -> dict:
    return {
        "type": "OBJECT",
        "properties": {
            "status":   {"type": "STRING", "enum": status_names},
            "analysis": {"type": "STRING"},
            "evidence": {
                "type": "ARRAY",
                "maxItems": 3,
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "chunk_id": {"type": "STRING", "enum": chunk_ids},
                        "quote":    {"type": "STRING"},
                    },
                    "required": ["chunk_id", "quote"],
                },
            },
            "comments": {"type": "STRING"},
        },
        "required": ["status", "analysis", "evidence", "comments"],
    }


def _engine() -> str:
    """Etiqueta del motor en uso — se imprime para dejar rastro de custodia."""
    return (f"ollama:{config.OLLAMA_MODEL}" if config.LLM_BACKEND == "ollama"
            else f"gemini:{config.GEMINI_MODEL}")


def _call(system: str, user: str, schema: dict) -> dict:
    """Una evaluación con salida forzada por schema. Local (ollama) o nube (gemini).

    Ambos backends imponen el enum de chunk_id en el DECODIFICADOR, no en el
    prompt: la trazabilidad garantizada se mantiene igual en local.
    """
    last: Exception | None = None
    for attempt in range(3):
        try:
            if config.LLM_BACKEND == "ollama":
                return ollama.generate_json_schema(
                    base_url=config.OLLAMA_BASE_URL, model=config.OLLAMA_MODEL,
                    user_text=user, system_instruction=system,
                    response_schema=schema, temperature=0.1,
                    num_ctx=config.OLLAMA_NUM_CTX, num_gpu=config.OLLAMA_NUM_GPU,
                    num_thread=config.OLLAMA_NUM_THREAD, timeout_s=config.LLM_TIMEOUT,
                )
            return gemini.generate_json_schema(
                api_key=config.GEMINI_API_KEY, model=config.GEMINI_MODEL,
                user_text=user, system_instruction=system,
                response_schema=schema, temperature=0.1,
                timeout_s=config.LLM_TIMEOUT,
            )
        except ValueError as e:
            raise RuntimeError(f"{_engine()}: {e}") from e   # truncado: no reintentar
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"{_engine()} falló tras 3 intentos: {last}")


def main() -> int:
    only = sys.argv[1] if len(sys.argv) > 1 else None
    if config.LLM_BACKEND not in ("ollama", "gemini"):
        print(f"s4: CTSM_LLM_BACKEND='{config.LLM_BACKEND}' no válido (ollama|gemini)")
        return 1
    if config.LLM_BACKEND == "gemini" and not config.GEMINI_API_KEY:
        print("s4: falta GEMINI_API_KEY (.env)")
        return 1
    print(f"s4: motor = {_engine()}" +
          (f"  ctx={config.OLLAMA_NUM_CTX}  [AIR-GAP: nada sale de la máquina]"
           if config.LLM_BACKEND == "ollama" else "  [!] datos de cliente salen a Google"))
    stk_jsons = sorted(config.STK_JSON_DIR.glob("*.json"))
    if only:
        stk_jsons = [p for p in stk_jsons if only.lower() in p.stem.lower()]
    if not stk_jsons:
        print(f"s4: no hay stk.json que matcheen — ¿corriste s1?")
        return 1

    corpus = json.loads((config.CORPUS_DIR / "corpus.json").read_text(encoding="utf-8"))
    chunk_by_id = {c["chunk_id"]: c for c in corpus["chunks"]}
    prompt_tpl = (config.PROMPTS_DIR / "evaluar_status.txt").read_text(encoding="utf-8")

    config.EVAL_DIR.mkdir(parents=True, exist_ok=True)
    for stk_path in stk_jsons:
        stk = json.loads(stk_path.read_text(encoding="utf-8"))
        ev_path = config.EVIDENCE_DIR / stk_path.name
        if not ev_path.is_file():
            print(f"s4: falta {ev_path.name} — ¿corrió s3?")
            return 1
        evidence = {e["spec_object_id"]: e["candidates"]
                    for e in json.loads(ev_path.read_text(encoding="utf-8"))}
        objects = {o["identifier"]: o for o in stk["objects"]}
        status_names = list(stk["status_enum_values"])
        sem = stk.get("status_semantics") or {}
        system = (prompt_tpl
                  .replace("<<STATUS_RULES>>", _status_rules(sem, status_names))
                  .replace("<<STATUS_YES>>", sem.get("yes") or status_names[0])
                  .replace("<<STATUS_NO>>", sem.get("no") or status_names[-1])
                  .replace("<<STATUS_OPEN>>", sem.get("open") or status_names[-1]))

        items = list(evidence.items())
        if config.SAMPLE_N and config.SAMPLE_N < len(items):
            paso = len(items) / config.SAMPLE_N
            idx = sorted({int(k * paso) for k in range(config.SAMPLE_N)})
            items = [items[i] for i in idx]
            print(f"s4: MUESTREO — {len(items)} de {len(evidence)} requisitos "
                  f"(uniformes por el documento). El eval resultante es PARCIAL.")

        # Checkpoint: en una corrida de horas, un cuelgue no puede costar todo el
        # trabajo. Se guarda cada pocos veredictos y al arrancar se reanuda por
        # los que falten (CTSM_RESUME=0 para empezar de cero).
        out = config.EVAL_DIR / stk_path.name
        results = []
        if os.environ.get("CTSM_RESUME", "1") != "0" and out.is_file():
            try:
                results = json.loads(out.read_text(encoding="utf-8"))
                hechos = {r.get("spec_object_id") for r in results}
                antes = len(items)
                items = [it for it in items if it[0] not in hechos]
                if antes != len(items):
                    print(f"s4: REANUDANDO — {len(results)} ya evaluados, "
                          f"quedan {len(items)} de {antes}")
            except Exception as e:  # noqa: BLE001
                print(f"s4: eval previo ilegible ({e}), empiezo de cero")
                results = []

        def _guardar() -> None:
            tmp = out.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(results, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            tmp.replace(out)          # atómico: nunca deja el fichero a medias

        for i, (oid, candidates) in enumerate(items, 1):
            obj = objects[oid]
            chunk_ids = [c["chunk_id"] for c in candidates]
            blocks = []
            for c in candidates:
                ch = chunk_by_id[c["chunk_id"]]
                blocks.append(f"[{ch['chunk_id']}] ({ch['doc']} {ch['section']}, "
                              f"pp.{ch['page_start']}-{ch['page_end']})\n{ch['text']}")
            user = (f"# REQUIREMENT {obj.get('oem_req_id') or oid}\n{obj['text']}\n\n"
                    f"# DOCUMENTATION EXCERPTS ({len(blocks)} chunks)\n\n"
                    + "\n\n---\n\n".join(blocks))
            t0 = time.time()
            verdict = _call(system, user, _schema(status_names, chunk_ids))
            verdict["spec_object_id"] = oid
            verdict["oem_req_id"] = obj.get("oem_req_id")
            results.append(verdict)
            print(f"s4: [{i}/{len(items)}] {oid} → {verdict['status']} "
                  f"({len(verdict.get('evidence') or [])} evidencias, {time.time()-t0:.1f}s)")
            if i % 5 == 0:
                _guardar()

        _guardar()
        print(f"s4: {len(results)} veredictos → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
