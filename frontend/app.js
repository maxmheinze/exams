"use strict";

/* ============================================================
   exams.maxheinze.eu — client logic
   All state lives in memory; nothing is persisted. The server is
   only contacted at generation time. JSON escaping is handled by
   JSON.parse / JSON.stringify, so the editor shows raw LaTeX.
   ============================================================ */

const DEFAULT_FIELDS = {
  exam_title: "Midterm Exam",
  subject: "Econometrics III / Applied Econometrics",
  course_no: "(Courses No. 4352 and 5913)",
  date: "May 21, 2026",
  rules_latex: String.raw`Please be aware of the following \textbf{rules} for this exam:

\begin{itemize}
  \item You have \textbf{100 Minutes} to answer the questions.
  \item You can receive up to \textbf{40 points}.
  \item There are 11 differently weighted questions in this exam. You should aim not to use more than 2 minutes per point in order to have 20 minutes to check your answers. The order of questions is randomized and they can be answered independently.
  \item Your exam is marked with an ID number on every page. \textbf{Please do neither write your name nor your student ID number anywhere on this exam}, so that we can guarantee fairness and anonymity while grading. Name and exam number are matched on a separate attendance sheet.
  \item You are only allowed to answer the questions in \textbf{English}.
  \item The following \textbf{aids} are allowed:
  \begin{itemize}
    \item A calculator.
    \item The cheat sheet that was created by your Cheat Sheet Group.
    \item Empty sheets for taking notes (which cannot be handed in).
    \item A bilingual dictionary (English and your native language).
    \item Coffee.
  \end{itemize}
\end{itemize}`,
};

const ASSET_OK = /^[A-Za-z0-9._-]{1,128}$/;
const ASSET_EXT = ["png", "jpg", "jpeg", "pdf", "txt", "dat", "csv", "tex"];

const state = {
  pool: [],                  // {qt, wid, points, text}
  assets: new Map(),         // name -> File
  fields: { ...DEFAULT_FIELDS },
  language: "en",
  options: { n: 1, extra: 0, demo: false, fixed: false,
             include: new Set(), bonus: new Set() },
};

const $ = (sel) => document.querySelector(sel);
const el = (tag, props = {}, ...kids) => {
  const n = Object.assign(document.createElement(tag), props);
  for (const k of kids) n.append(k.nodeType ? k : document.createTextNode(k));
  return n;
};
const pad2 = (x) => String(x).padStart(2, "0");

/* ---------- view switching ---------- */
function show(view) {
  for (const v of ["landing", "editor", "template", "options"])
    $("#view-" + v).classList.toggle("hidden", v !== view);
  const order = { editor: 1, template: 2, options: 3 };
  $("#stepper").classList.toggle("hidden", !(view in order));
  if (view in order) {
    const cur = order[view];
    document.querySelectorAll(".step").forEach((s) => {
      const n = Number(s.dataset.step);
      s.classList.toggle("active", n === cur);
      s.classList.toggle("done", n < cur);
    });
  }
  window.scrollTo(0, 0);
}

/* ---------- pool helpers ---------- */
function normalizePool(arr) {
  return arr.map((q) => ({
    qt: pad2(q.question_type),
    wid: pad2(q.within_type_id),
    points: Number.isFinite(+q.points) ? +q.points : 1,
    text: typeof q.question_text === "string" ? q.question_text : "",
  }));
}
function typesInPool() {
  return [...new Set(state.pool.map((q) => q.qt))].sort();
}
function nextType() {
  const used = new Set(state.pool.map((q) => q.qt));
  for (let i = 1; i < 100; i++) if (!used.has(pad2(i))) return pad2(i);
  return "99";
}
function nextWithin(qt) {
  const used = new Set(state.pool.filter((q) => q.qt === qt).map((q) => q.wid));
  for (let i = 1; i < 100; i++) if (!used.has(pad2(i))) return pad2(i);
  return "99";
}

