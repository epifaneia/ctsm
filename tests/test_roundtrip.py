"""roundtrip_diff contra sabotajes: el fichero de salida solo puede cambiar en los tres
campos objetivo. Cada sabotaje es algo que un s7 descuidado (o un modelo) podría hacer;
el diff tiene que detectarlos todos, y una salida legítima tiene que pasar. Sin red.

    python tests/test_roundtrip.py
"""
import copy
import sys
import tempfile
from pathlib import Path

from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.roundtrip_diff import diff_files  # noqa: E402

RQ = "http://www.omg.org/spec/ReqIF/20110401/reqif.xsd"
XH = "http://www.w3.org/1999/xhtml"
Q = lambda t: f"{{{RQ}}}{t}"  # noqa: E731

# Un ReqIF mínimo con lo que trae un export de Polarion: tipos, enum de estado, tres
# requisitos con su texto, los tres campos objetivo declarados y vacíos, y jerarquía.
ORIGINAL = f"""<?xml version="1.0" encoding="UTF-8"?>
<REQ-IF xmlns="{RQ}" xmlns:xhtml="{XH}">
  <THE-HEADER><REQ-IF-HEADER IDENTIFIER="hdr"><CREATION-TIME>2026-07-15T12:00:00</CREATION-TIME><TITLE>Prueba</TITLE></REQ-IF-HEADER></THE-HEADER>
  <CORE-CONTENT><REQ-IF-CONTENT>
    <DATATYPES>
      <DATATYPE-DEFINITION-XHTML IDENTIFIER="dt-xhtml" LAST-CHANGE="2026-07-15T12:00:00"/>
      <DATATYPE-DEFINITION-ENUMERATION IDENTIFIER="dt-status" LAST-CHANGE="2026-07-15T12:00:00">
        <SPECIFIED-VALUES>
          <ENUM-VALUE IDENTIFIER="ev-yes" LONG-NAME="Compliant"/>
          <ENUM-VALUE IDENTIFIER="ev-no" LONG-NAME="Not compliant"/>
          <ENUM-VALUE IDENTIFIER="ev-open" LONG-NAME="Unconfirmed"/>
        </SPECIFIED-VALUES>
      </DATATYPE-DEFINITION-ENUMERATION>
    </DATATYPES>
    <SPEC-TYPES>
      <SPEC-OBJECT-TYPE IDENTIFIER="sot-req" LONG-NAME="Requirement" LAST-CHANGE="2026-07-15T12:00:00">
        <SPEC-ATTRIBUTES>
          <ATTRIBUTE-DEFINITION-XHTML IDENTIFIER="ad-text" LONG-NAME="ReqIF.Text"><TYPE><DATATYPE-DEFINITION-XHTML-REF>dt-xhtml</DATATYPE-DEFINITION-XHTML-REF></TYPE></ATTRIBUTE-DEFINITION-XHTML>
          <ATTRIBUTE-DEFINITION-ENUMERATION IDENTIFIER="ad-status" LONG-NAME="Status" MULTI-VALUED="false"><TYPE><DATATYPE-DEFINITION-ENUMERATION-REF>dt-status</DATATYPE-DEFINITION-ENUMERATION-REF></TYPE></ATTRIBUTE-DEFINITION-ENUMERATION>
          <ATTRIBUTE-DEFINITION-XHTML IDENTIFIER="ad-rationale" LONG-NAME="Rationale"><TYPE><DATATYPE-DEFINITION-XHTML-REF>dt-xhtml</DATATYPE-DEFINITION-XHTML-REF></TYPE></ATTRIBUTE-DEFINITION-XHTML>
          <ATTRIBUTE-DEFINITION-XHTML IDENTIFIER="ad-comments" LONG-NAME="Comments from/to External"><TYPE><DATATYPE-DEFINITION-XHTML-REF>dt-xhtml</DATATYPE-DEFINITION-XHTML-REF></TYPE></ATTRIBUTE-DEFINITION-XHTML>
        </SPEC-ATTRIBUTES>
      </SPEC-OBJECT-TYPE>
    </SPEC-TYPES>
    <SPEC-OBJECTS>
      {''.join(f'''<SPEC-OBJECT IDENTIFIER="req-{i}" LAST-CHANGE="2026-07-15T12:00:00"><VALUES>
        <ATTRIBUTE-VALUE-XHTML><DEFINITION><ATTRIBUTE-DEFINITION-XHTML-REF>ad-text</ATTRIBUTE-DEFINITION-XHTML-REF></DEFINITION><THE-VALUE><xhtml:div>Requisito {i}: the device shall do thing {i}.</xhtml:div></THE-VALUE></ATTRIBUTE-VALUE-XHTML>
      </VALUES><TYPE><SPEC-OBJECT-TYPE-REF>sot-req</SPEC-OBJECT-TYPE-REF></TYPE></SPEC-OBJECT>''' for i in (1, 2, 3))}
    </SPEC-OBJECTS>
    <SPECIFICATIONS><SPECIFICATION IDENTIFIER="spec" LAST-CHANGE="2026-07-15T12:00:00"><CHILDREN>
      {''.join(f'<SPEC-HIERARCHY IDENTIFIER="sh-{i}" LAST-CHANGE="2026-07-15T12:00:00"><OBJECT><SPEC-OBJECT-REF>req-{i}</SPEC-OBJECT-REF></OBJECT></SPEC-HIERARCHY>' for i in (1, 2, 3))}
    </CHILDREN></SPECIFICATION></SPECIFICATIONS>
  </REQ-IF-CONTENT></CORE-CONTENT>
</REQ-IF>"""


