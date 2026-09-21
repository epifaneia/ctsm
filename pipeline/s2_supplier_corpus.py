"""s2_supplier_corpus — supplier docs → corpus.json con anclaje por página.

DETERMINISTA, sin API. El corpus es la ÚNICA fuente de verdad para citar:
cada chunk lleva chunk_id, documento, sección y rango de páginas REALES del
PDF, más un mapa offset→página para que s6 fije la página exacta de una quote
dentro del chunk. El LLM nunca escribe ubicaciones: elige chunk_id de una
lista cerrada (s4) y el código deriva página/sección de estos metadatos.

Backends:
  · PDF digital → PyMuPDF (fitz): extracción en segundos, texto fiel.
    PDFs cifrados: la clave va en .env como CTSM_PDF_PASSWORDS (';' separa
    varias, se prueban en orden). El PDF se queda cifrado en disco.
  · TODO: escaneados/Word → docling (clients/docling_adapter, lento);
    se enchufa cuando lleguen supplier docs reales de ese tipo.

Chunking: acumula líneas hasta config.CHUNK_CHARS respetando límites de
sección (heading numerado tipo '5.3.5 Standby mode' abre chunk nuevo).
Se filtra ruido de cabecera/pie (nº de página, 'RM0008 Rev 21', ...).
PDFs duplicados (mismo sha256) se procesan una sola vez.

Entrada:  config.SUPPLIER_DOCS_DIR/**/*.pdf
Salida:   config.CORPUS_DIR/corpus.json

Uso:  python pipeline/s2_supplier_corpus.py [substring-ignorado]
      (el corpus es global al set de supplier docs, no por STK)
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import fitz  # PyMuPDF

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402

# '5.3.5 Standby mode' en una línea, o '5.3.5' con el título en la siguiente
_HEADING_INLINE = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){0,3})\s+([A-Z(][^\n]{2,90})$")


def _titulo_valido(t: str) -> bool:
    """Filtra los falsos positivos del detector de secciones.

    El patrón "número + texto en mayúscula" también encaja con una frase normal
    partida por el salto de línea del PDF: "25 MHz. You select this mode by
    setting the HSEBYP..." se tomaba por la sección '§25 MHz. You select...'.
    Eso partía el chunk a mitad de frase —perdiendo justo el valor numérico— y
    además etiquetaba las citas con secciones inventadas.

    Un título de sección real es corto, no cierra frase y no lleva relleno de
    índice.
    """
    t = t.strip()
    if len(t) > 70 or t.endswith("."):
        return False
    if re.search(r"\.\s+[A-Z]", t):        # ". Y" → es prosa, no un título
        return False
    if ".." in t or "…" in t:              # línea de índice con puntos de relleno
        return False
    return True
_HEADING_NUM    = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){0,3})\s*$")
_NOISE          = re.compile(r"^(?:\d{1,4}/\d{1,4}|RM\d{4}\s+Rev\s+\d+|RM\d{4}|www\.st\.com.*)$",
                             re.IGNORECASE)


def _doc_short(name: str) -> str:
    """'rm0008-stm32f101xx-...' → 'RM0008';  'r01uh0773ej0100-...' → 'R01UH0773'.

    El short es el prefijo del chunk_id, así que DOS documentos no pueden
    compartirlo: los ids colisionarían y el dict de s4 se quedaría solo con los
    chunks del último, citando páginas del documento equivocado. Por eso se
    consume la segunda pareja letras+dígitos cuando existe (los códigos Renesas
    son 'r01uh0773', no 'r01'). La unicidad la garantiza además _unique_short().
    """
    m = re.match(r"([A-Za-z]+\d+(?:[A-Za-z]+\d+)?)", name)
    return m.group(1).upper() if m else re.sub(r"[^A-Za-z0-9]", "", name)[:12].upper()


def _unique_short(short: str, usados: set[str]) -> str:
    """Red de seguridad: si dos ficheros dan el mismo short, desambigua."""
    if short not in usados:
        return short
    i = 2
    while f"{short}-{i}" in usados:
        i += 1
    return f"{short}-{i}"


def _clean_lines(page_text: str) -> list[str]:
    return [ln.rstrip() for ln in page_text.splitlines()
            if ln.strip() and not _NOISE.match(ln.strip())]


def _open_pdf(pdf: Path) -> "fitz.Document":
    """Abre el PDF; si pide contraseña, prueba las de config.PDF_PASSWORDS.

    Un PDF con solo owner-password (restringe copiar/imprimir, no abrir) no
    marca needs_pass: PyMuPDF lo extrae igual y no hace falta clave.
    """
    doc = fitz.open(str(pdf))
    if not doc.needs_pass:
        return doc
    for pw in config.PDF_PASSWORDS:
        if doc.authenticate(pw):        # 0 = falla; 1/2 user, 4/6 owner
            return doc
    doc.close()
    raise SystemExit(
        f"s2: '{pdf.name}' está cifrado y ninguna de las "
        f"{len(config.PDF_PASSWORDS)} contraseña(s) de CTSM_PDF_PASSWORDS lo abre.\n"
        f"     Añádela en .env (fichero ya ignorado por git):\n"
        f"     CTSM_PDF_PASSWORDS=clave1;clave2"
    )


def _extract_pdf(pdf: Path) -> list[dict]:
    doc = _open_pdf(pdf)
    pages = [{"page": i + 1, "lines": _clean_lines(p.get_text())}
             for i, p in enumerate(doc)]
    doc.close()
    return pages


# Final de frase de verdad: puntuación de cierre, y no un numeral suelto
# ("8." o "1)" encabezan una lista, no cierran nada).
_FIN_FRASE = re.compile(r"[.!?:]$")
_SOLO_NUM = re.compile(r"^\s*\d+[.)]?\s*$")


def _cierra_frase(linea: str) -> bool:
    t = linea.strip()
    return bool(t) and not _SOLO_NUM.match(t) and bool(_FIN_FRASE.search(t))


def _chunk_doc(short: str, pages: list[dict]) -> list[dict]:
    chunks: list[dict] = []
    cur_section = ""
    cur_parts: list[tuple[int, str]] = []   # (página, línea)
    cur_len = 0
    tope = int(config.CHUNK_CHARS * config.CHUNK_MAX_FACTOR)

    def flush(por_longitud: bool = True) -> None:
        """Cierra el chunk. `por_longitud` distingue el motivo del corte:

        · por longitud → el texto continúa, así que se arrastra un solape para
          que una frase partida entre dos chunks aparezca entera en uno.
        · por heading  → el corte es semántico y no parte ninguna frase. Solapar
          aquí solo duplica texto, y en un manual con secciones cortas puede
          llegar a duplicar el corpus entero.
        """
        nonlocal cur_parts, cur_len
        text = "\n".join(t for _, t in cur_parts).strip()
        if len(text) < 80:                   # migajas fuera
            cur_parts, cur_len = [], 0
            return
        cola: list[tuple[int, str]] = []
        if por_longitud:
            acum = 0
            # nunca más de un cuarto del chunk: el solape es una costura, no una copia
            techo = min(config.CHUNK_OVERLAP_CHARS, len(text) // 4)
            for parte in reversed(cur_parts):
                if acum >= techo:
                    break
                cola.insert(0, parte)
                acum += len(parte[1]) + 1
        page_map, off = [], 0
        for pg, t in cur_parts:
            if not page_map or page_map[-1]["page"] != pg:
                page_map.append({"page": pg, "offset": off})
            off += len(t) + 1
        chunks.append({
            "chunk_id": f"{short}-C{len(chunks):04d}",
            "doc": short,
            "section": cur_section,
            "page_start": cur_parts[0][0],
            "page_end": cur_parts[-1][0],
            "page_map": page_map,
            "text": text,
        })
        # la cola arrastrada abre el chunk siguiente (si no es el chunk entero)
        cur_parts = [] if len(cola) >= len(cur_parts) else cola
        cur_len = sum(len(t) + 1 for _, t in cur_parts)

    for pg in pages:
        lines = pg["lines"]
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            heading = None
            m = _HEADING_INLINE.match(line)
            if m and _titulo_valido(m.group(2)):
                heading = f"§{m.group(1)} {m.group(2).strip()}"
            else:
                m = _HEADING_NUM.match(line)
                if (m and i + 1 < len(lines)
                        and re.match(r"^[A-Z(]", lines[i + 1].strip())
                        and _titulo_valido(lines[i + 1])):
                    heading = f"§{m.group(1)} {lines[i + 1].strip()}"
                    i += 1
            if heading:
                flush(por_longitud=False)
                cur_section = heading
                i += 1
                continue
            cur_parts.append((pg["page"], line))
            cur_len += len(line) + 1
            # Pasado el objetivo se corta en el PRIMER final de frase; el tope
            # duro evita que un bloque sin puntuación (una tabla) crezca sin fin.
            if (cur_len >= config.CHUNK_CHARS and _cierra_frase(line)) or cur_len >= tope:
                flush()
            i += 1
    flush(por_longitud=False)
    return chunks


def main() -> int:
    pdfs = sorted(config.SUPPLIER_DOCS_DIR.glob("**/*.pdf"))
    if not pdfs:
        print(f"s2: no hay PDFs en {config.SUPPLIER_DOCS_DIR}")
        return 1

    seen: set[str] = set()
    docs_meta, all_chunks = [], []
    for pdf in pdfs:
        sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
        if sha in seen:
            print(f"s2: {pdf.name[:60]} duplicado (sha256), omitido")
            continue
        seen.add(sha)
        short = _unique_short(_doc_short(pdf.name), {d["doc"] for d in docs_meta})
        pages = _extract_pdf(pdf)
        chunks = _chunk_doc(short, pages)
        chars = sum(len(c["text"]) for c in chunks)
        docs_meta.append({"file": pdf.name, "doc": short, "sha256": sha,
                          "pages": len(pages), "chunks": len(chunks), "chars": chars})
        all_chunks.extend(chunks)
        print(f"s2: {short} — {len(pages)} págs → {len(chunks)} chunks, {chars:,} chars")

    config.CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    out = config.CORPUS_DIR / "corpus.json"
    out.write_text(json.dumps({"docs": docs_meta, "chunks": all_chunks},
                              ensure_ascii=False), encoding="utf-8")
    print(f"s2: corpus → {out}  ({len(all_chunks)} chunks totales)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