/* ---------- editor rendering ---------- */
function renderEditor() {
  const host = $("#qtypes");
  host.innerHTML = "";
  const types = typesInPool();
  if (!types.length) {
    host.append(el("p", { className: "muted" },
      "No questions yet. Use “Add question type” to begin."));
  }
  for (const qt of types) {
    const variants = state.pool.filter((q) => q.qt === qt)
      .sort((a, b) => a.wid.localeCompare(b.wid));
    const body = el("div", { className: "qtype-body" });

    // Points are per type — all variants of a type share the same value.
    const typePts = el("input", { type: "number", className: "pts", min: "1",
      max: "99", step: "1", value: variants.length ? variants[0].points : 1 });
    typePts.addEventListener("input", () => {
      const val = parseInt(typePts.value || "0", 10);
      for (const q of state.pool) if (q.qt === qt) q.points = val;
    });
    body.append(el("div", { className: "type-points" },
      el("label", {}, "Points for this type"), typePts));

    for (const v of variants) {
      const ta = el("textarea", { className: "tex", value: v.text,
        placeholder: "LaTeX snippet — no \\documentclass or \\begin{document} needed" });
      ta.addEventListener("input", () => { v.text = ta.value; });

      const del = el("button", { className: "btn-danger", title: "Delete variant" }, "Delete");
      del.addEventListener("click", () => {
        state.pool = state.pool.filter((q) => q !== v);
        renderEditor();
      });

      body.append(el("div", { className: "variant" },
        el("div", { className: "vhead" },
          el("span", { className: "vid" }, `variant ${v.wid}`),
          el("span", { style: "flex:1" }), del),
        ta));
    }

    const addVar = el("button", { className: "btn-ghost" }, "+ Add variant");
    addVar.addEventListener("click", () => {
      const pts = variants.length ? variants[0].points : 1;
      state.pool.push({ qt, wid: nextWithin(qt), points: pts, text: "" });
      renderEditor();
    });
    const delType = el("button", { className: "btn-danger" }, "Delete type");
    delType.addEventListener("click", () => {
      state.pool = state.pool.filter((q) => q.qt !== qt);
      renderEditor();
    });
    body.append(el("div", { className: "row" }, addVar, delType));

    const det = el("details", { className: "qtype", open: true });
    det.append(
      el("summary", {},
        el("span", {}, `Question type ${qt}`,
          " ", el("span", { className: "muted" }, `· ${variants.length} variant(s)`)),
        el("span", { className: "chev" }, "›")),
      body);
    host.append(det);
  }
}

/* ---------- assets ---------- */
function renderAssets() {
  const ul = $("#assetlist");
  ul.innerHTML = "";
  for (const [name] of state.assets) {
    const rm = el("button", { className: "btn-danger" }, "Remove");
    rm.addEventListener("click", () => { state.assets.delete(name); renderAssets(); });
    ul.append(el("li", {}, el("span", {}, name), rm));
  }
}
function addAssets(fileList) {
  const bad = [];
  for (const f of fileList) {
    const ext = f.name.split(".").pop().toLowerCase();
    if (!ASSET_OK.test(f.name) || !ASSET_EXT.includes(ext)) { bad.push(f.name); continue; }
    state.assets.set(f.name, f);
  }
  renderAssets();
  if (bad.length) alert("Skipped files with unsupported names/types:\n" + bad.join("\n") +
    "\n\nAllowed: letters, digits, . _ - and extensions: " + ASSET_EXT.join(", "));
}

/* ---------- save JSON ---------- */
function exportPoolJSON() {
  const arr = [...state.pool]
    .sort((a, b) => a.qt.localeCompare(b.qt) || a.wid.localeCompare(b.wid))
    .map((q) => ({
      question_type: q.qt, within_type_id: q.wid,
      points: q.points, question_text: q.text,
    }));
  const blob = new Blob([JSON.stringify(arr, null, 2)], { type: "application/json" });
  triggerDownload(blob, "question_pool.json");
}
function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = el("a", { href: url, download: filename });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/* ---------- template page ---------- */
function loadTemplateFields() {
  $("#f_title").value    = state.fields.exam_title;
  $("#f_subject").value  = state.fields.subject;
  $("#f_course").value   = state.fields.course_no;
  $("#f_date").value     = state.fields.date;
  $("#f_rules").value    = state.fields.rules_latex;
  $("#f_language").value = state.language;
}
function saveTemplateFields() {
  state.fields = {
    exam_title: $("#f_title").value,
    subject: $("#f_subject").value,
    course_no: $("#f_course").value,
    date: $("#f_date").value,
    rules_latex: $("#f_rules").value,
  };
  state.language = $("#f_language").value;
}

