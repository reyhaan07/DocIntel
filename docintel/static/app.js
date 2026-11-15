"use strict";

/* docintel web app - plain JS, no build step. */

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const STATUS = { completed: "Completed", needs_review: "Needs review", needs_ocr: "Needs OCR", failed: "Failed" };
const ATTR_STATUS = { valid: "Valid", needs_review: "Needs review", invalid: "Invalid" };
const MISSING_KIND = { not_provided: "Not provided", incomplete_record: "Incomplete record", not_signed: "Not signed" };
const ID_RE = /\b((?:PAT|SPO|EMC|INS|INSCO|MED|DR|ALG|COND|SURG|HOSP|FAM|CONS|AFM|AGR|REL|REV)_\d{3})(\.[a-z_]+)?\b/g;

const S = {
  docs: [], ocr: false, questions: {}, doc: null, id: null,
  tab: "entities", relFilter: "all", revFilter: "open", view: "source", page: 1, editing: null,
  sel: null, boxes: [], refs: [], ask: { q: "find", a: "" }, askResult: null,
};

/* ------------------------------------------------------------------ api */
async function api(path, opts) {
  const r = await fetch(path, opts);
  const ct = r.headers.get("content-type") || "";
  const data = ct.includes("json") ? await r.json() : await r.text();
  if (!r.ok) throw new Error((data && data.error) || data || r.statusText);
  return data;
}

function toast(html, err = false) {
  const el = document.createElement("div");
  el.className = "toast" + (err ? " err" : "");
  el.innerHTML = html;
  $("#toasts").appendChild(el);
  setTimeout(() => el.remove(), 5200);
}

/* ------------------------------------------------------------------ loading */
async function loadDocs(selectId) {
  const data = await api("/api/documents");
  S.docs = data.documents;
  S.ocr = data.ocr_available;
  S.questions = data.questions;
  renderSidebar();
  const fromHash = decodeURIComponent(location.hash.slice(1));
  const want = [selectId, S.id, fromHash].find((x) => x && S.docs.some((d) => d.doc_id === x)) || (S.docs[0] && S.docs[0].doc_id);
  if (want) await openDoc(want, want === S.id);
  else showEmpty();
}

async function openDoc(id, keep = false) {
  const doc = await api(`/api/documents/${id}`);
  const changed = id !== S.id;
  S.doc = doc;
  S.id = id;
  if (changed || !keep) {
    S.sel = null; S.boxes = []; S.refs = []; S.info = ""; S.page = 1; S.askResult = null;
    $("#pageWrap").scrollTop = 0;
    if (doc.document.status === "needs_ocr" && S.tab === "entities") S.tab = "review";
  }
  history.replaceState(null, "", `#${id}`);
  $("#emptyState").hidden = true;
  $("#docView").hidden = false;
  renderSidebar();
  renderDoc();
}

function showEmpty() {
  S.doc = null; S.id = null;
  $("#docView").hidden = true;
  $("#emptyState").hidden = false;
  renderSidebar();
}

/* ------------------------------------------------------------------ sidebar */
function renderSidebar() {
  $("#docCount").textContent = S.docs.length;
  $("#docList").innerHTML = S.docs.map((d) => `
    <button type="button" class="doccard ${d.doc_id === S.id ? "on" : ""}" data-doc="${esc(d.doc_id)}">
      <div class="row1"><span class="did">${esc(d.doc_id)}</span><span class="badge ${esc(d.status)}">${esc(STATUS[d.status] || d.status)}</span></div>
      <div class="fname" title="${esc(d.filename)}">${esc(d.filename)}</div>
      <div class="counts">${d.entities} entities · ${d.relationships} relationships · ${d.review_items} to review</div>
    </button>`).join("");
}

/* ------------------------------------------------------------------ document */
function renderDoc() {
  const d = S.doc, m = d.document, s = d.summary;
  $("#hId").textContent = m.doc_id;
  const b = $("#hStatus");
  b.className = `badge ${m.status}`;
  b.textContent = STATUS[m.status] || m.status;
  $("#hName").textContent = m.filename;
  $("#hMeta").innerHTML = [
    m.template_applied === false
      ? (m.document_type && m.document_type !== "unknown"
          ? `<span title="${esc(m.document_type_basis || "")} · no template: read with the template-free structure">${esc(m.document_type)} (guessed)</span>`
          : `<span title="No template matched: read with the template-free structure">document type not recognised</span>`)
      : esc(m.document_type || "document"),
    m.title ? `“${esc(m.title)}”` : "",
    `${m.page_count} page(s)`,
    `extraction: <b>${esc(m.extraction_method)}</b>`,
    m.sha256 ? `sha256 ${esc(m.sha256.slice(0, 12))}…` : "",
    esc(m.processed_at),
    m.processing_ms != null ? `${m.processing_ms} ms` : "",
  ].filter(Boolean).join(" · ") + (m.error ? ` · <span style="color:var(--red)">${esc(m.error)}</span>` : "");
  $("#dlJson").href = `/api/documents/${m.doc_id}/download.json`;
  $("#dlJson").setAttribute("download", `${m.doc_id}.json`);
  $("#dlMd").href = `/api/documents/${m.doc_id}/download.md`;
  $("#dlMd").setAttribute("download", `${m.doc_id}.md`);
  $("#dlSrc").href = `/api/documents/${m.doc_id}/source.pdf`;
  $("#dlStd").href = `/api/documents/${m.doc_id}/standardized.pdf`;
  $("#dlStd").hidden = !d.standardized;
  $("#ocrBtn").hidden = !(m.status === "needs_ocr" && S.ocr);
  const open = d.review_queue.filter((r) => !r.resolution).length;
  const truthBtn = $("#truthBtn");
  truthBtn.hidden = !Object.keys(d.entities).length;
  truthBtn.disabled = open > 0;
  truthBtn.title = open ? `Resolve the ${open} open review item(s) first` : "Save this checked result as ground truth for the accuracy suite";

  const tiles = [
    [s.entities, "entities"], [s.traced_values, "traced values"], [s.relationships, "relationships"],
    [s.uncertain_relationships, "uncertain links", s.uncertain_relationships ? "amber" : ""],
    [s.review_items, "review items", s.review_items ? "amber" : ""],
    [s.missing_items, "missing items"],
    [s.validation_errors, "validation errors", s.validation_errors ? "red" : ""],
    [s.text_coverage == null ? "—" : `${Math.round(s.text_coverage * 1000) / 10}%`, "of text read"],
  ];
  if (d.standardized) tiles.push([s.fields_filled, `fields filled · ${s.fields_withheld} withheld`, "wide"]);
  $("#stats").innerHTML = tiles.map(([n, l, c]) => `<div class="stat ${c || ""}"><div class="n">${n}</div><div class="l">${esc(l)}</div></div>`).join("");
  renderTabs();
  renderTab();
  renderViewer();
}

