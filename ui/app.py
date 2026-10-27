"""app — interfaz local de CTSM (FastAPI). La interfaz no decide nada: lanza el
pipeline y enseña lo que el pipeline escribió.

  python ui/app.py            # en vivo: sube un ReqIF y los PDFs del proveedor
  python ui/app.py --demo     # reproduce una ejecución real grabada, sin modelo ni red

Endpoints:
  GET  /api/info                      modo, motor, demos disponibles
  POST /api/jobs                      multipart: reqif + pdfs[]   (en vivo)
  POST /api/demo/{name}               arranca la reproducción de una demo
  GET  /api/jobs/{id}                 instantánea: pasos, progreso, filas, custodia
  GET  /api/jobs/{id}/page            PNG de la página citada con la cita resaltada
  GET  /api/jobs/{id}/reqif           el ReqIF de salida (en vivo)
  GET  /api/jobs/{id}/roundtrip       los tres candados de roundtrip_diff (en vivo)
"""
from __future__ import annotations

import argparse
import io
import os
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

UI_DIR = Path(__file__).resolve().parent
ROOT = UI_DIR.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(UI_DIR))
import config  # noqa: E402
import engine  # noqa: E402

DEMO = os.environ.get("CTSM_UI_DEMO") == "1"
SPEED = float(os.environ.get("CTSM_UI_SPEED", "12"))

app = FastAPI(title="CTSM", docs_url=None, redoc_url=None)


def _job(job_id: str) -> engine.Job:
    job = engine.JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "trabajo no encontrado")
    return job


@app.get("/api/info")
def info():
    from custodia.identity import current_actor, MissingActor
    try:
        actor = current_actor()
    except MissingActor:
        actor = None    # en demo no se ejecuta nada, no hace falta actor
    eng = (f"ollama · {config.OLLAMA_MODEL}" if config.LLM_BACKEND == "ollama"
           else f"gemini · {config.GEMINI_MODEL}")
    return {"mode": "demo" if DEMO else "live", "engine": eng,
            "local": config.LLM_BACKEND == "ollama", "actor": actor,
            "speed": SPEED, "demos": engine.available_demos()}


@app.post("/api/jobs")
async def create_job(reqif: UploadFile = File(...), pdfs: list[UploadFile] = File(...)):
    if DEMO:
        raise HTTPException(409, "la interfaz está en modo demo")
    if not (reqif.filename or "").lower().endswith(".reqif"):
        raise HTTPException(400, "la especificación del cliente tiene que ser un .reqif")
    docs = []
    for f in pdfs:
        if not (f.filename or "").lower().endswith(".pdf"):
            raise HTTPException(400, f"solo PDFs del proveedor: {f.filename}")
        docs.append((f.filename, await f.read()))
    if not docs:
        raise HTTPException(400, "falta la documentación del proveedor")
    return engine.create_live((reqif.filename, await reqif.read()), docs).snapshot()


@app.post("/api/demo/{name}")
def start_demo(name: str):
    try:
        return engine.create_demo(name, SPEED).snapshot()
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    return _job(job_id).snapshot()


@lru_cache(maxsize=64)
def _render(pdf: str, page: int, quote: str) -> bytes | None:
    """La página citada, con la cita resaltada donde el código la encontró."""
    import fitz
    doc = fitz.open(pdf)
    try:
        # la página de la evidencia es 1-based; si la cita no aparece, se mira al lado
        for p in (page, page - 1, page + 1):
            if not 1 <= p <= doc.page_count:
                continue
            pg = doc[p - 1]
            hits = pg.search_for(quote) if quote else []
            if not hits and quote:
                # una cita que cruza saltos de línea o guiones no se encuentra entera:
                # se resalta por tramos de unas seis palabras, los que aparezcan
                words = quote.split()
                for i in range(0, len(words), 6):
                    hits += pg.search_for(" ".join(words[i:i + 6]))
            if hits or p == page:
                for r in hits:
                    pg.add_highlight_annot(r).update()
                return pg.get_pixmap(dpi=110, annots=True).tobytes("png")
        return None
    finally:
        doc.close()


@app.get("/api/jobs/{job_id}/page")
def page_png(job_id: str, doc: str = Query(...), page: int = Query(..., ge=1), q: str = ""):
    job = _job(job_id)
    # el documento se elige por nombre de entre los que hay, nunca por ruta
    pdfs = {p.stem: p for p in Path(job.supplier_dir()).glob("*.pdf")}
    if doc not in pdfs:
        raise HTTPException(404, "PDF del proveedor no disponible en esta máquina")
    png = _render(str(pdfs[doc]), page, q[:400])
    if png is None:
        raise HTTPException(404, "página fuera del documento")
    return Response(png, media_type="image/png", headers={"Cache-Control": "max-age=3600"})


@app.get("/api/jobs/{job_id}/reqif")
def download_reqif(job_id: str):
    out = _job(job_id).output_reqif()
    if out is None:
        raise HTTPException(404, "no hay ReqIF de salida")
    return FileResponse(out, filename=out.name, media_type="application/xml")


@app.get("/api/jobs/{job_id}/roundtrip")
def roundtrip(job_id: str):
    job = _job(job_id)
    src, out = job.prepared_reqif(), job.output_reqif()
    if src is None or out is None:
        raise HTTPException(404, "no hay ficheros que comparar")
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "roundtrip_diff.py"), str(src), str(out)],
                       capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT),
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    return {"ok": r.returncode == 0, "report": (r.stdout + r.stderr).strip()[-4000:]}


app.mount("/", StaticFiles(directory=UI_DIR / "static", html=True), name="static")


def main() -> int:
    global DEMO, SPEED
    ap = argparse.ArgumentParser(description="Interfaz local de CTSM")
    ap.add_argument("--demo", action="store_true", help="reproduce una ejecución grabada")
    ap.add_argument("--speed", type=float, default=SPEED, help="aceleración de la reproducción demo")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8078")))
    args = ap.parse_args()
    SPEED = max(1.0, args.speed)
    if args.demo:
        os.environ["CTSM_UI_DEMO"] = "1"
        DEMO = True
    else:
        # cable 1: como run.py, la interfaz no arranca de forma anónima
        from custodia.identity import require_actor, MissingActor
        try:
            require_actor()
        except MissingActor as e:
            print(f"ui: {e}")
            return 2
    import uvicorn
    print(f"CTSM → http://127.0.0.1:{args.port}   ({'demo' if DEMO else 'en vivo'})")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