/* ---------- options page ---------- */
function renderOptions() {
  const types = typesInPool();
  // default include = all types; keep prior bonus picks that still exist
  state.options.include = new Set(types);
  state.options.bonus = new Set([...state.options.bonus].filter((t) => types.includes(t)));

  const host = $("#qtable");
  host.innerHTML = "";
  host.append(el("div", { className: "qrow qhead" },
    el("span", {}, "Question type"), el("span", {}, "Include"), el("span", {}, "Bonus")));
  for (const qt of types) {
    const inc = el("input", { type: "checkbox", checked: true });
    const bon = el("input", { type: "checkbox" });
    inc.addEventListener("change", () => {
      inc.checked ? state.options.include.add(qt) : state.options.include.delete(qt);
    });
    bon.addEventListener("change", () => {
      if (bon.checked) {
        state.options.bonus.add(qt);
        inc.checked = true; inc.disabled = true; state.options.include.add(qt);
      } else {
        state.options.bonus.delete(qt);
        inc.disabled = false;
      }
    });
    host.append(el("div", { className: "qrow" },
      el("span", { className: "name" }, qt),
      el("label", { className: "checkline" }, inc),
      el("label", { className: "checkline" }, bon)));
  }
  $("#o_n").value = state.options.n;
  $("#o_extra").value = String(state.options.extra);
  $("#o_demo").checked = state.options.demo;
  $("#o_fixed").checked = state.options.fixed;
  syncDemo();
}
function syncDemo() {
  const demo = $("#o_demo").checked;
  $("#qtable").classList.toggle("disabled", demo);
  if (demo) {
    state.options.include = new Set(typesInPool());
    state.options.bonus = new Set();
    document.querySelectorAll("#qtable .qrow").forEach((row) => {
      const ins = row.querySelectorAll(".checkline input");
      if (ins[0]) { ins[0].checked = true; ins[0].disabled = false; }
      if (ins[1]) { ins[1].checked = false; }
    });
  }
}

/* ---------- generation ---------- */
async function generate() {
  saveOptionsFromForm();
  const err = $("#gen-error");
  err.classList.add("hidden"); err.innerHTML = "";

  // validation
  if (!state.pool.length) return fail("The question pool is empty.");
  for (const q of state.pool) {
    if (!(q.points >= 1 && q.points <= 99)) return fail(`Points must be 1–99 (type ${q.qt}, variant ${q.wid}).`);
  }
  if (!(state.options.n >= 1 && state.options.n <= 200)) return fail("Number of exams must be 1–200.");
  if (!state.options.demo && state.options.include.size === 0)
    return fail("Select at least one question type to include.");

  const spec = {
    questions: state.pool.map((q) => ({
      question_type: q.qt, within_type_id: q.wid,
      points: q.points, question_text: q.text,
    })),
    fields: state.fields,
    n: state.options.n,
    extra_pages: state.options.extra,
    q_types: state.options.demo ? null : [...state.options.include].sort(),
    bonus_types: [...state.options.bonus],
    demo: state.options.demo,
    fixed: state.options.fixed,
    language: state.language,
  };

  const fd = new FormData();
  fd.append("spec", JSON.stringify(spec));
  for (const [name, file] of state.assets) fd.append("assets", file, name);

  const btn = $("#btn-generate");
  btn.disabled = true;
  $("#gen-status").classList.remove("hidden");
  try {
    const resp = await fetch("/api/generate", { method: "POST", body: fd });
    if (!resp.ok) {
      let detail = `HTTP ${resp.status}`;
      try { detail = (await resp.json()).detail || detail; } catch (_) {}
      return fail("Generation failed.", detail);
    }
    const blob = await resp.blob();
    triggerDownload(blob, "exams.zip");
  } catch (e) {
    fail("Network error.", String(e));
  } finally {
    btn.disabled = false;
    $("#gen-status").classList.add("hidden");
  }
}
function saveOptionsFromForm() {
  state.options.n = parseInt($("#o_n").value || "1", 10);
  state.options.extra = parseInt($("#o_extra").value || "0", 10);
  state.options.demo = $("#o_demo").checked;
  state.options.fixed = $("#o_fixed").checked;
}
function fail(msg, detail) {
  const err = $("#gen-error");
  err.classList.remove("hidden");
  err.innerHTML = "";
  err.append(el("strong", {}, msg));
  if (detail) err.append(el("pre", {}, detail));
}

