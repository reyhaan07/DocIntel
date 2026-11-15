// Screen-recording style demo: start the app from a command window; then for each document,
// open the original in its own program, scroll through it, close it; click Upload files,
// pick it in the Open dialog; then show what docintel read.  The command window, the
// document windows and the Open dialog are drawn inside the page (a headless browser
// cannot film the real ones).
//
//   python -I samples/demo/video/previews.py . samples/demo/video/prev   (needs LibreOffice for the Word preview)
//   python -m docintel serve --data demo_data            (a new folder: the 7 sample forms are read first)
//   node samples/demo/video/record.js out                (Node.js with Playwright)
//   ffmpeg -i out/*.webm -c:v libx264 -crf 21 -pix_fmt yuv420p docintel_demo.mp4
// out/scenes.json holds each scene's start time and caption, for subtitles.
// The command window shows term_lines.txt (the server's own start-up lines); TERM_LINES=file replaces it.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const { CURSOR } = require('./cursor.js');
const { STYLE, ICON, APP } = require('./windows.js');

const URL = process.env.APP || 'http://localhost:8000/';
const PREV = process.env.PREV || path.join(__dirname, 'prev');
const OUT = process.argv[2] || path.join(__dirname, 'out');
const FOLDERS = JSON.parse(fs.readFileSync(path.join(PREV, 'folders.json'), 'utf8'));
const TERM_FILE = process.env.TERM_LINES || path.join(__dirname, 'term_lines.txt');
const TERM_LINES = (fs.existsSync(TERM_FILE) ? fs.readFileSync(TERM_FILE, 'utf8') : '').split('\n').filter((l) => l.trim());
const TERM_STYLE = `
.__term { width: 1180px; height: 640px; background: #0c0c0c; border-radius: 9px; overflow: hidden; display: flex;
  flex-direction: column; box-shadow: 0 24px 70px rgba(0,0,0,.6); }
.__ttb { height: 38px; background: #202020; display: flex; align-items: center; color: #ddd; font-size: 12.5px; }
.__ttab { background: #0c0c0c; height: 38px; display: flex; align-items: center; padding: 0 18px; border-radius: 8px 8px 0 0;
  margin-left: 8px; margin-top: 6px; }
.__tb2 { width: 46px; text-align: center; color: #bbb; }
.__tbody { flex: 1; margin: 0; padding: 14px 18px; color: #cccccc; font: 15px/1.45 "Cascadia Mono", Consolas, "DejaVu Sans Mono", monospace;
  white-space: pre-wrap; overflow: hidden; }`;

function content(row) {
  const p = row.preview;
  if (p.endsWith('.html')) return { html: fs.readFileSync(p, 'utf8') };
  return { src: 'data:image/png;base64,' + fs.readFileSync(p).toString('base64') };
}

// ------------------------------------------------------------------ in-page builders
function pageSetup(style) {
  window.__winStyle = style;
  // each window lives in its own shadow root: none of the app's styles reach it
  window.__host = (id) => {
    const h = document.createElement('div');
    h.id = id; h.style.cssText = 'position:fixed;inset:0;z-index:2147483000';
    const root = h.attachShadow({ mode: 'open' });
    root.innerHTML = `<style>${window.__winStyle}</style>`;
    document.body.appendChild(h);
    return root;
  };
}

function openWindow(a) {
  const root = window.__host('__win');
  const w = document.createElement('div');
  w.className = 'wrap win __show';
  const ribbon = a.app.ribbon ? `<div class="__rib" style="background:${a.app.color}">${a.app.ribbon.map((r, i) =>
    `<span class="${i === 1 ? 'on' : ''}">${r}</span>`).join('')}</div>` : '';
  const tool = a.app.kind === 'pdf' ? `<div class="__tool"><span>☰</span><span>${a.name}</span><span style="flex:1"></span>
    <span class="pg">1</span><span>/ ${a.pages || 1}</span><span style="opacity:.5">|</span><span>−</span><span>100%</span><span>+</span>
    <span style="flex:1"></span><span>⤓</span><span>⎙</span><span>⋮</span></div>` : '';
  const tall = a.app.kind === 'photo' ? ' tall' : '';
  const body = a.html ? `<div class="${a.app.kind === 'xls' ? '' : ''}">${a.html}</div>`
    : `<img class="${a.app.kind === 'photo' ? '' : '__page'}" src="${a.src}">`;
  w.innerHTML = `<div class="__w"><div class="__tb"><span class="ico" style="background:${a.app.color}">${a.icon}</span>
    <span class="t">${a.name} - ${a.app.title}</span><span class="b">—</span><span class="b">▢</span><span class="b x">✕</span></div>
    ${ribbon}${tool}<div class="__body ${a.app.kind}${tall}">${body}</div></div>`;
  root.appendChild(w);
  w.querySelector('.x').addEventListener('mouseenter', (e) => e.target.classList.add('hot'));
}

