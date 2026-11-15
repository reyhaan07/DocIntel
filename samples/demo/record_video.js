// Screen-recording style demo of the docintel web app (run the app first:
//   python -m docintel serve --data demo_data --no-seed ; then: node samples/demo/record_video.js out_dir)
// Needs Node.js with Playwright (npm i playwright; npx playwright install chromium).
// The docintel web app: a visible mouse pointer moves to
// each control, clicks (with a ripple), uploads the ten demo documents one by one and
// shows what was read.  Writes the raw video and a JSON list of scene times (captions).
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const URL = process.env.APP || 'http://localhost:8000/';
const REPO = process.env.REPO || path.resolve(__dirname, '..', '..');
const OUT = process.argv[2] || path.join(__dirname, 'raw');

const CURSOR = `
(() => {
  const add = () => {
    if (document.getElementById('__cur')) return;
    const st = document.createElement('style');
    st.textContent = \`
      #__cur{position:fixed;left:0;top:0;width:26px;height:26px;z-index:2147483647;pointer-events:none;
             transform:translate(-3px,-2px);transition:none;filter:drop-shadow(0 1px 2px rgba(0,0,0,.6))}
      .__rip{position:fixed;width:34px;height:34px;margin:-17px 0 0 -17px;border-radius:50%;z-index:2147483646;
             pointer-events:none;border:3px solid rgba(255,214,10,.95);animation:__r .55s ease-out forwards}
      @keyframes __r{from{transform:scale(.3);opacity:1}to{transform:scale(1.6);opacity:0}}\`;
    document.head.appendChild(st);
    const c = document.createElement('div');
    c.id = '__cur';
    c.innerHTML = '<svg width="26" height="26" viewBox="0 0 26 26"><path d="M3 2 L3 21 L8 16 L11.5 24 L15 22.5 L11.5 14.8 L18.5 14.8 Z" fill="white" stroke="black" stroke-width="1.6" stroke-linejoin="round"/></svg>';
    document.body.appendChild(c);
    const pos = window.__curpos || {x: 960, y: 540};
    c.style.left = pos.x + 'px'; c.style.top = pos.y + 'px';
    document.addEventListener('mousemove', (e) => {
      c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px';
      window.__curpos = {x: e.clientX, y: e.clientY};
    }, true);
    document.addEventListener('mousedown', (e) => {
      const r = document.createElement('div');
      r.className = '__rip'; r.style.left = e.clientX + 'px'; r.style.top = e.clientY + 'px';
      document.body.appendChild(r); setTimeout(() => r.remove(), 600);
    }, true);
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', add); else add();
})();`;

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
    ms = ms || Math.min(1100, 350 + d * 0.55);
    const n = Math.max(8, Math.round(ms / 16));
    const sx = cur.x, sy = cur.y;
    // a slight arc, like a hand moving a mouse
    const bend = (Math.random() - 0.5) * Math.min(80, d * 0.15);
    for (let i = 1; i <= n; i++) {
      const u = ease(i / n);
      const off = Math.sin(Math.PI * (i / n)) * bend;
      const nx = sx + (x - sx) * u + off * ((y - sy) / (d || 1));
      const ny = sy + (y - sy) * u - off * ((x - sx) / (d || 1));
      await page.mouse.move(nx, ny);
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
  async function click(loc, opts = {}) {
    await hover(loc, opts.dx ?? 0.5, opts.dy ?? 0.5);
    await pause(140 + Math.random() * 120);
    await page.mouse.down();
    await pause(70);
    await page.mouse.up();
    await pause(opts.after ?? 600);
  }
  async function wheel(over, dy, steps = 6) {
    await hover(over);
    for (let i = 0; i < steps; i++) { await page.mouse.wheel(0, dy / steps); await pause(60); }
    await pause(500);
  }
  const tab = (k) => page.locator(`[data-tab="${k}"]`);
  const fact = (name) => page.locator('.tabbody .blk.bf', { has: page.locator('.lab', { hasText: new RegExp('^' + name + '$') }) }).first();

  async function upload(rel) {
    const file = path.join(REPO, rel);
    const name = path.basename(file);
    const [chooser] = await Promise.all([page.waitForEvent('filechooser'), click(page.locator('#uploadBtn'), { after: 200 })]);
    await pause(900); // as if picking the file in the dialog
    await chooser.setFiles(file);
    await page.waitForFunction((n) => !document.querySelector('#dropzone').classList.contains('busy')
      && [...document.querySelectorAll('.doccard .fname')].some((e) => e.textContent.includes(n))
      && document.querySelector('#hName') && document.querySelector('#hName').textContent.includes(n), name, { timeout: 180000 });
    await pause(1200);
  }
  async function showFacts(names, linger = 1300) {
    await click(tab('document'), { after: 900 });
    for (const n of names) {
      const f = fact(n);
      if (await f.count()) { await click(f, { dx: 0.35, after: linger }); }
    }
  }
  const safe = async (fn) => { try { await fn(); } catch (e) { console.log('  (skipped: ' + e.message.split('\n')[0] + ')'); } };

  // ------------------------------------------------------------------ the recording
  await page.goto(URL);
  await page.mouse.move(cur.x, cur.y);
  await pause(1500);
  scene('docintel - reads any document on your own computer: no AI model, no cloud service');
  await moveTo(1200, 420); await pause(600); await moveTo(1450, 160); await pause(900);

  scene('1  Invoice (PDF): invoice number, date, seller and client blocks, total');
  await upload('samples/demo/01_invoice.pdf');
  await safe(() => showFacts(['invoice number', 'seller', 'buyer', 'total'], 1500));
  await safe(() => wheel(page.locator('#tabBody'), 600));

  scene('2  Receipt photo: tilt levelled, lighting evened, total confirmed by subtotal + tax');
  await upload('samples/demo/02_receipt_photo.jpg');
  await safe(() => showFacts(['merchant', 'subtotal', 'tax', 'total', 'change'], 1300));

  scene('3  Bank statement: account, period, opening and closing balance, every transaction');
  await upload('samples/demo/03_bank_statement.pdf');
  await safe(() => showFacts(['account number', 'opening balance', 'closing balance'], 1300));
  await safe(() => wheel(page.locator('#tabBody'), 700));

  scene('4  Payslip (Word file): converted and read like any page');
  await upload('samples/demo/04_payslip.docx');
  await safe(() => showFacts(['employee name', 'gross pay', 'net pay'], 1300));

  scene('5  Scanned electricity bill (image): read by OCR, every value traced to the scan');
  await upload('samples/demo/05_utility_bill_scan.png');
  await safe(() => showFacts(['account number', 'usage', 'amount due', 'due date'], 1300));

  scene('6  Hospital discharge summary: patient, dates, physician, diagnosis, medications');
  await upload('samples/demo/06_discharge_summary.pdf');
  await safe(() => showFacts(['patient name', 'discharge date', 'diagnosis'], 1300));
  await safe(async () => { await click(tab('entities'), { after: 1200 }); await wheel(page.locator('#tabBody'), 500); });

  scene('7  Scanned prescription: what OCR is unsure of goes to Review - nothing is guessed');
  await upload('samples/demo/07_prescription_scan.pdf');
  await safe(() => showFacts(['patient name', 'prescriber'], 1200));
  await safe(async () => {
    await click(tab('review'), { after: 1500 });
    const item = page.locator('#tabBody [data-sel]').first();
    if (await item.count()) await click(item, { dx: 0.3, after: 1500 });
    const ok = page.locator('#tabBody [data-act="confirm"]').first();
    if (await ok.count()) await click(ok, { after: 1500 });
  });

  scene('8  Purchase order (Excel): fields and the items table');
  await upload('samples/demo/08_purchase_order.xlsx');
  await safe(() => showFacts(['po number', 'vendor', 'total'], 1300));
  await safe(() => wheel(page.locator('#tabBody'), 500));

  scene('9  E-mail about an invoice: invoice number, due date and amount read from the body');
  await upload('samples/demo/09_payment_reminder.eml');
  await safe(() => showFacts(['invoice number', 'due date', 'total'], 1300));

  scene('10  Fillable insurance claim form: every filled box and the ticked check box');
  await upload('samples/demo/10_insurance_claim_form.pdf');
  await safe(() => showFacts(['policy number', 'claim number', 'insured'], 1300));
  await safe(async () => { await click(tab('entities'), { after: 1200 }); await wheel(page.locator('#tabBody'), 500); });

  scene('Patient intake form: 11 sections, entities and how they are related');
  await upload('samples/stress/intake_S_field_value_tables.pdf');
  await safe(async () => {
    const v = page.locator('#tabBody [data-sel^="attr:"]');
    for (const i of [0, 3, 6]) { if (await v.count() > i) await click(v.nth(i), { dx: 0.3, after: 1100 }); }
    await wheel(page.locator('#tabBody'), 900);
    const v2 = page.locator('#tabBody [data-sel^="attr:"]');
    if (await v2.count() > 12) await click(v2.nth(12), { dx: 0.3, after: 1200 });
  });
  await safe(async () => {
    await click(tab('relationships'), { after: 1300 });
    const r = page.locator('#tabBody [data-sel^="rel:"]');
    for (const i of [0, 4, 9]) { if (await r.count() > i) await click(r.nth(i), { dx: 0.3, after: 1300 }); }
  });
  await safe(async () => { await click(tab('validation'), { after: 1800 }); await wheel(page.locator('#tabBody'), 400); });
  await safe(async () => {
    await click(tab('ask'), { after: 1000 });
    const ex = page.locator('#askEx button');
    if (await ex.count()) { await click(ex.first(), { after: 700 }); }
    await click(page.locator('#askForm button[type=submit]'), { after: 2200 });
    if (await ex.count() > 2) { await click(ex.nth(2), { after: 600 }); await click(page.locator('#askForm button[type=submit]'), { after: 2200 }); }
  });

  scene('Every document: download JSON or Markdown, review queue, all on your machine');
  await safe(async () => { await hover(page.locator('#dlJson')); await pause(900); await hover(page.locator('#dlMd')); await pause(900); });
  await safe(async () => {
    const cards = page.locator('.doccard');
    const n = await cards.count();
    for (const i of [n - 1, Math.floor(n / 2), 0]) { if (i >= 0) await click(cards.nth(i), { after: 1300 }); }
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
