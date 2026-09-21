"""s1_parse_stk — STK ReqIF (export Polarion) → stk.json. DETERMINISTA, sin API.

LECTURA, nunca escritura: el ReqIF original queda intacto como base del roundtrip
de s7. Extrae a stk.json:

  · objects[]          — por SPEC-OBJECT: identifier (INTOCABLE), tipo, nivel en la
                         jerarquía, atributos por LONG-NAME (XHTML aplanado a texto),
                         y el valor actual de los campos objetivo si ya existe.
  · hierarchy[]        — orden documental plano [{spec_object, level}] reconstruible.
  · target_fields      — por SPEC-OBJECT-TYPE: refs a los ATTRIBUTE-DEFINITION destino
                         (config.TARGET_FIELD_LONGNAMES), con datatype.
  · status_enum_values — mapeo LONG-NAME → ENUM-VALUE IDENTIFIER del enum de Status
                         (s7 escribe por referencia, jamás texto libre).
  · source_reqif       — ruta absoluta del original (base de la cirugía de s7).

Los .reqif se buscan RECURSIVAMENTE bajo config.STK_INPUTS_DIR (un export .reqifz
descomprimido vive en su propia carpeta junto a files/).

Entrada:  config.STK_INPUTS_DIR/**/*.reqif
Salida:   config.STK_JSON_DIR/<stem>.json   (contrato en docs/PLAN.md)

Uso:  python pipeline/s1_parse_stk.py [substring]
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402

RQ = "http://www.omg.org/spec/ReqIF/20110401/reqif.xsd"
XH = "http://www.w3.org/1999/xhtml"
NS = {"r": RQ, "xhtml": XH}


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")


def _xhtml_to_text(the_value: etree._Element) -> str:
    """Aplana un THE-VALUE XHTML a texto plano; <xhtml:br/> → salto de línea."""
    parts: list[str] = []
    for node in the_value.iter():
        if node.tag == f"{{{XH}}}br":
            parts.append("\n")
        elif node.text and node.tag != f"{{{RQ}}}THE-VALUE":
            parts.append(node.text)
        elif node.tag == f"{{{RQ}}}THE-VALUE" and node.text:
            parts.append(node.text)
        if node.tail and node is not the_value:
            parts.append(node.tail)
    text = "".join(parts)
    return re.sub(r"[ \t]*\n[ \t]*", "\n", text).strip()


def _parse_datatypes(root: etree._Element) -> dict:
    """Enums: datatype_id → {long_name, values: {LONG-NAME: ENUM-VALUE IDENTIFIER}}."""
    enums: dict[str, dict] = {}
    for dt in root.iterfind(f".//{{{RQ}}}DATATYPE-DEFINITION-ENUMERATION"):
        values = {
            ev.get("LONG-NAME"): ev.get("IDENTIFIER")
            for ev in dt.iterfind(f".//{{{RQ}}}ENUM-VALUE")
        }
        enums[dt.get("IDENTIFIER")] = {"long_name": dt.get("LONG-NAME"), "values": values}
    return enums


def _parse_spec_object_types(root: etree._Element) -> dict:
    """type_id → {long_name, attrs: {attr_def_id: {long_name, kind, datatype_ref}}}."""
    types: dict[str, dict] = {}
    for sot in root.iterfind(f".//{{{RQ}}}SPEC-OBJECT-TYPE"):
        attrs: dict[str, dict] = {}
        for ad in sot.iterfind(f".//{{{RQ}}}SPEC-ATTRIBUTES/*"):
            tag = etree.QName(ad).localname          # ATTRIBUTE-DEFINITION-STRING, ...
            kind = tag.replace("ATTRIBUTE-DEFINITION-", "")
            dt_ref = None
            for ref in ad.iterfind(f"{{{RQ}}}TYPE/*"):
                dt_ref = ref.text
            attrs[ad.get("IDENTIFIER")] = {
                "long_name": ad.get("LONG-NAME"), "kind": kind, "datatype_ref": dt_ref,
            }
        types[sot.get("IDENTIFIER")] = {"long_name": sot.get("LONG-NAME"), "attrs": attrs}
    return types


def _target_fields(types: dict, enums: dict) -> dict:
    """Por tipo, localiza los ATTRIBUTE-DEFINITION destino por LONG-NAME exacto."""
    out: dict[str, dict] = {}
    for type_id, t in types.items():
        found: dict[str, dict] = {}
        for attr_id, a in t["attrs"].items():
            for role, long_name in config.TARGET_FIELD_LONGNAMES.items():
                if a["long_name"] == long_name:
                    entry = {"attr_def_id": attr_id, "long_name": long_name, "kind": a["kind"]}
                    if a["kind"] == "ENUMERATION" and a["datatype_ref"] in enums:
                        entry["enum_values"] = enums[a["datatype_ref"]]["values"]
                    found[role] = entry
        if found:
            out[type_id] = found
    return out


def _attr_value_readout(av: etree._Element, attr_meta: dict, enums: dict):
    """Valor legible de un ATTRIBUTE-VALUE-* según su clase."""
    tag = etree.QName(av).localname
    if tag in ("ATTRIBUTE-VALUE-STRING", "ATTRIBUTE-VALUE-DATE",
               "ATTRIBUTE-VALUE-INTEGER", "ATTRIBUTE-VALUE-REAL",
               "ATTRIBUTE-VALUE-BOOLEAN"):
        return av.get("THE-VALUE")
    if tag == "ATTRIBUTE-VALUE-XHTML":
        tv = av.find(f"{{{RQ}}}THE-VALUE")
        return _xhtml_to_text(tv) if tv is not None else None
    if tag == "ATTRIBUTE-VALUE-ENUMERATION":
        refs = [r.text for r in av.iterfind(f"{{{RQ}}}VALUES/{{{RQ}}}ENUM-VALUE-REF")]
        dt = enums.get(attr_meta.get("datatype_ref"), {}) if attr_meta else {}
        id2name = {v: k for k, v in dt.get("values", {}).items()}
        names = [id2name.get(r, r) for r in refs]
        return names[0] if len(names) == 1 else names
    return None


def _parse_objects(root: etree._Element, types: dict, enums: dict, targets: dict) -> list[dict]:
    objects: list[dict] = []
    for so in root.iterfind(f".//{{{RQ}}}SPEC-OBJECTS/{{{RQ}}}SPEC-OBJECT"):
        type_ref = so.findtext(f"{{{RQ}}}TYPE/{{{RQ}}}SPEC-OBJECT-TYPE-REF")
        t = types.get(type_ref, {"long_name": None, "attrs": {}})
        values: dict[str, object] = {}
        for av in so.iterfind(f"{{{RQ}}}VALUES/*"):
            def_ref = None
            for ref in av.iterfind(f"{{{RQ}}}DEFINITION/*"):
                def_ref = ref.text
            attr_meta = t["attrs"].get(def_ref, {})
            values[attr_meta.get("long_name", def_ref)] = _attr_value_readout(av, attr_meta, enums)
        tgt = targets.get(type_ref, {})
        existing = {role: values.get(meta["long_name"]) for role, meta in tgt.items()}
        objects.append({
            "identifier": so.get("IDENTIFIER"),
            "type": t["long_name"],
            "type_ref": type_ref,
            "foreign_id": values.get("ReqIF.ForeignID"),
            "oem_req_id": values.get("OEM REQ ID"),
            "text": values.get("ReqIF.Text"),
            "chapter_name": values.get("ReqIF.ChapterName"),
            "values": values,
            "existing_targets": existing,
            "evaluable": bool(tgt),   # tiene campos objetivo → se audita en s3-s6
        })
    return objects


def _parse_hierarchy(root: etree._Element) -> list[dict]:
    """Orden documental plano: [{spec_object, hierarchy_id, level}]. NO se toca en s7."""
    flat: list[dict] = []

    def walk(el: etree._Element, level: int) -> None:
        for sh in el.iterfind(f"{{{RQ}}}CHILDREN/{{{RQ}}}SPEC-HIERARCHY"):
            obj = sh.findtext(f"{{{RQ}}}OBJECT/{{{RQ}}}SPEC-OBJECT-REF")
            flat.append({"spec_object": obj, "hierarchy_id": sh.get("IDENTIFIER"), "level": level})
            walk(sh, level + 1)

    for spec in root.iterfind(f".//{{{RQ}}}SPECIFICATIONS/{{{RQ}}}SPECIFICATION"):
        walk(spec, 1)
    return flat


def _status_semantics(names: list[str]) -> dict:
    """Clasifica los nombres del enum en roles yes/no/open (heurística; si el
    STK real trae otra taxonomía y esto falla, corregir a mano en el stk.json)."""
    sem = {"yes": None, "no": None, "open": None}
    for n in names:
        low = n.lower()
        if re.search(r"\bnot\b|reject", low) and not sem["no"]:
            sem["no"] = n
        elif re.search(r"unconf|review|open|tbd|clarif|pending", low) and not sem["open"]:
            sem["open"] = n
        elif not sem["yes"]:
            sem["yes"] = n
    return sem


def parse_stk(reqif_path: Path) -> dict:
    tree = etree.parse(str(reqif_path))
    root = tree.getroot()
    enums = _parse_datatypes(root)
    types = _parse_spec_object_types(root)
    targets = _target_fields(types, enums)
    objects = _parse_objects(root, types, enums, targets)
    hierarchy = _parse_hierarchy(root)
    level_by_obj = {h["spec_object"]: h["level"] for h in hierarchy}
    for o in objects:
        o["level"] = level_by_obj.get(o["identifier"])

    status_enum = {}
    for t in targets.values():
        if "status" in t and "enum_values" in t["status"]:
            status_enum = t["status"]["enum_values"]
    return {
        "source_reqif": str(reqif_path.resolve()),
        "title": root.findtext(f".//{{{RQ}}}REQ-IF-HEADER/{{{RQ}}}TITLE"),
        "spec_object_types": types,
        "enums": enums,
        "target_fields": targets,
        "status_enum_values": status_enum,
        "status_semantics": _status_semantics(list(status_enum)),
        "hierarchy": hierarchy,
        "objects": objects,
    }


def main() -> int:
    only = sys.argv[1] if len(sys.argv) > 1 else None
    # s0 deja en STK_PREPARED_DIR el ReqIF con los campos objetivo ya creados.
    # Si existe, ESE es el original sagrado del resto de la cadena (s7 lo hereda
    # por stk["source_reqif"]); si no, se trabaja directamente sobre la entrada.
    src_dir = (config.STK_PREPARED_DIR
               if any(config.STK_PREPARED_DIR.glob("**/*.reqif"))
               else config.STK_INPUTS_DIR)
    print(f"s1: fuente = {src_dir.name}")
    reqifs = sorted(src_dir.glob("**/*.reqif"))
    if only:
        reqifs = [p for p in reqifs if only.lower() in p.name.lower()
                  or only.lower() in _slug(p.stem).lower()]
    if not reqifs:
        print(f"s1: no hay .reqif bajo {src_dir}"
              + (f" que matcheen '{only}'" if only else ""))
        return 1

    config.STK_JSON_DIR.mkdir(parents=True, exist_ok=True)
    for reqif in reqifs:
        data = parse_stk(reqif)
        stem = _slug(reqif.stem)
        out = config.STK_JSON_DIR / f"{stem}.json"
        out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        n_req = sum(1 for o in data["objects"] if o["existing_targets"])
        print(f"s1: {reqif.name} → {out.name}  "
              f"({len(data['objects'])} objetos, {n_req} con campos objetivo, "
              f"enum status: {list(data['status_enum_values'])})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
