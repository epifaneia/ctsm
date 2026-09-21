"""s0_prepare_stk — añade al ReqIF los campos objetivo que no trae. DETERMINISTA.

El pipeline asume que el STK YA declara `OEM Status` (ENUMERATION), `Rationale`
y `Comments from/to External` (XHTML), y s7 solo rellena sus ATTRIBUTE-VALUE.
Un ReqIF exportado sin esas columnas no tiene dónde recibir el veredicto: s1
detecta 0 campos objetivo y enum vacío, y la cadena se para.

Este paso crea el ESQUEMA que falta, y solo eso:

  · DATATYPE-DEFINITION-ENUMERATION con un ENUM-VALUE por valor de la taxonomía.
  · ATTRIBUTE-DEFINITION-ENUMERATION (status) + 2 ATTRIBUTE-DEFINITION-XHTML
    (rationale, comments) en el SPEC-OBJECT-TYPE de los requisitos.
  · Reutiliza el DATATYPE-DEFINITION-XHTML que el fichero ya tenga; solo crea
    uno si no hay ninguno.

NO escribe valores, NO toca SPEC-OBJECTS, NO toca la jerarquía, NO toca ningún
IDENTIFIER existente. La salida es el nuevo "original sagrado": s1 y s7 trabajan
sobre ella y los candados de roundtrip_diff siguen aplicando sin cambios.

Idempotente: si el ReqIF ya trae los tres campos, lo copia tal cual.

Los IDENTIFIER nuevos son deterministas (uuid5 del stem + nombre del campo):
re-ejecutar da el mismo fichero, y un re-import a Polarion casa los mismos IDs.
LAST-CHANGE se hereda del propio fichero — no se inventan fechas.

AVISO: que el ReqIF declare los campos no significa que Polarion sepa dónde
ponerlos. El proyecto destino necesita los campos custom correspondientes en su
configuración. Probar SIEMPRE con un documento desechable antes de confiar.

Entrada:  config.STK_INPUTS_DIR/**/*.reqif
Salida:   config.STK_PREPARED_DIR/<nombre>.reqif  (+ adjuntos al lado)

Uso:  python pipeline/s0_prepare_stk.py [substring] [--status-values "A,B,C"]
"""
from __future__ import annotations

import shutil
import sys
import uuid
from pathlib import Path

from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402

RQ = "http://www.omg.org/spec/ReqIF/20110401/reqif.xsd"
NS = f"{{{RQ}}}"
# Namespace fijo para los uuid5: mismo fichero + mismo campo -> mismo IDENTIFIER.
_UUID_NS = uuid.UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")


def _det_id(stem: str, clave: str) -> str:
    return f"ctsm-{uuid.uuid5(_UUID_NS, f'{stem}|{clave}')}"


def _spec_object_type(root: etree._Element) -> etree._Element | None:
    """El SPEC-OBJECT-TYPE de los requisitos: el que más SPEC-OBJECTs usan."""
    tipos = {st.get("IDENTIFIER"): st
             for st in root.iterfind(f".//{NS}SPEC-TYPES/{NS}SPEC-OBJECT-TYPE")}
    if not tipos:
        return None
    uso: dict[str, int] = {}
    for so in root.iterfind(f".//{NS}SPEC-OBJECTS/{NS}SPEC-OBJECT"):
        for ref in so.iterfind(f"{NS}TYPE/{NS}SPEC-OBJECT-TYPE-REF"):
            uso[ref.text] = uso.get(ref.text, 0) + 1
    if not uso:
        return None
    return tipos.get(max(uso, key=uso.get))


def _last_change(root: etree._Element) -> str:
    """Hereda una marca temporal del propio fichero; no se inventan fechas."""
    for el in root.iter():
        if isinstance(el.tag, str) and el.get("LAST-CHANGE"):
            return el.get("LAST-CHANGE")
    ct = root.find(f".//{NS}CREATION-TIME")
    return ct.text if ct is not None and ct.text else "2000-01-01T00:00:00.000+00:00"