def _so(root, i):
    return root.find(f".//{Q('SPEC-OBJECT')}[@IDENTIFIER='req-{i}']")


def _escribir(root, i, estado="ev-yes", rationale_divs=1):
    """Lo que hace s7: rellena estado y rationale de un requisito, y nada más."""
    values = _so(root, i).find(Q("VALUES"))
    av = etree.SubElement(values, Q("ATTRIBUTE-VALUE-ENUMERATION"))
    etree.SubElement(etree.SubElement(av, Q("DEFINITION")), Q("ATTRIBUTE-DEFINITION-ENUMERATION-REF")).text = "ad-status"
    etree.SubElement(etree.SubElement(av, Q("VALUES")), Q("ENUM-VALUE-REF")).text = estado
    av = etree.SubElement(values, Q("ATTRIBUTE-VALUE-XHTML"))
    etree.SubElement(etree.SubElement(av, Q("DEFINITION")), Q("ATTRIBUTE-DEFINITION-XHTML-REF")).text = "ad-rationale"
    tv = etree.SubElement(av, Q("THE-VALUE"))
    for _ in range(rationale_divs):
        etree.SubElement(tv, f"{{{XH}}}div").text = '[RM0008 p.67 §5.1] "The device requires a 2.0-to-3.6 V supply."'


def legitima(root):
    _escribir(root, 1, "ev-yes")
    _escribir(root, 2, "ev-open")


def borra_requisito(root):
    legitima(root)
    so = _so(root, 3)
    so.getparent().remove(so)


def anade_requisito(root):
    legitima(root)
    nuevo = copy.deepcopy(_so(root, 3))
    nuevo.set("IDENTIFIER", "req-99")
    _so(root, 3).addnext(nuevo)


def cambia_texto_del_cliente(root):
    legitima(root)
    div = _so(root, 2).find(f".//{{{XH}}}div")
    div.text = div.text.replace("shall", "should")


def dos_raices_en_rationale(root):
    _escribir(root, 1, "ev-yes", rationale_divs=2)


def estado_que_no_existe(root):
    _escribir(root, 1, "ev-maybe")


def reordena_jerarquia(root):
    legitima(root)
    hijos = root.find(f".//{Q('SPECIFICATION')}/{Q('CHILDREN')}")
    primero = hijos[0]
    hijos.remove(primero)
    hijos.append(primero)


def toca_la_cabecera(root):
    legitima(root)
    root.find(f".//{Q('TITLE')}").text = "Prueba (revisado por IA)"


def toca_last_change(root):
    legitima(root)
    _so(root, 1).set("LAST-CHANGE", "2026-10-28T09:00:00")


def enum_nuevo_en_datatypes(root):
    legitima(root)
    valores = root.find(f".//{Q('SPECIFIED-VALUES')}")
    etree.SubElement(valores, Q("ENUM-VALUE"), IDENTIFIER="ev-maybe", **{"LONG-NAME": "Maybe"})


SABOTAJES = [borra_requisito, anade_requisito, cambia_texto_del_cliente, dos_raices_en_rationale,
             estado_que_no_existe, reordena_jerarquia, toca_la_cabecera, toca_last_change,
             enum_nuevo_en_datatypes]


def main() -> int:
    fallos = 0
    with tempfile.TemporaryDirectory() as d:
        orig = Path(d) / "original.reqif"
        orig.write_text(ORIGINAL, encoding="utf-8")

        def salida(cambio) -> list[str]:
            root = etree.fromstring(ORIGINAL.encode("utf-8"))
            cambio(root)
            out = Path(d) / f"{cambio.__name__}.reqif"
            out.write_bytes(etree.tostring(root, xml_declaration=True, encoding="UTF-8"))
            return diff_files(orig, out)

        v = salida(legitima)
        ok = not v
        fallos += not ok
        print(f"  {'ok  ' if ok else 'FALLA'} salida legítima (estado y rationale en dos requisitos): pasa"
              + ("" if ok else f"  -> {v[:2]}"))
        for s in SABOTAJES:
            v = salida(s)
            ok = bool(v)
            fallos += not ok
            print(f"  {'ok  ' if ok else 'FALLA'} sabotaje «{s.__name__}»: detectado"
                  + (f"  ({v[0][:90]})" if ok else ""))

        mal = Path(d) / "roto.reqif"
        mal.write_text(ORIGINAL[:-40], encoding="utf-8")
        v = diff_files(orig, mal)
        ok = bool(v) and "bien formado" in v[0]
        fallos += not ok
        print(f"  {'ok  ' if ok else 'FALLA'} sabotaje «xml_cortado»: detectado")

    if not fallos:
        print(f"{len(SABOTAJES) + 1} de {len(SABOTAJES) + 1} sabotajes detectados; la salida legítima, aceptada")
    print("TODO OK" if not fallos else f"{fallos} FALLOS")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
