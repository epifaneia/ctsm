# -*- coding: utf-8 -*-
"""build_demo_stk — JSON de requisitos → STK ReqIF INICIAL (banco de pruebas).

HERRAMIENTA DE DEMO, NO ES PARTE DEL MOTOR. El motor (s1..s7) jamás genera
ReqIFs: edita el original (garantía del roundtrip). Esto existe solo para
fabricar un STK de partida cuando el set de requisitos es sintético (no hay
archivo de partida), calcando el ESQUEMA de un ReqIF exportado desde tu
Polarion: mismos DATATYPES/SPEC-TYPES/enum de estado → la plantilla de mapeo
de Polarion de ese documento aplica tal cual.

Los IDENTIFIER de los SPEC-OBJECT de requisito son los req_id del JSON, de
modo que el results.json del motor casa 1:1 al inyectar. Los IDs de instancia
(header, specification, hierarchy, heading) llevan prefijo propio — cicatriz
Polarion: jamás compartir IDs de instancia entre documentos.

Entrada:  JSON con contrato {headers: [{title, number}], requisitos: [{req_id, texto}]}
          (campos extra como `coverage` se ignoran aquí: son para scoring en s6)
Plantilla de esquema: cualquier ReqIF exportado desde Polarion, indicado en la
variable de entorno CTSM_STK_TEMPLATE (o config.STK_TEMPLATE). Los
ATTRIBUTE-DEFINITION se localizan por LONG-NAME (ReqIF.Text, ReqIF.ChapterName,
ReqIF.ForeignID); los que no existan en tu plantilla se omiten.
Salida:   config.STK_INPUTS_DIR/<title>.reqif  — STK inicial con los campos
          objetivo (OEM Status/Rationale/Comments) VACÍOS, listo para import
          CREATE en Polarion y para que el motor corra sobre él.

Uso:  python tools/build_demo_stk.py [fixture.json] [Titulo]
      (defaults: tools/fixtures/stm32_validation_9reqs.json, STM32F10xxx_Validation)
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from lxml import etree

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import config  # noqa: E402

RQ = "http://www.omg.org/spec/ReqIF/20110401/reqif.xsd"
XH = "http://www.w3.org/1999/xhtml"
NOW = "2026-07-15T12:00:00.000+02:00"   # fijo: salida determinista

import os
TEMPLATE = Path(os.environ.get("CTSM_STK_TEMPLATE")
                or getattr(config, "STK_TEMPLATE", ROOT / "reference" / "stk_template.reqif"))
DEFAULT_FIXTURE = ROOT / "tools" / "fixtures" / "stm32_validation_9reqs.json"
DEFAULT_TITLE = "STM32F10xxx_Validation"
AUTHOR = "demo"

# Los ATTRIBUTE-DEFINITION se detectan en la plantilla por LONG-NAME. Se rellenan
# en build() a partir del ReqIF indicado; si un campo no existe, no se emite.
H: dict[str, str] = {}   # tipo heading
R: dict[str, str] = {}   # tipo requisito


def _detect_schema(root: etree._Element) -> None:
    """Rellena H y R desde los SPEC-OBJECT-TYPE de la plantilla."""
    types = root.findall(f".//{q('SPEC-OBJECT-TYPE')}")
    if len(types) < 2:
        raise SystemExit("build_demo_stk: la plantilla necesita al menos dos SPEC-OBJECT-TYPE "
                         "(heading y requisito)")
    def is_heading(t):
        return bool(re.search(r"head|info|chapter", t.get("LONG-NAME", ""), re.I))
    heading = next((t for t in types if is_heading(t)), types[0])
    req = next((t for t in types if t is not heading), types[1])
    wanted = {"ReqIF.Text": "text", "ReqIF.ChapterName": "chapname",
              "ReqIF.ForeignID": "foreignid", "ReqIF.CreatedBy": "createdby",
              "ReqIF.CreatedOn": "createdon"}
    for t, target in ((heading, H), (req, R)):
        target.clear()
        target["type"] = t.get("IDENTIFIER")
        for ad in t.iterfind(f"{q('SPEC-ATTRIBUTES')}/*"):
            ln = ad.get("LONG-NAME", "")
            if ln in wanted:
                target[wanted[ln]] = ad.get("IDENTIFIER")
            elif re.search(r"oem.*req.*id", ln, re.I):
                target["oemreqid"] = ad.get("IDENTIFIER")
    for name, d in (("heading", H), ("requisito", R)):
        if "text" not in d:
            raise SystemExit(f"build_demo_stk: el tipo {name} de la plantilla no tiene ReqIF.Text")


def q(tag: str) -> str:
    return f"{{{RQ}}}{tag}"


def _ind(depth: int) -> str:
    return "\n" + "  " * depth


def _pretty(el: etree._Element, depth: int) -> None:
    """Indentación recursiva estilo export Polarion (2 espacios por nivel)."""
    if len(el) == 0:
        return
    el.text = _ind(depth + 1)
    for i, child in enumerate(el):
        child.tail = _ind(depth + 1) if i < len(el) - 1 else _ind(depth)
        if child.tag != f"{{{XH}}}div":   # los div van en una sola línea
            _pretty(child, depth + 1)


def av_string(def_id: str, value: str) -> etree._Element:
    av = etree.Element(q("ATTRIBUTE-VALUE-STRING"), {"THE-VALUE": value})
    ref = etree.SubElement(etree.SubElement(av, q("DEFINITION")),
                           q("ATTRIBUTE-DEFINITION-STRING-REF"))
    ref.text = def_id
    return av


def av_date(def_id: str, value: str) -> etree._Element:
    av = etree.Element(q("ATTRIBUTE-VALUE-DATE"), {"THE-VALUE": value})
    ref = etree.SubElement(etree.SubElement(av, q("DEFINITION")),
                           q("ATTRIBUTE-DEFINITION-DATE-REF"))
    ref.text = def_id
    return av


def av_xhtml(def_id: str, first_line: str, rest: str | None = None) -> etree._Element:
    av = etree.Element(q("ATTRIBUTE-VALUE-XHTML"))
    ref = etree.SubElement(etree.SubElement(av, q("DEFINITION")),
                           q("ATTRIBUTE-DEFINITION-XHTML-REF"))
    ref.text = def_id
    div = etree.SubElement(etree.SubElement(av, q("THE-VALUE")), f"{{{XH}}}div")
    div.text = first_line
    if rest:
        etree.SubElement(div, f"{{{XH}}}br").tail = rest
    return av


def spec_object(identifier: str, type_ref: str, values: list) -> etree._Element:
    so = etree.Element(q("SPEC-OBJECT"), {"IDENTIFIER": identifier, "LAST-CHANGE": NOW})
    vals = etree.SubElement(so, q("VALUES"))
    for v in values:
        vals.append(v)
    tref = etree.SubElement(etree.SubElement(so, q("TYPE")), q("SPEC-OBJECT-TYPE-REF"))
    tref.text = type_ref
    return so


def build(fixture: Path, title: str) -> Path:
    data = json.loads(fixture.read_text(encoding="utf-8"))
    reqs = data["requisitos"]
    header_meta = (data.get("headers") or [{}])[0]
    heading_title = header_meta.get("title", title)
    heading_number = header_meta.get("number", "1")
    prefix = "".join(c for c in title.upper() if c.isalnum())[:12] or "DEMO"

    tree = etree.parse(str(TEMPLATE))
    root = tree.getroot()
    _detect_schema(root)

    header = root.find(f".//{q('REQ-IF-HEADER')}")
    header.set("IDENTIFIER", f"_{prefix.lower()}-header-0001")
    header.find(q("TITLE")).text = title
    header.find(q("CREATION-TIME")).text = NOW

    so_container = root.find(f".//{q('SPEC-OBJECTS')}")
    for child in list(so_container):
        so_container.remove(child)

    heading_id = f"{prefix}_SO-H-0001"
    hv = [av_xhtml(H["text"], heading_title)]
    if "createdon" in H: hv.append(av_date(H["createdon"], NOW))
    if "createdby" in H: hv.append(av_string(H["createdby"], AUTHOR))
    if "chapname" in H: hv.append(av_string(H["chapname"], f"{heading_number} {heading_title}"))
    so_container.append(spec_object(heading_id, H["type"], hv))

    for r in reqs:
        rid, text = r["req_id"], r["texto"]
        chap = f"{rid} {text}"
        chap = chap[:80] + "..." if len(chap) > 80 else chap
        rv = [av_xhtml(R["text"], rid, text)]
        if "foreignid" in R: rv.append(av_string(R["foreignid"], rid))
        if "chapname" in R: rv.append(av_string(R["chapname"], chap))
        if "createdon" in R: rv.append(av_date(R["createdon"], NOW))
        if "oemreqid" in R: rv.append(av_string(R["oemreqid"], rid))
        if "createdby" in R: rv.append(av_string(R["createdby"], AUTHOR))
        so_container.append(spec_object(rid, R["type"], rv))

    spec = root.find(f".//{q('SPECIFICATION')}")
    spec.set("IDENTIFIER", f"_{prefix.lower()}-spec-0001")
    spec.set("LAST-CHANGE", NOW)
    spec.set("LONG-NAME", title.upper())
    children = spec.find(q("CHILDREN"))
    for child in list(children):
        children.remove(child)

    sh_head = etree.SubElement(children, q("SPEC-HIERARCHY"),
                               {"IDENTIFIER": f"{prefix}_SH-0001", "LAST-CHANGE": NOW})
    oref = etree.SubElement(etree.SubElement(sh_head, q("OBJECT")), q("SPEC-OBJECT-REF"))
    oref.text = heading_id
    sub = etree.SubElement(sh_head, q("CHILDREN"))
    for i, r in enumerate(reqs, start=2):
        sh = etree.SubElement(sub, q("SPEC-HIERARCHY"),
                              {"IDENTIFIER": f"{prefix}_SH-{i:04d}", "LAST-CHANGE": NOW})
        ref = etree.SubElement(etree.SubElement(sh, q("OBJECT")), q("SPEC-OBJECT-REF"))
        ref.text = r["req_id"]

    _pretty(so_container, 3)
    _pretty(spec, 3)

    out = config.STK_INPUTS_DIR / f"{title}.reqif"
    body = etree.tostring(root, encoding="UTF-8", xml_declaration=False)
    out.write_bytes(b'<?xml version="1.0" encoding="UTF-8"?>\n' + body + b"\n")

    check = etree.parse(str(out))
    n_so = len(check.findall(f".//{q('SPEC-OBJECT')}"))
    n_sh = len(check.findall(f".//{q('SPEC-HIERARCHY')}"))
    print(f"build_demo_stk: {out.name} — {n_so} spec-objects "
          f"(1 heading + {len(reqs)} reqs), {n_sh} nodos de jerarquía")
    return out


def main() -> int:
    fixture = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_FIXTURE
    title = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_TITLE
    if not fixture.is_file():
        print(f"build_demo_stk: no existe {fixture}")
        return 1
    if not TEMPLATE.is_file():
        print(f"build_demo_stk: falta la plantilla de esquema {TEMPLATE}")
        print("  Exporta cualquier documento ReqIF desde tu Polarion y apunta a él con "
              "CTSM_STK_TEMPLATE=ruta.reqif")
        return 1
    build(fixture, title)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
