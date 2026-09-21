# PLAN — diseño del pipeline CTSM y preguntas abiertas

## Contratos JSON (la columna vertebral)

### `stk_json/<stem>.json` — lo que sale de s1 (lectura del STK)
```json
{
  "source_file": "STM32F10xxx_Validation.reqif",
  "requisitos": [
    {
      "spec_object_id": "…",        // IDENTIFIER del SPEC-OBJECT — INTOCABLE
      "foreign_id": "…",            // ReqIF.ForeignID (OEM REQ ID) si existe
      "texto": "…",                  // ReqIF.Text plano (extraído del XHTML)
      "campos_objetivo": {           // refs a los ATTRIBUTE-DEFINITION destino
        "status": "AD-…",            // el enum de cumplimiento
        "comments": "AD-…",          // Comments from/to External | Rationale
        "config": "AD-…"             // campo de configuración (si existe)
      },
      "status_enum_values": {        // mapeo LONG-NAME → ENUM-VALUE IDENTIFIER
        "Accepted": "EV-…", "Accepted with deviation": "EV-…", "...": "…"
      }
    }
  ]
}
```

### `results/<stem>.json` — la FRONTERA (s6 la sella, s7 la consume)
```json
{
  "source_file": "STM32F10xxx_Validation.reqif",
  "resultados": [
    {
      "spec_object_id": "…",
      "status": "Accepted with deviation",     // ∈ taxonomía, validado en s6
      "rationale": "…",                         // texto para Comments/Rationale
      "evidencias": [
        {"doc": "HSM_Manual.pdf", "ubicacion": "§4.2 / p.31", "quote": "…"}
      ],
      "config": "HSM_NUMBER_OF_POSITIONS=0xFF @ 0xFACC500 …",  // o null
      "confianza": 0.86,
      "flags": []                               // p.ej. ["quote_no_encontrada"]
    }
  ]
}
```

## Decisiones ya tomadas (heredadas de reqif-extractor y de un pipeline anterior)

1. **s7 edita, no construye.** lxml sobre el original; tocar SOLO los
   `ATTRIBUTE-VALUE-*` de los campos objetivo. Los `IDENTIFIER`, `SPEC-TYPES`,
   `SPEC-HIERARCHY` y el orden de elementos no se tocan ni se re-serializan
   alegremente (cuidado con lxml normalizando el XML: preservar declaración,
   namespaces y formato tanto como sea posible).
2. **XHTML con UN solo `<xhtml:div>` raíz** en cualquier valor XHTML que
   escribamos (bug histórico de import ya conocido).
3. **Enum por referencia, no por texto.** El Status se escribe como
   `ATTRIBUTE-VALUE-ENUMERATION` apuntando al `ENUM-VALUE` del propio archivo
   (mapeo LONG-NAME→IDENTIFIER extraído en s1). Nada de strings sueltos.
4. **Guard anti-alucinación (s6).** Toda evidencia lleva quote textual; s6
   comprueba que la quote existe (fuzzy razonable) en el corpus del proveedor.
   Si no → flag + degradar a `In review`. Herencia del guard de reqif-extractor.
5. **`In review` es el default ante la duda.** Mejor un humano mira 20 que
   fiarse de 200 mal puestos.
6. **Frontera results.json** para iterar la parte cara (s4/s5) sin re-escribir,
   y la escritura (s7) sin re-pagar.
7. **run.py estilo reqif-extractor**: docs en paralelo, cada paso subproceso, fallo de
   un doc no tumba a los demás.

## Preguntas ABIERTAS (a resolver con material real)

1. **Necesitamos un STK real** en `reference/` para fijar s1: nombres exactos de
   los ATTRIBUTE-DEFINITION destino (¿"Comments from/to External"? ¿"Rationale"?
   ¿campo de config propio o va dentro de comments?), y el ENUMERATION real del
   Status (¿existen los 5 valores? ¿con qué LONG-NAMEs exactos?).
2. **Retrieval (s3): ¿RAG o contexto entero?** Depende del tamaño real de los
   supplier docs. Si el corpus cabe en 1M de contexto → s3 trivial (todo el
   corpus por llamada, agrupando requisitos por lotes). Si no → BM25/embeddings
   por requisito. Empezar simple: corpus entero si cabe; medir.
3. **Batching de s4:** ¿requisito a requisito (caro, trazable) o lotes de N
   contra el mismo corpus (barato, riesgo de mezcla)? Propuesta: lotes de
   10-20 con responseSchema por lote.
4. **¿Un solo LLM-pass para status+config o dos (s4/s5)?** Separados de inicio
   (prompts más simples, config solo para Accepted/deviation); fusionar si el
   coste duele.
5. **Roundtrip real:** validar con un import de verdad en Polarion
   lo antes posible — el diff estructural (tools/roundtrip_diff.py) es necesario
   pero no suficiente; la prueba de fuego es el importador.
6. **Volumen y coste:** ¿cuántos requisitos por STK y cuántas páginas de
   proveedor? Fija el presupuesto por documento y la decisión 2/3.
```

---

## Estado 2026-07-13 — fase 2 validada (motor s2–s6)

Prueba con RM0008 (1136 págs, 2M chars → 1804 chunks PyMuPDF) y 9 requisitos
sintéticos de NotebookLM (3 aceptar / 3 rechazar / 3 ambiguos): **9/9 contra
ground truth, 0 flags del guard**.

Decisiones que quedan fijadas por esta prueba:
- **Cita constrained de verdad**: s4 usa responseSchema con enum dinámico — el
  chunk_id citable se restringe a los candidatos de s3 POR REQUISITO. El LLM
  nunca escribe página/sección: las deriva s6 del page_map del chunk
  (offset del match rapidfuzz → página exacta).
- **Retrieval**: BM25 top-10 suficiente en manual de 1136 págs (recall 9/9 en
  top-4). Passthrough automático si corpus ≤ CORPUS_MAX_CHARS.
- **Extracción**: PyMuPDF para PDF digital (1.9s las 1136 págs); docling queda
  reservado para docs feos (escaneado/Word). Dedupe por sha256.
- **1 llamada por requisito** (no lotes): permite el enum dinámico de chunk_ids
  y aísla fallos. ~5-9s/req con gemini-3.1-pro-preview.
- **Semántica de taxonomía**: stk.json lleva status_semantics (yes/no/open)
  inferida por heurística en s1; corregible a mano. El STK real de la prueba traía
  enum de 3 valores: Compliant / Not compliant / Unconfirmed.

Pendiente: import Polarion de la fase 1 · s5 config
(extracción de parámetros; el STK de prueba no trae campo de config dedicado)
· docling para supplier docs no-digitales · run.py end-to-end cuando s5 exista.