/* ---------- wire up ---------- */
function init() {
  // landing
  $("#choice-generate").addEventListener("click", () => {
    renderEditor(); renderAssets();
    const hasPool = state.pool.length > 0;
    $("#editor-intro").classList.toggle("hidden", hasPool);
    $("#editor-body").classList.toggle("hidden", !hasPool);
    show("editor");
  });

  // editor: upload / scratch
  $("#json-upload").addEventListener("change", async (e) => {
    const f = e.target.files[0]; if (!f) return;
    try {
      const data = JSON.parse(await f.text());
      if (!Array.isArray(data)) throw new Error("JSON must be an array of questions.");
      state.pool = normalizePool(data);
      renderEditor();
      $("#editor-body").classList.remove("hidden");
      $("#editor-intro").classList.add("hidden");
    } catch (err) { alert("Could not read JSON: " + err.message); }
    e.target.value = "";
  });
  $("#start-scratch").addEventListener("click", () => {
    state.pool = [];
    renderEditor();
    $("#editor-body").classList.remove("hidden");
    $("#editor-intro").classList.add("hidden");
  });
  $("#add-type").addEventListener("click", () => {
    const qt = nextType();
    state.pool.push({ qt, wid: "01", points: 1, text: "" });
    renderEditor();
  });
  $("#asset-input").addEventListener("change", (e) => { addAssets(e.target.files); e.target.value = ""; });

  $("#editor-intro-back").addEventListener("click", () => show("landing"));
  $("#editor-back").addEventListener("click", () => {
    $("#editor-body").classList.add("hidden");
    $("#editor-intro").classList.remove("hidden");
  });

  $("#editor-continue").addEventListener("click", () => {
    if (!state.pool.length) { alert("Add at least one question first."); return; }
    exportPoolJSON();
    loadTemplateFields();
    show("template");
  });

  // template
  $("#template-back").addEventListener("click", () => { saveTemplateFields(); show("editor"); });
  $("#template-continue").addEventListener("click", () => { saveTemplateFields(); renderOptions(); show("options"); });

  // options
  $("#o_demo").addEventListener("change", syncDemo);
  $("#options-back").addEventListener("click", () => { saveOptionsFromForm(); show("template"); });
  $("#btn-generate").addEventListener("click", generate);

  show("landing");
}
document.addEventListener("DOMContentLoaded", init);

/* ============================================================
   GRADING FLOW (steps 1–3). Steps 2 and 3 run in the browser;
   the server is only contacted to read/sort (step 1) and to
   compile the report. Nothing is persisted anywhere.
   ============================================================ */

const GEN_VIEWS = ["landing", "editor", "template", "options"];
const G_VIEWS = ["g-step1", "g-grade-entry", "g-grade", "g-review", "g-split", "g-done"];

const G = {
  files: [], sortedBytes: null, header: [], pagelist: [],
  questions: [], cur: 0, summary: null, job: null,
  pdfDoc: null, renderToken: 0, curTask: null, fromFlow: false,
};

function gReset() {
  if (G.pdfDoc) { try { G.pdfDoc.destroy(); } catch (e) {} }
  Object.assign(G, { files: [], sortedBytes: null, header: [], pagelist: [],
    questions: [], cur: 0, summary: null, job: null, pdfDoc: null,
    renderToken: 0, curTask: null, fromFlow: false });
}

function showG(view) {
  for (const v of GEN_VIEWS) $("#view-" + v).classList.add("hidden");
  $("#stepper").classList.add("hidden");
  for (const v of G_VIEWS) $("#view-" + v).classList.toggle("hidden", v !== view);
  const order = { "g-step1": 1, "g-grade-entry": 2, "g-grade": 2, "g-review": 2, "g-split": 3, "g-done": 3 };
  const has = view in order;
  $("#g-stepper").classList.toggle("hidden", !has);
  if (has) {
    const cur = order[view];
    document.querySelectorAll("#g-stepper .step").forEach((s) => {
      const n = Number(s.dataset.gstep);
      s.classList.toggle("active", n === cur);
      s.classList.toggle("done", n < cur);
    });
  }
  window.scrollTo(0, 0);
}
function backToStart() {
  for (const v of G_VIEWS) $("#view-" + v).classList.add("hidden");
  $("#g-stepper").classList.add("hidden");
  gReset();
  show("landing");
}

