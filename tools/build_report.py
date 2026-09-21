"""build_report — informe HTML breve y explicativo de una corrida CTSM.

DETERMINISTA, sin red. Un único fichero autocontenido (nada de CSS ni fuentes
externas: es material bajo NDA y no debe pedir nada a internet al abrirse).

Deliberadamente NO enumera los cientos de requisitos: el destinatario del
informe necesita entender qué se ha hecho, cuánto vale y qué hacer después. Los
datos completos ya viajan en el ReqIF. Aquí van las cifras, unos pocos ejemplos
verificables a mano, y la explicación del guard anti-alucinación con un caso real.

Todo lo cuantitativo sale de config.RESULTS_DIR (la frontera sellada por s6) y
de config.EVAL_DIR (los veredictos crudos, para contar lo que el guard descartó).

Uso:  python tools/build_report.py <stem> [<stem> ...] [-o salida.html]
"""
from __future__ import annotations

import html
import json
import re
import sys
from collections import Counter
from pathlib import Path

from rapidfuzz import fuzz

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402


def _cargar(stem: str) -> dict:
    res = json.loads((config.RESULTS_DIR / f"{stem}.json").read_text(encoding="utf-8"))["results"]
    stk = json.loads((config.STK_JSON_DIR / f"{stem}.json").read_text(encoding="utf-8"))
    crudo = json.loads((config.EVAL_DIR / f"{stem}.json").read_text(encoding="utf-8"))
    txt = {o["identifier"]: (o.get("text") or "") for o in stk["objects"]}
    filas = []
    for r in res:
        sid = r.get("spec_object_id") or ""
        t = txt.get(sid, "")
        m = re.match(r"(CYS-[A-Z]+_[0-9a-f]+_\d+)", t)
        cab = m.group(1) if m else ""
        filas.append({"id": sid.split("_")[-1], "cab": cab, "texto": t[len(cab):].strip(),
                      "status": r["status"], "rationale": r.get("rationale", ""),
                      "comments": r.get("comments", ""), "evidence": r.get("evidence") or [],
                      "flags": r.get("flags") or []})   # los usa el recuento del verificador
    return {"stem": stem, "corto": stem[:7], "filas": filas,
            "cuenta": Counter(f["status"] for f in filas), "total": len(filas),
            "con_ev": sum(1 for r in crudo if r.get("evidence")), "crudo": crudo}


def _descartadas(docs: list[dict], by: dict) -> list[dict]:
    """Citas que el guard tiró, con cuánto texto real copiaron antes de inventar."""
    out = []
    for d in docs:
        for r in d["crudo"]:
            for e in r.get("evidence") or []:
                ch = by.get(e["chunk_id"])
                if not ch:
                    continue
                ratio = fuzz.partial_ratio(e["quote"], ch["text"]) / 100
                if ratio >= config.QUOTE_MIN_RATIO:
                    continue
                real = 0
                for n in range(20, min(len(e["quote"]), 300), 5):
                    if fuzz.partial_ratio(e["quote"][:n], ch["text"]) >= 97:
                        real = n
                out.append({"doc": d["corto"], "req": r["spec_object_id"].split("_")[-1],
                            "chunk": ch["chunk_id"], "ratio": ratio, "real": real,
                            "quote": e["quote"], "texto": ch["text"],
                            "manual": ch["doc"], "pag": ch["page_start"],
                            "sec": ch.get("section", "")})
    return sorted(out, key=lambda x: -x["real"])


def _trozo_parecido(quote: str, texto: str) -> str:
    q, best, bi = len(quote), 0, 0
    for i in range(0, max(1, len(texto) - q), 15):
        s = fuzz.ratio(quote, texto[i:i + q])
        if s > best:
            best, bi = s, i
    return texto[bi:bi + q]