function renderTabs() {
  const d = S.doc, s = d.summary;
  const vIssues = d.validation.errors.length + d.validation.warnings.length;
  const tabs = [
    ["entities", "Entities", s.entities],
    ["document", "Document", (d.blocks || []).length],
    ["relationships", "Relationships", s.relationships, s.uncertain_relationships],
    ["review", "Review", null, s.review_items],
    ["missing", "Missing", s.missing_items],
    ["validation", "Validation", null, vIssues],
    ["ask", "Ask"],
  ];
  $("#tabs").innerHTML = tabs.map(([k, label, n, amber]) => `
    <button type="button" role="tab" class="tab ${S.tab === k ? "on" : ""}" data-tab="${k}" aria-selected="${S.tab === k}">
      ${label}${n != null ? ` <span class="chip-n">${n}</span>` : ""}${amber ? ` <span class="chip-n amber">${amber}</span>` : ""}
    </button>`).join("");
}

/* ------------------------------------------------------------------ helpers */
const ent = (id) => S.doc.entities[id];
const fmtVal = (v) => (v == null ? "—" : Array.isArray(v) ? v.join(", ") : String(v));
const idlink = (id, extra = "") => `<span class="idlink" data-ref="${esc(id)}${esc(extra)}">${esc(id)}${esc(extra)}</span>`;
const linkify = (text) => esc(text).replace(ID_RE, (m, id, attr) => (S.doc && (S.doc.entities[id] || id.startsWith("REL_") || id.startsWith("REV_")) ? idlink(id, attr || "") : m));

function confHTML(c) {
  const pct = Math.round((c || 0) * 100);
  return `<span class="conf ${c < 0.6 ? "low" : ""}"><i><b style="width:${pct}%"></b></i>${(c || 0).toFixed(2)}</span>`;
}

function relsOf(id) {
  return S.doc.relationships.filter((r) => r.subject === id || r.object === id);
}

function relChip(r, perspective) {
  const unc = r.support === "uncertain" ? " uncertain" : "";
  let text;
  if (r.object === perspective) {
    const s = ent(r.subject);
    text = `← ${r.subject} ${s ? s.label : ""} ${r.predicate}`;
  } else {
    const o = ent(r.object);
    text = `${r.predicate} → ${r.object} ${o ? o.label : ""}`;
  }
  return `<button type="button" class="rchip${unc}" data-sel="rel:${r.relationship_id}" title="${esc(r.relationship_id)}: ${esc(r.basis)}">${esc(text)}</button>`;
}

function whereText(e) {
  const parts = [e.section || "—"];
  if (e.row) parts.push(`row ${e.row}`);
  if (e.derived) parts.push("derived");
  if (e.page) parts.push(`p.${e.page}`);
  return parts.join(" · ");
}

/* ------------------------------------------------------------------ tabs */
function renderTab() {
  const body = $("#tabBody");
  const fn = { entities: tabEntities, document: tabDocument, relationships: tabRelationships, review: tabReview, missing: tabMissing, validation: tabValidation, ask: tabAsk }[S.tab];
  body.innerHTML = fn();
  if (S.tab === "ask") wireAsk();
  markSelection();
}

function tabEntities() {
  const d = S.doc;
  if (!Object.keys(d.entities).length) return `<div class="nothing">No entities were extracted.</div>`;
  let h = "";
  for (const g of d.entity_groups) {
    h += `<div class="grouphead">${esc(g.group)} <span class="chip-n">${g.ids.length}</span></div>`;
    for (const id of g.ids) h += entityCard(d.entities[id]);
  }
  return h;
}

function entityCard(e) {
  const attrs = Object.entries(e.attributes);
  const rows = attrs.map(([k, a]) => `
    <tr data-sel="attr:${e.id}:${k}">
      <td class="k">${esc(k)}</td>
      <td class="v ${a.value == null ? "none" : ""}">${esc(fmtVal(a.value))}</td>
      <td class="lab">${esc(a.field_label || "")}</td>
      <td class="cf">${confHTML(a.confidence)}</td>
      <td class="st"><span class="badge ${esc(a.status)}" title="${a.reviewed ? `${esc(a.reviewed.action)} by ${esc(a.reviewed.by)}` : ""}">${a.reviewed ? (a.reviewed.action === "corrected" ? "Corrected" : "Reviewed") : esc(ATTR_STATUS[a.status] || a.status)}</span></td>
    </tr>`).join("");
  const rels = relsOf(e.id);
  const chips = rels.length ? `<div class="chips">${rels.map((r) => relChip(r, e.id)).join("")}</div>` : "";
  return `
    <article class="ecard" id="card-${e.id}">
      <div class="ehead" data-sel="ent:${e.id}">
        <span class="eid">${esc(e.id)}</span><span class="etype">${esc(e.type_name || e.type)}</span>
        <span class="elabel">${esc(e.label)}</span><span class="ewhere">${esc(whereText(e))}</span>
      </div>
      ${attrs.length ? `<table class="attrs"><tbody>${rows}</tbody></table>` : `<div class="nothing" style="padding:10px 12px">Nothing could be read for this entity yet.</div>`}
      ${chips}
    </article>`;
}

