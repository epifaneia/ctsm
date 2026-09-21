"""s5_review — revisión por pasaje sobre lo que s4 ya decidió. LLM (barato).

s4 pregunta "¿cuál es tu veredicto y qué citas lo apoyan?", y el modelo responde
con las mínimas para justificarse: de 10 pasajes candidatos cita entre 0 y 3. Eso
deja tres agujeros medidos en la corrida sobre dos STK reales:

  · Un pasaje que CONTRADIGA el requisito puede no mencionarse nunca. Nadie se
    entera. Es el más grave: un manual de cientos de páginas escrito por partes
    puede contradecirse, y detectarlo es parte del valor de auditar.
  · Las citas se escriben a mano y se parafrasean (41 de 550 no son literales).
  · Al descartar una cita, el razonamiento que se apoyaba en ella sobrevive
    intacto — un veredicto puede quedar sostenido por evidencia que ya no está.

Este paso invierte la pregunta: por CADA pasaje candidato, ¿apoya, contradice o
es irrelevante? Y el veredicto lo compone el código con una regla fija:

    UN SOLO PASAJE QUE CONTRADIGA basta para que el requisito quede como "no",
    por muchos que lo apoyen. La contradicción se hace explícita, no se promedia.

El modelo no escribe citas: devuelve ÍNDICES de las unidades del pasaje y el
código copia el texto del original (utils/citables). Literal por construcción.

Cascada: el grueso lo hace un modelo pequeño — la tarea es mecánica y el trabajo
difícil ya está hecho. Pero un modelo pequeño no enmienda al grande sin permiso:
todo requisito cuyo veredicto agregado DIFIERA del de s4 se reevalúa con el
modelo grande, y su palabra es la definitiva.

Entrada:  stk_json + evidence (s3) + corpus (s2) + eval (s4)
Salida:   config.REVIEW_DIR/<stem>.json   (s6 lo prefiere al eval crudo)

Uso:  python pipeline/s5_review.py [substring] [--solo-desacuerdos]
"""
from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
from clients import gemini, ollama  # noqa: E402
from utils.citables import reconstruir, trocear  # noqa: E402

JUICIOS = ["apoya", "contradice", "irrelevante"]

SYSTEM = """You are a requirements auditor. For EVERY excerpt you are given, decide
whether it SUPPORTS, CONTRADICTS or is IRRELEVANT to the requirement.

  supports    - the excerpt states that the product does what the requirement asks
  contradicts - the excerpt states something incompatible with the requirement
                (a different value, a lower limit, an explicit inability)
  irrelevant  - the excerpt does not settle the question either way

Judge each excerpt ON ITS OWN. Do not skip any: return exactly one verdict per
excerpt, using the excerpt id given to you.

Quote by NUMBER, never by writing text: list the sentence numbers that justify
your verdict. For 'irrelevant' return an empty list.

Be strict with "contradicts": choose it only when the text really says something
incompatible, not when it merely fails to mention the topic. Silence is
'irrelevant', never 'contradicts'."""


def _schema(chunk_ids: list[str]) -> dict:
    return {
        "type": "OBJECT",
        "properties": {
            "juicios": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "pasaje": {"type": "STRING", "enum": chunk_ids},
                        "juicio": {"type": "STRING", "enum": JUICIOS},
                        "frases": {"type": "ARRAY", "items": {"type": "INTEGER"}},
                    },
                    "required": ["pasaje", "juicio", "frases"],
                },
            }
        },
        "required": ["juicios"],
    }


def _prompt(req_texto: str, pasajes: list[tuple[str, dict, list[dict]]]) -> str:
    partes = [f"# REQUIREMENT\n{req_texto}\n", "# EXCERPTS"]
    for cid, ch, unidades in pasajes:
        partes.append(f"\n## {cid}  ({ch['doc']} {ch.get('section','')}, "
                      f"pp.{ch['page_start']}-{ch['page_end']})")
        for u in unidades:
            partes.append(f"[{u['i']}] {u['texto']}")
    return "\n".join(partes)


