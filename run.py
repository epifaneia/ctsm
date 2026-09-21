"""run — orquestador CTSM: s1→s7 por documento STK. Patrón heredado de reqif-extractor.

Recorre los .reqif de data/inputs/stk_reqif (o los que matcheen un substring) y
procesa los documentos EN PARALELO (config.DOC_WORKERS): cada documento avanza
sus pasos en secuencia como subproceso (mismo CLI que a mano). s2 (docling) es
pesado en CPU/RAM: semáforo a config.S2_CONCURRENCY.

Si un paso falla para un documento, se aborta el resto de pasos de ESE documento
y los demás siguen; al final, resumen de fallos.

Uso:
  python run.py            # todos los STK de data/inputs/stk_reqif
  python run.py STM32      # solo los que matcheen

Notas:
  · SOLO s4 sale a la red (Gemini); s1/s2/s3/s6/s7 son 100% locales.
  · s2 depende de los supplier docs, no del STK: se corre una vez por corpus
    (el orquestador lo lanza si el corpus no existe aún).
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
STEPS = [
    ("s1_parse_stk", "STK ReqIF → stk.json"),
    ("s2_supplier_corpus", "supplier docs → corpus (docling)"),
    ("s3_retrieve", "requisito → evidencia candidata"),
    ("s4_evaluate", "Status + trazabilidad (Gemini)"),
    # s5_config RETIRADO del alcance (stub que devuelve 1): dejarlo aquí abortaba
    # s6 y s7 de todos los documentos. Ver README y docs/PLAN.md.
    ("s6_verify", "guard anti-alucinación + sellado"),
    ("s7_inject", "cirugía sobre el ReqIF original"),
]

_S2_SEM = threading.Semaphore(max(1, config.S2_CONCURRENCY))
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


def _process_doc(stk: Path) -> dict:
    stem = _slug(stk.stem)
    lines: list[str] = [f"### {stk.name}  (stem: {stem})"]
    failure: tuple[str, str, str] | None = None
    try:
        for script, desc in STEPS:
            t0 = time.time()
            if script == "s2_supplier_corpus":
                with _S2_SEM:
                    ok, out = _run_step(script, stem)
            else:
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
    only = sys.argv[1] if len(sys.argv) > 1 else None
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
    print(f"== run: {len(stks)} STK(s), {len(STEPS)} pasos, {workers} doc(s) en paralelo ==")
    failures: list[tuple[str, str, str]] = []
    t_total = time.time()

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(_process_doc, stk) for stk in stks]
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
    print(f"  ✓ {len(stks)} documento(s) completaron los {len(STEPS)} pasos.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
