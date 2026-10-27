// CTSM · interfaz. Pide instantáneas al servidor y las pinta; no calcula veredictos.
const T = {
  es: {
    tagline: "Requisitos del cliente contra la documentación del proveedor",
    h_inicio: "Audita una especificación contra la documentación del proveedor",
    lead: "Devuelve el mismo ReqIF con el veredicto de cada requisito y la cita exacta, anclada a su página. El modelo nunca escribe una ubicación: la pone el código.",
    in_reqif: "Especificación del cliente", in_reqif_hint: ".reqif exportado de Polarion",
    in_pdf: "Documentación del proveedor", in_pdf_hint: "uno o varios PDF",
    go: "Auditar", t_req: "requisitos evaluados", t_calls: "llamadas al modelo",
    t_left: "salieron de la máquina", t_time: "transcurrido", pick: "Elige un requisito para ver su evidencia.",
    footer: "Local · el pipeline corre en esta máquina · la interfaz solo enseña lo que el pipeline escribió",
    live: "EN VIVO", demo: "DEMO", local: "sin red", cloud: "nube",
    steps: [["Limpieza", "s0 · s1 · s2"], ["Contexto", "s3 · BM25 top-10"], ["Guardarraíl de entrada", "esquema · enum · chunk_id"],
            ["Proceso", "s4 · una llamada por requisito"], ["Guardarraíl de salida", "s6 · s7 · roundtrip"]],
    code: "código", model: "modelo",
    demo_note: (d) => `Reproducción acelerada ×${d.speed} de una ejecución real: ${d.engine}, ${d.recorded}, ${d.machine}. Veredictos y citas, los grabados.`,
    demo_input: (d) => [`${d.reqif} · ${d.total} requisitos`, d.supplier_docs],
    evidence: "Evidencia verificada por el código", why: "Análisis del modelo", none: "Sin evidencia verificada: el código degradó el veredicto al valor abierto.",
    match: "coincidencia", page: "pág.", noimg: "La página no se puede mostrar: el PDF del proveedor no está en esta máquina.",
    expected: "Ground truth", hit: "acierto", miss: "fallo", roles: { yes: "cumple", no: "no cumple", open: "sin confirmar" }, unverified: "sin verificar aún",
    flag: "⚑ marcado para revisión", flags: "Marcas del verificador (s6)", download: "Descargar ReqIF", locks: "Comprobar los tres candados", again: "Otra auditoría",
    locks_ok: "✓ roundtrip_diff: el fichero de entrada sigue intacto fuera de los tres campos", locks_bad: "✗ roundtrip_diff ha encontrado cambios",
    score: (h, n) => `${h}/${n} contra ground truth`, nofalse: "0 falsos «cumple»", falses: (n) => `${n} falsos «cumple»`,
  },
  en: {
    tagline: "Customer requirements against supplier documentation",
    h_inicio: "Audit a specification against the supplier's documentation",
    lead: "Returns the same ReqIF with a verdict for every requirement and the exact quote, anchored to its page. The model never writes a location: code does.",
    in_reqif: "Customer specification", in_reqif_hint: ".reqif exported from Polarion",
    in_pdf: "Supplier documentation", in_pdf_hint: "one or more PDFs",
    go: "Audit", t_req: "requirements evaluated", t_calls: "model calls",
    t_left: "left the machine", t_time: "elapsed", pick: "Pick a requirement to see its evidence.",
    footer: "Local · the pipeline runs on this machine · the interface only shows what the pipeline wrote",
    live: "LIVE", demo: "DEMO", local: "offline", cloud: "cloud",
    steps: [["Cleaning", "s0 · s1 · s2"], ["Context", "s3 · BM25 top-10"], ["Input guardrail", "schema · enum · chunk_id"],
            ["Process", "s4 · one call per requirement"], ["Output guardrail", "s6 · s7 · roundtrip"]],
    code: "code", model: "model",
    demo_note: (d) => `Replay at ×${d.speed} of a real run: ${d.engine}, ${d.recorded}, ${d.machine}. Verdicts and quotes as recorded.`,
    demo_input: (d) => [`${d.reqif} · ${d.total} requirements`, d.supplier_docs],
    evidence: "Evidence verified by code", why: "Model analysis", none: "No verified evidence: code degraded the verdict to the open value.",
    match: "match", page: "p.", noimg: "The page cannot be shown: the supplier PDF is not on this machine.",
    expected: "Ground truth", hit: "hit", miss: "miss", roles: { yes: "compliant", no: "not compliant", open: "unconfirmed" }, unverified: "not verified yet",
    flag: "⚑ flagged for review", flags: "Verifier flags (s6)", download: "Download ReqIF", locks: "Check the three locks", again: "Another audit",
    locks_ok: "✓ roundtrip_diff: the input file is intact outside the three fields", locks_bad: "✗ roundtrip_diff found changes",
    score: (h, n) => `${h}/${n} against ground truth`, nofalse: "0 false “compliant”", falses: (n) => `${n} false “compliant”`,
  },
};
let lang = "es";
try { lang = localStorage.getItem("ctsm-lang") || "es"; } catch (e) {}
const t = (k, ...a) => { const v = T[lang][k]; return typeof v === "function" ? v(...a) : v; };
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// el enum lo declara el fichero del cliente; aquí solo se colorea por su papel
const role = (s) => /not|non|reject|no\b/i.test(s) ? "no" : /unconf|open|tbd|pending|review/i.test(s) ? "open" : "yes";