def _llamar(system: str, user: str, schema: dict, modelo: str, backend: str) -> dict:
    ultimo: Exception | None = None
    for intento in range(3):
        try:
            if backend == "ollama":
                return ollama.generate_json_schema(
                    base_url=config.OLLAMA_BASE_URL, model=modelo,
                    user_text=user, system_instruction=system,
                    response_schema=schema, temperature=0.1,
                    num_ctx=config.OLLAMA_NUM_CTX, num_gpu=config.OLLAMA_NUM_GPU,
                    num_thread=config.OLLAMA_NUM_THREAD, timeout_s=config.LLM_TIMEOUT)
            return gemini.generate_json_schema(
                api_key=config.GEMINI_API_KEY, model=modelo, user_text=user,
                system_instruction=system, response_schema=schema,
                temperature=0.1, timeout_s=config.LLM_TIMEOUT)
        except ValueError as e:
            raise RuntimeError(f"{modelo}: {e}") from e     # truncado: no reintentar
        except Exception as e:  # noqa: BLE001
            ultimo = e
            time.sleep(5 * (intento + 1))
    raise RuntimeError(f"{modelo} falló tras 3 intentos: {ultimo}")


def _agregar(juicios: list[dict], sem: dict, enum: list[str]) -> str:
    """La regla, en código y no en el prompt: un 'contradice' manda."""
    abierto = sem.get("open") or (enum[-1] if enum else config.STATUS_DEFAULT)
    if any(j["juicio"] == "contradice" for j in juicios):
        return sem.get("no") or abierto
    if any(j["juicio"] == "apoya" for j in juicios):
        return sem.get("yes") or abierto
    return abierto


