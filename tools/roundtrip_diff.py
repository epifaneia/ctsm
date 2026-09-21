"""roundtrip_diff — verificador estructural original ↔ salida. DETERMINISTA.

Garantiza que s7 fue quirúrgico. Compara el STK original con el reqif de salida
y FALLA si encuentra cualquier cambio fuera de los permitidos:

  PERMITIDO:
    · Contenido de ATTRIBUTE-VALUE de los campos objetivo (status/rationale/
      comments, config.TARGET_FIELD_LONGNAMES) dentro de <VALUES> de SPEC-OBJECTs.
    · ATTRIBUTE-VALUEs NUEVOS de esos mismos campos (si el original no traía).

  PROHIBIDO (cualquier otra cosa):
    · IDENTIFIERs nuevos/desaparecidos/alterados.
    · Cualquier diferencia en HEADER, DATATYPES, SPEC-TYPES, SPEC-HIERARCHY,
      orden de elementos o atributos (LAST-CHANGE incluido: NO se toca).

  Además, sobre la salida:
    · XML bien formado.
    · Cada XHTML escrito en campos objetivo: UN solo elemento raíz (xhtml:div).
    · Cada ENUM-VALUE-REF escrito existe como ENUM-VALUE en el original.

La comparación normaliza SOLO el whitespace de indentación (text/tail formados
únicamente por espacios/saltos); todo lo demás es literal.

Uso:  python tools/roundtrip_diff.py <original.reqif> <salida.reqif>
Sale 0 si todo OK; 1 con el listado de violaciones.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402

RQ = "http://www.omg.org/spec/ReqIF/20110401/reqif.xsd"


def _local(el: etree._Element) -> str:
    return etree.QName(el).localname if isinstance(el.tag, str) else str(el.tag)


def _detect_allowed_defs(root: etree._Element) -> set[str]:
    """IDs de los ATTRIBUTE-DEFINITION objetivo, por LONG-NAME (sobre el ORIGINAL)."""
    names = set(config.TARGET_FIELD_LONGNAMES.values())
    return {
        ad.get("IDENTIFIER")
        for ad in root.iterfind(f".//{{{RQ}}}SPEC-ATTRIBUTES/*")
        if ad.get("LONG-NAME") in names
    }


def _def_ref(av: etree._Element) -> str | None:
    for ref in av.iterfind(f"{{{RQ}}}DEFINITION/*"):
        return ref.text
    return None


def _strip_allowed(root: etree._Element, allowed: set[str]) -> None:
    """Elimina de <VALUES> de cada SPEC-OBJECT los ATTRIBUTE-VALUE permitidos."""
    for so in root.iterfind(f".//{{{RQ}}}SPEC-OBJECTS/{{{RQ}}}SPEC-OBJECT"):
        values = so.find(f"{{{RQ}}}VALUES")
        if values is None:
            continue
        for av in list(values):
            if _def_ref(av) in allowed:
                values.remove(av)


def _normalize_ws(el: etree._Element) -> None:
    """Indentación fuera: text/tail SOLO-whitespace → None (recursivo)."""
    if el.text is not None and not el.text.strip() and len(el):
        el.text = None
    for child in el:
        if child.tail is not None and not child.tail.strip():
            child.tail = None
        _normalize_ws(child)


def _cmp(a: etree._Element, b: etree._Element, path: str, out: list[str]) -> None:
    """Comparación literal elemento a elemento; reporta ruta de cada diferencia."""
    if len(out) > 40:
        return
    here = f"{path}/{_local(a)}"
    if a.tag != b.tag:
        out.append(f"{here}: tag distinto ({a.tag} ≠ {b.tag})")
        return
    if dict(a.attrib) != dict(b.attrib):
        out.append(f"{here}: atributos distintos ({dict(a.attrib)} ≠ {dict(b.attrib)})")
    if (a.text or "") != (b.text or ""):
        out.append(f"{here}: texto distinto ({(a.text or '')!r} ≠ {(b.text or '')!r})")
    if (a.tail or "") != (b.tail or ""):
        out.append(f"{here}: tail distinto")
    if len(a) != len(b):
        ids = lambda e: [c.get("IDENTIFIER") or _local(c) for c in e]  # noqa: E731
        out.append(f"{here}: nº de hijos distinto ({len(a)} ≠ {len(b)}): "
                   f"{ids(a)} ≠ {ids(b)}")
    for ca, cb in zip(a, b):
        _cmp(ca, cb, here, out)


def diff_files(original: Path, salida: Path) -> list[str]:
    violations: list[str] = []
    t_orig = etree.parse(str(original))
    try:
        t_out = etree.parse(str(salida))
    except etree.XMLSyntaxError as e:
        return [f"salida NO es XML bien formado: {e}"]

    ro, rs = t_orig.getroot(), t_out.getroot()
    allowed = _detect_allowed_defs(ro)
    if not allowed:
        violations.append("no se detectó ningún ATTRIBUTE-DEFINITION objetivo en el original")

    # 1. IDENTIFIERs: mismo multiconjunto exacto (nada nuevo, nada perdido).
    ids = lambda r: sorted((_local(e), e.get("IDENTIFIER"))  # noqa: E731
                           for e in r.iter() if isinstance(e.tag, str) and e.get("IDENTIFIER"))
    io_, is_ = ids(ro), ids(rs)
    if io_ != is_:
        gone = set(io_) - set(is_)
        new = set(is_) - set(io_)
        if gone:
            violations.append(f"IDENTIFIERs desaparecidos: {sorted(gone)[:10]}")
        if new:
            violations.append(f"IDENTIFIERs nuevos: {sorted(new)[:10]}")
        if not gone and not new:
            violations.append("IDENTIFIERs duplicados o reordenados entre archivos")

    # 2. Chequeos sobre lo ESCRITO en la salida (antes de podar las copias).
    enum_ids = {ev.get("IDENTIFIER") for ev in ro.iterfind(f".//{{{RQ}}}ENUM-VALUE")}
    for so in rs.iterfind(f".//{{{RQ}}}SPEC-OBJECTS/{{{RQ}}}SPEC-OBJECT"):
        for av in so.iterfind(f"{{{RQ}}}VALUES/*"):
            if _def_ref(av) not in allowed:
                continue
            oid = so.get("IDENTIFIER")
            if _local(av) == "ATTRIBUTE-VALUE-XHTML":
                tv = av.find(f"{{{RQ}}}THE-VALUE")
                kids = list(tv) if tv is not None else []
                stray = tv is not None and tv.text and tv.text.strip()
                if len(kids) != 1 or stray:
                    violations.append(
                        f"{oid}: THE-VALUE XHTML debe tener UN solo elemento raíz "
                        f"sin texto suelto (tiene {len(kids)} hijos)")
            if _local(av) == "ATTRIBUTE-VALUE-ENUMERATION":
                for ref in av.iterfind(f"{{{RQ}}}VALUES/{{{RQ}}}ENUM-VALUE-REF"):
                    if ref.text not in enum_ids:
                        violations.append(f"{oid}: ENUM-VALUE-REF '{ref.text}' "
                                          f"no existe en el original")

    # 3. Podadas las AVs permitidas en AMBOS lados, el resto debe ser IDÉNTICO.
    co, cs = copy.deepcopy(ro), copy.deepcopy(rs)
    _strip_allowed(co, allowed)
    _strip_allowed(cs, allowed)
    _normalize_ws(co)
    _normalize_ws(cs)
    diffs: list[str] = []
    _cmp(co, cs, "", diffs)
    violations.extend(diffs)
    return violations


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    original, salida = Path(sys.argv[1]), Path(sys.argv[2])
    violations = diff_files(original, salida)
    if violations:
        print(f"roundtrip_diff: {len(violations)} violación(es):")
        for v in violations:
            print(f"  ✗ {v}")
        return 1
    print("roundtrip_diff: OK — fuera de los campos objetivo, cero diferencias.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
