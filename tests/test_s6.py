"""s6_verify: la cita que se guarda es siempre texto del manual, y una paráfrasis solo vale
si conserva cifras y negaciones. Sin red, sin modelo.

    python tests/test_s6.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.s6_verify import _verify_evidence  # noqa: E402

TEXTO = ("5.1 Power supplies\nThe device requires a 2.0-to-3.6 V oper-\nating voltage supply (VDD). "
         "An embedded regulator is used to supply the internal 1.8 V digital power.\n"
         "The real-time clock and backup registers can be powered from the VBAT voltage "
         "when the main VDD supply is powered off.")
CHUNK = {"chunk_id": "RM0008-C0100", "doc": "RM0008", "section": "§5.1 Power supplies", "text": TEXTO,
         "page_start": 67, "page_map": [{"offset": 0, "page": 67}, {"offset": TEXTO.index("The real-time"), "page": 68}]}
CHUNKS = {CHUNK["chunk_id"]: CHUNK}
fallos = 0


def check(cond, nombre, detalle=""):
    global fallos
    fallos += not cond
    print(f"  {'ok  ' if cond else 'FALLA'} {nombre}" + (f"  -> {detalle}" if detalle and not cond else ""))


def verificar(quote, chunk_id="RM0008-C0100"):
    return _verify_evidence({"chunk_id": chunk_id, "quote": quote}, CHUNKS)


ok, _ = verificar("The device requires a 2.0-to-3.6 V operating voltage supply (VDD).")
check(ok and ok["literal"] and ok["match_ratio"] == 1.0, "literal pese al guion de partición y el salto de línea", ok)
check(ok and ok["quote"] == "The device requires a 2.0-to-3.6 V operating voltage supply (VDD).",
      "la cita guardada es el texto del manual, con la palabra partida recompuesta", ok and ok["quote"])
check(ok and ok["page"] == 67 and "quote_modelo" not in ok, "página 67 y sin rastro de paráfrasis")

ok, _ = verificar("The real-time clock and backup registers can be powered from the VBAT voltage")
check(ok and ok["literal"] and ok["page"] == 68, "la página sale del offset, no del chunk", ok and ok["page"])

ok, why = verificar("The device requires a 2.0-to-5.5 V operating voltage supply (VDD).")
check(ok is None and "cifras distintas" in why and "5 5" in why and "3 6" in why,
      "una cifra cambiada no cuenta como evidencia, y queda dicho cuál", why)

ok, why = verificar("The device does not require a 2.0-to-3.6 V operating voltage supply (VDD).")
check(ok is None and "negación" in why, "una negación añadida tampoco, aunque se parezca", why)

ok, _ = verificar("The device requires a 2.0-to-3.6 V operating voltage supply VDD.")
check(ok and not ok["literal"], "una paráfrasis con las mismas cifras pasa como aproximada", ok)
check(ok and "(VDD)" in ok["quote"], "y la cita guardada es el texto del manual, no el del modelo", ok and ok["quote"])
check(ok and ok["quote_modelo"].endswith("supply VDD."), "lo que escribió el modelo queda aparte")

ok, why = verificar("Flash memory supports 100 000 write cycles over the full temperature range.")
check(ok is None and "no encontrada" in why, "algo que no está en el manual se descarta", why)

ok, why = verificar("The device requires a 2.0-to-3.6 V operating voltage supply (VDD).", "RM0008-C9999")
check(ok is None and "inexistente" in why, "un chunk que no existe se descarta", why)

print("modo revision: un pasaje que contradiga manda")
from pipeline.s6_verify import _sellar_revision  # noqa: E402

STATUS = {"Compliant", "Not compliant", "Unconfirmed"}
revision = {"status_revisado": "Not compliant", "escalado": True, "juicios": [
    {"chunk_id": "RM0008-C0100", "juicio": "apoya", "quote": "The device requires a 2.0-to-3.6 V oper-\nating voltage supply (VDD)."},
    {"chunk_id": "RM0008-C0100", "juicio": "contradice", "quote": "The real-time clock and backup registers can be powered from the VBAT voltage"},
    {"chunk_id": "RM0008-C0100", "juicio": "irrelevante"},
]}
flags = []
status, analisis, ev = _sellar_revision(revision, "Compliant", "s4 decía que cumple", CHUNKS, STATUS, "Unconfirmed", flags)
check(status == "Not compliant", "aunque un pasaje apoye y s4 dijera «cumple», el que contradice manda", status)
check(len(ev) == 2 and {e["juicio"] for e in ev} == {"apoya", "contradice"}, "las dos citas, con su juicio; la irrelevante fuera")
check(any(f.startswith("revision:Compliant->Not compliant") and "modelo grande" in f for f in flags),
      "queda marcado qué cambió respecto a s4 y quién lo arbitró", flags)
check("s4 decía" not in analisis and "contradiga" in analisis, "el razonamiento de s4 no se queda junto a un veredicto que no sostiene")

flags = []
revision["juicios"][1]["quote"] = "The device is powered from a 12 V automotive battery directly."
status, _, ev = _sellar_revision(revision, "Compliant", "", CHUNKS, STATUS, "Unconfirmed", flags)
check(len(ev) == 1 and any(f.startswith("quote_failed") for f in flags),
      "una cita de la revisión que no está en el manual también se descarta", flags)

print("TODO OK" if not fallos else f"{fallos} FALLOS")
sys.exit(1 if fallos else 0)