def _sub(parent: etree._Element, tag: str, **attrs) -> etree._Element:
    el = etree.SubElement(parent, NS + tag)
    for k, v in attrs.items():
        el.set(k.replace("_", "-"), v)
    return el


def _crear_enum_datatype(datatypes, stem, valores, lc, nombre_campo) -> str:
    # el nombre del tipo se deriva del campo: si el destino se renombra en
    # config, el esquema no se queda con un nombre huérfano del anterior
    dt = _sub(datatypes, "DATATYPE-DEFINITION-ENUMERATION",
              IDENTIFIER=_det_id(stem, "dt-status"), LAST_CHANGE=lc,
              LONG_NAME=f"{nombre_campo} Type")
    specified = _sub(dt, "SPECIFIED-VALUES")
    for i, nombre in enumerate(valores):
        ev = _sub(specified, "ENUM-VALUE", IDENTIFIER=_det_id(stem, f"ev-{nombre}"),
                  LAST_CHANGE=lc, LONG_NAME=nombre)
        props = _sub(ev, "PROPERTIES")
        _sub(props, "EMBEDDED-VALUE", KEY=str(i), OTHER_CONTENT=nombre)
    return dt.get("IDENTIFIER")


def _xhtml_datatype(datatypes, stem, lc) -> str:
    existente = datatypes.find(f"{NS}DATATYPE-DEFINITION-XHTML")
    if existente is not None:
        return existente.get("IDENTIFIER")
    dt = _sub(datatypes, "DATATYPE-DEFINITION-XHTML",
              IDENTIFIER=_det_id(stem, "dt-xhtml"), LAST_CHANGE=lc,
              LONG_NAME="Rich Text (multi-line)")
    return dt.get("IDENTIFIER")


def preparar(path: Path, valores_status: list[str]):
    """Devuelve (tree preparado, lista de campos creados)."""
    tree = etree.parse(str(path))
    root = tree.getroot()
    stem = path.stem
    lc = _last_change(root)
    creados: list[str] = []

    sot = _spec_object_type(root)
    if sot is None:
        raise SystemExit(f"s0: {path.name}: no encuentro el SPEC-OBJECT-TYPE de requisitos")
    spec_attrs = sot.find(f"{NS}SPEC-ATTRIBUTES")
    if spec_attrs is None:
        spec_attrs = _sub(sot, "SPEC-ATTRIBUTES")

    ya = {ad.get("LONG-NAME") for ad in spec_attrs}
    datatypes = root.find(f".//{NS}DATATYPES")

    nombre_status = config.TARGET_FIELD_LONGNAMES["status"]
    if nombre_status not in ya:
        dt_id = _crear_enum_datatype(datatypes, stem, valores_status, lc, nombre_status)
        ad = _sub(spec_attrs, "ATTRIBUTE-DEFINITION-ENUMERATION",
                  IDENTIFIER=_det_id(stem, "ad-status"), LAST_CHANGE=lc,
                  LONG_NAME=nombre_status, MULTI_VALUED="false")
        ref = _sub(_sub(ad, "TYPE"), "DATATYPE-DEFINITION-ENUMERATION-REF")
        ref.text = dt_id
        creados.append(f"{nombre_status} (ENUMERATION: {', '.join(valores_status)})")

    xhtml_id = None
    for clave in ("rationale", "comments"):
        nombre = config.TARGET_FIELD_LONGNAMES[clave]
        if nombre in ya:
            continue
        if xhtml_id is None:
            xhtml_id = _xhtml_datatype(datatypes, stem, lc)
        ad = _sub(spec_attrs, "ATTRIBUTE-DEFINITION-XHTML",
                  IDENTIFIER=_det_id(stem, f"ad-{clave}"), LAST_CHANGE=lc,
                  LONG_NAME=nombre)
        ref = _sub(_sub(ad, "TYPE"), "DATATYPE-DEFINITION-XHTML-REF")
        ref.text = xhtml_id
        creados.append(f"{nombre} (XHTML)")

    return tree, creados


def _norm(el: etree._Element) -> None:
    """Normaliza solo el whitespace de indentación, como roundtrip_diff."""
    if el.text is not None and not el.text.strip():
        el.text = None
    if el.tail is not None and not el.tail.strip():
        el.tail = None
    for h in el:
        _norm(h)


