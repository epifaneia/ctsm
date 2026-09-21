"""reqif_lint — integridad referencial de un ReqIF. DETERMINISTA, sin red.

Polarion rechaza un import por motivos que el XML "bien formado" no detecta: una
referencia que apunta a un IDENTIFIER inexistente, un ENUM-VALUE-REF a un valor
que no pertenece al datatype del atributo, un IDENTIFIER duplicado. Este linter
comprueba todo eso en local, sin depender de tener Polarion delante.

No sustituye a un import real —solo Polarion sabe si su configuración acepta los
campos— pero descarta el grueso de los fallos de fichero.

Comprobaciones:
  1. IDENTIFIER únicos en todo el documento.
  2. Toda referencia (*-REF) resuelve a un IDENTIFIER existente.
  3. Cada referencia apunta a un elemento del TIPO correcto
     (SPEC-OBJECT-TYPE-REF → SPEC-OBJECT-TYPE, no a otra cosa).
  4. Cada ATTRIBUTE-VALUE apunta a una ATTRIBUTE-DEFINITION que su SPEC-OBJECT
     tiene declarada en su SPEC-OBJECT-TYPE.
  5. Cada ENUM-VALUE-REF escrito pertenece al DATATYPE del atributo que lo usa
     (el error clásico: enum válido, pero de otro campo).
  6. Cada SPEC-HIERARCHY referencia un SPEC-OBJECT existente.
  7. Cada ATTRIBUTE-VALUE-XHTML tiene exactamente un elemento raíz.

Uso:  python tools/reqif_lint.py <fichero.reqif> [...]
Sale 0 si todo OK; 1 con el listado de problemas.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

from lxml import etree

RQ = "http://www.omg.org/spec/ReqIF/20110401/reqif.xsd"
NS = f"{{{RQ}}}"
XH = "http://www.w3.org/1999/xhtml"

# sufijo de la referencia -> nombre del elemento al que DEBE apuntar
REF_DESTINO = {
    "SPEC-OBJECT-TYPE-REF": "SPEC-OBJECT-TYPE",
    "SPECIFICATION-TYPE-REF": "SPECIFICATION-TYPE",
    "SPEC-RELATION-TYPE-REF": "SPEC-RELATION-TYPE",
    "DATATYPE-DEFINITION-STRING-REF": "DATATYPE-DEFINITION-STRING",
    "DATATYPE-DEFINITION-XHTML-REF": "DATATYPE-DEFINITION-XHTML",
    "DATATYPE-DEFINITION-ENUMERATION-REF": "DATATYPE-DEFINITION-ENUMERATION",
    "DATATYPE-DEFINITION-INTEGER-REF": "DATATYPE-DEFINITION-INTEGER",
    "DATATYPE-DEFINITION-BOOLEAN-REF": "DATATYPE-DEFINITION-BOOLEAN",
    "DATATYPE-DEFINITION-DATE-REF": "DATATYPE-DEFINITION-DATE",
    "DATATYPE-DEFINITION-REAL-REF": "DATATYPE-DEFINITION-REAL",
    "ATTRIBUTE-DEFINITION-STRING-REF": "ATTRIBUTE-DEFINITION-STRING",
    "ATTRIBUTE-DEFINITION-XHTML-REF": "ATTRIBUTE-DEFINITION-XHTML",
    "ATTRIBUTE-DEFINITION-ENUMERATION-REF": "ATTRIBUTE-DEFINITION-ENUMERATION",
    "ATTRIBUTE-DEFINITION-INTEGER-REF": "ATTRIBUTE-DEFINITION-INTEGER",
    "ATTRIBUTE-DEFINITION-BOOLEAN-REF": "ATTRIBUTE-DEFINITION-BOOLEAN",
    "ATTRIBUTE-DEFINITION-DATE-REF": "ATTRIBUTE-DEFINITION-DATE",
    "ATTRIBUTE-DEFINITION-REAL-REF": "ATTRIBUTE-DEFINITION-REAL",
    "ENUM-VALUE-REF": "ENUM-VALUE",
    "SPEC-OBJECT-REF": "SPEC-OBJECT",
    "OBJECT": None,   # dentro de SPEC-HIERARCHY: contiene SPEC-OBJECT-REF
}


def _local(el) -> str:
    return etree.QName(el).localname if isinstance(el.tag, str) else ""


def lint(path: Path) -> list[str]:
    problemas: list[str] = []
    root = etree.parse(str(path)).getroot()

    # 1. IDENTIFIER únicos + índice id -> nombre de elemento
    tipo_de: dict[str, str] = {}
    cuenta = Counter()
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        ident = el.get("IDENTIFIER")
        if ident:
            cuenta[ident] += 1
            tipo_de[ident] = _local(el)
    for ident, n in cuenta.items():
        if n > 1:
            problemas.append(f"IDENTIFIER duplicado ({n}x): {ident}")

    # 2 y 3. referencias resuelven y apuntan al tipo correcto
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        nombre = _local(el)
        if not nombre.endswith("-REF") or nombre not in REF_DESTINO:
            continue
        destino = REF_DESTINO[nombre]
        valor = (el.text or "").strip()
        if not valor:
            problemas.append(f"{nombre} vacía")
            continue
        if valor not in tipo_de:
            problemas.append(f"{nombre} apunta a un IDENTIFIER inexistente: {valor}")
        elif destino and tipo_de[valor] != destino:
            problemas.append(
                f"{nombre} apunta a un {tipo_de[valor]} (esperado {destino}): {valor}")

    # 4 y 5. coherencia atributo <-> tipo del spec-object, y enum <-> datatype
    # atributos declarados por cada SPEC-OBJECT-TYPE
    attrs_por_tipo: dict[str, set[str]] = {}
    datatype_de_attr: dict[str, str] = {}
    for st in root.iter(f"{NS}SPEC-OBJECT-TYPE"):
        ids = set()
        for ad in st.iterfind(f"{NS}SPEC-ATTRIBUTES/*"):
            ids.add(ad.get("IDENTIFIER"))
            for ref in ad.iterfind(f"{NS}TYPE/*"):
                datatype_de_attr[ad.get("IDENTIFIER")] = (ref.text or "").strip()
        attrs_por_tipo[st.get("IDENTIFIER")] = ids

    # valores legales de cada DATATYPE-DEFINITION-ENUMERATION
    valores_de_datatype: dict[str, set[str]] = {}
    for dt in root.iter(f"{NS}DATATYPE-DEFINITION-ENUMERATION"):
        valores_de_datatype[dt.get("IDENTIFIER")] = {
            ev.get("IDENTIFIER") for ev in dt.iter(f"{NS}ENUM-VALUE")}

    for so in root.iter(f"{NS}SPEC-OBJECT"):
        so_id = so.get("IDENTIFIER")
        tipo_ref = None
        for ref in so.iterfind(f"{NS}TYPE/{NS}SPEC-OBJECT-TYPE-REF"):
            tipo_ref = (ref.text or "").strip()
        declarados = attrs_por_tipo.get(tipo_ref, set())
        for av in so.iterfind(f"{NS}VALUES/*"):
            ad_id = None
            for ref in av.iterfind(f"{NS}DEFINITION/*"):
                ad_id = (ref.text or "").strip()
            if ad_id and ad_id not in declarados:
                problemas.append(
                    f"SPEC-OBJECT {so_id[:28]}: usa el atributo {ad_id[:28]} "
                    f"que su SPEC-OBJECT-TYPE no declara")
            if _local(av) == "ATTRIBUTE-VALUE-ENUMERATION" and ad_id:
                legales = valores_de_datatype.get(datatype_de_attr.get(ad_id, ""), set())
                for ref in av.iter(f"{NS}ENUM-VALUE-REF"):
                    v = (ref.text or "").strip()
                    if legales and v not in legales:
                        problemas.append(
                            f"SPEC-OBJECT {so_id[:28]}: ENUM-VALUE-REF {v[:28]} no "
                            f"pertenece al datatype del atributo")
            if _local(av) == "ATTRIBUTE-VALUE-XHTML":
                for the in av.iterfind(f"{NS}THE-VALUE"):
                    hijos = [h for h in the if isinstance(h.tag, str)]
                    if len(hijos) != 1:
                        problemas.append(
                            f"SPEC-OBJECT {so_id[:28]}: XHTML con {len(hijos)} "
                            f"elementos raíz (debe ser exactamente 1)")

    # 6. jerarquía
    for sh in root.iter(f"{NS}SPEC-HIERARCHY"):
        refs = [r for r in sh.iterfind(f"{NS}OBJECT/{NS}SPEC-OBJECT-REF")]
        if not refs:
            problemas.append(f"SPEC-HIERARCHY {sh.get('IDENTIFIER')} sin SPEC-OBJECT-REF")

    return problemas


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    total = 0
    for arg in sys.argv[1:]:
        p = Path(arg)
        problemas = lint(p)
        total += len(problemas)
        if problemas:
            print(f"✗ {p.name}: {len(problemas)} problema(s)")
            for x in problemas[:30]:
                print(f"    ✗ {x}")
            if len(problemas) > 30:
                print(f"    … y {len(problemas)-30} más")
        else:
            print(f"✓ {p.name}: integridad referencial correcta")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
