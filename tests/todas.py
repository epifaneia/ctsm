"""Todas las pruebas, sin red ni modelo:  python tests/todas.py"""
import os
import subprocess
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
env = dict(os.environ, PYTHONIOENCODING="utf-8")
fallos = 0
for prueba in sorted(AQUI.glob("test_*.py")):
    r = subprocess.run([sys.executable, str(prueba)], capture_output=True, text=True, encoding="utf-8", env=env)
    ok = r.returncode == 0
    fallos += not ok
    print(f"{'ok   ' if ok else 'FALLA'} {prueba.stem}")
    if not ok:
        print((r.stdout + r.stderr).strip()[-1500:])
print("TODO VERDE" if not fallos else f"{fallos} fichero(s) con fallos")
sys.exit(1 if fallos else 0)
