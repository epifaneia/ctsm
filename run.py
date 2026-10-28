"""run — orquestador CTSM: s0→s7 por documento STK. Patrón heredado de reqif-extractor.

Recorre los .reqif de data/inputs/stk_reqif (o los que matcheen un substring) y
procesa los documentos EN PARALELO (config.DOC_WORKERS): cada documento avanza
sus pasos en secuencia como subproceso (mismo CLI que a mano).

s2 depende de los manuales del proveedor, no del STK: se lanza UNA vez, antes de
los documentos, y todos leen el mismo corpus.

Si un paso falla para un documento, se aborta el resto de pasos de ESE documento
y los demás siguen; al final, resumen de fallos.

Tres modos, el mismo contrato de salida (results.json → s7):
  · veredicto  (por defecto) s4 decide el estado y cita; s6 verifica cada cita.
  · revision   además, s5_review juzga CADA pasaje candidato (apoya / contradice /
               irrelevante) con un modelo pequeño y el código aplica la regla: un
               solo pasaje que contradiga basta para el "no". s6 sella eso.
  · evidencia  sin modelo y sin veredicto: s4_evidence ancla los pasajes candidatos
               a su página y deja el estado abierto para que decida el ingeniero.

Uso:
  python run.py                          # todos los STK, modo veredicto
  python run.py STM32                    # solo los que matcheen
  python run.py STM32 --modo revision

Notas:
  · Solo s4 y s5 llaman a un modelo: Ollama en local por defecto; Gemini si
    CTSM_LLM_BACKEND=gemini. s0/s1/s2/s3/s6/s7 son código, sin red.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import config  # noqa: E402

PIPELINE = ROOT / "pipeline"
CORPUS = ("s2_supplier_corpus", "manuales del proveedor → corpus")
_INICIO = [
    # s0 es idempotente: si el ReqIF ya declara los campos objetivo, lo copia tal cual.
    ("s0_prepare_stk", "campos objetivo en el ReqIF (esquema)"),
    ("s1_parse_stk", "STK ReqIF → stk.json"),
    ("s3_retrieve", "requisito → evidencia candidata"),
]
_FIN = [("s6_verify", "guard anti-alucinación + sellado"), ("s7_inject", "cirugía sobre el ReqIF original")]
# s5_config está RETIRADO del alcance (stub que devuelve 1). Ver README y docs/PLAN.md.
MODOS = {
    "veredicto": _INICIO + [("s4_evaluate", "estado + citas (modelo)")] + _FIN,
    "revision": _INICIO + [("s4_evaluate", "estado + citas (modelo)"),
                           ("s5_review", "juicio por pasaje (modelo)")] + _FIN,
    "evidencia": _INICIO + [("s4_evidence", "pasajes anclados, sin veredicto"),
                            ("s7_inject", "cirugía sobre el ReqIF original")],
}
STEPS = MODOS["veredicto"]

_PRINT_LOCK = threading.Lock()


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")


def _run_step(script: str, arg: str) -> tuple[bool, str]:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        proc = subprocess.run(
            [sys.executable, str(PIPELINE / f"{script}.py"), arg],
            capture_output=True, text=True, encoding="utf-8", env=env,
            cwd=str(ROOT), timeout=5400,
        )
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT (90 min)"
    out = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr.strip() else "")
    return proc.returncode == 0, out.strip()


def _process_doc(stk: Path, steps: list[tuple[str, str]]) -> dict:
    stem = _slug(stk.stem)
    lines: list[str] = [f"### {stk.name}  (stem: {stem})"]
    failure: tuple[str, str, str] | None = None
    try:
        for script, desc in steps:
            t0 = time.time()
            ok, out = _run_step(script, stem)
            dt = time.time() - t0
            lines.append(f"  [{'OK ' if ok else 'FAIL'}] {script:20s} {desc:38s} ({dt:5.1f}s)")
            for line in out.splitlines():
                lines.append(f"         | {line}")
            if not ok:
                failure = (stem, script, out.splitlines()[-1] if out else "sin salida")
                lines.append(f"         ! abortando pasos restantes de {stem}")
                break
    except Exception as e:  # noqa: BLE001
        failure = (stem, "run", f"excepción del orquestador: {e}")
        lines.append(f"  [FAIL] excepción inesperada: {e}")
    return {"stem": stem, "lines": lines, "failure": failure}


def main() -> int:
    # --- cable 1: identidad. El pipeline no corre de forma anónima. ---
    from custodia.identity import require_actor, MissingActor
    try:
        actor = require_actor()
    except MissingActor as e:
        print(f"run: {e}")
        return 2
    print(f"run: actor {actor}")
    args = sys.argv[1:]
    modo = "veredicto"
    if "--modo" in args:
        i = args.index("--modo")
        modo = args[i + 1] if i + 1 < len(args) else ""
        del args[i:i + 2]
    if modo not in MODOS:
        print(f"run: --modo {modo!r} no existe ({' | '.join(MODOS)})")
        return 2
    steps = MODOS[modo]
    os.environ["CTSM_MODO"] = modo          # s6 sella la revisión por pasaje solo en modo revision
    only = args[0] if args else None
    # recursivo como s1: los .reqifz se descomprimen en su propia carpeta (con
    # files/ al lado) y un glob plano no los vería.
    stks = sorted(config.STK_INPUTS_DIR.glob("**/*.reqif"))
    if only:
        stks = [p for p in stks if only.lower() in p.name.lower()
                or only.lower() in _slug(p.stem).lower()]
    if not stks:
        print(f"No hay .reqif en {config.STK_INPUTS_DIR}" + (f" que matcheen '{only}'" if only else ""))
        return 1

    workers = max(1, min(config.DOC_WORKERS, len(stks)))
    print(f"== run: {len(stks)} STK(s), modo {modo}, {len(steps)} pasos + corpus, "
          f"{workers} doc(s) en paralelo ==")
    failures: list[tuple[str, str, str]] = []
    t_total = time.time()

    # el corpus, una vez y antes que nadie: los documentos lo leen en paralelo
    t0 = time.time()
    ok, out = _run_step(CORPUS[0], "")
    print(f"  [{'OK ' if ok else 'FAIL'}] {CORPUS[0]:20s} {CORPUS[1]:38s} ({time.time() - t0:5.1f}s)")
    for line in out.splitlines():
        print(f"         | {line}")
    if not ok:
        print("\n== resumen: sin corpus no hay nada que auditar ==")
        return 1

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(_process_doc, stk, steps) for stk in stks]
        for fut in as_completed(futures):
            r = fut.result()
            with _PRINT_LOCK:
                print()
                for line in r["lines"]:
                    print(line)
            if r["failure"]:
                failures.append(r["failure"])

    print(f"\n== resumen ({time.time() - t_total:.1f}s) ==")
    if failures:
        print(f"  {len(failures)} documento(s) con fallo:")
        for stem, script, err in sorted(failures):
            print(f"  ✗ {stem} en {script}: {err[:160]}")
        return 1
    print(f"  ✓ {len(stks)} documento(s) completaron los {len(steps)} pasos (modo {modo}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
