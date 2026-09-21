"""Cliente HTTP para Ollama (inferencia LOCAL, air-gap).

Alternativa a clients/gemini para que NINGÚN dato de cliente salga de la
máquina: mismo contrato que `gemini.generate_json_schema` — salida forzada
por JSON Schema — contra http://127.0.0.1:11434.

Dos diferencias con Gemini que aquí importan y mucho:

  · Dialecto de schema. s4 construye el schema en el dialecto OpenAPI de
    Gemini ("type": "OBJECT"). Ollama espera JSON Schema puro
    ("type": "object"). `to_json_schema()` traduce — sin eso el enum de
    chunk_id no se aplica y se pierde la trazabilidad garantizada.

  · Ventana de contexto. Ollama trunca el prompt a num_ctx EN SILENCIO
    (default 4096 = ~16k chars). Un prompt de 10 chunks son ~30k chars: se
    perdería la mitad de la documentación sin un solo aviso, y el modelo
    citaría sobre evidencia que no vio. Por eso num_ctx es explícito y
    `assert_fits()` aborta antes de llamar si no cabe.

No depende de ningún SDK — solo urllib de la stdlib.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

_log = logging.getLogger(__name__)

# Traducción del dialecto OpenAPI (Gemini) a JSON Schema (Ollama/llama.cpp)
_TYPES = {"OBJECT": "object", "STRING": "string", "ARRAY": "array",
          "INTEGER": "integer", "NUMBER": "number", "BOOLEAN": "boolean"}

# Estimador conservador de tokens para texto técnico en inglés (~3.6 chars/token
# medido sobre RM0008). Se queda corto a propósito: preferimos abortar de más.
_CHARS_PER_TOKEN = 3.2


def to_json_schema(schema: Any) -> Any:
    """OpenAPI dialect (type en MAYÚSCULAS) → JSON Schema puro, recursivo."""
    if isinstance(schema, list):
        return [to_json_schema(s) for s in schema]
    if not isinstance(schema, dict):
        return schema
    out: dict[str, Any] = {}
    for k, v in schema.items():
        if k == "type" and isinstance(v, str):
            out[k] = _TYPES.get(v.upper(), v.lower())
        elif k in ("properties", "$defs") and isinstance(v, dict):
            # mapa nombre->schema: recursión sobre los VALORES, no sobre el mapa
            out[k] = {name: to_json_schema(sub) for name, sub in v.items()}
        elif k == "items":
            out[k] = to_json_schema(v)
        else:
            out[k] = v
    if out.get("type") == "object" and "properties" in out:
        out.setdefault("additionalProperties", False)
    return out


def estimate_tokens(text: str) -> int:
    return int(len(text) / _CHARS_PER_TOKEN) + 1


def assert_fits(*, system: str, user: str, num_ctx: int, reserve: int = 1024) -> None:
    """Aborta si el prompt no cabe en num_ctx (Ollama truncaría en silencio)."""
    need = estimate_tokens(system) + estimate_tokens(user) + reserve
    if need > num_ctx:
        raise ValueError(
            f"prompt ~{need} tokens > num_ctx {num_ctx}: Ollama truncaría la "
            f"documentación en silencio y el veredicto citaría sobre evidencia "
            f"no vista. Sube CTSM_OLLAMA_NUM_CTX o baja CTSM_S3_TOP_K."
        )


def generate_json_schema(
    *,
    base_url: str,
    model: str,
    user_text: str,
    response_schema: dict,
    system_instruction: str | None = None,
    temperature: float = 0.1,
    num_ctx: int = 16384,
    num_gpu: int | None = None,
    num_thread: int | None = None,
    timeout_s: float = 1200.0,
) -> Any:
    """Como `gemini.generate_json_schema` pero 100% local. Misma garantía:
    la salida ES el schema (enums cerrados impuestos por el decodificador,
    no prometidos en el prompt)."""
    assert_fits(system=system_instruction or "", user=user_text, num_ctx=num_ctx)

    messages = []
    if system_instruction:
        messages.append({"role": "system", "content": system_instruction})
    messages.append({"role": "user", "content": user_text})

    body = {
        "model": model,
        "messages": messages,
        "format": to_json_schema(response_schema),
        "stream": False,
        "options": {"temperature": temperature, "num_ctx": num_ctx},
    }
    # num_gpu: capas en VRAM. El autofit de Ollama es conservador y deja VRAM sin
    # usar; cada capa que baja a CPU cuesta velocidad. num_thread: por defecto usa
    # la mitad de los núcleos, que en un CPU sin SMT es dejarse la mitad.
    if num_gpu is not None:
        body["options"]["num_gpu"] = num_gpu
    if num_thread is not None:
        body["options"]["num_thread"] = num_thread
    raw = _post(f"{base_url.rstrip('/')}/api/chat", body, timeout_s=timeout_s)

    # Guard duro: si Ollama truncó pese a todo, el contador lo delata.
    ev = raw.get("prompt_eval_count")
    if isinstance(ev, int) and ev >= num_ctx - 8:
        raise ValueError(
            f"prompt_eval_count={ev} tocó num_ctx={num_ctx}: hubo truncado. "
            f"Veredicto descartado."
        )

    text = ((raw.get("message") or {}).get("content") or "").strip()
    if not text:
        raise ValueError(f"Ollama sin contenido: {str(raw)[:300]}")
    return json.loads(text)


def _post_raw(url: str, body: dict, *, timeout_s: float) -> dict:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"Ollama no responde en {url} ({e}). ¿Arrancaste 'ollama serve'?"
        ) from e

ENGINE_NAME = "ollama"

# --- cable 2: libro de custodia. Toda llamada al modelo pasa por aquí. ---
def _post(url: str, body: dict, *, timeout_s: float) -> dict:
    import json as _json, sys as _sys
    from pathlib import Path as _Path
    from custodia.ledger import record_call, is_local
    payload = _json.dumps(body, ensure_ascii=False)
    step = _Path(_sys.argv[0]).stem if _sys.argv and _sys.argv[0] else "unknown"
    with record_call(step=step, engine=ENGINE_NAME, endpoint=url.split("/")[2] if "//" in url else url,
                     leaves_machine=not is_local(url), payload=payload) as rec:
        raw = _post_raw(url, body, timeout_s=timeout_s)
        rec["output_chars"] = len(_json.dumps(raw)) if raw is not None else 0
        return raw