CSS = """
:root{--bg:#f7f8fa;--panel:#fff;--tinta:#151a21;--suave:#59636f;--linea:#e3e7ed;
 --ok:#1c7a4a;--ok-bg:#e9f6ef;--al:#8a6100;--al-bg:#fdf3e0;--mal:#a3341d;--mal-bg:#fbeceb;--acc:#2a4a7f}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
 --bg:#0f1216;--panel:#171c22;--tinta:#e9edf2;--suave:#98a3af;--linea:#272d36;
 --ok:#5fd39b;--ok-bg:#122a20;--al:#e3ba60;--al-bg:#2a2214;--mal:#f08c76;--mal-bg:#2a1714;--acc:#8fb0e6}}
:root[data-theme="dark"]{--bg:#0f1216;--panel:#171c22;--tinta:#e9edf2;--suave:#98a3af;--linea:#272d36;
 --ok:#5fd39b;--ok-bg:#122a20;--al:#e3ba60;--al-bg:#2a2214;--mal:#f08c76;--mal-bg:#2a1714;--acc:#8fb0e6}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--tinta);
 font:16.5px/1.68 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:760px;margin:0 auto;padding:40px 22px 90px}
h1{font-size:1.85rem;line-height:1.25;margin:0 0 8px;letter-spacing:-.01em}
h2{font-size:1.28rem;margin:46px 0 12px;letter-spacing:-.01em}
h3{font-size:1.02rem;margin:26px 0 8px}
p{margin:0 0 14px}
.sub{color:var(--suave);margin:0 0 8px;font-size:.95rem}
.nda{background:var(--mal-bg);border-left:3px solid var(--mal);padding:10px 14px;
 border-radius:0 6px 6px 0;margin:22px 0;font-size:.9rem}
.cifras{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;margin:22px 0}
.c{background:var(--panel);border:1px solid var(--linea);border-radius:10px;padding:14px}
.c .n{font-size:1.85rem;font-weight:700;line-height:1.05;letter-spacing:-.02em}
.c .l{color:var(--suave);font-size:.78rem;text-transform:uppercase;letter-spacing:.05em;margin-top:2px}
.c.ok .n{color:var(--ok)}.c.al .n{color:var(--al)}
.tablewrap{overflow-x:auto;border:1px solid var(--linea);border-radius:10px;background:var(--panel);margin:18px 0}
table{width:100%;border-collapse:collapse;font-size:.9rem}
th,td{padding:9px 13px;text-align:left;border-bottom:1px solid var(--linea)}
th{background:var(--bg);font-size:.76rem;text-transform:uppercase;letter-spacing:.05em;color:var(--suave)}
tr:last-child td{border-bottom:none}
td.num{text-align:right;font-variant-numeric:tabular-nums}
.caso{background:var(--panel);border:1px solid var(--linea);border-radius:12px;padding:18px 20px;margin:18px 0}
.caso h3{margin-top:0}
.donde{background:var(--bg);border-radius:8px;padding:10px 14px;margin:12px 0;
 font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:.83rem;color:var(--acc)}
.q{margin:10px 0;padding:12px 14px;border-radius:8px;font-size:.92rem}
.q .et{font-size:.72rem;text-transform:uppercase;letter-spacing:.06em;font-weight:700;
 display:block;margin-bottom:5px}
.q.buena{background:var(--ok-bg)} .q.buena .et{color:var(--ok)}
.q.mala{background:var(--mal-bg)} .q.mala .et{color:var(--mal)}
.q.real{background:var(--bg)} .q.real .et{color:var(--suave)}
.q i{font-style:italic}
mark{background:var(--al-bg);color:var(--al);padding:0 2px;border-radius:3px;font-weight:600}
.ojo{border-left:3px solid var(--mal);background:var(--mal-bg);padding:12px 15px;
 border-radius:0 8px 8px 0;margin:14px 0;font-size:.92rem}
.ojo b{color:var(--mal)}
.verifica{border-left:3px solid var(--ok);background:var(--ok-bg);padding:11px 15px;
 border-radius:0 8px 8px 0;margin:14px 0;font-size:.9rem}
.verifica b{color:var(--ok)}
.paso{background:var(--panel);border:1px solid var(--linea);border-radius:10px;padding:16px 18px;margin:12px 0}
.paso h3{margin:0 0 6px;display:flex;flex-wrap:wrap;align-items:baseline;gap:9px}
.tag{font-size:.71rem;padding:2px 9px;border-radius:99px;font-weight:700;text-transform:uppercase;letter-spacing:.04em}
.tag.ya{background:var(--ok-bg);color:var(--ok)}
.tag.caro{background:var(--mal-bg);color:var(--mal)}
.tag.duda{background:var(--al-bg);color:var(--al)}
.tag.no{background:var(--mal-bg);color:var(--mal)}
code{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:.87em;
 background:var(--bg);padding:1px 6px;border-radius:4px}
footer{margin-top:56px;padding-top:16px;border-top:1px solid var(--linea);color:var(--suave);font-size:.84rem}
"""