function keyFacts() {
  const kf = S.doc.key_facts || {};
  const names = Object.keys(kf);
  if (!names.length) return "";
  const m = S.doc.document;
  const carries = m.carries ? ` carrying ${esc(m.carries)}` : "";
  let h = `<div class="grouphead" title="${esc(m.document_type_basis || "")}">Key facts · ${esc(m.document_type || "document")}${carries}</div>`;
  for (const k of names) {
    const f = kf[k];
    const sel = f.entity && f.attribute ? `data-sel="attr:${f.entity}:${f.attribute}"` : "";
    h += `<div class="blk bf" ${sel} title="${esc(f.method)}${f.notes && f.notes.length ? " · " + esc(f.notes.join("; ")) : ""}">
      <span class="lab">${esc(k.replace(/_/g, " "))}</span><span class="v">${esc(f.value)}</span>
      <span class="subtle"> ← ${esc(f.label || "")}</span>${f.status !== "valid" ? ` <span class="badge needs_review">review</span>` : ""}</div>`;
  }
  return h;
}

function tabDocument() {
  const blocks = S.doc.blocks || [];
  if (!blocks.length) return `<div class="nothing">No text was read from this document.</div>`;
  let page = null, h = keyFacts();
  for (const b of blocks) {
    if (b.page !== page) { page = b.page; h += `<div class="grouphead">Page ${page}</div>`; }
    const sel = `data-sel="blk:${b.block_id}"`;
    if (b.type === "heading") h += `<div class="blk bh" ${sel}>${esc(b.text)}</div>`;
    else if (b.type === "field") h += `<div class="blk bf" ${sel}><span class="lab">${esc(b.label)}</span><span class="v ${b.value == null ? "none" : ""}">${esc(b.value ?? "(blank)")}</span>${b.normalized ? `<span class="subtle"> → ${esc(b.normalized)}</span>` : ""}</div>`;
    else if (b.type === "signature") h += `<div class="blk bf" ${sel}><span class="lab">${esc(b.label)}</span><span class="v">${b.signed ? "✍ " + esc(b.value || "signed") : "<span class='none'>not signed</span>"}</span></div>`;
    else if (b.type === "question") h += `<div class="blk bq" ${sel}>${b.question ? `<span class="lab">${esc(b.question)}</span>` : ""}${b.options.map((o) => `<span class="opt ${o.checked ? "on" : ""}">${o.checked ? "☒" : "☐"} ${esc(o.label || "")}</span>`).join("")}</div>`;
    else if (b.type === "table") h += `<div class="blk bt" ${sel}><table class="mini"><thead><tr>${b.header.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>${b.rows.map((r) => `<tr>${r.map((c) => `<td>${esc(c)}</td>`).join("")}</tr>`).join("")}</tbody></table>${b.continued ? `<div class="subtle">continued from the previous page</div>` : ""}</div>`;
    else if (b.type === "text") h += `<div class="blk bx" ${sel}>${esc(b.text).replace(/\n/g, "<br>")}</div>`;
    else if (b.type === "page_furniture") h += `<div class="blk bp" ${sel}>${esc(b.text)}</div>`;
  }
  return h;
}

function relLine(r) {
  const s = ent(r.subject), o = ent(r.object);
  return `<span class="rid">${esc(r.relationship_id)}</span> ${idlink(r.subject)} <span>${esc(s ? s.label : "")}</span>
    <span class="pred">${esc(r.predicate)}</span> ${idlink(r.object)} <span>${esc(o ? o.label : "")}</span>`;
}

function tabRelationships() {
  const all = S.doc.relationships;
  const unc = all.filter((r) => r.support === "uncertain");
  const list = S.relFilter === "uncertain" ? unc : all;
  let h = `<div class="filters" role="group">
    <button type="button" data-filter="all" class="${S.relFilter === "all" ? "on" : ""}">All ${all.length}</button>
    <button type="button" data-filter="uncertain" class="${S.relFilter === "uncertain" ? "on" : ""}">Uncertain ${unc.length}</button>
  </div>`;
  if (!list.length) return h + `<div class="nothing">No ${S.relFilter === "uncertain" ? "uncertain " : ""}relationships.</div>`;
  h += list.map((r) => `
    <div class="lcard ${r.support === "uncertain" ? "uncertain" : ""}" data-sel="rel:${r.relationship_id}">
      <div class="l1">${relLine(r)}</div>
      <div class="l2"><span class="badge ${r.support}">${r.support}</span> conf ${r.confidence.toFixed(2)}${r.page ? ` · page ${r.page}` : ""} · ${esc(r.basis)}</div>
      ${r.warnings.map((w) => `<div class="l3">⚠ ${esc(w)}</div>`).join("")}
    </div>`).join("");
  return h;
}

