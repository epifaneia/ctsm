"""s7_inject — cirugía sobre el ReqIF ORIGINAL. DETERMINISTA, sin API.

EL PASO CRÍTICO DEL ROUNDTRIP. Lee el STK original + results.json sellado y
escribe la copia de salida alterando SOLO los valores permitidos:

  · status    → ATTRIBUTE-VALUE-ENUMERATION con ENUM-VALUE-REF a un IDENTIFIER
                que YA existe en el archivo (mapeo de s1). Nunca texto libre;
                status fuera del enum → ABORT.
  · rationale → XHTML con UN solo <xhtml:div> raíz ('\n' → <xhtml:br/>).
  · comments  → ídem.

PROHIBIDO (docs/RISK_roundtrip.md): tocar IDENTIFIERs, SPEC-TYPES,
SPEC-HIERARCHY, orden de elementos, declaración/namespaces, LAST-CHANGE. Si el
campo ya tiene valor se reemplaza su contenido; si no, se añade el
ATTRIBUTE-VALUE al final de <VALUES>.

Tras escribir, lanza tools/roundtrip_diff.py y FALLA si el diff estructural
encuentra cualquier cambio fuera de los permitidos. Si el original venía de un
.reqifz (carpeta con files/ adjuntos), re-empaqueta un .reqifz de salida con
los adjuntos intactos.

Entrada:  original (ruta en stk.json de s1) + config.RESULTS_DIR/<stem>.json
Salida:   config.OUTPUT_REQIF_DIR/<stem>.reqif  [+ <stem>.reqifz si aplica]

Uso:  python pipeline/s7_inject.py [substring]
"""
from __future__ import annotations

import json
import re
import sys
import zipfile
from pathlib import Path

from lxml import etree

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import config  # noqa: E402
from roundtrip_diff import diff_files  # noqa: E402

RQ = "http://www.omg.org/spec/ReqIF/20110401/reqif.xsd"
XH = "http://www.w3.org/1999/xhtml"


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")


def _def_ref(av: etree._Element) -> str | None:
    for ref in av.iterfind(f"{{{RQ}}}DEFINITION/*"):
        return ref.text
    return None


def _indent(depth: int) -> str:
    return "\n" + "  " * depth


def _make_div(text: str) -> etree._Element:
    """UN solo <xhtml:div> raíz; saltos de línea como <xhtml:br/> (regla Polarion)."""
    div = etree.Element(f"{{{XH}}}div")
    lines = text.split("\n")
    div.text = lines[0]
    for line in lines[1:]:
        br = etree.SubElement(div, f"{{{XH}}}br")
        br.tail = line
    return div


def _append_pretty(values: etree._Element, av: etree._Element, depth: int) -> None:
    """Añade av al final de <VALUES> manteniendo la indentación del archivo."""
    if len(values):
        values[-1].tail = _indent(depth)
    else:
        values.text = _indent(depth)
    av.tail = _indent(depth - 1)
    values.append(av)


def _new_xhtml_value(attr_def_id: str, text: str, depth: int) -> etree._Element:
    av = etree.Element(f"{{{RQ}}}ATTRIBUTE-VALUE-XHTML")
    av.text = _indent(depth + 1)
    definition = etree.SubElement(av, f"{{{RQ}}}DEFINITION")
    definition.text = _indent(depth + 2)
    ref = etree.SubElement(definition, f"{{{RQ}}}ATTRIBUTE-DEFINITION-XHTML-REF")
    ref.text = attr_def_id
    ref.tail = _indent(depth + 1)
    definition.tail = _indent(depth + 1)
    the_value = etree.SubElement(av, f"{{{RQ}}}THE-VALUE")
    the_value.text = _indent(depth + 2)
    div = _make_div(text)
    div.tail = _indent(depth + 1)
    the_value.append(div)
    the_value.tail = _indent(depth)
    return av


def _new_enum_value(attr_def_id: str, enum_value_id: str, depth: int) -> etree._Element:
    av = etree.Element(f"{{{RQ}}}ATTRIBUTE-VALUE-ENUMERATION")
    av.text = _indent(depth + 1)
    values = etree.SubElement(av, f"{{{RQ}}}VALUES")
    values.text = _indent(depth + 2)
    ref = etree.SubElement(values, f"{{{RQ}}}ENUM-VALUE-REF")
    ref.text = enum_value_id
    ref.tail = _indent(depth + 1)
    values.tail = _indent(depth + 1)
    definition = etree.SubElement(av, f"{{{RQ}}}DEFINITION")
    definition.text = _indent(depth + 2)
    dref = etree.SubElement(definition, f"{{{RQ}}}ATTRIBUTE-DEFINITION-ENUMERATION-REF")
    dref.text = attr_def_id
    dref.tail = _indent(depth + 1)
    definition.tail = _indent(depth)
    return av


