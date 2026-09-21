"""Configuración central de CTSM: rutas y parámetros. Sin lógica.

Patrón heredado de reqif-extractor (probado): .env sin dependencias, rutas overridables
por variables de entorno CTSM_*.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _load_env(path: Path) -> None:
    """Carga KEY=VALUE de .env a os.environ (sin dependencias, no pisa lo ya puesto)."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env(ROOT / ".env")


def _env_dir(var: str, default: Path) -> Path:
    v = os.environ.get(var, "").strip()
    return Path(v).resolve() if v else default


# --- Datos (flujo STK+docs -> ... -> reqif actualizado) ---
_DATA_DIR         = _env_dir("CTSM_DATA_DIR", ROOT / "data")
STK_INPUTS_DIR    = _env_dir("CTSM_STK_DIR",      _DATA_DIR / "inputs" / "stk_reqif")      # ReqIF de Polarion
SUPPLIER_DOCS_DIR = _env_dir("CTSM_SUPPLIER_DIR", _DATA_DIR / "inputs" / "supplier_docs")  # PDFs/Words proveedor
STK_PREPARED_DIR  = _env_dir("CTSM_STK_PREP_DIR", _DATA_DIR / "interim" / "stk_prepared") # s0: ReqIF con campos objetivo creados
STK_JSON_DIR      = _env_dir("CTSM_STK_JSON_DIR", _DATA_DIR / "interim" / "stk_json")      # s1 lectura
CORPUS_DIR        = _env_dir("CTSM_CORPUS_DIR",   _DATA_DIR / "interim" / "corpus")        # s2 extracción
EVIDENCE_DIR      = _env_dir("CTSM_EVIDENCE_DIR", _DATA_DIR / "interim" / "evidence")      # s3 retrieval
EVAL_DIR          = _env_dir("CTSM_EVAL_DIR",     _DATA_DIR / "interim" / "eval")          # s4 veredictos crudos
REVIEW_DIR        = _env_dir("CTSM_REVIEW_DIR",   _DATA_DIR / "interim" / "review")        # s5 juicio por pasaje
RESULTS_DIR       = _env_dir("CTSM_RESULTS_DIR",  _DATA_DIR / "interim" / "results")       # s6 sellado = CONTRATO
OUTPUT_REQIF_DIR  = _env_dir("CTSM_OUTPUT_DIR",   _DATA_DIR / "outputs" / "reqif")         # s7 entregable

# --- Assets ---
PROMPTS_DIR = ROOT / "prompts"

# --- LLM (solo s4; el resto del pipeline NO usa modelo) ---
# Backend de inferencia. "ollama" = AIR-GAP: ningún dato de cliente sale de la
# máquina (default deliberado: la documentación del proveedor es confidencial).
# "gemini" = nube; solo con clave de tier de pago y con el cliente informado.
LLM_BACKEND = os.environ.get("CTSM_LLM_BACKEND", "ollama").strip().lower()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
GEMINI_MODEL   = os.environ.get("GEMINI_MODEL", "gemini-3.1-pro-preview")

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL    = os.environ.get("CTSM_OLLAMA_MODEL", "qwen2.5:7b")
# num_ctx explícito: Ollama trunca a 4096 por defecto EN SILENCIO — con 10 chunks
# de 2800 chars se comería media documentación sin avisar. Ver clients/ollama.py.
OLLAMA_NUM_CTX  = int(os.environ.get("CTSM_OLLAMA_NUM_CTX", "16384"))
# Capas en GPU (None = autofit de Ollama, conservador: deja VRAM libre) y núcleos
# de CPU (None = default, la mitad). Ajustar al hardware sube el throughput de un
# modelo que no cabe entero en VRAM sin tocar la calidad del veredicto.
_g = os.environ.get("CTSM_OLLAMA_NUM_GPU", "").strip()
_t = os.environ.get("CTSM_OLLAMA_NUM_THREAD", "").strip()
OLLAMA_NUM_GPU    = int(_g) if _g else None
OLLAMA_NUM_THREAD = int(_t) if _t else None

# --- Campos objetivo en el STK (detectados por LONG-NAME en s1) ---
# El enum REAL de status lo dicta el propio STK (s1 extrae LONG-NAME → ENUM-VALUE
# IDENTIFIER); esta lista es solo una taxonomía de referencia.
TARGET_FIELD_LONGNAMES = {
    "status":    "Status",                     # ENUMERATION
    "rationale": "Rationale",                  # XHTML
    "comments":  "Comments from/to External",  # XHTML
}

# --- Taxonomía de Status (mapeo 1:1 con el enum del STK; NO texto libre) ---
# STK de demo: Compliant / Not compliant / Unconfirmed (demo).
STATUS_TAXONOMY = [
    "Accepted",
    "Accepted with deviation",
    "Not accepted",
    "Not applicable",
    "In review",
]
STATUS_DEFAULT = "In review"   # ante la duda, SIEMPRE a revisión humana

# Valores del enum que s0 CREA cuando el ReqIF no trae campo de status. Por
# defecto los del STK real que se procese, no la taxonomía de referencia
# de arriba: tienen que coincidir con el campo custom del Polarion destino.
STATUS_VALUES_NUEVO_STK = [
    v.strip() for v in os.environ.get(
        "CTSM_STATUS_VALUES", "Compliant,Not compliant,Unconfirmed").split(",") if v.strip()
]