function reviewActions(it) {
  if (it.resolution) {
    const r = it.resolution;
    const what = r.action === "correct" ? `corrected to “${esc(fmtVal(r.value))}”` : r.action === "reject" ? "rejected" : r.action === "dismiss" ? "dismissed" : "confirmed";
    return `<div class="resolved">✓ ${what} by ${esc(r.by)} · ${esc(r.at)}</div>`;
  }
  if (S.editing === it.review_id) {
    const cur = it.value == null ? "" : Array.isArray(it.value) ? it.value.join(", ") : String(it.value);
    const input = it.attribute === "decision"
      ? `<select class="fixval" aria-label="Correct value"><option value="yes">yes</option><option value="no">no</option></select>`
      : `<input class="fixval" value="${esc(cur)}" aria-label="Correct value">`;
    return `<div class="ractions">${input}<button type="button" class="btn primary sm" data-act="correct" data-rev="${it.review_id}">Save</button><button type="button" class="btn sm" data-act="cancel">Cancel</button></div>`;
  }
  const btn = (act, label, cls = "") => `<button type="button" class="btn sm ${cls}" data-act="${act}" data-rev="${it.review_id}">${label}</button>`;
  if (it.kind === "attribute") return `<div class="ractions">${btn("confirm", "Confirm value", "ok")}${btn("edit", "Correct…")}</div>`;
  if (it.kind === "relationship") return `<div class="ractions">${btn("confirm", "Confirm link", "ok")}${btn("reject", "Reject link", "danger")}</div>`;
  if (it.kind === "validation") return `<div class="ractions">${btn("confirm", "Acknowledge", "ok")}</div>`;
  return `<div class="ractions">${btn("dismiss", "Dismiss")}</div>`;
}

function tabReview() {
  const all = S.doc.review_queue;
  if (!all.length) return `<div class="nothing">Nothing needs a person - every value and link was confirmed by the checks.</div>`;
  const open = all.filter((r) => !r.resolution), done = all.filter((r) => r.resolution);
  const list = S.revFilter === "open" ? open : S.revFilter === "resolved" ? done : all;
  let h = `<div class="filters" role="group">
    <button type="button" data-rfilter="open" class="${S.revFilter === "open" ? "on" : ""}">Open ${open.length}</button>
    <button type="button" data-rfilter="resolved" class="${S.revFilter === "resolved" ? "on" : ""}">Resolved ${done.length}</button>
    <button type="button" data-rfilter="all" class="${S.revFilter === "all" ? "on" : ""}">All ${all.length}</button>
  </div>`;
  if (!list.length) return h + `<div class="nothing">${S.revFilter === "open" ? "All review items are resolved. You can save this result as ground truth." : "Nothing here yet."}</div>`;
  return h + list.map((it) => {
    let body = "";
    if (it.kind === "relationship") {
      body += `<div class="l2">${idlink(it.subject)} ${esc(it.predicate)} ${idlink(it.object)}</div>`;
    }
    if (it.kind === "attribute") body += `<div class="l2">value: ${esc(fmtVal(it.value))}</div>`;
    const target = it.kind === "ocr" ? `<b>${esc(it.target)}</b>` : linkify(it.target);
    return `<div class="lcard ${it.resolution ? "done" : ""}" data-sel="rev:${it.review_id}">
      <div class="top"><div class="l1"><span class="rid">${esc(it.review_id)}</span> · ${target}</div><span class="badge kind">${esc(it.kind)}</span></div>
      ${body}<div class="l1" style="margin-top:4px">${linkify(it.reason)}</div>${reviewActions(it)}</div>`;
  }).join("");
}