let INFO = null, JOB = null, SEL = null, timer = null;
const files = { reqif: null, pdfs: [] };

function applyLang() {
  document.documentElement.lang = lang;
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    const v = T[lang][el.dataset.i18n];
    if (typeof v === "string") el.textContent = v;
  });
  document.querySelectorAll(".lang button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.lang === lang)));
  if (INFO) header();
  if (INFO && INFO.mode === "demo") demoInputs(); else refreshInputs();
  if (JOB) render(JOB);
}
document.querySelectorAll(".lang button").forEach((b) => b.addEventListener("click", () => {
  lang = b.dataset.lang; try { localStorage.setItem("ctsm-lang", lang); } catch (e) {}
  applyLang();
}));

function header() {
  const m = $("#modo");
  m.textContent = t(INFO.mode === "demo" ? "demo" : "live");
  m.className = "badge" + (INFO.mode === "demo" ? " demo" : "");
  const d = INFO.demos[0];
  const eng = INFO.mode === "demo" && d ? d.engine : INFO.engine;
  $("#motor").textContent = `${eng} · ${INFO.mode === "demo" || INFO.local ? t("local") : t("cloud")}`;
}

function demoInputs() {
  const d = INFO.demos[0];
  if (!d) return;
  const [a, b] = t("demo_input", { ...d, total: d.total || 9 });
  $("#reqif-name").textContent = a; $("#pdf-name").textContent = b;
  $("#drop-reqif").classList.add("filled"); $("#drop-pdf").classList.add("filled");
  $("#go").disabled = false;
  const n = $("#nota-demo"); n.hidden = false; n.textContent = t("demo_note", { ...d, speed: INFO.speed });
}

// ── entrada ──
function wireDrop(id, input, onFiles) {
  const el = $(id);
  ["dragenter", "dragover"].forEach((e) => el.addEventListener(e, (ev) => { ev.preventDefault(); el.classList.add("over"); }));
  ["dragleave", "drop"].forEach((e) => el.addEventListener(e, () => el.classList.remove("over")));
  el.addEventListener("drop", (ev) => { ev.preventDefault(); onFiles([...ev.dataTransfer.files]); });
  $(input).addEventListener("change", (ev) => onFiles([...ev.target.files]));
}
function refreshInputs() {
  if (files.reqif) { $("#reqif-name").textContent = files.reqif.name; $("#drop-reqif").classList.add("filled"); }
  if (files.pdfs.length) { $("#pdf-name").textContent = files.pdfs.map((f) => f.name).join(" · "); $("#drop-pdf").classList.add("filled"); }
  $("#go").disabled = !(files.reqif && files.pdfs.length);
}
wireDrop("#drop-reqif", "#f-reqif", (fs) => { if (INFO?.mode === "demo") return; files.reqif = fs.find((f) => /\.reqif$/i.test(f.name)) || null; refreshInputs(); });
wireDrop("#drop-pdf", "#f-pdf", (fs) => { if (INFO?.mode === "demo") return; files.pdfs = fs.filter((f) => /\.pdf$/i.test(f.name)); refreshInputs(); });