def revisar_requisito(req_texto: str, candidatos: list[str], chunk_by_id: dict,
                      modelo: str, backend: str) -> list[dict]:
    """→ juicios con la cita ya reconstruida del original y su offset."""
    pasajes = []
    for cid in candidatos:
        ch = chunk_by_id.get(cid)
        if ch:
            pasajes.append((cid, ch, trocear(ch["text"])))
    if not pasajes:
        return []
    unidades_por_id = {cid: u for cid, _, u in pasajes}

    salida = _llamar(SYSTEM, _prompt(req_texto, pasajes),
                     _schema([cid for cid, _, _ in pasajes]), modelo, backend)

    juicios: list[dict] = []
    vistos: set[str] = set()
    for j in salida.get("juicios") or []:
        cid = j.get("pasaje")
        if cid not in unidades_por_id or cid in vistos:
            continue
        vistos.add(cid)
        ch = chunk_by_id[cid]
        item = {"chunk_id": cid, "doc": ch["doc"], "section": ch.get("section", ""),
                "juicio": j.get("juicio"), "frases": j.get("frases") or []}
        if item["juicio"] in ("apoya", "contradice"):
            comp = reconstruir(ch["text"], unidades_por_id[cid], item["frases"])
            if comp is None:
                # sin frases que lo respalden, un juicio afirmativo no vale nada
                item["juicio"] = "irrelevante"
                item["frases"] = []
            else:
                item["quote"], item["offset"] = comp
        juicios.append(item)
    return juicios


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    only = args[0] if args else None
    backend = config.LLM_BACKEND
    if backend not in ("ollama", "gemini"):
        print(f"s5: CTSM_LLM_BACKEND='{backend}' no válido")
        return 1
    chico = config.REVIEW_MODEL if backend == "ollama" else config.GEMINI_MODEL
    grande = config.OLLAMA_MODEL if backend == "ollama" else config.GEMINI_MODEL
    print(f"s5: revisión con {chico}, escalada a {grande}"
          + ("  [AIR-GAP]" if backend == "ollama" else "  [!] sale a la red"))

    corpus = json.loads((config.CORPUS_DIR / "corpus.json").read_text(encoding="utf-8"))
    chunk_by_id = {c["chunk_id"]: c for c in corpus["chunks"]}

    stk_jsons = sorted(config.STK_JSON_DIR.glob("*.json"))
    if only:
        stk_jsons = [p for p in stk_jsons if only.lower() in p.stem.lower()]
    if not stk_jsons:
        print("s5: no hay stk.json que matcheen")
        return 1

    config.REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    for stk_path in stk_jsons:
        stk = json.loads(stk_path.read_text(encoding="utf-8"))
        ev_path = config.EVIDENCE_DIR / stk_path.name
        eval_path = config.EVAL_DIR / stk_path.name
        if not ev_path.is_file() or not eval_path.is_file():
            print(f"s5: faltan evidence o eval de {stk_path.stem} — ¿corrieron s3 y s4?")
            return 1
        evidencia = {e["spec_object_id"]: [c["chunk_id"] for c in e["candidates"]]
                     for e in json.loads(ev_path.read_text(encoding="utf-8"))}
        previo = {r["spec_object_id"]: r
                  for r in json.loads(eval_path.read_text(encoding="utf-8"))}
        objetos = {o["identifier"]: o for o in stk["objects"]}
        sem = stk.get("status_semantics") or {}
        enum = list(stk["status_enum_values"])

        out = config.REVIEW_DIR / stk_path.name
        hechos: dict[str, dict] = {}
        if os.environ.get("CTSM_RESUME", "1") != "0" and out.is_file():
            try:
                hechos = {r["spec_object_id"]: r
                          for r in json.loads(out.read_text(encoding="utf-8"))}
                if hechos:
                    print(f"s5: REANUDANDO — {len(hechos)} ya revisados")
            except Exception:  # noqa: BLE001
                hechos = {}

        pendientes = [oid for oid in evidencia if oid not in hechos]

        def tarea(oid: str) -> dict:
            obj = objetos.get(oid) or {}
            juicios = revisar_requisito(obj.get("text") or "", evidencia[oid],
                                        chunk_by_id, chico, backend)
            agregado = _agregar(juicios, sem, enum)
            anterior = (previo.get(oid) or {}).get("status")
            return {"spec_object_id": oid, "oem_req_id": obj.get("oem_req_id"),
                    "juicios": juicios, "status_revisado": agregado,
                    "status_s4": anterior, "coincide": agregado == anterior,
                    "revisado_por": chico, "escalado": False}

        t0 = time.time()
        hilos = max(1, config.REVIEW_WORKERS) if backend == "ollama" else 4
        with ThreadPoolExecutor(max_workers=hilos) as ex:
            for n, res in enumerate(ex.map(tarea, pendientes), 1):
                hechos[res["spec_object_id"]] = res
                marca = "=" if res["coincide"] else "≠"
                print(f"s5: [{n}/{len(pendientes)}] {res['spec_object_id'].split('_')[-1]} "
                      f"{marca} {res['status_s4']} → {res['status_revisado']}")
                if n % 5 == 0:
                    tmp = out.with_suffix(".json.tmp")
                    tmp.write_text(json.dumps(list(hechos.values()), ensure_ascii=False,
                                              indent=2), encoding="utf-8")
                    tmp.replace(out)

        # --- escalada: el modelo grande arbitra donde el pequeño discrepa ---
        desacuerdos = [r for r in hechos.values() if not r["coincide"] and not r["escalado"]]
        print(f"s5: {len(desacuerdos)} desacuerdo(s) de {len(hechos)} "
              f"({100*len(desacuerdos)/max(1,len(hechos)):.1f}%) → escalando a {grande}")
        for n, r in enumerate(desacuerdos, 1):
            oid = r["spec_object_id"]
            obj = objetos.get(oid) or {}
            juicios = revisar_requisito(obj.get("text") or "", evidencia[oid],
                                        chunk_by_id, grande, backend)
            r["juicios"] = juicios
            r["status_revisado"] = _agregar(juicios, sem, enum)
            r["coincide"] = r["status_revisado"] == r["status_s4"]
            r["revisado_por"] = grande
            r["escalado"] = True
            print(f"s5: escalada [{n}/{len(desacuerdos)}] {oid.split('_')[-1]} "
                  f"→ {r['status_revisado']}")

        out.write_text(json.dumps(list(hechos.values()), ensure_ascii=False, indent=2),
                       encoding="utf-8")
        contra = sum(1 for r in hechos.values()
                     for j in r["juicios"] if j["juicio"] == "contradice")
        print(f"s5: {len(hechos)} revisados en {time.time()-t0:.0f}s → {out.name}")
        print(f"s5: {contra} pasaje(s) marcados como contradicción")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
