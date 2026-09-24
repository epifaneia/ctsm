"""score_vs_fixture — scoring de results.json contra el ground truth de un fixture.

El scoring que s6 promete en su docstring NUNCA se ejecuta: s6 lee
`ground_truth` de los objetos del stk.json, pero build_demo_stk ignora el campo
`coverage` del fixture (lo dice en su línea 17) y s1 no puede recuperar lo que
no está en el ReqIF. Resultado: la cadena fixture → ReqIF → stk.json → s6 está
rota y el scoring se salta en silencio.

Esta herramienta puentea el hueco por fuera, sin tocar el ReqIF (que es sagrado)
ni el contrato de results.json: compara directamente results ↔ fixture.

Uso:  python tools/score_vs_fixture.py <stem> <fixture.json> [results_a_comparar.json]

El tercer argumento es opcional: un results.json de otra corrida (p.ej. otro
modelo) para comparativa lado a lado.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402

# coverage del fixture → rol semántico (el mismo mapeo yes/no/open de s1)
COVERAGE_TO_ROLE = {"YES": "yes", "NO": "no", "TBD": "open"}
# status del STK → rol. demo: Compliant / Not compliant / Unconfirmed
STATUS_TO_ROLE = {"Compliant": "yes", "Not compliant": "no", "Unconfirmed": "open"}


def _load_results(path: Path) -> dict[str, dict]:
    d = json.loads(path.read_text(encoding="utf-8"))
    # clave: el OEM Req ID si el STK lo trae; si no, el IDENTIFIER del SPEC-OBJECT (demo STK)
    return {(r.get("oem_req_id") or r["spec_object_id"]): r for r in d["results"]}


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    stem, fixture = sys.argv[1], Path(sys.argv[2])
    fx = json.loads(fixture.read_text(encoding="utf-8"))
    gt = {r["req_id"]: COVERAGE_TO_ROLE[r["coverage"]] for r in fx["requisitos"]}

    main_path = next(config.RESULTS_DIR.glob(f"*{stem}*.json"), None)
    if main_path is None:
        print(f"no hay results para '{stem}' en {config.RESULTS_DIR}")
        return 1
    A = _load_results(main_path)
    B = _load_results(Path(sys.argv[3])) if len(sys.argv) > 3 else None

    w = 26
    head = f"{'requisito':20s} {'esperado':9s} {main_path.stem[:w]:{w}s}"
    if B:
        head += f" {'(comparativa)':{w}s}"
    print(head); print("-" * len(head))

    ok_a = ok_b = 0
    falsos_yes: list[str] = []
    for rid in sorted(gt):
        exp = gt[rid]
        if rid not in A:
            print(f"{rid:20s} {exp:9s} {'AUSENTE':{w}s}"); continue
        sa = A[rid]["status"]
        hit_a = STATUS_TO_ROLE.get(sa) == exp
        ok_a += hit_a
        if STATUS_TO_ROLE.get(sa) == "yes" and exp != "yes":
            falsos_yes.append(rid)
        row = f"{rid:20s} {exp:9s} {sa + (' OK' if hit_a else ' FALLO'):{w}s}"
        if B:
            sb = B.get(rid, {}).get("status", "AUSENTE")
            hit_b = STATUS_TO_ROLE.get(sb) == exp
            ok_b += hit_b
            row += f" {sb + (' OK' if hit_b else ' FALLO'):{w}s}"
        if A[rid].get("flags"):
            row += "  ⚑" + ";".join(str(f) for f in A[rid]["flags"])[:70]
        print(row)

    print("-" * len(head))
    print(f"aciertos: {ok_a}/{len(gt)}" + (f"   comparativa: {ok_b}/{len(gt)}" if B else ""))
    # El único error inaceptable del proyecto: declarar conforme lo que no lo es.
    print(f"falsos '{[k for k,v in STATUS_TO_ROLE.items() if v=='yes'][0]}': "
          f"{falsos_yes or 'NINGUNO'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