$("#go").addEventListener("click", async () => {
  $("#go").disabled = true;
  let r;
  if (INFO.mode === "demo") {
    r = await fetch(`/api/demo/${encodeURIComponent(INFO.demos[0].name)}`, { method: "POST" });
  } else {
    const fd = new FormData();
    fd.append("reqif", files.reqif);
    files.pdfs.forEach((f) => fd.append("pdfs", f));
    r = await fetch("/api/jobs", { method: "POST", body: fd });
  }
  if (!r.ok) { alert((await r.json()).detail || r.statusText); $("#go").disabled = false; return; }
  JOB = await r.json(); SEL = null;
  $("#inicio").hidden = true; $("#proceso").hidden = false;
  render(JOB); poll();
});

function poll() {
  clearTimeout(timer);
  timer = setTimeout(async () => {
    const r = await fetch(`/api/jobs/${JOB.id}`);
    if (r.ok) { JOB = await r.json(); render(JOB); }
    if (JOB.status === "running") poll();
  }, 350);
}

// ── proceso ──
const GROUPS = [1, 2, 3, 4, 5];
function render(j) {
  const steps = T[lang].steps;
  $("#steps").innerHTML = GROUPS.map((g) => {
    const mine = j.steps.filter((s) => s.design === g);
    const st = mine.some((s) => s.state === "error") ? "error" : mine.every((s) => s.state === "done") ? "done"
      : mine.some((s) => s.state !== "pending") ? "running" : "pending";
    const model = g === 4;
    const bar = model ? `<div class="bar"><i style="width:${j.s4_total ? (100 * j.s4_done / j.s4_total) : 0}%"></i></div>` : "";
    return `<div class="step ${st}${model ? " model" : ""}"><span class="num">${g}</span><b>${steps[g - 1][0]}</b>
      <span class="kind ${model ? "model" : "code"}">${model ? "▲ " + t("model") : "■ " + t("code")}</span>
      <div class="sub">${model && j.s4_total ? `${j.s4_done}/${j.s4_total}` : steps[g - 1][1]}</div>${bar}</div>`;
  }).join("");
  $("#t-req").textContent = `${j.s4_done}/${j.s4_total || "–"}`;
  $("#t-calls").textContent = j.custody.calls;
  $("#t-left").textContent = j.custody.left_machine;
  $("#t-left").parentElement.classList.toggle("ok", j.custody.left_machine === 0);
  $("#t-time").textContent = `${Math.round(j.elapsed)} s`;
  const av = $("#aviso-demo");
  if (j.mode === "demo" && INFO.demos[0]) { av.hidden = false; av.textContent = t("demo_note", { ...INFO.demos[0], speed: INFO.speed }); }
  if (j.status === "error") { av.hidden = false; av.textContent = "✗ " + j.error; }
  if (j.rows.length) { $("#resultado").hidden = false; results(j); }
}