function closeWindow() {
  const w = document.getElementById('__win');
  if (w) { w.style.transition = 'opacity .15s'; w.style.opacity = '0'; setTimeout(() => w.remove(), 160); }
}

function openDialog(a) {
  const root = window.__host('__dlg');
  const d = document.createElement('div');
  d.className = 'wrap dlg __show';
  d.innerHTML = `<div class="__d"><div class="__tb"><span class="ico" style="background:#e8b130"></span><span class="t">Open</span>
    <span class="b x">✕</span></div>
    <div class="bar"><span class="nav-b">←</span><span class="nav-b">→</span><span class="nav-b">↑</span><span class="nav-b">⟳</span>
      <div class="addr"></div><div class="search">🔍&nbsp; Search</div></div>
    <div class="main"><div class="side"><div>🏠 Home</div><div>🖼 Gallery</div><hr><div>🖥 Desktop</div><div>⬇ Downloads</div>
      <div class="on">📄 Documents</div><div>🖼 Pictures</div><div>🎵 Music</div><div>🎬 Videos</div><hr><div>💻 This PC</div>
      <div>🌐 Network</div></div>
      <div class="list"><div class="hdr"><span>Name</span><span>Date modified</span><span>Type</span><span>Size</span></div>
        <div class="rows"></div></div>
      <div class="prev">Select a file to preview.</div></div>
    <div class="foot"><span>File name:</span><div class="fname"></div>
      <div class="ftype">All supported files (*.pdf;*.jpg;*.png;*.docx;*.xlsx;*.eml…) ⌄</div>
      <div class="btn open">Open</div><div class="btn">Cancel</div></div></div>`;
  root.appendChild(d);
  window.__dlgRender(a);
}

function dialogRender(a) {
  const d = document.getElementById('__dlg').shadowRoot;
  d.querySelector('.addr').innerHTML = '📁 ' + a.crumbs.map((c) => `<span class="crumb" data-crumb="${c}">${c}</span>`)
    .join('<span class="sep">›</span>');
  d.querySelector('.search').innerHTML = `🔍&nbsp; Search ${a.crumbs[a.crumbs.length - 1]}`;
  d.querySelector('.rows').innerHTML = a.rows.map((r) => {
    const [bg, t] = a.icons[r.type] || ['#888', ''];
    const ic = r.folder ? `<span class="fi" style="background:${bg};height:15px;width:20px;border-radius:2px 6px 2px 2px"></span>`
      : `<span class="fi" style="background:${bg}">${t}</span>`;
    return `<div class="row" data-name="${r.name}"><span class="nm">${ic}${r.name}</span><span>${r.date}</span>
      <span>${r.type}</span><span>${r.size}</span></div>`;
  }).join('');
  d.querySelector('.prev').innerHTML = 'Select a file to preview.';
  d.querySelector('.fname').textContent = '';
  d.querySelectorAll('.row, .crumb, .btn.open').forEach((el) => {
    el.addEventListener('mouseenter', () => el.classList.add('hot'));
    el.addEventListener('mouseleave', () => el.classList.remove('hot'));
  });
}

function dialogSelect(a) {
  const d = document.getElementById('__dlg').shadowRoot;
  d.querySelectorAll('.row').forEach((r) => r.classList.toggle('sel', r.dataset.name === a.name));
  d.querySelector('.fname').textContent = a.name;
  const p = d.querySelector('.prev');
  p.innerHTML = a.html ? `<div class="mini">${a.html}</div>` : `<img src="${a.src}">`;
}

function openTerminal() {
  const root = window.__host('__term');
  const d = document.createElement('div');
  d.className = 'wrap __show';
  d.innerHTML = `<div class="__term"><div class="__ttb"><span class="__ttab">⊞&nbsp; Command Prompt</span><span style="flex:1"></span>
    <span class="__tb2">—</span><span class="__tb2">▢</span><span class="__tb2">✕</span></div><pre class="__tbody"></pre></div>`;
  root.appendChild(d);
}

function termWrite(text) {
  const b = document.getElementById('__term').shadowRoot.querySelector('.__tbody');
  b.textContent += text;
}

function closeTerminal() {
  const t = document.getElementById('__term');
  if (t) t.remove();
}