def verificar(original: Path, preparado: Path) -> list[str]:
    """Candado de s0: quitando del preparado lo que s0 creó (IDs 'ctsm-'), el
    fichero tiene que quedar LITERALMENTE igual al original. Así se demuestra
    que no se tocó nada más: ni un IDENTIFIER, ni un SPEC-OBJECT, ni el orden.
    """
    a = etree.parse(str(original)).getroot()
    b = etree.parse(str(preparado)).getroot()

    creados = [el for el in b.iter()
               if isinstance(el.tag, str) and (el.get("IDENTIFIER") or "").startswith("ctsm-")]
    for el in creados:
        el.getparent().remove(el)
    # los contenedores que s0 pudo crear vacíos (SPEC-ATTRIBUTES) se ignoran si
    # quedaron sin hijos tras retirar lo añadido
    for el in list(b.iter(NS + "SPEC-ATTRIBUTES")):
        if len(el) == 0 and a.find(f".//{NS}SPEC-ATTRIBUTES") is None:
            el.getparent().remove(el)

    _norm(a); _norm(b)
    ca = etree.tostring(a, method="c14n2")
    cb = etree.tostring(b, method="c14n2")
    if ca == cb:
        return []
    # localizar dónde difieren para un mensaje útil
    fallos = []
    ids_a = sorted(e.get("IDENTIFIER") for e in a.iter()
                   if isinstance(e.tag, str) and e.get("IDENTIFIER"))
    ids_b = sorted(e.get("IDENTIFIER") for e in b.iter()
                   if isinstance(e.tag, str) and e.get("IDENTIFIER"))
    if ids_a != ids_b:
        faltan = set(ids_a) - set(ids_b)
        sobran = set(ids_b) - set(ids_a)
        if faltan:
            fallos.append(f"IDENTIFIERs desaparecidos: {sorted(faltan)[:5]}")
        if sobran:
            fallos.append(f"IDENTIFIERs nuevos no declarados: {sorted(sobran)[:5]}")
    if not fallos:
        fallos.append("el contenido difiere fuera de lo añadido por s0 "
                      "(serialización o atributos alterados)")
    return fallos


def main() -> int:
    args = list(sys.argv[1:])
    valores = list(config.STATUS_VALUES_NUEVO_STK)
    if "--status-values" in args:
        i = args.index("--status-values")
        valores = [v.strip() for v in args[i + 1].split(",") if v.strip()]
        del args[i:i + 2]
    only = args[0] if args else None

    reqifs = sorted(config.STK_INPUTS_DIR.glob("**/*.reqif"))
    if only:
        reqifs = [p for p in reqifs if only.lower() in p.name.lower()]
    if not reqifs:
        print(f"s0: no hay .reqif en {config.STK_INPUTS_DIR}")
        return 1

    config.STK_PREPARED_DIR.mkdir(parents=True, exist_ok=True)
    for src in reqifs:
        tree, creados = preparar(src, valores)
        dst = config.STK_PREPARED_DIR / src.name
        tree.write(str(dst), xml_declaration=True,
                   encoding=tree.docinfo.encoding or "UTF-8")
        # Los adjuntos viajan con el .reqif: s7 los busca junto al fichero.
        for hermano in src.parent.iterdir():
            if hermano.is_dir():
                shutil.copytree(hermano, dst.parent / hermano.name, dirs_exist_ok=True)
        if creados:
            print(f"s0: {src.name[:56]}")
            for c in creados:
                print(f"      + {c}")
        else:
            print(f"s0: {src.name[:56]} — ya traía los 3 campos, copiado sin cambios")

        violaciones = verificar(src, dst)
        if violaciones:
            print(f"s0: ✗ el preparado difiere del original fuera de lo añadido:")
            for v in violaciones:
                print(f"     ✗ {v}")
            return 1
        print(f"    ✓ verificado: idéntico al original salvo el esquema añadido")
    print(f"s0: {len(reqifs)} ReqIF preparado(s) → {config.STK_PREPARED_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
