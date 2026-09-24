# CTSM · Customer-to-Supplier Mapping

*Read this in [English](README.md).*

Audita los requisitos de una especificación de cliente (un ReqIF exportado de Polarion) contra la documentación del proveedor (PDF), y devuelve **el mismo fichero ReqIF** con, por cada requisito, la evidencia encontrada y su página exacta. El modelo nunca escribe una ubicación. El fichero de entrada nunca se regenera. Funciona sin red.

> La IA tiene riesgos. El código los acota. La norma responde de lo que queda.

[Filosofía de diseño](#filosofía-de-diseño) · [Dónde aporta valor la IA](#dónde-aporta-valor-la-ia) · [Los cinco pasos](#los-cinco-pasos-en-este-proyecto) · [Medido](#medido) · [Demo](#demo-en-cinco-comandos-datos-públicos) · [Limitaciones](#limitaciones) · [Seguridad y regulación](#seguridad-y-regulación)

---

## Filosofía de diseño

Cualquier aplicación con IA tiene cinco pasos. Solo el paso 4 invoca un modelo; los otros cuatro son código: reproducibles, testeables, sin red. El paso 5 nunca corrige: marca y degrada. Texto completo en [epifaneia.dev](https://epifaneia.dev).

```
 1 LIMPIEZA      2 CONTEXTO      3 GUARDARRAÍL IN    4 PROCESO        5 GUARDARRAÍL OUT
 ■ código        ■ código        ■ código            ▲ modelo         ■ código
```

## Dónde aporta valor la IA

Una especificación de cliente tiene decenas de requisitos; el manual del proveedor que los responde tiene mil páginas. Cruzar lo uno con lo otro es leer y juzgar, y una herramienta convencional se ahoga: una búsqueda por palabras sobre un export de Polarion de miles de líneas XML y un manual de 1.136 páginas devuelve ruido, y una persona a mano tarda días por documento. El modelo hace lo único que solo un modelo puede hacer, leer un requisito y encontrar el pasaje que lo responde, y el código hace todo lo demás: dónde está el pasaje, si la cita es real, y que el fichero que recibe el cliente es el mismo que envió.

---

## Los cinco pasos en este proyecto

★ marca dónde está la mejora en este proyecto: el **contexto** y el **guardarraíl de salida**.

| Paso | Qué hace aquí | |
|---|---|---|
| 1 · Limpieza | `s0` añade al ReqIF los tres campos objetivo si el export no los trae (solo esquema, ids deterministas). `s1` parsea ids, jerarquía, campos objetivo y el enum de estado del propio fichero. `s2` convierte los PDF del proveedor en chunks con sección, página y `page_map` por offset (PyMuPDF; PDFs cifrados descifrados en memoria). | |
| 2 · Contexto | `s3` recupera BM25 top-K chunks por requisito, o pasa el corpus entero cuando cabe. Cada chunk lleva id, página y sección: el modelo podrá señalar, nunca describir. `utils/citables` trocea cada chunk en unidades numeradas para que una cita se elija por índice. | ★ |
| 3 · Guardarraíl de entrada | `s4` llama con un schema de respuesta forzado: `status` restringido al enum que declara el fichero, `chunk_id` restringido, por requisito, a los candidatos de ese requisito. Citar una ubicación no dada es estructuralmente imposible. | |
| 4 · Proceso | Una llamada por requisito, sin lotes. Backend `ollama` (local, por defecto) o `gemini` (nube), mismo contrato. En modo v2 no hay llamada: `s4_evidence` localiza y recorta los pasajes literales, y `s5_review` pregunta a un modelo pequeño, por pasaje, "¿apoya, contradice, irrelevante?". | |
| 5 · Guardarraíl de salida | `s6` comprueba cada quote verbatim contra el chunk citado (rapidfuzz ≥ 0,85), deriva la página exacta del offset del match, y degrada al valor abierto, con flag, cualquier veredicto que se quede sin evidencia verificada. En v2, un solo pasaje que contradiga basta para un "no". `s7` edita el original con lxml y `roundtrip_diff` demuestra que nada más cambió: tres candados, cinco sabotajes, cinco detectados. | ★ |

### Qué escribe, y dónde

| Campo del ReqIF de cliente | Qué se escribe |
|---|---|
| `Status` (enumeración) | El veredicto, por `ENUM-VALUE-REF` a un valor que el fichero ya declara. Jamás texto libre. |
| `Rationale` (XHTML) | El análisis más las citas ancladas: `[RM0008 p.81 §6.1] "quote..."`. |
| `Comments from/to External` (XHTML) | Mensaje corto al cliente: confirmación, deviation request o pregunta. |

## Medido

Set: 9 requisitos escritos contra el manual de referencia STM32F10xxx RM0008 (1.136 páginas, documento público de ST), con ground truth construido a mano. Máquina: RTX 2060 de 6 GB, Ryzen 5 3500X.

| Motor | Aciertos vs ground truth | Falsos "cumple" | Segundos / requisito |
|---|---|---|---|
| gemini (nube) | 9 / 9 | 0 | — |
| **qwen2.5:14b, local** | **8 / 9** | **0** | 122 → 77 tras calibrar |
| qwen2.5:7b, local | 7 / 9 | 0 | 25 |

De esa tabla salen tres cosas, en orden. El modelo local elimina la salida del dato. La tarea acotada es lo que hace que un 14B baste. Y lo que el 14B pierde, el guardarraíl lo marca en vez de colarlo: uno de nueve se fue a *Unconfirmed*, ninguno a un falso *Compliant*.

`tools/score_vs_fixture.py` reproduce la tabla. Calibra los hilos de Ollama con el prompt **más largo** del set, no con el más corto: un barrido con el prompt corto sugería forzar 32 capas en GPU con un +59 % aparente; con el prompt largo ese mismo ajuste era peor que el autofit de Ollama.

Además del set público, el pipeline se ha corrido sobre una especificación real de cliente (53 requisitos) y los manuales de su proveedor. Esos datos no están en este repositorio. Las capturas de abajo son de esa corrida, tachadas.

## Polarion

Datos públicos en un Polarion de prueba: los nueve requisitos de STM32 contra el RM0008. Nada que tachar.

*El documento de demo tras el import: una cabecera, nueve requisitos, cada uno con su identificador verbatim como título.*

![Documento de validación STM32 en Polarion](docs/img/polarion-02-tree.png)

*El mismo requisito después de que el pipeline escribiera en el fichero: el enum de estado puesto, el rationale con la cita, y la página y la sección derivadas por código del manual del proveedor.*

![Requisito con estado y rationale rellenados por CTSM](docs/img/polarion-04-status-rationale.png)

*El mapeo de importación ReqIF en Polarion: los campos del pipeline se mapean a los del proyecto; en el lado de Polarion no se crea nada.*

![Mapeo de importación ReqIF](docs/img/polarion-01-import.png)

## Demo en cinco comandos (datos públicos)

```bash
pip install -r requirements.txt
ollama serve && ollama pull qwen2.5:7b            # local por defecto; nada sale de la máquina

# 1. un ReqIF de partida desde el fixture, clonando el esquema de cualquier ReqIF exportado de tu Polarion
CTSM_STK_TEMPLATE=ruta/a/cualquier_export.reqif python tools/build_demo_stk.py
# 2. deja RM0008 (st.com, manual de referencia STM32F10xxx) en data/inputs/supplier_docs/
python pipeline/s2_supplier_corpus.py             # PDF → corpus (1,9 s para 1.136 páginas)
python run.py STM32                               # s1 → s7 sobre el fichero de demo
python tools/roundtrip_diff.py data/inputs/stk_reqif/STM32F10xxx_Validation.reqif data/outputs/reqif/STM32F10xxx_Validation.reqif
```

Este repositorio no lleva datos: ni entradas, ni intermedios, ni salidas. `data/` está fuera de git.

## Limitaciones

- La demo necesita un ReqIF exportado de *tu* Polarion como plantilla de esquema. Los exports cambian por proyecto, así que `build_demo_stk` clona el tuyo por `LONG-NAME` en vez de traer uno.
- `s5_config` (extracción de parámetros de configuración) es un stub retirado del alcance.
- El scoring que `s6` promete en su docstring nunca corre sobre ficheros reales. Usa `tools/score_vs_fixture.py`.
- El import en Polarion de un fichero escrito por el pipeline se ha verificado estructuralmente (roundtrip_diff) y visualmente (capturas); el import en sí es un paso manual.
- Docling queda reservado para documentos escaneados y no está conectado por defecto: descarga modelos en la primera ejecución, y eso rompería el air gap de `s2`.
- Identidad, eventos y firma van como contrato con un valor local por defecto (variable de entorno, fichero JSONL, clave HMAC). Los adaptadores al Entra ID, SIEM o PKI de una empresa no están aquí ni se pueden probar aquí: ver [docs/INTEGRATION.es.md](docs/INTEGRATION.es.md).

---

## Seguridad y regulación

Los mismos cuatro epígrafes en todos los repositorios. Las filas **hoy** son lo que hace el código. Las filas **cable** son los tres cables de integración que el repositorio trae como contrato (identidad, eventos, firma) y la empresa conecta a sus sistemas: ver [docs/INTEGRATION.es.md](docs/INTEGRATION.es.md). Pruebas locales: `python tests/test_custodia.py`.

| | | |
|---|---|---|
| **Confidencialidad** | Local por defecto: Ollama en `127.0.0.1`, un modelo de 14B, ningún byte sale de la máquina, el pipeline completo funciona con la red desenchufada. La tarea está lo bastante acotada para que ese modelo baste (8/9, 0 falsos "cumple"). El backend de nube es solo para dato no confidencial y comparación: cuando está activo, `s4` imprime en cada ejecución que envía el texto del requisito y hasta 10 chunks del manual (~28.000 caracteres) a Google. Los PDF cifrados se descifran en memoria; no se escribe copia en claro. `data/` y `.env` fuera de git. | **hoy** |
| **Trazabilidad** | Cada veredicto lleva su evidencia con documento, página, sección y ratio de match; la cita la compone el código, nunca el modelo. `logs/` guarda trazas por ejecución con ids de chunk, puntuaciones y flags, nunca el texto del requisito ni el prompt. | **hoy** |
| | **Cable 2 · eventos.** Toda llamada al modelo pasa por `custodia/ledger`: una línea JSON con actor, paso, motor, endpoint, si el dato salió, tamaño y hash. Nunca el texto. `logs/custody.jsonl` o stdout. La empresa apunta su SIEM ahí. | **cable** |
| **Prevención de fugas** | El modelo no tiene credenciales; el paso que lo invoca tiene el endpoint y solo ve los chunks seleccionados para ese requisito. Todo lo demás es código sin acceso a red. | **hoy** |
| | **Cable 1 · identidad.** `run.py` se niega a arrancar sin un actor con nombre (`custodia/identity`, por defecto `CUSTODIA_ACTOR`); el actor se estampa en cada evento y cada firma. La empresa sustituye el proveedor por Entra ID, LDAP, Kerberos o su SSO en una llamada. Los permisos por capa sobre entradas, intermedios, modelo y salidas son los de la empresa, en su sistema de ficheros y su vault. | **cable** |
| **Humano en el bucle** | Todo requisito sin evidencia verificada se queda en el valor abierto con un flag; el revisor mira lo marcado, no todo. En modo v2 el sistema nunca dictamina: localiza evidencia y decide el ingeniero. | **hoy** |
| | **Cable 3 · firma.** Una salida es una propuesta hasta que `tools/signoff.py sign` escribe su manifiesto (hash del fichero, actor, fecha, firma) y `verify` pasa; un fichero cambiado o una clave distinta fallan. Nada que haya tocado el modelo se importa ni se envía sin un manifiesto que verifique. La empresa sustituye la clave HMAC local por su PKI o por el flujo de aprobación de Polarion registrando dos funciones. | **cable** |

Marco: EU AI Act (2024/1689) · RGPD · ISO/IEC 42001 · ISO/IEC 27001 · TISAX.

---

## Estructura

```
pipeline/    s0..s7 (s5_config retirado)      docs/       PLAN.md · RISK_roundtrip.md · INTEGRATION.es.md · pipeline_arquitectura.html
clients/     ollama (local, por defecto) · gemini (nube) · docling_adapter
prompts/     evaluar_status.txt (taxonomía inyectada en runtime)
tools/       roundtrip_diff · reqif_lint · score_vs_fixture · build_demo_stk · build_report · signoff
utils/       citables · text_norm · json_helpers
custodia/    identity · ledger · signoff · cli  — los tres cables de integración
data/        inputs · interim · outputs — todo fuera de git
```

Daniel Martín · [epifaneia.dev](https://epifaneia.dev) · Apache-2.0
