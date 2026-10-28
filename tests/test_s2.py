"""s2_supplier_corpus: el nombre de la sección sale del índice del PDF. Sin red, sin modelo.

    python tests/test_s2.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.s2_supplier_corpus import _chunk_doc, _toc_anchors  # noqa: E402

# Una página de registros como las de RM0008: un "0" suelto de un diagrama de bits
# seguido de un nombre de campo parece una cabecera, y antes daba "§0 HSICAL[7:0]".
PROSA = "The HSE crystal can be switched on and off using the HSEON bit in the clock control register."
PAGINAS = [
    {"page": 10, "lines": ["8.2.1", "HSE clock", PROSA, PROSA, PROSA]},
    {"page": 11, "lines": [PROSA, "0", "HSICAL[7:0]", PROSA, PROSA, "8.3.1 Clock control register (RCC_CR)", PROSA, PROSA, PROSA]},
]
TOC = [[1, "8 Reset and clock control", 10], [3, "8.2.1 HSE clock", 10],
       [4, "External crystal (HSE crystal)", 10],            # sin número: no da nombre
       [3, "8.3.1 Clock control register (RCC_CR)", 11]]
fallos = 0


def check(cond, nombre, detalle=""):
    global fallos
    fallos += not cond
    print(f"  {'ok  ' if cond else 'FALLA'} {nombre}" + (f"  -> {detalle}" if detalle and not cond else ""))


anchors = _toc_anchors(PAGINAS, TOC)
check([a[2] for a in anchors] == ["§8 Reset and clock control", "§8.2.1 HSE clock", "§8.3.1 Clock control register (RCC_CR)"],
      "solo las entradas numeradas del índice dan nombre", anchors)
check(anchors[1][:2] == (10, 0) and anchors[2][:2] == (11, 5),
      "cada sección se sitúa en su línea de la página", anchors)

con = _chunk_doc("RM0008", PAGINAS, anchors)
sin = _chunk_doc("RM0008", PAGINAS)
secciones = [c["section"] for c in con]
check(secciones[0] == "§8.2.1 HSE clock", "dos secciones en el mismo punto: gana la más concreta", secciones)
check(not any(s.startswith("§0") for s in secciones), "ningún «§0 …» de un diagrama de bits", secciones)
check(secciones[-1] == "§8.3.1 Clock control register (RCC_CR)", "el último trozo cae en su sección", secciones)
check([c["chunk_id"] for c in con] == [c["chunk_id"] for c in sin] and [c["text"] for c in con] == [c["text"] for c in sin],
      "el índice cambia solo los nombres: mismos cortes, mismos ids")
check(any(s.startswith("§0") for s in (c["section"] for c in sin)), "sin índice se mantiene el comportamiento anterior")

print("TODO OK" if not fallos else f"{fallos} FALLO(S)")
sys.exit(1 if fallos else 0)