def _replace_or_append(so: etree._Element, av_new: etree._Element,
                       attr_def_id: str, depth: int) -> None:
    values = so.find(f"{{{RQ}}}VALUES")
    if values is None:  # SPEC-OBJECT sin VALUES: no debería pasar en un export Polarion
        raise ValueError(f"SPEC-OBJECT {so.get('IDENTIFIER')} sin <VALUES>")
    for av in list(values):
        if _def_ref(av) == attr_def_id:
            av_new.tail = av.tail  # ocupa exactamente su sitio: el orden no cambia
            values.replace(av, av_new)
            return
    _append_pretty(values, av_new, depth)


def inject(original: Path, stk: dict, results: dict) -> bytes:
    parser = etree.XMLParser(remove_blank_text=False, strip_cdata=False,
                             resolve_entities=False)
    tree = etree.parse(str(original), parser)
    root = tree.getroot()

    so_by_id = {so.get("IDENTIFIER"): so
                for so in root.iterfind(f".//{{{RQ}}}SPEC-OBJECTS/{{{RQ}}}SPEC-OBJECT")}
    targets_by_type = stk["target_fields"]

    n_status = n_xhtml = 0
    for r in results["results"]:
        oid = r["spec_object_id"]
        so = so_by_id.get(oid)
        if so is None:
            raise ValueError(f"results.json referencia SPEC-OBJECT inexistente: {oid}")
        type_ref = so.findtext(f"{{{RQ}}}TYPE/{{{RQ}}}SPEC-OBJECT-TYPE-REF")
        tgt = targets_by_type.get(type_ref)
        if not tgt:
            raise ValueError(f"{oid}: su tipo {type_ref} no tiene campos objetivo")
        depth = 6  # <VALUES> de SPEC-OBJECT: hijos a 12 espacios en export Polarion

        if r.get("status"):
            meta = tgt["status"]
            enum_id = meta["enum_values"].get(r["status"])
            if not enum_id:  # taxonomía CERRADA: jamás texto libre ni valores nuevos
                raise ValueError(f"{oid}: status '{r['status']}' no existe en el enum "
                                 f"del STK {list(meta['enum_values'])}")
            _replace_or_append(so, _new_enum_value(meta["attr_def_id"], enum_id, depth),
                               meta["attr_def_id"], depth)
            n_status += 1

        for role in ("rationale", "comments"):
            if r.get(role) and role in tgt:
                meta = tgt[role]
                _replace_or_append(so, _new_xhtml_value(meta["attr_def_id"], r[role], depth),
                                   meta["attr_def_id"], depth)
                n_xhtml += 1

    print(f"s7: {n_status} status + {n_xhtml} campos XHTML inyectados "
          f"en {len(results['results'])} SPEC-OBJECTs")
    body = etree.tostring(root, encoding="UTF-8", xml_declaration=False)
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + body + b"\n"


def _repack_reqifz(original: Path, out_reqif: Path, out_zip: Path) -> None:
    """Reconstruye el contenedor .reqifz: reqif actualizado + adjuntos intactos."""
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(out_reqif, original.name)
        for f in sorted(original.parent.rglob("*")):
            if f.is_file() and f != original:
                zf.write(f, f.relative_to(original.parent).as_posix())


def main() -> int:
    only = sys.argv[1] if len(sys.argv) > 1 else None
    stk_jsons = sorted(config.STK_JSON_DIR.glob("*.json"))
    if only:
        stk_jsons = [p for p in stk_jsons if only.lower() in p.stem.lower()]
    if not stk_jsons:
        print(f"s7: no hay stk.json en {config.STK_JSON_DIR}"
              + (f" que matcheen '{only}'" if only else "") + " — ¿corriste s1?")
        return 1

    config.OUTPUT_REQIF_DIR.mkdir(parents=True, exist_ok=True)
    for stk_path in stk_jsons:
        stk = json.loads(stk_path.read_text(encoding="utf-8"))
        if not stk.get("source_reqif"):   # sets de prueba sin ReqIF: nada que inyectar
            print(f"s7: {stk_path.stem} no tiene source_reqif (set de prueba), omitido")
            continue
        results_path = config.RESULTS_DIR / stk_path.name
        if not results_path.is_file():
            print(f"s7: falta {results_path.name} en {config.RESULTS_DIR} — ¿corrió s6?")
            return 1
        results = json.loads(results_path.read_text(encoding="utf-8"))
        original = Path(stk["source_reqif"])

        out_reqif = config.OUTPUT_REQIF_DIR / original.name
        out_reqif.write_bytes(inject(original, stk, results))

        violations = diff_files(original, out_reqif)
        if violations:
            print(f"s7: ✗ roundtrip_diff encontró {len(violations)} violación(es):")
            for v in violations[:20]:
                print(f"     ✗ {v}")
            return 1
        print(f"s7: roundtrip_diff OK → {out_reqif}")

        # Solo hay adjuntos si el reqif vive en SU PROPIA carpeta de .reqifz
        # descomprimido (con files/ al lado) — no si está suelto en inputs.
        has_attachments = (original.parent / "files").is_dir() \
            and original.parent != config.STK_INPUTS_DIR
        if has_attachments or ".reqifz" in original.parent.name:
            out_zip = config.OUTPUT_REQIF_DIR / f"{original.stem}.reqifz"
            _repack_reqifz(original, out_reqif, out_zip)
            print(f"s7: re-empaquetado con adjuntos → {out_zip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