// ── resultado ──
function results(j) {
  const done = j.status === "done";
  const c = { yes: 0, no: 0, open: 0 }, names = {};
  j.rows.forEach((r) => { c[role(r.status)]++; names[role(r.status)] = r.status; });
  let html = ["yes", "no", "open"].filter((k) => c[k]).map((k) => `<span class="chip ${k}">${c[k]} · ${esc(names[k])}</span>`).join("");
  const gt = j.rows.filter((r) => r.expected);
  if (done && gt.length) {
    const hits = gt.filter((r) => role(r.status) === r.expected).length;
    const falses = gt.filter((r) => role(r.status) === "yes" && r.expected !== "yes").length;
    html += `<span class="chip plain">${t("score", hits, gt.length)}</span><span class="chip ${falses ? "no" : "yes"}">${falses ? t("falses", falses) : t("nofalse")}</span>`;
  }
  $("#summary").innerHTML = html;
  $("#rows").innerHTML = j.rows.map((r) => `
    <div class="row${r.id === SEL ? " sel" : ""}${r.unverified && !done ? " unverified" : ""}" role="listitem" tabindex="0" data-id="${esc(r.id)}">
      <span class="id">${esc(r.id)}</span><span class="chip ${role(r.status)}">${esc(r.status)}</span>
      <span class="tx">${esc(r.text)}</span>
      ${r.flags.length ? `<span class="flag">${t("flag")}</span>` : r.unverified && !done ? `<span class="flag">${t("unverified")}</span>` : ""}
    </div>`).join("");
  document.querySelectorAll(".row").forEach((el) => {
    const open = () => { SEL = el.dataset.id; results(JOB); detail(JOB.rows.find((r) => r.id === SEL)); };
    el.addEventListener("click", open);
    el.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
  });
  if (done) actions(j);
}

function detail(r) {
  if (!r) return;
  const ev = r.evidence.map((e) => {
    const src = `/api/jobs/${JOB.id}/page?doc=${encodeURIComponent(e.doc)}&page=${e.page}&q=${encodeURIComponent(e.quote || "")}`;
    return `<div class="ev"><div class="cite">[${esc(e.doc)} ${t("page")}${e.page} ${esc(e.section || "")}]</div>
      <q>${esc(e.quote)}</q><div class="meta">${t("match")} ${Number(e.match_ratio ?? 0).toFixed(2)} · chunk ${esc(e.chunk_id)}</div>
      <img alt="${esc(e.doc)} ${t("page")}${e.page}" src="${src}" onerror="this.outerHTML='<div class=noimg>${t("noimg")}</div>'"></div>`;
  }).join("") || `<p class="muted">${t("none")}</p>`;
  // el razonamiento del modelo sin el bloque de citas, que ya se pinta verificado debajo
  const why = (r.rationale || "").split(/\n\s*(Evidence|Evidencia):/)[0].trim();
  const gt = r.expected ? `<div class="gt">${t("expected")}: ${t("roles")[r.expected]} ·<span class="${role(r.status) === r.expected ? "hit" : "miss"}">${role(r.status) === r.expected ? t("hit") : t("miss")}</span></div>` : "";
  $("#detail").innerHTML = `<h2>${esc(r.id)}</h2><p class="req">${esc(r.text)}</p>
    <span class="chip ${role(r.status)}">${esc(r.status)}</span> ${r.flags.length ? `<span class="chip open">${t("flag")}</span>` : ""} ${gt}
    ${r.flags.length ? `<h3>${t("flags")}</h3>${r.flags.map((f) => `<div class="gt">⚑ ${esc(f)}</div>`).join("")}` : ""}
    <h3>${t("evidence")}</h3>${ev}
    ${why ? `<h3>${t("why")}</h3><div class="why">${esc(why)}</div>` : ""}`;
}

function actions(j) {
  const a = $("#actions");
  if (a.dataset.job === j.id) return;
  a.dataset.job = j.id;
  a.innerHTML = (j.mode === "live" ? `<a class="primary" href="/api/jobs/${j.id}/reqif"><button class="primary">${t("download")}</button></a>
    <button class="ghost" id="locks">${t("locks")}</button><span class="locks" id="locks-out"></span>` : "") +
    `<button class="ghost" id="again">${t("again")}</button>`;
  $("#again").addEventListener("click", () => location.reload());
  $("#locks")?.addEventListener("click", async () => {
    const r = await (await fetch(`/api/jobs/${j.id}/roundtrip`)).json();
    $("#locks-out").textContent = r.ok ? t("locks_ok") : t("locks_bad");
  });
}

(async () => {
  INFO = await (await fetch("/api/info")).json();
  applyLang();
})();