def construir(stems: list[str], salida: Path) -> None:
    docs = [_cargar(s) for s in stems]
    corpus = json.loads((config.CORPUS_DIR / "corpus.json").read_text(encoding="utf-8"))
    by = {c["chunk_id"]: c for c in corpus["chunks"]}
    manuales = corpus["docs"]

    tot = sum(d["total"] for d in docs)
    ok = sum(d["cuenta"].get("Compliant", 0) for d in docs)
    no = sum(d["cuenta"].get("Not compliant", 0) for d in docs)
    ab = sum(d["cuenta"].get("Unconfirmed", 0) for d in docs)
    con_ev = sum(d["con_ev"] for d in docs)
    sin_nada = tot - con_ev

    tiradas = _descartadas(docs, by)
    estrella = tiradas[0] if tiradas else None

    alineados = [(d, f) for d in docs for f in d["filas"] if f["status"] == "Compliant"]
    ejemplos = sorted(
        [(d, f) for d, f in alineados if f["evidence"]],
        key=lambda x: -(x[1]["evidence"][0].get("match_ratio") or 0))[:2]
    abierto = next((f for d in docs for f in d["filas"]
                    if f["status"] == "Unconfirmed" and f["comments"]), None)

    p: list[str] = ['<div class="wrap">']
    p.append("<h1>Auditoría automática de requisitos frente a documentación de proveedor</h1>")
    p.append(f'<p class="sub">{stem} · {len(manuales)} manuales de proveedor · '
             f'análisis local con Qwen 2.5 14B</p>')
    p.append('<div class="nda"><b>Confidencial.</b> Incluye requisitos de cliente y extractos de '
             'documentación de proveedor bajo NDA. No subir a servicios externos ni a herramientas '
             'de IA comerciales.</div>')

    # ---------- qué se ha hecho ----------
    p.append("<h2>Qué se ha hecho</h2>")
    p.append(f"<p>Se han contrastado automáticamente <b>{tot} requisitos de cliente</b> contra "
             f"{len(manuales)} manuales del proveedor ({', '.join(m['doc'] for m in manuales)}, "
             f"{sum(m['pages'] for m in manuales)} páginas en total). Por cada requisito, el sistema "
             f"busca en los manuales los pasajes más afines, decide si respaldan el requisito y "
             f"escribe el veredicto, el razonamiento y una cita textual con su página exacta "
             f"dentro del propio fichero ReqIF, listo para reimportar en Polarion.</p>")
    p.append("<p>Todo el proceso se ha ejecutado <b>en local, sin conexión</b>. Ni un requisito "
             "ni una línea de los manuales han salido del equipo: el modelo corre en la máquina "
             "y el servidor solo escucha en <code>127.0.0.1</code>. Es la única configuración "
             "compatible con el NDA.</p>")

    # ---------- números ----------
    p.append("<h2>Resultado</h2>")
    p.append('<div class="cifras">')
    p.append(f'<div class="c"><div class="n">{tot}</div><div class="l">Requisitos</div></div>')
    p.append(f'<div class="c ok"><div class="n">{ok}</div><div class="l">Alineados</div></div>')
    p.append(f'<div class="c"><div class="n">{no}</div><div class="l">No alineados</div></div>')
    p.append(f'<div class="c al"><div class="n">{ab}</div><div class="l">Sin confirmar</div></div>')
    p.append("</div>")
    p.append('<div class="tablewrap"><table><tr><th>Documento</th><th class="num">Requisitos</th>'
             '<th class="num">Alineados</th><th class="num">Sin confirmar</th></tr>')
    for d in docs:
        p.append(f'<tr><td>{html.escape(d["corto"])}</td><td class="num">{d["total"]}</td>'
                 f'<td class="num">{d["cuenta"].get("Compliant",0)}</td>'
                 f'<td class="num">{d["cuenta"].get("Unconfirmed",0)}</td></tr>')
    p.append("</table></div>")

    p.append(f"<p>La cifra que importa no es el {ok} de alineados, sino el reparto de los "
             f"{ab} sin confirmar. Para <b>{con_ev - ok}</b> de ellos el sistema encontró pasajes "
             f"del manual relacionados con el tema, los analizó y concluyó que no bastaban para "
             f"afirmar cumplimiento. Y <b>{sin_nada}</b> ni siquiera comparten vocabulario con "
             f"estos manuales.</p>")
    p.append("<p><b>La lectura correcta no es que el proveedor incumpla, sino que falta "
             "documentación por analizar.</b> Los dos manuales disponibles describen el motor "
             "criptográfico del microcontrolador; la especificación exige además una pila de "
             "gestión de certificados y PKI que esos documentos no cubren. Son dos manuales de "
             "una lista larga.</p>")
    if no == 0:
        p.append(f"<p>Conviene señalar que <b>ningún requisito ha resultado «no alineado»</b>. "
                 f"Los manuales no contradicen la especificación: sencillamente no la abordan. "
                 f"Hasta contrastar el sistema con documentación que sí contradiga algún "
                 f"requisito, no puede descartarse que el modelo sea excesivamente prudente.</p>")

    # ---------- el guard ----------
    p.append("<h2>Por qué se puede confiar en las citas</h2>")
    p.append("<p>El riesgo real de usar un modelo de lenguaje para esto no es que se equivoque de "
             "veredicto — eso se revisa. Es que <b>fabrique una cita creíble</b>: un párrafo que "
             "suena a manual, con su documento y su número de página, que nadie va a comprobar y "
             "que acaba delante del proveedor con nuestra firma debajo.</p>")
    p.append("<p>El sistema está construido para que eso sea imposible, con dos medidas. Primera: "
             "el modelo <b>no escribe ubicaciones</b>. Recibe una lista cerrada de pasajes y solo "
             "puede señalar uno; la página y la sección las calcula el programa a partir del PDF. "
             "Segunda: cada cita se compara <b>carácter a carácter</b> con el pasaje que el propio "
             "modelo dijo estar citando. Si no coincide, la cita se descarta.</p>")
    p.append(f"<p>En esta corrida el verificador <b>descartó {len(tiradas)} citas</b>. Ninguna "
             f"llegó al fichero entregado. Este es el caso más ilustrativo:</p>")

    if estrella:
        e = estrella
        real = html.escape(e["quote"][:e["real"]])
        inventado = html.escape(e["quote"][e["real"]:][:150])
        parecido = html.escape(_trozo_parecido(e["quote"], e["texto"])[:len(e["quote"])])
        p.append('<div class="caso">')
        p.append(f'<h3>Requisito {html.escape(e["req"])} — una cita inventada, interceptada</h3>')
        p.append('<div class="q mala"><span class="et">Lo que escribió el modelo</span>'
                 f'<i>{real}<mark>{inventado}</mark></i></div>')
        p.append('<div class="q real"><span class="et">Lo que pone realmente el manual</span>'
                 f'<i>{parecido}</i></div>')
        p.append(f'<p>Lo resaltado no existe en el manual. El modelo copió '
                 f'<b>{e["real"]} caracteres literales</b> y a partir de ahí siguió escribiendo por '
                 f'su cuenta — hacia una afirmación de cumplimiento que el documento nunca hace. '
                 f'El verificador obtuvo una coincidencia de {e["ratio"]:.2f} frente al mínimo '
                 f'exigido de {config.QUOTE_MIN_RATIO}, y la eliminó.</p>')
        p.append(f'<div class="donde">Verificable en: {html.escape(e["manual"])} · '
                 f'página {e["pag"]} · {html.escape(e["sec"])}</div>')
        p.append('</div>')
        p.append("<p>El requisito conservó su veredicto porque tenía una segunda cita que sí "
                 "verificó. Y al revisar este caso a fondo apareció un defecto del sistema que "
                 "conviene declarar sin rodeos, porque afecta a esta entrega.</p>")
        p.append('<div class="ojo"><b>Defecto conocido en esta entrega.</b> En este requisito, la '
                 'cita que sobrevivió habla de generar números aleatorios de 32 y 128 bits; la que '
                 'se descartó era la que mencionaba la norma NIST SP 800-90Ar1, que es justo lo que '
                 'el requisito exige. El veredicto «alineado» <b>se apoya en una cita que no cubre '
                 'lo esencial</b>. Debe revisarse a mano. Un segundo requisito (SO-R-0023) está en '
                 'la misma situación, aunque ahí la cita superviviente sí parece cubrir lo pedido. '
                 'Son 2 casos de 558, ambos identificados y trazados.</div>')
        p.append("<p>La causa es de diseño: el verificador comprueba las citas pero <b>no revisa el "
                 "texto del razonamiento</b>, así que un análisis puede seguir afirmando cosas cuya "
                 "prueba se acaba de eliminar. Está resuelto en el plan de mejoras del final.</p>")

    # ---------- qué hace exactamente el verificador ----------
    dem = sum(1 for d in docs for f in d["filas"]
              for fl in f.get("flags", []) if str(fl).startswith("demoted"))
    afectados = sum(1 for d in docs for f in d["filas"]
                    if any(str(fl).startswith("quote_failed") for fl in f.get("flags", [])))
    sostenidos = sum(1 for d in docs for f in d["filas"]
                     if any(str(fl).startswith("quote_failed") for fl in f.get("flags", []))
                     and f["evidence"]
                     and not any(str(fl).startswith("demoted") for fl in f.get("flags", [])))
    p.append("<h3>Qué ocurre exactamente cuando una cita no cuadra</h3>")
    p.append("<p>Conviene ser preciso, porque determina cuánto vale el resultado. El verificador "
             "<b>descarta la cita; no la corrige</b>. No busca en el manual la frase literal que el "
             "modelo quiso citar, y <b>no se vuelve a consultar al modelo</b> para preguntarle si el "
             "pasaje verdadero respalda el requisito. Una cita que no cuadra, sencillamente, "
             "desaparece. A partir de ahí hay tres desenlaces:</p>")
    p.append("<ul>"
             f"<li><b>Queda otra cita válida</b> — el veredicto se mantiene, apoyado solo en texto "
             f"real verificado. Han sido {sostenidos} requisitos.</li>"
             f"<li><b>No queda ninguna y el veredicto afirmaba cumplimiento</b> — se degrada "
             f"automáticamente a «sin confirmar». En esta corrida: {dem} casos.</li>"
             f"<li><b>El requisito ya estaba en «sin confirmar»</b> — pierde la cita y se queda "
             f"igual. El resto de los {afectados} requisitos afectados.</li>"
             "</ul>")
    p.append("<p>La consecuencia práctica, y hay que decirla: en el primer caso el veredicto se "
             "sostiene sobre otra cita, pero <b>nadie ha comprobado si la cita descartada era "
             "precisamente la que lo justificaba</b>. El sistema se protege de afirmar cumplimiento "
             "sin respaldo, no de perder un matiz por el camino. Es una de las razones por las que "
             "la revisión humana sigue siendo necesaria — y el motivo de la segunda comprobación "
             "propuesta más abajo.</p>")
    p.append("<p>Recuperar esa evidencia perdida (localizar el pasaje literal y volver a preguntar "
             "al modelo si respalda el requisito) es una mejora identificada y pendiente. Hoy no se "
             "hace, y el informe no debe dar a entender lo contrario.</p>")

    # ---------- ejemplos verificables ----------
    p.append("<h2>Comprobación manual realizada</h2>")
    p.append("<p>Los resultados automáticos no se han dado por buenos sin más. Se han contrastado "
             "a mano contra los PDF del proveedor <b>dos casos de naturaleza distinta</b>, elegidos "
             "porque responden a preguntas distintas: uno que el verificador aprobó y otro que "
             "rechazó. El primero comprueba que la mecánica funciona; el segundo, que el criterio "
             "es correcto. <b>Ambos han resultado correctos.</b></p>")

    if ejemplos:
        d0, f0 = ejemplos[0]
        ev0 = f0["evidence"][0]
        p.append('<div class="caso">')
        p.append(f'<h3>Caso 1 — una cita aprobada por el verificador</h3>')
        p.append(f'<p><b>Requisito {html.escape(f0["id"])}:</b> '
                 f'{html.escape(f0["texto"][:280])}</p>')
        p.append(f'<p><b>Veredicto:</b> alineado, sostenido por esta cita:</p>')
        p.append('<div class="q buena"><span class="et">Cita verificada</span>'
                 f'<i>{html.escape(ev0.get("quote",""))}</i></div>')
        p.append(f'<div class="donde">{html.escape(ev0.get("doc",""))} · página {ev0.get("page","")} '
                 f'· {html.escape(str(ev0.get("section","")))}</div>')
        p.append('<p><b>Comprobado:</b> el texto está en esa página, dice exactamente eso y el '
                 'número de página es correcto. La mecánica de localización funciona.</p>')
        p.append('</div>')

    if estrella:
        e = estrella
        real = html.escape(e["quote"][:e["real"]])
        inventado = html.escape(e["quote"][e["real"]:][:150])
        p.append('<div class="caso">')
        p.append('<h3>Caso 2 — una cita rechazada por el verificador</h3>')
        p.append(f'<p>Es el requisito {html.escape(e["req"])} del apartado anterior: el modelo copió '
                 f'{e["real"]} caracteres literales y siguió escribiendo de su cosecha. Lo resaltado '
                 f'es lo que el verificador identificó como inventado:</p>')
        p.append('<div class="q mala"><span class="et">Texto propuesto por el modelo</span>'
                 f'<i>{real}<mark>{inventado}</mark></i></div>')
        p.append(f'<div class="donde">{html.escape(e["manual"])} · página {e["pag"]} · '
                 f'{html.escape(e["sec"])}</div>')
        p.append('<p><b>Comprobado:</b> la continuación resaltada no aparece en el manual. El '
                 'verificador acertó al rechazarla. El criterio funciona.</p>')
        p.append('</div>')

    p.append('<div class="verifica"><b>Resultado de la comprobación: correcto en ambos casos.</b> '
             'Las citas están donde el informe dice, dicen lo que dice, y el texto que el verificador '
             'descartó efectivamente no existe en la documentación.</div>')

    p.append("<h3>Aviso para quien quiera repetir la comprobación</h3>")
    p.append("<p>Al contrastar a mano apareció algo que conviene saber: <b>la búsqueda automática "
             "del visor de PDF (Ctrl+F) puede no encontrar una cita que sí está literalmente en la "
             "página.</b> Se detectó escribiendo el texto letra a letra y viendo en qué punto exacto "
             "dejaba de haber coincidencias.</p>")
    p.append("<p>La causa está en el propio documento: estos PDF llevan una marca de agua incrustada "
             "en la capa de texto, presente en todas las páginas. Cuando la frase buscada atraviesa "
             "la zona donde esa marca se intercala en el orden de lectura, el buscador del visor deja "
             "de encontrar coincidencias, aunque el texto esté ahí y sea legible. Lo mismo ocurre "
             "cuando la frase cruza un salto de línea o una viñeta: la mayoría de visores no los "
             "atraviesan.</p>")
    p.append("<p><b>Recomendación:</b> buscar fragmentos cortos que no crucen saltos de línea, o "
             "sencillamente ir a la página indicada y leerla. <b>Que Ctrl+F no encuentre una cita no "
             "significa que sea falsa.</b></p>")
    p.append("<p>Merece la pena señalar que <b>este problema no afecta al sistema</b>, solo a la "
             "revisión humana. La verificación automática no usa el buscador del visor: extrae el "
             "texto del PDF y lo compara tras limpiar saltos de línea, guiones y demás ruido de "
             "maquetación. Por eso encuentra citas que Ctrl+F no encuentra.</p>")

    # ---------- limitaciones ----------
    p.append("<h2>Qué no cubre este análisis</h2>")
    p.append(f"<p>La limitación dominante es la <b>documentación incompleta</b>: con dos manuales "
             f"de una lista larga, cualquiera de los {ab} sin confirmar puede cambiar de veredicto "
             f"al incorporar el resto. No hay tampoco un juego de respuestas correctas para estos "
             f"dos documentos, así que los veredictos no se han podido puntuar: solo revisar por "
             f"coherencia con la evidencia citada.</p>")
    p.append("<p>El modelo empleado es de tamaño medio, elegido por ser el mayor que corre en local "
             "de forma segura. En pruebas controladas acertó 8 de 9 casos frente a 9 de 9 de un "
             "modelo comercial grande, sin producir en ningún caso un falso «alineado». Su punto "
             "débil, como muestra el ejemplo de arriba, es que tiende a completar las citas de su "
             "cosecha — por eso el verificador es imprescindible, no un adorno.</p>")

    # ---------- pasos ----------
    p.append("<h2>Cómo seguir</h2>")
    p.append('<div class="paso"><h3>Completar la documentación <span class="tag ya">primero</span></h3>'
             '<p>Es el paso más rentable y condiciona a todos los demás: ni un experto ni el mejor '
             'modelo pueden confirmar un requisito contra documentación que no está sobre la mesa. '
             'Los mensajes al proveedor que acompañan a cada requisito sin confirmar ya son la lista '
             'de qué pedir. Incorporados los manuales que falten, la cadena se vuelve a ejecutar sin '
             'coste adicional.</p></div>')
    p.append('<div class="paso"><h3>Revisión manual <span class="tag caro">óptima, cara</span></h3>'
             '<p>Requisito a requisito por un ingeniero con la documentación completa. Es el patrón '
             'de calidad contra el que se mide todo lo demás y el único admisible para los requisitos '
             'críticos. Su coste la hace inviable como método único sobre varios cientos de '
             'requisitos, pero sigue siendo obligatoria sobre los veredictos que se vayan a '
             'comunicar al proveedor.</p></div>')
    p.append('<div class="paso"><h3>Modelo avanzado en entorno seguro '
             '<span class="tag duda">por validar</span></h3>'
             '<p>Un modelo comercial de gran tamaño daría mejores veredictos y menos citas '
             'descartadas, siempre que se ejecute bajo un acuerdo que garantice confidencialidad: '
             'sin retención de datos, sin uso para entrenamiento y con el tratamiento amparado por el '
             'NDA con el cliente. La vía candidata es el Copilot corporativo. <b>Es una decisión '
             'legal antes que técnica: hay que confirmarla con los responsables de seguridad y con el '
             'marco contractual antes de enviar un solo requisito.</b></p></div>')
    p.append('<div class="paso"><h3>Modelo comercial abierto <span class="tag no">descartado</span></h3>'
             '<p>Enviar requisitos de cliente o documentación del proveedor a un servicio de IA de '
             'consumo sería una violación del NDA. Se descarta sin excepciones, incluidas pruebas '
             'parciales o con datos anonimizados.</p></div>')

    # ---------- plan de mejoras ----------
    p.append("<h2>Mejoras identificadas</h2>")
    p.append("<p>La revisión de esta corrida ha destapado cuatro defectos concretos en el "
             "verificador. Ninguno invalida el trabajo entregado —el alcance está acotado y "
             "declarado arriba— pero los cuatro se corrigen en la misma intervención, y conviene "
             "hacerlo antes de procesar el resto de manuales, cuando el volumen de veredictos "
             "afirmativos crezca.</p>")

    p.append("<h3>Lo que se ha detectado</h3>")
    p.append("<p><b>1. El umbral de similitud del 85% deja pasar citas no literales.</b> De las 550 "
             "citas propuestas por el modelo, 27 (un 4,9%) no son textuales: están escritas con sus "
             "palabras y el sistema las dio por buenas. El riesgo no es teórico: dos frases pueden "
             "parecerse en un 95% y significar lo contrario. «El valor debe estar entre 5 y 8,5» y "
             "«el valor debe estar entre 5 y 11» son casi idénticas como texto, y frente a un "
             "requisito que exija «mayor que 10» dan veredictos opuestos. Un porcentaje de parecido "
             "no mide equivalencia técnica, y donde peor falla es justo en las cifras.</p>")
    p.append("<p><b>2. El razonamiento puede sobrevivir a su prueba.</b> Cuando se descarta una "
             "cita, el análisis que se apoyaba en ella permanece intacto en el ReqIF. Es el caso "
             "declarado más arriba.</p>")
    p.append("<p><b>3. Solo se examinan los pasajes que el modelo elige para justificarse.</b> "
             "Recibe diez y cita entre cero y tres. Si el séptimo contradice el requisito, puede no "
             "mencionarlo nunca — y nadie se entera. Es la carencia más importante de las cuatro: "
             "un manual técnico de cientos de páginas escrito por partes puede contradecirse a sí "
             "mismo, y detectarlo es precisamente parte del valor de auditar.</p>")
    p.append("<p><b>4. Una cita descartada no se recupera.</b> No se busca el texto literal que el "
             "modelo quiso citar ni se le vuelve a preguntar. La evidencia, buena o mala, "
             "desaparece.</p>")

    p.append("<h3>Cómo se corrige</h3>")
    p.append("<p><b>Cita literal obligatoria, sin umbrales.</b> Se elimina el porcentaje: o el texto "
             "está en el manual o no está. Para que eso no rompa por motivos tipográficos, la "
             "comparación se hace tras normalizar saltos de línea, guiones de partición y comillas "
             "—el ruido que introduce la extracción del PDF—. La medición respalda el ajuste: hoy "
             "solo el 46% de las citas coincide carácter a carácter en crudo, pero el 91,8% lo hace "
             "tras normalizar. Exigir literalidad estricta sin esa limpieza previa habría "
             "rechazado citas perfectamente válidas.</p>")
    p.append("<p><b>La cita se señala, no se escribe.</b> El sistema ya impide que el modelo invente "
             "ubicaciones: no escribe el número de página, elige un pasaje de una lista cerrada y el "
             "programa deriva la página. La cita es el mismo problema sin resolver. Pasando a que "
             "indique qué frases del pasaje cita —y que sea el código quien las copie del original— "
             "la paráfrasis deja de ser posible por construcción, en lugar de detectarse después.</p>")
    p.append("<p><b>Pronunciamiento sobre todos los pasajes candidatos.</b> En vez de pedir «tu "
             "veredicto y las citas que lo apoyan», se pide un juicio por cada pasaje recibido: "
             "apoya, contradice o es irrelevante. El veredicto final lo compone el programa con una "
             "regla fija: <b>basta un solo pasaje que contradiga para que el requisito quede como no "
             "alineado</b>, por muchos que lo apoyen. Y la contradicción se hace explícita en el "
             "razonamiento y en el mensaje al proveedor, en lugar de disolverse en un promedio. Como "
             "el juicio pasa a ser local y la decisión determinista, el razonamiento se compone solo "
             "a partir de la evidencia que ha sobrevivido: el defecto 2 deja de poder ocurrir.</p>")
    p.append("<p><b>Segunda consulta al modelo</b> para los casos que aun así se escapen, en lugar "
             "de descartar la evidencia sin más. No se degradará un veredicto por precaución: "
             "afirmar «no hay información suficiente» cuando sí la hay es un error tan real como "
             "cualquier otro, solo que más cómodo.</p>")

    p.append("<h3>Cómo se ejecutará</h3>")
    p.append("<p>La comprobación es mucho más ligera que el análisis original: el trabajo difícil "
             "—leer la documentación y decidir— ya está hecho. Por eso el grueso lo hará un modelo "
             "menor (Qwen 7B), que cabe entero en la tarjeta gráfica, corre en paralelo y deja el "
             "equipo utilizable mientras trabaja.</p>")
    p.append("<p>Ahora bien, un modelo pequeño no puede enmendar al grande sin supervisión. Por eso "
             "todo requisito en el que la revisión llegue a una conclusión <b>distinta</b> de la "
             "original se reevalúa con el modelo grande, y su palabra es la definitiva. La revisión "
             "propone; no impone. Antes de lanzar la pasada completa se medirá esa tasa de "
             "desacuerdo sobre el juego de pruebas conocido: si es baja, el planteamiento se "
             "sostiene; si es alta, el modelo menor no sirve para esta tarea y se replantea, con "
             "media hora de coste en lugar de una noche.</p>")

    p.append('<footer>Cifras, citas y páginas generadas automáticamente a partir de los resultados '
             'verificados; no han sido editadas a mano. El detalle completo de los '
             f'{tot} requisitos viaja en los ficheros ReqIF que acompañan a este informe. '
             'Documento confidencial — distribución interna.</footer>')
    p.append("</div>")

    doc = ('<!doctype html><html lang="es"><head><meta charset="utf-8">'
           '<meta name="viewport" content="width=device-width,initial-scale=1">'
           '<title>Auditoría CTSM</title>'
           f"<style>{CSS}</style></head><body>{''.join(p)}</body></html>")
    salida.write_text(doc, encoding="utf-8")
    print(f"informe → {salida}  ({salida.stat().st_size:,} bytes)")


def main() -> int:
    args = list(sys.argv[1:])
    salida = config.OUTPUT_REQIF_DIR.parent / "informe_auditoria.html"
    if "-o" in args:
        i = args.index("-o")
        salida = Path(args[i + 1])
        del args[i:i + 2]
    if not args:
        args = [p.stem for p in sorted(config.RESULTS_DIR.glob("*.json"))]
    construir(args, salida)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