async function reviewAct(revId, action, value) {
  try {
    const r = await api(`/api/documents/${S.id}/review/${revId}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action, value }),
    });
    S.editing = null;
    toast(`<b>${esc(revId)}</b> ${esc(action === "correct" ? "corrected" : action === "reject" ? "rejected" : action + "ed")} — ${r.summary.review_items} open · ${esc(STATUS[r.status] || r.status)}`);
    const keepTab = S.tab, keepSel = S.sel;
    await loadDocs(S.id);
    S.tab = keepTab;
    renderTabs();
    renderTab();
    if (keepSel) select(keepSel);
  } catch (e) { toast(esc(e.message), true); }
}

function tabMissing() {
  const m = S.doc.missing;
  if (!m.length) return `<div class="nothing">No required field is missing.</div>`;
  return m.map((it, i) => `
    <div class="lcard" data-sel="miss:${i}">
      <div class="top"><div class="l1">${it.entity && it.kind === "incomplete_record" ? linkify(it.path) : `<b class="mono" style="font-size:12.5px">${esc(it.path)}</b>`}</div>
        <span class="badge ${it.kind === "not_provided" ? "neutral" : "warn"}">${esc(MISSING_KIND[it.kind] || it.kind)}</span></div>
      <div class="l2">${esc(it.label)} — ${esc(it.reason)}${it.section ? ` · ${esc(it.section)}` : ""}</div>
    </div>`).join("");
}

function tabValidation() {
  const v = S.doc.validation;
  if (!v.checks.length) return `<div class="nothing">Validation did not run.</div>`;
  let h = v.checks.map((c) => `
    <div class="check">
      <div class="top"><div><div class="name">${esc(c.name)}</div><div class="desc">${esc(c.description)}</div></div>
        <div class="right">${c.checked} checked <span class="badge ${c.status}">${c.status}</span></div></div>
      ${c.issues.length ? `<ul>${c.issues.map((i) => `<li>${linkify(i.target)}: ${esc(i.message)}</li>`).join("")}</ul>` : ""}
    </div>`).join("");
  for (const [title, list] of [["Errors", v.errors], ["Warnings", v.warnings]]) {
    if (!list.length) continue;
    h += `<div class="grouphead">${title} <span class="chip-n">${list.length}</span></div>
      <div class="warnbox"><ul>${list.map((i) => `<li>${linkify(i.target)} ${esc(i.message)}</li>`).join("")}</ul></div>`;
  }
  return h;
}

/* ------------------------------------------------------------------ ask */
function askExamples() {
  const d = S.doc, E = Object.values(d.entities);
  const famCond = E.find((e) => e.type === "Condition" && (e.owner_hint || "").startsWith("FAM"));
  const med = E.find((e) => e.type === "Medication");
  const dr = E.find((e) => e.type === "Doctor");
  const unc = d.relationships.find((r) => r.support === "uncertain") || d.relationships[0];
  const cond = E.find((e) => e.type === "Condition");
  return {
    find: cond ? cond.attributes.name.value.toLowerCase() : (E.find((e) => e.type === "Field") ? String(E.find((e) => e.type === "Field").attributes.value.value).split(" ")[0] : ""),
    entity: med ? med.id : (E[0] ? E[0].id : ""),
    owner: famCond ? famCond.id : cond ? cond.id : (E.find((e) => e.type !== "Section") || {}).id || "",
    section: med && med.attributes.dosage ? `${med.id}.dosage` : (E[0] ? `${E[0].id}.${Object.keys(E[0].attributes)[0]}` : ""),
    related: dr ? `${dr.id} PAT_001` : "",
    evidence: unc ? unc.relationship_id : "",
  };
}

function tabAsk() {
  const ex = askExamples();
  const opts = Object.entries(S.questions).map(([k, label]) => `<option value="${k}" ${S.ask.q === k ? "selected" : ""}>${esc(label)}</option>`).join("");
  const sugg = [...Object.keys(S.doc.entities), ...Object.values(S.doc.entities).flatMap((e) => Object.keys(e.attributes).map((k) => `${e.id}.${k}`)), ...S.doc.relationships.map((r) => r.relationship_id)];
  return `
    <form class="askform" id="askForm" autocomplete="off">
      <select id="askQ" aria-label="Question">${opts}</select>
      <div class="row"><input id="askA" list="askList" value="${esc(S.ask.a)}" placeholder="Pick a question and a reference, e.g. an entity ID, an attribute path or a relationship ID." aria-label="Reference"></div>
      <datalist id="askList">${sugg.map((s) => `<option value="${esc(s)}">`).join("")}</datalist>
      <div class="row"><button class="btn primary" type="submit">Ask</button><span class="hint">IDs in the answer are clickable.</span></div>
      <div class="examples" id="askEx">${Object.entries(ex).filter(([, v]) => v).map(([q, v]) => `<button type="button" data-q="${q}" data-a="${esc(v)}">${q} ${esc(v)}</button>`).join("")}</div>
    </form>
    <div class="answer" id="askOut">${S.askResult ?? `<span class="subtle">Pick a question and a reference, e.g. an entity ID, an attribute path or a relationship ID.</span>`}</div>`;
}

function jsonHTML(obj) {
  const txt = esc(JSON.stringify(obj, null, 2));
  return txt.replace(/(&quot;(?:[^&]|&(?!quot;))*?&quot;)(\s*:)?|(\b-?\d+(?:\.\d+)?\b)/g, (m, str, colon, num) => {
    if (str) {
      const inner = str.replace(ID_RE, (mm, id, attr) => (S.doc.entities[id] || id.startsWith("REL_") ? idlink(id, attr || "") : mm));
      return colon ? `<span class="key">${str}</span>${colon}` : `<span class="str">${inner}</span>`;
    }
    return `<span class="num">${num}</span>`;
  });
}

function wireAsk() {
  const form = $("#askForm");
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    S.ask = { q: $("#askQ").value, a: $("#askA").value };
    $("#askOut").innerHTML = `<span class="spin"></span>`;
    try {
      const res = await api(`/api/documents/${S.id}/ask?q=${encodeURIComponent(S.ask.q)}&a=${encodeURIComponent(S.ask.a)}`);
      S.askResult = jsonHTML(res.answer);
    } catch (e) {
      S.askResult = `<span class="err">${esc(e.message)}</span>`;
    }
    $("#askOut").innerHTML = S.askResult;
  });
  $("#askQ").addEventListener("change", (e) => { S.ask.q = e.target.value; });
  $("#askEx").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-q]");
    if (!b) return;
    $("#askQ").value = b.dataset.q;
    $("#askA").value = b.dataset.a;
    form.requestSubmit();
  });
}

/* ------------------------------------------------------------------ selection */
function attrBoxes(eid, key, roleValue = "value") {
  const a = ent(eid) && ent(eid).attributes[key];
  if (!a || !a.page) return [];
  const out = [];
  if (a.bbox) out.push({ page: a.page, bbox: a.bbox, role: key === "signature" ? "signature" : roleValue });
  if (a.label_bbox && a.extraction_method !== "section_heading") out.push({ page: a.page, bbox: a.label_bbox, role: "label" });
  if (a.extraction_method === "section_heading" && a.bbox) out[0].role = "heading";
  return out;
}

function sectionHeading(e) {
  const s = S.doc.sections.find((x) => x.section_id === e.section_id);
  return s ? [{ page: s.heading_page || s.page, bbox: s.heading_bbox, role: "heading" }] : [];
}

function attrTrace(eid, key) {
  const a = ent(eid).attributes[key];
  const st = `<span class="badge ${a.status}">${ATTR_STATUS[a.status] || a.status}</span>`;
  let h = `<b>${esc(eid)}.${esc(key)}</b> = <b>${esc(fmtVal(a.value))}</b> · printed label “${esc(a.field_label || "")}” · page ${a.page ?? "—"} · ${esc(a.extraction_method)} · confidence ${a.confidence.toFixed(2)} · ${st}`;
  if (a.raw && a.raw !== fmtVal(a.value)) h += ` · as printed “${esc(a.raw)}”`;
  for (const n of a.notes || []) h += `<span class="warn">⚠ ${esc(n)}</span>`;
  return h;
}

function relTrace(r) {
  const s = ent(r.subject), o = ent(r.object);
  let h = `<b>${esc(r.relationship_id)}</b>: ${esc(r.subject)} (${esc(s ? s.label : "")}) <b>${esc(r.predicate)}</b> ${esc(r.object)} (${esc(o ? o.label : "")}) · <span class="badge ${r.support}">${r.support}</span> · conf ${r.confidence.toFixed(2)}<br>${esc(r.basis)}`;
  for (const w of r.warnings) h += `<span class="warn">⚠ ${esc(w)}</span>`;
  return h;
}

function compute(sel) {
  const d = S.doc;
  if (!sel) return { boxes: [], refs: [], info: "" };
  if (sel.kind === "attr") {
    return { boxes: attrBoxes(sel.eid, sel.key), refs: [`${sel.eid}.${sel.key}`], info: attrTrace(sel.eid, sel.key) };
  }
  if (sel.kind === "ent") {
    const e = ent(sel.eid);
    if (!e) return { boxes: [], refs: [], info: "" };
    const boxes = Object.keys(e.attributes).flatMap((k) => attrBoxes(e.id, k).filter((b) => b.role !== "label"));
    return {
      boxes: [...sectionHeading(e), ...boxes], refs: Object.keys(e.attributes).map((k) => `${e.id}.${k}`),
      info: `<b>${esc(e.id)}</b> ${esc(e.type_name || e.type)} <b>${esc(e.label)}</b> · ${esc(whereText(e))} · ${Object.keys(e.attributes).length} traced values`,
    };
  }
  if (sel.kind === "rel") {
    const r = d.relationships.find((x) => x.relationship_id === sel.id);
    if (!r) return { boxes: [], refs: [], info: "" };
    const refs = [];
    for (const id of [r.subject, r.object]) {
      const e = ent(id);
      if (e && e.type !== "Patient") refs.push(...Object.keys(e.attributes).map((k) => `${id}.${k}`));
    }
    return { boxes: r.evidence.map((ev) => ({ page: ev.page, bbox: ev.bbox, role: ev.role })), refs, info: relTrace(r) };
  }
  if (sel.kind === "rev") {
    const it = d.review_queue.find((x) => x.review_id === sel.id);
    if (!it) return { boxes: [], refs: [], info: "" };
    let inner = { boxes: [], refs: [], info: "" };
    if (it.kind === "attribute") inner = compute({ kind: "attr", eid: it.entity, key: it.attribute });
    else if (it.kind === "relationship") inner = compute({ kind: "rel", id: it.target });
    else if (it.kind === "validation" && ent(it.entity)) inner = compute({ kind: "ent", eid: it.entity });
    else if (it.kind === "ocr") inner = { boxes: [], refs: [], info: "", page: it.page };
    inner.info = `<b>${esc(it.review_id)}</b> · ${esc(it.kind)} · ${linkify(it.reason)}` + (inner.info ? `<br>${inner.info}` : "");
    return inner;
  }
  if (sel.kind === "blk") {
    const b = (d.blocks || []).find((x) => x.block_id === sel.id);
    if (!b) return { boxes: [], refs: [], info: "" };
    const what = { heading: "heading", field: "field", signature: "signature", question: "check-box question", table: "table", text: "text", page_furniture: "running header / footer" }[b.type] || b.type;
    return { boxes: [{ page: b.page, bbox: b.bbox, role: b.type === "heading" || b.type === "page_furniture" ? "heading" : "value" }], refs: [],
      info: `<b>${esc(b.block_id)}</b> · ${esc(what)} · page ${b.page}${b.section ? ` · section ${esc(b.section)}` : ""}` };
  }
  if (sel.kind === "miss") {
    const it = d.missing[sel.idx];
    let boxes = [];
    let refs = [];
    if (it.entity && ent(it.entity)) {
      const e = ent(it.entity);
      boxes = [...sectionHeading(e), ...Object.keys(e.attributes).flatMap((k) => attrBoxes(e.id, k).filter((b) => b.role !== "label"))];
      refs = Object.keys(e.attributes).map((k) => `${e.id}.${k}`);
    } else if (it.bbox) boxes = [{ page: it.page, bbox: it.bbox, role: "heading" }];
    return { boxes, refs, info: `<b>${esc(it.path)}</b> · ${esc(it.label)} — ${esc(it.reason)}` };
  }
  return { boxes: [], refs: [], info: "" };
}

function selKey(sel) {
  if (!sel) return "";
  return { attr: `attr:${sel.eid}:${sel.key}`, ent: `ent:${sel.eid}`, rel: `rel:${sel.id}`, rev: `rev:${sel.id}`, miss: `miss:${sel.idx}`, blk: `blk:${sel.id}` }[sel.kind];
}

function parseSel(key) {
  const [kind, a, b] = key.split(":");
  if (kind === "attr") return { kind, eid: a, key: b };
  if (kind === "ent") return { kind, eid: a };
  if (kind === "miss") return { kind, idx: +a };
  return { kind, id: a };
}

function select(sel, { scrollList = false } = {}) {
  S.sel = sel;
  const c = compute(sel);
  S.boxes = c.boxes;
  S.refs = c.refs;
  S.info = c.info;
  if (S.view === "source") {
    const first = c.boxes.find((b) => b.page) || (c.page ? { page: c.page } : null);
    if (first) S.page = first.page;
  } else {
    const pl = placementsFor(S.refs)[0];
    if (pl) S.page = pl.page;
  }
  markSelection(scrollList);
  renderViewer(true);
}

function markSelection(scroll = false) {
  $$("#tabBody .sel").forEach((el) => el.classList.remove("sel"));
  const key = selKey(S.sel);
  if (!key) return;
  const els = $$(`#tabBody [data-sel="${CSS.escape(key)}"]`);
  els.forEach((el) => el.classList.add("sel"));
  if (scroll && els[0]) els[0].scrollIntoView({ block: "center", behavior: "smooth" });
}

function handleRef(ref) {
  const [id, attr] = ref.split(".");
  if (id.startsWith("REL_")) return select({ kind: "rel", id });
  if (id.startsWith("REV_")) { S.tab = "review"; renderTabs(); renderTab(); return select({ kind: "rev", id }, { scrollList: true }); }
  if (!ent(id)) return;
  if (S.tab !== "entities" && S.tab !== "ask") { S.tab = "entities"; renderTabs(); renderTab(); }
  if (S.tab === "entities") {
    const card = $(`#card-${CSS.escape(id)}`);
    if (card) { card.scrollIntoView({ block: "start", behavior: "smooth" }); card.classList.remove("flash"); void card.offsetWidth; card.classList.add("flash"); }
  }
  if (attr && ent(id).attributes[attr]) select({ kind: "attr", eid: id, key: attr }, { scrollList: S.tab === "entities" });
  else select({ kind: "ent", eid: id });
}

/* ------------------------------------------------------------------ viewer */
function pageCount() {
  if (S.view === "standardized") return S.doc.standardized ? S.doc.standardized.page_count : 0;
  return S.doc.document.page_count;
}

function pageSize(n) {
  if (S.view === "standardized") {
    const ps = S.doc.standardized.page_sizes[n - 1];
    return { w: ps[0], h: ps[1] };
  }
  const p = S.doc.document.pages[n - 1];
  return { w: p.width, h: p.height };
}

function placementsFor(refs) {
  const std = S.doc.standardized;
  if (!std || !refs.length) return [];
  const want = new Set(refs);
  return std.placements.filter((p) => p.ref && want.has(p.ref));
}

function renderViewer(scrollTo = false) {
  const d = S.doc;
  $$(".seg button").forEach((b) => b.classList.toggle("on", b.dataset.view === S.view));
  const n = pageCount();
  const img = $("#pageImg");
  const overlay = $("#overlay");
  if (!n) {
    $("#pageLabel").textContent = "no pages";
    img.removeAttribute("src");
    overlay.innerHTML = "";
    $("#trace").innerHTML = S.view === "standardized" ? "No standardized form for this document." : "This document has no pages.";
    return;
  }
  S.page = Math.min(Math.max(1, S.page), n);
  $("#pageLabel").textContent = `Page ${S.page} / ${n}`;
  $("#prevPage").disabled = S.page <= 1;
  $("#nextPage").disabled = S.page >= n;
  const { w, h } = pageSize(S.page);
  $("#page").style.aspectRatio = `${w} / ${h}`;
  const src = `/api/documents/${d.document.doc_id}/pages/${S.view}/${S.page}.png?v=${encodeURIComponent(d.document.processed_at)}`;
  if (img.getAttribute("src") !== src) img.src = src;
  img.alt = `${S.view} page ${S.page} of ${d.document.filename}`;

  let boxes;
  if (S.view === "source") {
    boxes = S.boxes.filter((b) => b.page === S.page && b.bbox).map((b) => ({ bbox: b.bbox, cls: b.role }));
  } else {
    boxes = placementsFor(S.refs).filter((p) => p.page === S.page).map((p) => ({ bbox: p.bbox, cls: p.status === "withheld" ? "withheld" : "field" }));
  }
  const pad = 1.6;
  overlay.innerHTML = boxes.map((b) => {
    const [x0, y0, x1, y1] = b.bbox;
    const l = ((x0 - pad) / w) * 100, t = ((y0 - pad) / h) * 100;
    const bw = ((x1 - x0 + 2 * pad) / w) * 100, bh = ((y1 - y0 + 2 * pad) / h) * 100;
    return `<div class="hl ${esc(b.cls)} pulse" style="left:${l}%;top:${t}%;width:${bw}%;height:${bh}%"></div>`;
  }).join("");

  let info = S.info || `<span>Click any value, relationship or review item to see where it came from.</span>`;
  if (S.view === "standardized" && S.sel) {
    const pl = placementsFor(S.refs);
    const withheld = pl.filter((p) => p.status === "withheld");
    const filled = pl.filter((p) => p.status === "filled");
    if (filled.length) info += `<br>fills ${filled.length} standardized field(s): ${filled.map((p) => esc(p.field)).join(", ")}`;
    if (withheld.length) info += `<span class="warn">⚠ left blank on the standardized form while awaiting review (${withheld.map((p) => esc(p.field)).join(", ")})</span>`;
    if (!filled.length && !withheld.length) info += `<br>not placed on the standardized form`;
  } else if (S.view === "standardized" && !S.sel && d.standardized) {
    info = `Standardized form <b>${esc(d.standardized.form)}</b> · ${d.standardized.fields_filled} fields filled · ${d.standardized.fields_withheld} withheld while awaiting review. Click a value to see the field it filled.`;
  }
  $("#trace").innerHTML = info;

  if (scrollTo && overlay.firstElementChild) {
    const go = () => {
      const el = overlay.firstElementChild;
      if (!el) return;
      const wrap = $("#pageWrap");
      const top = el.offsetTop + $("#page").offsetTop - wrap.clientHeight / 2 + el.offsetHeight / 2;
      wrap.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
    };
    if (img.complete && img.naturalWidth) requestAnimationFrame(go);
    else img.addEventListener("load", go, { once: true });
  }
}

/* ------------------------------------------------------------------ upload */
async function uploadFiles(fileList) {
  const files = [...fileList].filter((f) => /\.(pdf|png|jpe?g|tiff?)$/i.test(f.name) || f.type === "application/pdf" || f.type.startsWith("image/"));
  if (!files.length) { toast("Only PDF and image files (PNG, JPG, TIFF) can be processed.", true); return; }
  const dz = $("#dropzone");
  let last = null;
  for (const f of files) {
    dz.classList.add("busy");
    dz.innerHTML = `<strong><span class="spin"></span> Processing</strong><span>${esc(f.name)}</span>`;
    const fd = new FormData();
    fd.append("files", f, f.name);
    try {
      const res = await api("/api/documents", { method: "POST", body: fd });
      for (const r of res.documents) {
        if (!r.doc_id) { toast(`${esc(r.filename)}: ${esc(r.error)}`, true); continue; }
        last = r.doc_id;
        const split = r.packet ? ` · <b>separate form ${r.packet.index} of ${r.packet.count}</b>` : "";
        toast(`<b>${esc(r.doc_id)}</b> ${esc(r.filename)} — ${esc(STATUS[r.status] || r.status)}${split}`, r.status === "failed");
      }
    } catch (e) {
      toast(`${esc(f.name)}: ${esc(e.message)}`, true);
    }
  }
  dz.classList.remove("busy");
  dz.innerHTML = `<strong>Drop PDFs or scans here</strong><span>or click to choose · PDF, PNG, JPG, TIFF · each file is processed on its own</span>`;
  if (last) { S.tab = "entities"; await loadDocs(last); }
}

/* ------------------------------------------------------------------ events */
function wire() {
  $("#uploadBtn").addEventListener("click", () => $("#fileInput").click());
  $("#dropzone").addEventListener("click", () => $("#fileInput").click());
  $("#dropzone").addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("#fileInput").click(); } });
  $("#fileInput").addEventListener("change", (e) => { uploadFiles(e.target.files); e.target.value = ""; });

  let depth = 0;
  window.addEventListener("dragenter", (e) => { if ([...(e.dataTransfer?.types || [])].includes("Files")) { depth++; $("#dragmask").classList.add("on"); } });
  window.addEventListener("dragleave", () => { depth = Math.max(0, depth - 1); if (!depth) $("#dragmask").classList.remove("on"); });
  window.addEventListener("dragover", (e) => e.preventDefault());
  window.addEventListener("drop", (e) => { e.preventDefault(); depth = 0; $("#dragmask").classList.remove("on"); if (e.dataTransfer?.files?.length) uploadFiles(e.dataTransfer.files); });

  $("#docList").addEventListener("click", (e) => {
    const b = e.target.closest("[data-doc]");
    if (b && b.dataset.doc !== S.id) openDoc(b.dataset.doc);
  });
  $("#tabs").addEventListener("click", (e) => {
    const b = e.target.closest("[data-tab]");
    if (!b) return;
    S.tab = b.dataset.tab;
    renderTabs();
    renderTab();
    if (S.sel) markSelection(true);
  });
  $("#tabBody").addEventListener("click", (e) => {
    const link = e.target.closest("[data-ref]");
    if (link) { e.stopPropagation(); handleRef(link.dataset.ref); return; }
    const f = e.target.closest("[data-filter]");
    if (f) { S.relFilter = f.dataset.filter; renderTab(); return; }
    const rf = e.target.closest("[data-rfilter]");
    if (rf) { S.revFilter = rf.dataset.rfilter; renderTab(); return; }
    const act = e.target.closest("[data-act]");
    if (act) {
      e.stopPropagation();
      const a = act.dataset.act;
      if (a === "edit") { S.editing = act.dataset.rev; renderTab(); const inp = $("#tabBody .fixval"); if (inp) inp.focus(); return; }
      if (a === "cancel") { S.editing = null; renderTab(); return; }
      if (a === "correct") { const v = $("#tabBody .fixval").value; reviewAct(act.dataset.rev, "correct", v); return; }
      if (a === "reject" && !confirm("Reject this link? It is removed from the result (kept in the audit log).")) return;
      reviewAct(act.dataset.rev, a);
      return;
    }
    if (e.target.closest(".fixval")) return;
    const s = e.target.closest("[data-sel]");
    if (s) select(parseSel(s.dataset.sel));
  });
  $("#trace").addEventListener("click", (e) => {
    const link = e.target.closest("[data-ref]");
    if (link) handleRef(link.dataset.ref);
  });
  $$(".seg button").forEach((b) => b.addEventListener("click", () => {
    if (S.view === b.dataset.view) return;
    S.view = b.dataset.view;
    if (S.view === "standardized") {
      const pl = placementsFor(S.refs)[0];
      S.page = pl ? pl.page : 1;
    } else {
      const first = S.boxes.find((x) => x.page);
      S.page = first ? first.page : 1;
    }
    renderViewer(true);
  }));
  $("#prevPage").addEventListener("click", () => { S.page--; renderViewer(); });
  $("#nextPage").addEventListener("click", () => { S.page++; renderViewer(); });

  $("#delBtn").addEventListener("click", async () => {
    const m = S.doc.document;
    if (!confirm(`Delete ${m.doc_id} (${m.filename})?\nThe uploaded PDF, its JSON and its standardized form are removed.`)) return;
    try {
      await api(`/api/documents/${m.doc_id}`, { method: "DELETE" });
      toast(`<b>${esc(m.doc_id)}</b> deleted`);
      const idx = S.docs.findIndex((d) => d.doc_id === m.doc_id);
      const next = S.docs[idx + 1] || S.docs[idx - 1];
      S.id = null;
      await loadDocs(next ? next.doc_id : null);
    } catch (e) { toast(esc(e.message), true); }
  });
  $("#ocrBtn").addEventListener("click", async () => {
    const btn = $("#ocrBtn");
    btn.disabled = true;
    btn.innerHTML = `<span class="spin"></span> Running OCR`;
    try {
      const r = await api(`/api/documents/${S.id}/reprocess?ocr=1`, { method: "POST" });
      toast(`<b>${esc(r.doc_id)}</b> read with OCR — ${esc(STATUS[r.status] || r.status)}`);
      S.tab = "entities";
      await loadDocs(S.id);
      await openDoc(S.id);
    } catch (e) { toast(esc(e.message), true); }
    btn.disabled = false;
    btn.textContent = "Run OCR";
  });
  $("#truthBtn").addEventListener("click", async () => {
    try {
      const r = await api(`/api/documents/${S.id}/ground-truth`, { method: "POST" });
      toast(`Saved as ground truth: <b>${esc(r.file)}</b>`);
    } catch (e) { toast(esc(e.message), true); }
  });
  window.addEventListener("hashchange", () => {
    const id = decodeURIComponent(location.hash.slice(1));
    if (id && id !== S.id && S.docs.some((d) => d.doc_id === id)) openDoc(id);
  });
}

wire();
loadDocs().catch((e) => toast(esc(e.message), true));