# --- Corpus (s2) ---
CHUNK_CHARS         = int(os.environ.get("CTSM_CHUNK_CHARS", "2800"))    # tamaño objetivo de chunk
# Un chunk NO se cierra a mitad de frase: al llegar al objetivo se sigue hasta el
# siguiente final de frase, con este margen como tope duro. Cortar por número de
# caracteres entregaba evidencia mutilada ("puede tener una frecuencia de hasta",
# con el valor en el chunk siguiente) y el modelo juzgaba sobre texto roto.
CHUNK_MAX_FACTOR    = float(os.environ.get("CTSM_CHUNK_MAX_FACTOR", "1.35"))
# Solape entre chunks contiguos: lo que quede a caballo aparece completo en uno.
CHUNK_OVERLAP_CHARS = int(os.environ.get("CTSM_CHUNK_OVERLAP", "220"))

# PDFs cifrados: contraseñas candidatas. Se prueban en orden contra cada PDF que
# las pida, así un set con varios proveedores no necesita mapear fichero→clave.
# Nunca se imprimen ni se persisten.
#
# Dos vías, y la segunda gana cuando la clave tiene caracteres incómodos:
#   1) CTSM_PDF_PASSWORDS en .env, separadas por ';'  — cómodo, pero el ';' no
#      puede aparecer DENTRO de una clave y las comillas de los extremos se comen.
#   2) CTSM_PDF_PASSWORD_FILE — fichero aparte, UNA CLAVE POR LÍNEA, tomada
#      LITERAL: sin separadores, sin comillas, sin comentarios, sin strip. Admite
#      ';', '#', '=', comillas y espacios al borde. Se lee como utf-8-sig para
#      tolerar el BOM que mete el Bloc de notas de Windows.
# Por defecto se mira .pdf_passwords en la raíz del proyecto (ya en .gitignore).

def _read_password_file(path: Path) -> list[str]:
    if not path.is_file():
        return []
    # utf-8-sig: se traga el BOM si lo hay. newline='' no hace falta: splitlines()
    # corta bien con CRLF, y no tocamos el contenido de cada línea.
    return [ln for ln in path.read_text(encoding="utf-8-sig").splitlines() if ln]


_pw_file = _env_dir("CTSM_PDF_PASSWORD_FILE", ROOT / ".pdf_passwords")
PDF_PASSWORDS: list[str] = (
    _read_password_file(_pw_file)
    or [pw for pw in os.environ.get("CTSM_PDF_PASSWORDS", "").split(";") if pw]
)
PDF_PASSWORDS_SOURCE = (f"{_pw_file.name} ({len(PDF_PASSWORDS)} clave/s)"
                        if _read_password_file(_pw_file) else "CTSM_PDF_PASSWORDS (.env)")

# --- Retrieval (s3) ---
S3_TOP_K            = int(os.environ.get("CTSM_S3_TOP_K", "10"))         # chunks candidatos por requisito

# --- Evaluación (s4/s5) ---
BATCH_SIZE          = int(os.environ.get("CTSM_BATCH_SIZE", "15"))       # reqs por llamada
# Muestreo para sondear un STK grande antes de comprometer horas de inferencia:
# N requisitos repartidos UNIFORMEMENTE por el documento (no los N primeros, que
# suelen ser portada y referencias). 0 = todos.
SAMPLE_N            = int(os.environ.get("CTSM_SAMPLE_N", "0"))
LLM_TIMEOUT         = float(os.environ.get("CTSM_LLM_TIMEOUT", "1200"))  # s por llamada
CORPUS_MAX_CHARS    = int(os.environ.get("CTSM_CORPUS_MAX_CHARS", "900000"))  # si el corpus cabe, va entero


def corpus_max_chars() -> int:
    """Umbral REAL de passthrough para el backend en uso.

    CORPUS_MAX_CHARS (900k) está dimensionado para el contexto de Gemini. Con
    Ollama a 16k tokens, pasar el corpus entero es imposible: el guard de
    clients/ollama abortaría cada requisito. Aquí se deriva el límite de la
    ventana real, dejando sitio al system prompt y a la respuesta, para que s3
    caiga solo a BM25 top-K cuando toca.
    """
    if LLM_BACKEND != "ollama":
        return CORPUS_MAX_CHARS
    disponible = OLLAMA_NUM_CTX - 1024 - 900        # respuesta + system prompt
    return max(0, int(disponible * 3.2))            # ~3,2 chars/token

# --- Revisión por pasaje (s5) ---
# Modelo barato para el grueso: la tarea es mecánica (juzgar un pasaje contra un
# requisito) y el trabajo difícil ya lo hizo s4. Los desacuerdos con s4 los
# arbitra OLLAMA_MODEL — un modelo pequeño no enmienda al grande sin revisar.
REVIEW_MODEL   = os.environ.get("CTSM_REVIEW_MODEL", "qwen2.5:7b")
REVIEW_WORKERS = int(os.environ.get("CTSM_REVIEW_WORKERS", "2"))

# --- Verificación (s6) ---
QUOTE_MIN_RATIO     = float(os.environ.get("CTSM_QUOTE_MIN_RATIO", "0.85"))  # fuzzy match quote↔corpus
JUDGE_ENABLED       = os.environ.get("CTSM_JUDGE", "0") in ("1", "true", "True")

# --- Orquestación (run.py) ---
DOC_WORKERS    = int(os.environ.get("CTSM_DOC_WORKERS", "3"))
S2_CONCURRENCY = int(os.environ.get("CTSM_S2_CONCURRENCY", "1"))  # docling pesado en CPU/RAM
