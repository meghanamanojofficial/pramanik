// End-to-end test of the real pages against the real running backend (jsdom = a DOM without a screen).
//   1. start the backend + issuer (python run_all.py), with a fresh ledger  2. npm install  3. npm test
// It signs up, fills the forms, uploads documents and reads the pages the way a person's browser would.
// It cannot judge how the pages LOOK; it checks that they WORK and show the right things.
import { JSDOM, VirtualConsole, CookieJar } from 'jsdom';
import { indexedDB } from 'fake-indexeddb';
import { readFileSync, existsSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const BASE = process.env.BASE_URL || 'http://127.0.0.1:8001';
const DOCS = resolve(dirname(fileURLToPath(import.meta.url)), '../../demo_docs');
const jar = new CookieJar();
const results = [];
let pageErrors = [];

function check(name, ok, detail = '') {
  results.push(ok);
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${ok || !detail ? '' : '  (' + detail + ')'}`);
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(fn, ms = 60000, what = 'condition') {
  const end = Date.now() + ms;
  while (Date.now() < end) { try { const v = fn(); if (v) return v; } catch (e) { /* not yet */ } await sleep(60); }
  throw new Error('timed out waiting for ' + what);
}

/* ---- a fetch that behaves like the browser's: cookies, Origin header, FormData from the page's own realm ---- */
async function toNodeBody(body, readBlob) {
  if (body && typeof body.entries === 'function' && body.constructor && body.constructor.name === 'FormData') {
    const fd = new FormData();
    for (const [k, v] of body.entries()) {
      if (typeof v === 'string') fd.append(k, v);
      else fd.append(k, new Blob([Buffer.from(await readBlob(v))], { type: v.type }), v.name);
    }
    return fd;
  }
  return body;
}
async function browserFetch(url, init = {}, origin = BASE, readBlob = null) {
  let target = new URL(url, origin).href;
  for (let hop = 0; hop < 6; hop++) {
    const headers = new Headers(init.headers || {});
    const cookie = jar.getCookieStringSync(target);
    if (cookie) headers.set('cookie', cookie);
    if ((init.method || 'GET') !== 'GET') headers.set('origin', new URL(BASE).origin);
    const res = await fetch(target, { ...init, headers, body: await toNodeBody(init.body, readBlob), redirect: 'manual' });
    for (const c of res.headers.getSetCookie()) jar.setCookieSync(c, target);
    if (res.status >= 300 && res.status < 400 && res.headers.get('location')) {
      target = new URL(res.headers.get('location'), target).href; init = { method: 'GET' }; continue;
    }
    res.finalUrl = target;
    return res;
  }
  throw new Error('too many redirects');
}

/* ---- load a page and run its scripts ---- */
async function openPage(name, carry = {}) {
  const res = await browserFetch(`/app/${name}`);
  const html = await res.text();
  const finalUrl = res.finalUrl;
  const vc = new VirtualConsole();
  vc.on('jsdomError', (e) => { if (!/Not implemented: navigation/.test(e.message)) pageErrors.push(`${name}: ${e.message}`); });
  vc.on('error', (...a) => pageErrors.push(`${name}: console.error ${a.join(' ')}`));
  const dom = new JSDOM(html, { url: finalUrl, runScripts: 'outside-only', pretendToBeVisual: true, virtualConsole: vc });
  const w = dom.window;
  // jsdom has no Blob.arrayBuffer(); real browsers do. Reading through FileReader here keeps the harness honest
  // and leaves the page's own code to use its FileReader fallback.
  const readBlob = (blob) => new Promise((res, rej) => { const fr = new w.FileReader(); fr.onload = () => res(fr.result); fr.onerror = () => rej(fr.error); fr.readAsArrayBuffer(blob); });
  w.fetch = (u, init) => browserFetch(new URL(u, finalUrl).href, init || {}, BASE, readBlob);
  w.indexedDB = indexedDB;
  w.navs = [];
  w.__nav = (u) => { w.navs.push(new URL(u, finalUrl).pathname.replace(/^\/app\//, '')); };
  for (const [k, v] of Object.entries(carry)) w.sessionStorage.setItem(k, v);
  const noStyle = /<script[^>]*>[\s\S]*?<\/script>/i.test(html.replace(/<script[^>]*src=[^>]*><\/script>/gi, ''));
  w.document.__inlineScript = noStyle;
  const srcs = [...w.document.querySelectorAll('script[src]')].map((s) => s.getAttribute('src'));
  w.srcs = srcs;
  for (const src of srcs) {
    const js = await (await browserFetch(new URL(src, finalUrl).href)).text();
    // test-only: jsdom cannot navigate, so record where the page tried to go instead
    w.eval(js.replace(/\blocation\.replace\(/g, '__nav(').replace(/\blocation\.href\s*=\s*([^;]+);/g, '__nav($1);'));
  }
  w.finalUrl = finalUrl;
  return w;
}
const store = (w) => Object.fromEntries(Array.from({ length: w.sessionStorage.length }, (_, i) => { const k = w.sessionStorage.key(i); return [k, w.sessionStorage.getItem(k)]; }));
const $ = (w, sel) => w.document.querySelector(sel);
const text = (w, sel) => ($(w, sel) ? $(w, sel).textContent : null);

async function uploadViaDashboard(carry, file, caseId, opts = {}) {
  const w = await openPage('maindash.html', carry);
  await until(() => text(w, '#userName') !== '…', 15000, 'dashboard to load');
  const input = $(w, '#realFileInput');
  w.document.querySelector('#caseId').value = caseId;
  if (opts.fresh) w.document.querySelector('#freshCheck').checked = true;
  const f = new w.File([readFileSync(file.path)], file.name, { type: file.type });
  Object.defineProperty(input, 'files', { value: [f], configurable: true });
  input.dispatchEvent(new w.Event('change'));
  if (opts.expectBlocked) { await sleep(600); return { w, carry: store(w) }; }   // nothing should happen
  await until(() => w.navs.includes('analysing.html') || /Unsupported|large|empty|Could not/i.test(text(w, '#liveStatusScan') || ''), 15000, 'upload to start');
  return { w, carry: store(w) };
}
async function runAnalysing(carry) {
  const w = await openPage('analysing.html', carry);
  await until(() => w.navs.includes('result.html') || !$(w, '#errorCard').classList.contains('hidden'), 90000, 'analysis to finish');
  if (!w.navs.includes('result.html')) throw new Error('analysing page stopped: ' + text(w, '#errorTitle') + ' / ' + text(w, '#errorDetail'));
  return { w, carry: store(w) };
}
async function showResult(carry) {
  const w = await openPage('result.html', carry);
  await until(() => text(w, '#status-badge') !== 'LOADING', 10000, 'result to render');
  return w;
}
const fileOf = (dir, name, type) => ({ path: `${DOCS}/${dir}/${name}`, name, type });
const PDF = (n) => fileOf('pdfs', n, 'application/pdf');
const JPG = (n) => fileOf('scans', n, 'image/jpeg');

/* ======================================================================================== */
async function main() {
  for (const f of ['pdfs/genuine.pdf', 'scans/genuine_clean.jpg', 'pdfs/hostile_name.pdf']) {
    if (!existsSync(`${DOCS}/${f}`)) { console.log(`Missing demo document ${f}. Run: python run_all.py (it creates them).`); process.exit(2); }
  }

  /* -- 1. signed-out visitors get the sign-in page, not the app -- */
  let r = await browserFetch('/app/maindash.html');
  check('signed out: the dashboard is not served, visitor lands on sign-in', r.finalUrl.endsWith('/app/signin.html'), r.finalUrl);
  r = await browserFetch('/verify', { method: 'POST', body: new FormData() });
  check('signed out: /verify refuses (401)', r.status === 401, String(r.status));
  const html = await (await browserFetch('/app/signin.html')).text();
  check('sign-in page: no pre-filled password, no fake "Continue with Google"',
    !/Pramanik2026|value="[^"]*@/.test(html) && !/Continue with Google/i.test(html));
  check('sign-in page: no CDN or Google Fonts requests', !/cdn\.tailwindcss|googleapis|gstatic/.test(html));

  /* -- 2. sign up through the real form -- */
  let w = await openPage('signin.html');
  await until(() => text(w, '#heading') === 'Create your account', 5000, 'sign-up form');
  w.document.querySelector('#email').value = 'officer1@revenue.gov.in';
  w.document.querySelector('#password').value = 'short';
  w.document.querySelector('#signup-form').dispatchEvent(new w.Event('submit', { cancelable: true }));
  await sleep(200);
  check('sign-up: a short password is refused with a message', !$(w, '#password-error').classList.contains('hidden') && w.navs.length === 0);
  w.document.querySelector('#password').value = 'a-long-enough-pass';
  w.document.querySelector('#signup-form').dispatchEvent(new w.Event('submit', { cancelable: true }));
  await until(() => w.navs.length, 8000, 'sign-up to complete');
  check('sign-up: creates the account and moves on to the profile page', w.navs[0] === 'creds.html', w.navs.join());

  r = await browserFetch('/app/maindash.html');
  check('profile incomplete: the dashboard still redirects to the profile page', r.finalUrl.endsWith('/app/creds.html'), r.finalUrl);

  /* -- 3. profile -- */
  w = await openPage('creds.html');
  await until(() => $(w, '#fullName'), 3000);
  await sleep(300);
  check('profile form starts empty (no pre-filled person)', w.document.querySelector('#fullName').value === '' && w.document.querySelector('#officerId').value === '');
  w.document.querySelector('#fullName').value = 'Asha Menon';
  w.document.querySelector('#officerId').value = 'bad id!';
  w.document.querySelector('#creds-form').dispatchEvent(new w.Event('submit', { cancelable: true }));
  await until(() => !$(w, '#formError').classList.contains('hidden'), 5000, 'profile error');
  check('profile: an invalid officer ID is explained, not accepted', /officer ID/i.test(text(w, '#formError')) && w.navs.length === 0);
  w.document.querySelector('#officerId').value = 'OFC-7001';
  check('profile: what was typed survives the late server pre-fill', w.document.querySelector('#fullName').value === 'Asha Menon');
  w.document.querySelector('#creds-form').dispatchEvent(new w.Event('submit', { cancelable: true }));
  await until(() => w.navs.length, 5000, 'profile saved');
  check('profile: saved, then the dashboard opens', w.navs[0] === 'maindash.html');

  /* -- 4. dashboard -- */
  w = await openPage('maindash.html');
  await until(() => text(w, '#userName') !== '…', 15000, 'dashboard');
  check('dashboard: shows the signed-in officer from the server', text(w, '#userName') === 'Asha Menon' && text(w, '#userRoleBadge') === 'OFC-7001');
  const docs = [...w.document.querySelectorAll('#acceptedDocsList li')].map((l) => l.textContent);
  check('dashboard: lists only the documents actually supported (no Aadhaar, PAN...)', docs.length === 1 && /Income Certificate/.test(docs[0]) && !/Aadhaar|PAN|Vehicle/.test(w.document.body.textContent), docs.join(' | '));
  check('dashboard: no fabricated history', w.document.querySelectorAll('.audit-card').length === 0 && !/degree_certificate|experience_letter|trade_licence/.test(w.document.body.textContent));
  check('dashboard: telemetry comes from the server', text(w, '#sysStatus') === 'SYSTEM ONLINE' && /REVENUE/.test(text(w, '#sysIssuer')), text(w, '#sysStatus') + ' / ' + text(w, '#sysIssuer'));
  check('dashboard: accepts images as well as PDFs', /image\/jpeg/.test(w.document.querySelector('#realFileInput').getAttribute('accept')));

  /* -- 5. upload guards -- */
  let up = await uploadViaDashboard({}, PDF('genuine.pdf'), '', { expectBlocked: true });
  check('upload: a case ID is required before anything is sent', up.w.navs.length === 0 && /case ID/i.test(text(up.w, '#toastMessage')));
  up = await uploadViaDashboard({}, { path: `${DOCS}/pdfs/genuine.pdf`, name: 'notes.txt', type: 'text/plain' }, 'CASE-E2E-1', { expectBlocked: false });
  check('upload: an unsupported type is rejected in the page, nothing is sent', up.w.navs.length === 0 && /Unsupported/i.test(text(up.w, '#liveStatusScan')));

  /* -- 6. the full journey for each kind of document -- */
  const journeys = [
    ['genuine PDF', PDF('genuine.pdf'), 'CASE-E2E-A', /^VERIFIED$/, null],
    ['phone photo of the genuine certificate', JPG('genuine_photographed.jpg'), 'CASE-E2E-A', /^VERIFIED$/, null],
    ['edited amount (PDF)', PDF('edited_amount.pdf'), 'CASE-E2E-B', /^MISMATCH$/, null],
    ['painted-over amount (PDF)', PDF('painted_over_amount.pdf'), 'CASE-E2E-C', /^MISMATCH$/, /differs from what is shown/],
    ['forged QR signature (PDF)', PDF('forged_signature.pdf'), 'CASE-E2E-D', /INTEGRITY/, /signature/i],
    ['blurry photo', JPG('genuine_blurry.jpg'), 'CASE-E2E-E', /^RESCAN$/, /blurry/i],
    ['unreadable noisy scan', JPG('unreadable_noise.jpg'), 'CASE-E2E-F', /^INCONCLUSIVE$/, null],
  ];
  let carry = {};
  for (const [label, file, caseId, verdictRe, reasonRe] of journeys) {
    const u = await uploadViaDashboard(carry, file, caseId);
    const a = await runAnalysing(u.carry);
    const resultWin = await showResult(a.carry);
    const badge = text(resultWin, '#status-badge');
    const last = JSON.parse(a.carry.pramanik_last_result);
    let verdictRaw = last.verdict;
    // The ledger may already know this certificate from another test suite that ran first: a reuse notice is then
    // correct. It is the only warning that is tolerated here.
    const onlyReuse = (last.signals || []).filter((s) => s.severity !== 'ok').every((s) => /^duplicate_scan_/.test(s.name));
    if (verdictRaw === 'VERIFIED_WITH_WARNINGS' && onlyReuse) verdictRaw = 'VERIFIED';
    const body = resultWin.document.body.textContent;
    check(`journey: ${label} -> ${verdictRaw}`, verdictRe.test(verdictRaw) && badge.length > 0, `${verdictRaw} / ${badge}`);
    if (reasonRe) check(`journey: ${label}: the explanation is shown`, reasonRe.test(body), body.slice(0, 120));
    if (label === 'genuine PDF') {
      const fieldsText = text(resultWin, '#extracted-fields-container');
      check('result: real values from the document, with the real issuer name', /INC-0000-0001/.test(fieldsText) && /Sample Holder/.test(fieldsText) && /Revenue Department/.test(fieldsText));
      check('result: risk is shown with its factors', /Risk \d+\/100/.test(text(resultWin, '#risk-box')));
      check('result: no mode-switcher to fake a verdict, no hard-coded claims',
        !resultWin.document.querySelector('[role="tablist"]') && !/OCR: complete|Auth Net|automated provisioning/.test(body));
    }
    if (label === 'blurry photo') {
      check('analysing: a rejected image fails at the image step and later steps are skipped',
        /Image quality/.test(text(a.w, '#step-file .step-status')) && /Skipped/.test(text(a.w, '#step-text .step-status')), text(a.w, '#step-file .step-status'));
    }
    if (label.startsWith('phone photo')) {
      check('result: a photo shows per-value OCR confidence', /read with \d+% confidence/.test(text(resultWin, '#extracted-fields-container')));
    }
    carry = a.carry;
    carry = { ...carry }; delete carry.pramanik_pending_meta;
  }

  /* -- 7. hostile document: its text must never become markup -- */
  const hu = await uploadViaDashboard(carry, PDF('hostile_name.pdf'), 'CASE-E2E-X');
  const ha = await runAnalysing(hu.carry);
  const hw = await showResult(ha.carry);
  const holder = text(hw, '#extracted-fields-container');
  check('XSS: markup in a document field is shown as plain text', /<img src=x/.test(holder), holder.slice(0, 160));
  check('XSS: no element was injected and no script ran', hw.document.querySelectorAll('#extracted-fields-container img, #extracted-fields-container b, #evidence-list img').length === 0 && !hw.__pwned);

  /* -- 8. history comes from the server and the report is real -- */
  const dash = await openPage('maindash.html', carry);
  await until(() => text(dash, '#userName') !== '…', 15000);
  dash.document.querySelector('#hamburgerBtn').dispatchEvent(new dash.Event('click'));
  await until(() => dash.document.querySelectorAll('.audit-card').length >= 5, 8000, 'history to load');
  const cards = [...dash.document.querySelectorAll('.audit-card')].map((c) => c.textContent);
  check('history: shows this officer\'s real checks with readable verdicts', cards.length >= 8 && cards.some((c) => /Verified/.test(c)) && cards.some((c) => /Rescan needed/.test(c)), `${cards.length} cards`);
  check('history: no fabricated entries', !/degree_certificate|experience_letter/.test(dash.document.body.textContent));
  let downloaded = null;
  dash.URL.createObjectURL = (b) => { downloaded = b; return 'blob:x'; };
  dash.URL.revokeObjectURL = () => {};
  dash.HTMLAnchorElement.prototype.click = function () {};
  const reportBtn = [...dash.document.querySelectorAll('.audit-card button')][0];
  reportBtn.dispatchEvent(new dash.Event('click', { bubbles: true }));
  await sleep(100);
  const report = downloaded ? await new Promise((res) => { const fr = new dash.FileReader(); fr.onload = () => res(fr.result); fr.readAsText(downloaded); }) : '';
  check('report: built from the real result (verdict, hash, officer), not a template', /Result:/.test(report) && /Document hash:  SHA-256 [0-9a-f]{64}/.test(report) && /OFC-7001/.test(report) && !/Cryptographically validated/.test(report), report.slice(0, 200));

  /* -- 9. a result page opened with nothing to show must not invent one -- */
  const empty = await openPage('result.html', {});
  await until(() => text(empty, '#status-badge') !== 'LOADING', 8000);
  check('result: with no result it says so (no fake Verified card)', text(empty, '#status-badge') === 'NO RESULT' && !/Meghana|INC-2026-0412/.test(empty.document.body.textContent));

  /* -- 10. sign out really ends the session -- */
  const out = await openPage('maindash.html', carry);
  await until(() => text(out, '#userName') !== '…', 15000);
  out.document.querySelector('#floatingLogoutBtn').dispatchEvent(new out.Event('click'));
  await until(() => out.navs.includes('signin.html'), 8000, 'sign-out');
  check('sign-out: browser storage is wiped', out.sessionStorage.length === 0);
  r = await browserFetch('/api/auth/me');
  check('sign-out: the server no longer accepts the old session', r.status === 401, String(r.status));

  check('no script errors on any page', pageErrors.length === 0, pageErrors.slice(0, 3).join(' | '));
  const failed = results.filter((x) => !x).length;
  console.log(`\n${results.length - failed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}
main().catch((e) => { console.error('TEST RUN FAILED:', e.stack || e); process.exit(1); });
