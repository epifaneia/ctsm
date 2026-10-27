"""grabar_demo — empaqueta una ejecución REAL del pipeline como demo de la interfaz.

    python run.py STM32 > run.log
    python ui/grabar_demo.py stm32 run.log [fixture.json] --machine "RTX 2060 6 GB"

Lee lo que el pipeline dejó en data/ (stk.json, results.json) y los tiempos del
log de run.py, y escribe ui/demo/<nombre>/. Nada se inventa ni se retoca: la
demo reproduce esos veredictos, esas citas y esos tiempos (acelerados al
reproducir, y la interfaz lo dice). Las rutas locales no se guardan.

Lo que se publica de la documentación del proveedor son las citas cortas que el
pipeline ya escribe en el ReqIF; los chunks y el PDF no se copian.
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path

UI = Path(__file__).resolve().parent
ROOT = UI.parent
sys.path.insert(0, str(ROOT))
import config  # noqa: E402

COVERAGE_TO_ROLE = {"YES": "yes", "NO": "no", "TBD": "open"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("run_log", type=Path)
    ap.add_argument("fixture", type=Path, nargs="?")
    ap.add_argument("--machine", default="")
    a = ap.parse_args()

    log = a.run_log.read_text(encoding="utf-8")
    m = re.search(r"### (\S+\.reqif)\s+\(stem: (\S+)\)", log)
    if not m:
        print("grabar_demo: el log no es de run.py")
        return 1
    reqif, stem = m.groups()
    steps = {s: float(sec) for s, sec in re.findall(r"\[OK \] (s\d\w+)\s+.*?\(\s*([\d.]+)s\)", log)}
    s4 = [float(x) for x in re.findall(r"s4: \[\d+/\d+\] .*?, ([\d.]+)s\)", log)]
    engine = re.search(r"s4: motor = (\S+)", log)
    if not s4 or "s7_inject" not in steps:
        print("grabar_demo: la ejecución no llegó a s7; no se graba una demo incompleta")
        return 1

    results = json.loads((config.RESULTS_DIR / f"{stem}.json").read_text(encoding="utf-8"))
    results["stk"] = Path(str(results.get("stk", ""))).name    # sin rutas locales
    stk = json.loads((config.STK_JSON_DIR / f"{stem}.json").read_text(encoding="utf-8"))
    stk = {"objects": [{"identifier": o["identifier"], "text": o.get("text") or ""} for o in stk["objects"]]}

    out = UI / "demo" / a.name
    out.mkdir(parents=True, exist_ok=True)
    docs = sorted({e["doc"] for r in results["results"] for e in r.get("evidence") or []})
    timeline = {
        "stem": stem, "reqif": reqif, "supplier_docs": " · ".join(f"{d}.pdf" for d in docs),
        "engine": (engine.group(1) if engine else "?").replace("ollama:", "ollama · "),
        "recorded": datetime.date.today().isoformat(), "machine": a.machine,
        "total": len(results["results"]), "total_seconds": round(sum(steps.values()), 1),
        "steps": {**{k: v for k, v in steps.items() if k != "s4_evaluate"}, "s4_schema": 0.2},
        "s4_per_requirement": s4,
        "custody": {"calls": len(s4), "left_machine": 0 if "AIR-GAP" in log else len(s4),
                    "model_seconds": round(sum(s4), 1)},
    }
    (out / "timeline.json").write_text(json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "stk.json").write_text(json.dumps(stk, ensure_ascii=False, indent=2), encoding="utf-8")
    if a.fixture:
        fx = json.loads(a.fixture.read_text(encoding="utf-8"))
        truth = {r["req_id"]: COVERAGE_TO_ROLE[r["coverage"]] for r in fx["requisitos"]}
        (out / "truth.json").write_text(json.dumps(truth, indent=2), encoding="utf-8")
    print(f"grabar_demo: {out.relative_to(ROOT)} · {len(s4)} requisitos · {timeline['engine']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