/* ---------- CSV helpers ---------- */
function splitCSVLine(line) {
  const out = []; let cur = "", q = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (q) { if (c === '"') { if (line[i + 1] === '"') { cur += '"'; i++; } else q = false; } else cur += c; }
    else { if (c === '"') q = true; else if (c === ",") { out.push(cur); cur = ""; } else cur += c; }
  }
  out.push(cur); return out;
}
function parseCSV(text) {
  const lines = text.replace(/\r/g, "").split("\n").filter((l) => l.length);
  const header = splitCSVLine(lines[0]);
  const rows = lines.slice(1).map((l) => {
    const cells = splitCSVLine(l), o = {};
    header.forEach((h, i) => (o[h] = cells[i] != null ? cells[i] : ""));
    return o;
  });
  return { header, rows };
}
function csvCell(v) {
  v = v == null ? "" : String(v);
  return /[",\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v;
}
const delay = (ms) => new Promise((r) => setTimeout(r, ms));

/* ---------- build gradeable question list ---------- */
function buildQuestions() {
  G.questions = G.pagelist
    .filter((r) => r.page_within_question === "1" &&
      !["00", "99", "N/A"].includes(r.question_type))
    .map((r) => ({
      row: r, page: Number(r.new_page_number), exam: r.exam_number,
      type: r.question_type, variant: r.within_type_id,
      max: parseFloat(r.max_points) || 0,
      points: r.points !== "" && r.points != null ? parseFloat(r.points) : null,
    }))
    .sort((a, b) => a.page - b.page);
  G.cur = 0;
}

/* ---------- step 1: read & sort ---------- */
function renderPdfList() {
  const ul = $("#g-pdf-list"); ul.innerHTML = "";
  let total = 0;
  for (const f of G.files) { total += f.size; ul.append(el("li", {}, el("span", {}, f.name),
    el("span", { className: "muted" }, (f.size / 1048576).toFixed(1) + " MB"))); }
  $("#g-read-btn").classList.toggle("hidden", G.files.length === 0);
  if (total > 250 * 1048576) gReadError("Total size exceeds 250 MB.");
}
function gReadError(msg) { const e = $("#g-read-error"); e.classList.remove("hidden");
  e.innerHTML = ""; e.append(el("strong", {}, msg)); }

async function doRead() {
  $("#g-read-error").classList.add("hidden");
  $("#g-read-result").classList.add("hidden");
  $("#g-to-grading").classList.add("hidden");
  $("#g-read-btn").disabled = true;
  $("#g-read-progress").classList.remove("hidden");
  setBar("#g-bar", 0); $("#g-read-status").textContent = "Uploading…";

  const fd = new FormData();
  for (const f of G.files) fd.append("pdfs", f, f.name);
  try {
    const resp = await fetch("/api/grade/read", { method: "POST", body: fd });
    if (!resp.ok || !resp.body) {
      let d = "HTTP " + resp.status; try { d = (await resp.json()).detail || d; } catch (e) {}
      throw new Error(d);
    }
    const reader = resp.body.getReader(); const dec = new TextDecoder(); let buf = "";
    let done = null;
    while (true) {
      const r = await reader.read(); if (r.done) break;
      buf += dec.decode(r.value, { stream: true });
      let nl;
      while ((nl = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, nl).trim(); buf = buf.slice(nl + 1);
        if (!line) continue;
        const msg = JSON.parse(line);
        if (msg.error) throw new Error(msg.error);
        if (msg.progress != null) {
          setBar("#g-bar", msg.progress / msg.total * 100);
          $("#g-read-status").textContent = `Reading page ${msg.progress} of ${msg.total}…`;
        } else if (msg.done) { done = msg; }
      }
    }
    if (!done) throw new Error("Stream ended unexpectedly.");
    G.job = done.job; G.summary = done.summary;
    $("#g-read-status").textContent = "Fetching results…";
    const ab = await (await fetch(`/api/grade/result/${G.job}/sorted.pdf`)).arrayBuffer();
    G.sortedBytes = new Uint8Array(ab);
    const csv = parseCSV(await (await fetch(`/api/grade/result/${G.job}/pagelist.csv`)).text());
    G.header = csv.header; G.pagelist = csv.rows;
    buildQuestions();
    renderReadResult();
  } catch (e) {
    gReadError(String(e.message || e));
  } finally {
    $("#g-read-btn").disabled = false;
    $("#g-read-progress").classList.add("hidden");
  }
}
function renderReadResult() {
  const s = G.summary, box = $("#g-read-result"); box.classList.remove("hidden"); box.innerHTML = "";
  const grid = el("div", { className: "summary-grid" });
  const cell = (n, lbl) => el("div", { className: "cell" }, el("b", {}, String(n)), el("span", {}, lbl));
  grid.append(cell(s.total_pages, "pages"), cell(s.gradeable_questions, "questions to grade"),
    cell(s.extrasheets, "extra-sheet pages"), cell(s.nocode, "unreadable pages"));
  box.append(grid);
  if (s.has_nocode) box.append(el("div", { className: "warn" },
    `Warning: ${s.nocode} page(s) had no readable code and were collected into nocode.pdf — check them by hand.`));
  $("#g-to-grading").classList.remove("hidden");
}
function setBar(sel, pct) { $(sel).style.width = Math.max(0, Math.min(100, pct)) + "%"; }

async function saveAndContinue() {
  // bundle the intermediate files into a single ZIP so nothing opens in a browser tab
  const zip = new JSZip();
  zip.file("sorted.pdf", G.sortedBytes);
  zip.file("pagelist.csv", csvFromRows(G.header, G.pagelist));
  if (G.summary.has_extrasheets)
    zip.file("extrasheets.pdf", await (await fetch(`/api/grade/result/${G.job}/extrasheets.pdf`)).arrayBuffer());
  if (G.summary.has_nocode)
    zip.file("nocode.pdf", await (await fetch(`/api/grade/result/${G.job}/nocode.pdf`)).arrayBuffer());
  const blob = await zip.generateAsync({ type: "blob", compression: "STORE" });
  triggerDownload(blob, "exam_read_results.zip");
  fetch(`/api/grade/cleanup/${G.job}`, { method: "POST" }).catch(() => {});
  G.fromFlow = true;
  startGrading();
}
function csvFromRows(header, rows) {
  return header.join(",") + "\n" +
    rows.map((r) => header.map((h) => csvCell(r[h])).join(",")).join("\n") + "\n";
}

/* ---------- step 2: grading ---------- */
async function getDoc() {
  if (!G.pdfDoc) {
    pdfjsLib.GlobalWorkerOptions.workerSrc = "vendor/pdf.worker.min.js";
    G.pdfDoc = await pdfjsLib.getDocument({ data: G.sortedBytes.slice() }).promise;
  }
  return G.pdfDoc;
}
function startGrading() {
  if (!G.questions.length) { alert("No gradeable questions were found."); return; }
  G.cur = 0; showG("g-grade"); renderQuestion();
}
function renderQuestion() {
  const q = G.questions[G.cur];
  $("#g-qcount").textContent = `Question ${G.cur + 1} of ${G.questions.length}`;
  $("#g-qmeta").textContent = `${q.points != null ? "entered" : "not yet entered"}`;
  const c = $("#g-controls"); c.innerHTML = "";
  const cn = (lbl, val, cls) => el("div", { className: "cn " + (cls || "") },
    el("small", {}, lbl), el("b", {}, val));
  c.append(cn("Exam", q.exam), cn("Type", q.type), cn("Variant", q.variant),
    cn("Max", String(q.max), "max"));
  const inp = $("#g-points");
  inp.value = q.points != null ? String(q.points) : "";
  inp.max = String(q.max);
  setTimeout(() => { inp.focus(); inp.select(); }, 30);
  renderPreview();
}
async function renderPreview() {
  const q = G.questions[G.cur]; const token = ++G.renderToken;
  if (G.curTask) { try { G.curTask.cancel(); } catch (e) {} }
  const doc = await getDoc();
  const page = await doc.getPage(q.page);
  const cont = $("#g-preview"); const cw = cont.clientWidth || 440;
  const base = page.getViewport({ scale: 1 });
  const vp = page.getViewport({ scale: cw / base.width });
  const off = document.createElement("canvas"); off.width = vp.width; off.height = vp.height;
  const task = page.render({ canvasContext: off.getContext("2d"), viewport: vp });
  G.curTask = task;
  try { await task.promise; } catch (e) { return; }
  if (token !== G.renderToken) return;
  const cv = $("#g-canvas"); cv.width = vp.width; cv.height = Math.floor(vp.height / 3);
  cv.getContext("2d").drawImage(off, 0, 0);
}
function saveCurrentPoints() {
  const v = $("#g-points").value.trim();
  G.questions[G.cur].points = v === "" ? null : (Number.isFinite(+v) ? +v : null);
}
function gotoQuestion(i) {
  saveCurrentPoints();
  G.cur = Math.max(0, Math.min(G.questions.length - 1, i));
  renderQuestion();
}
function nextQuestion() {
  saveCurrentPoints();
  if (G.cur >= G.questions.length - 1) { renderReview(); showG("g-review"); }
  else { G.cur++; renderQuestion(); }
}
async function expandPreview() {
  const q = G.questions[G.cur]; const doc = await getDoc();
  const draw = async (pageNum, cv) => {
    if (pageNum > doc.numPages) { cv.classList.add("hidden"); return; }
    cv.classList.remove("hidden");
    const page = await doc.getPage(pageNum);
    const base = page.getViewport({ scale: 1 });
    const w = Math.min(780, $("#g-overlay").clientWidth - 64);
    const vp = page.getViewport({ scale: w / base.width });
    cv.width = vp.width; cv.height = vp.height;
    await page.render({ canvasContext: cv.getContext("2d"), viewport: vp }).promise;
  };
  $("#g-overlay").classList.remove("hidden");
  await draw(q.page, $("#g-canvas-1"));
  await draw(q.page + 1, $("#g-canvas-2"));
}

/* ---------- review ---------- */
function renderReview() {
  const missing = G.questions.filter((q) => q.points == null).length;
  $("#g-review-warn").textContent = missing
    ? `${missing} question(s) have no points entered — they will count as 0.` : "";
  const t = $("#g-review-table"); t.innerHTML = "";
  t.append(el("div", { className: "rrow rhead" },
    el("span", {}, "Exam"), el("span", {}, "Type"), el("span", {}, "Variant"), el("span", {}, "Points")));
  G.questions.forEach((q, i) => {
    const row = el("div", { className: "rrow" + (q.points == null ? " missing" : "") },
      el("span", { className: "mono" }, q.exam), el("span", { className: "mono" }, q.type),
      el("span", { className: "mono" }, q.variant),
      el("span", { className: "mono" }, q.points == null ? "—" : String(q.points)));
    row.addEventListener("click", () => { G.cur = i; renderQuestion(); showG("g-grade"); });
    t.append(row);
  });
}

/* ---------- confirm & save: CSVs + report ---------- */
async function confirmAndSave() {
  $("#g-report-error").classList.add("hidden");
  const pbq = csvFromRows(G.header, G.questions.map((q) => {
    const o = { ...q.row }; o.points = q.points == null ? "" : String(q.points); return o;
  }));
  const totals = {};
  for (const q of G.questions) totals[q.exam] = (totals[q.exam] || 0) + (q.points || 0);
  const pbe = "exam_number,total_points\n" +
    Object.keys(totals).sort().map((e) => `${csvCell(e)},${totals[e]}`).join("\n") + "\n";

  $("#g-confirm").disabled = true;
  $("#g-report-status").classList.remove("hidden");
  try {
    const fd = new FormData();
    fd.append("points", new Blob([pbq], { type: "text/csv" }), "points_by_question.csv");
    const resp = await fetch("/api/grade/report", { method: "POST", body: fd });
    if (!resp.ok) {
      let d = "HTTP " + resp.status; try { d = (await resp.json()).detail || d; } catch (e) {}
      throw new Error(d);
    }
    const reportBlob = await resp.blob();
    const zip = new JSZip();
    zip.file("exam_results_report.pdf", reportBlob);
    zip.file("points_by_question.csv", pbq);
    zip.file("points_by_exam.csv", pbe);
    const out = await zip.generateAsync({ type: "blob", compression: "STORE" });
    triggerDownload(out, "exam_grading_results.zip");
    // proceed to step 3 (files already in memory)
    $("#g-split-upload").classList.add("hidden");
    showG("g-split");
  } catch (e) {
    const er = $("#g-report-error"); er.classList.remove("hidden");
    er.innerHTML = ""; er.append(el("strong", {}, "Report failed."), el("pre", {}, String(e.message || e)));
  } finally {
    $("#g-confirm").disabled = false;
    $("#g-report-status").classList.add("hidden");
  }
}

/* ---------- step 3: split into per-exam PDFs ---------- */
async function doSplit() {
  $("#g-split-error").classList.add("hidden");
  // direct entry: load from upload inputs first
  if (!G.sortedBytes || !G.pagelist.length) {
    const pf = $("#gs-pdf").files[0], cf = $("#gs-csv").files[0];
    if (!pf || !cf) return gSplitError("Please provide both the sorted PDF and the page list.");
    G.sortedBytes = new Uint8Array(await pf.arrayBuffer());
    const csv = parseCSV(await cf.text()); G.header = csv.header; G.pagelist = csv.rows;
  }
  // group pages by exam, ordered by question then page-within
  const groups = {};
  for (const r of G.pagelist) {
    const ex = r.exam_number && r.exam_number !== "N/A" ? r.exam_number : "NA";
    (groups[ex] = groups[ex] || []).push(r);
  }
  const numKey = (r) => [parseInt(r.question_number) || 999, parseInt(r.page_within_question) || 0];
  const exams = Object.keys(groups).sort();

  $("#g-split-go").disabled = true;
  $("#g-split-progress").classList.remove("hidden"); setBar("#g-split-bar", 0);
  try {
    const src = await PDFLib.PDFDocument.load(G.sortedBytes);
    const zip = new JSZip();
    for (let i = 0; i < exams.length; i++) {
      const ex = exams[i];
      const pages = groups[ex].slice().sort((a, b) => {
        const ka = numKey(a), kb = numKey(b); return ka[0] - kb[0] || ka[1] - kb[1];
      });
      const out = await PDFLib.PDFDocument.create();
      const idxs = pages.map((p) => Number(p.new_page_number) - 1);
      const copied = await out.copyPages(src, idxs);
      copied.forEach((p) => out.addPage(p));
      zip.file(`exam_graded_${ex}.pdf`, await out.save());
      setBar("#g-split-bar", (i + 1) / exams.length * 100);
      $("#g-split-status").textContent = `Building exam ${i + 1} of ${exams.length}…`;
      await delay(0);
    }
    $("#g-split-status").textContent = "Zipping…";
    const blob = await zip.generateAsync({ type: "blob", compression: "STORE" });
    triggerDownload(blob, "graded_exams.zip");
    showG("g-done");
  } catch (e) {
    gSplitError(String(e.message || e));
  } finally {
    $("#g-split-go").disabled = false;
    $("#g-split-progress").classList.add("hidden");
  }
}
function gSplitError(msg) { const e = $("#g-split-error"); e.classList.remove("hidden");
  e.innerHTML = ""; e.append(el("strong", {}, msg)); }

/* ---------- wire up grading ---------- */
function initGrading() {
  // Tab inserts a tab inside LaTeX editors instead of moving focus.
  document.addEventListener("keydown", (e) => {
    if (e.key === "Tab" && !e.shiftKey && e.target.tagName === "TEXTAREA" &&
        e.target.classList.contains("tex")) {
      e.preventDefault();
      const ta = e.target, s = ta.selectionStart, en = ta.selectionEnd;
      ta.value = ta.value.slice(0, s) + "\t" + ta.value.slice(en);
      ta.selectionStart = ta.selectionEnd = s + 1;
      ta.dispatchEvent(new Event("input"));
    }
  });

  $("#choice-grade").addEventListener("click", () => {
    gReset();
    $("#g-pdf-list").innerHTML = ""; $("#g-read-btn").classList.add("hidden");
    $("#g-read-result").classList.add("hidden"); $("#g-to-grading").classList.add("hidden");
    $("#g-read-progress").classList.add("hidden"); $("#g-read-error").classList.add("hidden");
    showG("g-step1");
  });

  $("#g-pdf-input").addEventListener("change", (e) => {
    G.files = [...e.target.files]; $("#g-read-error").classList.add("hidden"); renderPdfList();
  });
  $("#g-read-btn").addEventListener("click", doRead);
  $("#g-step1-back").addEventListener("click", backToStart);
  $("#g-to-grading").addEventListener("click", saveAndContinue);
  $("#g-skip-grade").addEventListener("click", (e) => { e.preventDefault(); showG("g-grade-entry"); });
  $("#g-skip-split").addEventListener("click", (e) => {
    e.preventDefault(); $("#g-split-upload").classList.remove("hidden"); showG("g-split");
  });

  // direct grade entry
  $("#ge-back").addEventListener("click", () => showG("g-step1"));
  $("#ge-start").addEventListener("click", async () => {
    const pf = $("#ge-pdf").files[0], cf = $("#ge-csv").files[0];
    const er = $("#ge-error");
    if (!pf || !cf) { er.classList.remove("hidden"); er.innerHTML = ""; er.append(el("strong", {}, "Provide both files.")); return; }
    er.classList.add("hidden");
    G.sortedBytes = new Uint8Array(await pf.arrayBuffer());
    const csv = parseCSV(await cf.text()); G.header = csv.header; G.pagelist = csv.rows;
    buildQuestions(); G.fromFlow = false; startGrading();
  });

  // grading screen
  $("#g-prev").addEventListener("click", () => gotoQuestion(G.cur - 1));
  $("#g-next").addEventListener("click", nextQuestion);
  $("#g-points").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); nextQuestion(); } });
  $("#g-finish").addEventListener("click", () => { saveCurrentPoints(); renderReview(); showG("g-review"); });
  $("#g-grade-back").addEventListener("click", backToStart);
  $("#g-preview").addEventListener("click", expandPreview);
  $("#g-overlay-close").addEventListener("click", () => $("#g-overlay").classList.add("hidden"));
  $("#g-overlay").addEventListener("click", (e) => { if (e.target.id === "g-overlay") $("#g-overlay").classList.add("hidden"); });

  // review
  $("#g-review-back").addEventListener("click", () => { renderQuestion(); showG("g-grade"); });
  $("#g-confirm").addEventListener("click", confirmAndSave);

  // split
  $("#g-split-go").addEventListener("click", doSplit);
  $("#g-split-back").addEventListener("click", backToStart);

  // done
  $("#g-done-home").addEventListener("click", backToStart);
}
document.addEventListener("DOMContentLoaded", initGrading);
