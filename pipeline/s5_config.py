"""s5_config — CASO DE USO 2: extracción de configuración. LLM (gasta API).

SOLO para requisitos con status Accepted / Accepted with deviation: peinar la
evidencia para rescatar el "cómo" — parámetros técnicos, registros de memoria,
valores hexadecimales, instrucciones operativas — VERBATIM y con cita.

Ej.: status = Accepted with deviation (30 slots de 50 pedidos) → config =
"escribir 0xFF en HSM_NUMBER_OF_POSITIONS @ 0xFACC500 para habilitar los 30".

Prompt: prompts/extraer_config.txt. Si el manual no da parámetros: config=null
explícito (no rellenar por rellenar).

Entrada:  results parcial de s4 + evidence + corpus
Salida:   config.RESULTS_DIR/<stem>.json (completa el campo config)

Uso:  python pipeline/s5_config.py [substring]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402


def main() -> int:
    print("s5_config: NO IMPLEMENTADO — esqueleto. Ver docstring y docs/PLAN.md.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