function desktop() {
  document.body.style.margin = '0';
  document.body.style.height = '100vh';
  document.body.style.background = 'radial-gradient(circle at 30% 40%, #2b5876 0%, #1b2a49 45%, #0f1626 100%)';
}

function closeDialog() {
  const d = document.getElementById('__dlg');
  if (d) d.remove();
}

// ------------------------------------------------------------------ the recording
(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    recordVideo: { dir: OUT, size: { width: 1920, height: 1080 } },
  });
  await context.addInitScript(CURSOR);
  const page = await context.newPage();
  const t0 = Date.now();
  const scenes = [];
  const scene = (text) => { scenes.push({ t: (Date.now() - t0) / 1000, text }); console.log(((Date.now() - t0) / 1000).toFixed(1), text); };
  const pause = (ms) => page.waitForTimeout(ms);

  let cur = { x: 960, y: 540 };
  const ease = (u) => (u < 0.5 ? 2 * u * u : 1 - Math.pow(-2 * u + 2, 2) / 2);
  async function moveTo(x, y, ms) {
    const d = Math.hypot(x - cur.x, y - cur.y);
    ms = ms || Math.min(650, 220 + d * 0.33);
    const n = Math.max(8, Math.round(ms / 16));
    const sx = cur.x, sy = cur.y;
    const bend = (Math.random() - 0.5) * Math.min(80, d * 0.15);
    for (let i = 1; i <= n; i++) {
      const u = ease(i / n);
      const off = Math.sin(Math.PI * (i / n)) * bend;
      await page.mouse.move(sx + (x - sx) * u + off * ((y - sy) / (d || 1)), sy + (y - sy) * u - off * ((x - sx) / (d || 1)));
      await page.waitForTimeout(14);
    }
    cur = { x, y };
  }
  async function box(loc) {
    await loc.scrollIntoViewIfNeeded().catch(() => {});
    const b = await loc.boundingBox();
    if (!b) throw new Error('no box');
    return b;
  }
  async function hover(loc, dx = 0.5, dy = 0.5) {
    const b = await box(loc);
    await moveTo(b.x + b.width * dx + (Math.random() - 0.5) * 6, b.y + b.height * dy + (Math.random() - 0.5) * 4);
  }
  async function press(after = 600) {
    await pause(90 + Math.random() * 70);
    await page.mouse.down(); await pause(60); await page.mouse.up();
    await pause(after);
  }
  async function click(loc, opts = {}) {
    await hover(loc, opts.dx ?? 0.5, opts.dy ?? 0.5);
    await press(opts.after ?? 600);
  }
  async function scrollBy(dy, ms = 900) {
    const n = Math.max(6, Math.round(ms / 45));
    for (let i = 0; i < n; i++) { await page.mouse.wheel(0, dy / n); await pause(40); }
  }
  async function wheel(over, dy, steps = 6) {
    await hover(over);
    for (let i = 0; i < steps; i++) { await page.mouse.wheel(0, dy / steps); await pause(60); }
    await pause(500);
  }
  const tab = (k) => page.locator(`[data-tab="${k}"]`);
  const fact = (name) => page.locator('.tabbody .blk.bf', { has: page.locator('.lab', { hasText: new RegExp('^' + name + '$') }) }).first();
  const safe = async (fn) => { try { await fn(); } catch (e) { console.log('  (skipped: ' + e.message.split('\n')[0] + ')'); } };

  // how the program is started: run_windows.bat in a command window, then the browser opens
  await page.goto('about:blank');
  await page.evaluate(desktop);
  await page.evaluate(pageSetup, STYLE + TERM_STYLE);
  await page.mouse.move(cur.x, cur.y);
  await pause(800);
  scene('Starting docintel: double-click run_windows.bat (or ./run_mac_linux.sh) - it sets everything up and opens the browser');
  await page.evaluate(openTerminal);
  await page.evaluate(termWrite, 'Microsoft Windows [Version 10.0.22631]\n(c) Microsoft Corporation. All rights reserved.\n\nD:\\DocIntel>');
  await pause(900);
  for (const ch of 'run_windows.bat') { await page.evaluate(termWrite, ch); await pause(70 + Math.random() * 60); }
  await pause(500);
  await page.evaluate(termWrite, '\n\ndocintel is starting at http://localhost:8000  - close this window to stop it.\n\n');
  await pause(900);
  for (const ln of TERM_LINES) { await page.evaluate(termWrite, ln + '\n'); await pause(ln.startsWith('processing') ? 380 : 600); }
  await pause(1500);
  await page.goto(URL);
  await page.evaluate(pageSetup, STYLE);
  await page.addScriptTag({ content: `window.__dlgRender = ${dialogRender.toString()};` });
  await page.mouse.move(cur.x, cur.y);

  // 1. the original document, in its own program: a look through it
  async function lookThrough(folder, name, glance = 1) {
    const row = FOLDERS[folder].files.find((r) => r.name === name);
    const app = APP[row.type];
    await page.evaluate(openWindow, { name, app, icon: ICON[row.type][1], pages: row.pages, ...content(row) });
    await pause(900);
    const body = page.locator('#__win .__body');
    await hover(body, 0.55, 0.42);
    await pause(700);
    const room = await body.evaluate((el) => el.scrollHeight - el.clientHeight);
    if (room > 40) {
      const down = Math.min(room, row.pages > 1 ? 2200 : 900);
      await scrollBy(down * 0.55, 1000); await pause(900 * glance);
      await moveTo(cur.x - 120, cur.y + 60); await pause(300);
      await scrollBy(down * 0.45, 900); await pause(1100 * glance);
      await scrollBy(-down * 0.6, 900); await pause(600);
      await scrollBy(-down * 0.4, 700); await pause(700);
    } else {
      await moveTo(cur.x - 200, cur.y + 160); await pause(1200 * glance);
      await moveTo(cur.x + 260, cur.y - 120); await pause(900 * glance);
    }
    await click(page.locator('#__win .x'), { after: 120 });
    await page.evaluate(closeWindow);
    await pause(500);
  }

  // 2. Upload files -> Open dialog -> pick the file -> Open
  let lastFolder = 'demo';
  async function upload(folder, name) {
    const row = FOLDERS[folder].files.find((r) => r.name === name);
    const [chooser] = await Promise.all([page.waitForEvent('filechooser'), click(page.locator('#uploadBtn'), { after: 150 })]);
    const f0 = FOLDERS[lastFolder];
    await page.evaluate(openDialog, { crumbs: f0.crumbs, rows: f0.files, icons: ICON });
    await pause(900);
    if (folder !== lastFolder) {
      // up to 'samples', then into the folder
      await click(page.locator('#__dlg .crumb[data-crumb="samples"]'), { after: 200 });
      await page.evaluate((a) => window.__dlgRender(a), { crumbs: FOLDERS.samples.crumbs, rows: FOLDERS.samples.files, icons: ICON });
      await pause(800);
      const fr = page.locator(`#__dlg .row[data-name="${folder}"]`);
      await hover(fr, 0.2); await pause(150);
      await page.mouse.down(); await pause(60); await page.mouse.up(); await pause(90);
      await page.mouse.down(); await pause(60); await page.mouse.up(); await pause(300);
      const f1 = FOLDERS[folder];
      await page.evaluate((a) => window.__dlgRender(a), { crumbs: f1.crumbs, rows: f1.files, icons: ICON });
      await pause(800);
      lastFolder = folder;
    }
    const target = page.locator(`#__dlg .row[data-name="${name}"]`);
    await hover(target, 0.22); await pause(250);
    await press(150);
    await page.evaluate(dialogSelect, { name, ...content(row) });
    await pause(1300);
    await click(page.locator('#__dlg .btn.open'), { after: 120 });
    await page.evaluate(closeDialog);
    await chooser.setFiles(row.path);
    await pause(400);
    await hover(page.locator('#dropzone'), 0.5, 0.45); // the app shows it working on the file
    await page.waitForFunction((n) => !document.querySelector('#dropzone').classList.contains('busy')
      && document.querySelector('#hName') && document.querySelector('#hName').textContent.includes(n), name, { timeout: 180000 });
    await pause(1000);
  }

  async function showFacts(names, linger = 1300) {
    await click(tab('document'), { after: 900 });
    for (const n of names) {
      const f = fact(n);
      if (await f.count()) { await click(f, { dx: 0.35, after: linger }); }
    }
  }

  async function demo(folder, name, caption, after) {
    scene(caption);
    await lookThrough(folder, name);
    await upload(folder, name);
    await safe(after);
  }

  // ------------------------------------------------------------------ script
  await pause(1200);
  scene('docintel - reads any document on your own computer: no AI model, no cloud service (7 sample forms are read on the first start)');
  await moveTo(1250, 430); await pause(500); await moveTo(1500, 200); await pause(700);

  await demo('demo', '01_invoice.pdf', '1  Invoice (PDF): number, date, seller and client blocks, totals', async () => {
    await showFacts(['invoice number', 'seller', 'buyer', 'total'], 1400);
    await wheel(page.locator('#tabBody'), 600);
  });
  await demo('demo', '02_receipt_photo.jpg', '2  Receipt photo: tilt levelled, lighting evened, total checked by subtotal + tax', async () => {
    await showFacts(['merchant', 'subtotal', 'tax', 'total', 'change'], 1200);
  });
  await demo('demo', '03_bank_statement.pdf', '3  Bank statement: account, period, balances, every transaction', async () => {
    await showFacts(['account number', 'opening balance', 'closing balance'], 1200);
    await wheel(page.locator('#tabBody'), 700);
  });
  await demo('demo', '04_payslip.docx', '4  Payslip (Word): converted and read like any page', async () => {
    await showFacts(['employee name', 'gross pay', 'net pay'], 1200);
  });
  await demo('demo', '05_utility_bill_scan.png', '5  Scanned electricity bill: read by OCR, every value traced to the scan', async () => {
    await showFacts(['account number', 'usage', 'amount due', 'due date'], 1200);
  });
  await demo('demo', '06_discharge_summary.pdf', '6  Hospital discharge summary: patient, dates, physician, diagnosis, medications', async () => {
    await showFacts(['patient name', 'discharge date', 'diagnosis'], 1200);
    await click(tab('entities'), { after: 1000 });
    await wheel(page.locator('#tabBody'), 500);
  });
  await demo('demo', '07_prescription_scan.pdf', '7  Scanned prescription: what OCR is unsure of goes to Review - nothing is guessed', async () => {
    await showFacts(['patient name', 'prescriber'], 1100);
    await click(tab('review'), { after: 1400 });
    const item = page.locator('#tabBody [data-sel]').first();
    if (await item.count()) await click(item, { dx: 0.3, after: 1400 });
    const ok = page.locator('#tabBody [data-act="confirm"]').first();
    if (await ok.count()) await click(ok, { after: 1400 });
  });
  await demo('demo', '08_purchase_order.xlsx', '8  Purchase order (Excel): fields and the items table', async () => {
    await showFacts(['po number', 'vendor', 'total'], 1200);
    await wheel(page.locator('#tabBody'), 500);
  });
  await demo('demo', '09_payment_reminder.eml', '9  E-mail about an invoice: invoice number, due date and amount from the body', async () => {
    await showFacts(['invoice number', 'due date', 'total'], 1200);
  });
  await demo('demo', '10_insurance_claim_form.pdf', '10  Fillable insurance claim form: every filled box and the ticked check box', async () => {
    await showFacts(['policy number', 'claim number', 'insured'], 1200);
    await click(tab('entities'), { after: 1000 });
    await wheel(page.locator('#tabBody'), 500);
  });
  await demo('stress', 'intake_S_field_value_tables.pdf', 'Patient intake form, 3 pages: 11 sections, entities and how they relate', async () => {
    const v = page.locator('#tabBody [data-sel^="attr:"]');
    for (const i of [0, 3, 6]) { if (await v.count() > i) await click(v.nth(i), { dx: 0.3, after: 1000 }); }
    await wheel(page.locator('#tabBody'), 900);
    await click(tab('relationships'), { after: 1200 });
    const r = page.locator('#tabBody [data-sel^="rel:"]');
    for (const i of [0, 4, 9]) { if (await r.count() > i) await click(r.nth(i), { dx: 0.3, after: 1200 }); }
    await click(tab('validation'), { after: 1600 });
    await click(tab('ask'), { after: 900 });
    const ex = page.locator('#askEx button');
    if (await ex.count()) { await click(ex.first(), { after: 600 }); }
    await click(page.locator('#askForm button[type=submit]'), { after: 2000 });
  });

  scene('Every result: download as JSON or Markdown - all on your own machine');
  await safe(async () => { await hover(page.locator('#dlJson')); await pause(800); await hover(page.locator('#dlMd')); await pause(800); });
  await safe(async () => {
    const cards = page.locator('.doccard');
    const n = await cards.count();
    for (const i of [n - 1, Math.floor(n / 2), 0]) { if (i >= 0) await click(cards.nth(i), { after: 1200 }); }
  });
  scene('');
  await pause(1500);

  const video = page.video();
  await context.close();
  await browser.close();
  const raw = await video.path();
  fs.writeFileSync(path.join(OUT, 'scenes.json'), JSON.stringify({ video: raw, total: (Date.now() - t0) / 1000, scenes }, null, 1));
  console.log('video', raw);
})();
