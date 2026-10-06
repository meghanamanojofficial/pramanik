/**
 * PRAMANIK front end: talks to the backend on the same origin.
 *
 * - Identity comes from the server session (an HttpOnly cookie). Nothing here invents a user.
 * - The file chosen on the dashboard is kept in IndexedDB so it survives the page change (sessionStorage
 *   would cap it at a few MB, and the last page would silently lose larger photos).
 * - Results hold personal data, so they live in sessionStorage only and everything is wiped on sign-out.
 */
(function (root) {
  'use strict';

  var KEY = {
    LAST: 'pramanik_last_result',
    BY_HASH: 'pramanik_results_by_hash',
    CASE: 'pramanik_case_id',
    PENDING: 'pramanik_pending_meta',
    CONFIG: 'pramanik_ui_config',
  };
  var DB_NAME = 'pramanik', STORE = 'pending';
  var me = null;
  var config = null;

  /* ---------- small helpers ---------- */
  function readJson(storage, key, fallback) {
    try { var raw = storage.getItem(key); return raw ? JSON.parse(raw) : fallback; } catch (e) { return fallback; }
  }
  function writeJson(storage, key, value) {
    try { storage.setItem(key, JSON.stringify(value)); return true; } catch (e) { return false; }
  }

  async function request(path, opts) {
    opts = opts || {};
    var init = { method: opts.method || 'GET', credentials: 'same-origin', headers: {} };
    if (opts.json !== undefined) { init.headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(opts.json); }
    if (opts.form) { init.body = opts.form; }
    var res = await fetch(path, init);
    var data = null;
    try { data = await res.json(); } catch (e) { /* not JSON */ }
    if (!res.ok) {
      var err = new Error((data && data.detail) || ('Server error (HTTP ' + res.status + ')'));
      err.status = res.status;
      throw err;
    }
    return data;
  }

  /* ---------- session ---------- */
  async function getMe(force) {
    if (me && !force) return me;
    try { me = (await request('/api/auth/me')).user; } catch (e) { me = null; if (e.status && e.status !== 401) throw e; }
    return me;
  }

  /** Pages call this first. Sends signed-out visitors to the sign-in page. */
  async function requireSession(needProfile) {
    var user = await getMe();
    if (!user) { root.location.replace('signin.html'); return new Promise(function () {}); }
    if (needProfile !== false && !user.profile_complete) { root.location.replace('creds.html'); return new Promise(function () {}); }
    return user;
  }

  async function signup(email, password, code) { me = (await request('/api/auth/signup', { method: 'POST', json: { email: email, password: password, signup_code: code || '' } })).user; return me; }
  async function login(email, password) { me = (await request('/api/auth/login', { method: 'POST', json: { email: email, password: password } })).user; return me; }
  async function saveProfile(profile) { me = (await request('/api/auth/profile', { method: 'PUT', json: profile })).user; return me; }
  function authOptions() { return request('/api/auth/options'); }

  async function logout() {
    try { await request('/api/auth/logout', { method: 'POST' }); } catch (e) { /* signing out locally anyway */ }
    await clearLocalData();
    me = null;
  }

  async function clearLocalData() {
    try { root.sessionStorage.clear(); } catch (e) {}
    try { Object.keys(root.localStorage).filter(function (k) { return k.indexOf('pramanik') === 0; }).forEach(function (k) { root.localStorage.removeItem(k); }); } catch (e) {}
    await clearPendingFile();
  }

  /* ---------- server settings ---------- */
  async function fetchUiConfig() {
    if (config) return config;
    try { config = await request('/api/ui-config'); writeJson(root.sessionStorage, KEY.CONFIG, config); return config; } catch (e) { /* fall through */ }
    config = readJson(root.sessionStorage, KEY.CONFIG, null) || {
      app_title: 'Document verification', max_upload_mb: 10, accept: ['application/pdf'], purposes: ['Benefit application'],
      verdict_labels: {}, risk_labels: {}, document_types: [], issuers: [],
    };
    return config;
  }

  /* ---------- the chosen file (IndexedDB) ---------- */
  /** Blob.arrayBuffer() where it exists; FileReader on older browsers (Safari before 14). */
  function readBuffer(blob) {
    if (typeof blob.arrayBuffer === 'function') return blob.arrayBuffer();
    return new Promise(function (resolve, reject) {
      var r = new FileReader();
      r.onload = function () { resolve(r.result); };
      r.onerror = function () { reject(r.error || new Error('The file could not be read.')); };
      r.readAsArrayBuffer(blob);
    });
  }

  function openDb() {
    return new Promise(function (resolve, reject) {
      if (!root.indexedDB) return reject(new Error('This browser cannot hold the file between pages.'));
      var req = root.indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = function () { req.result.createObjectStore(STORE); };
      req.onsuccess = function () { resolve(req.result); };
      req.onerror = function () { reject(req.error || new Error('Could not open local storage.')); };
    });
  }
  function idb(mode, fn) {
    return openDb().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(STORE, mode), out = fn(tx.objectStore(STORE));
        tx.oncomplete = function () { db.close(); resolve(out && out.result); };
        tx.onerror = tx.onabort = function () { db.close(); reject(tx.error || new Error('Local storage failed.')); };
      });
    });
  }

  async function setPendingFile(file, meta) {
    // an ArrayBuffer, not the Blob itself: some Safari versions lose Blobs kept in IndexedDB
    var record = { buffer: await readBuffer(file), name: file.name, type: file.type, size: file.size };
    await idb('readwrite', function (s) { return s.put(record, 'file'); });
    var m = Object.assign({ name: file.name, size: file.size, type: file.type, at: new Date().toISOString() }, meta || {});
    writeJson(root.sessionStorage, KEY.PENDING, m);
    return m;
  }
  function getPendingMeta() { return readJson(root.sessionStorage, KEY.PENDING, null); }
  async function getPendingBlob() {
    try {
      var r = await idb('readonly', function (s) { return s.get('file'); });
      return r ? new Blob([r.buffer], { type: r.type }) : null;
    } catch (e) { return null; }
  }
  async function clearPendingFile() {
    try { root.sessionStorage.removeItem(KEY.PENDING); } catch (e) {}
    try { await idb('readwrite', function (s) { return s.delete('file'); }); } catch (e) {}
  }

  /* ---------- case id, results ---------- */
  function getCaseId() { try { return root.sessionStorage.getItem(KEY.CASE) || ''; } catch (e) { return ''; } }
  function setCaseId(v) { try { root.sessionStorage.setItem(KEY.CASE, v); } catch (e) {} }

  function getLastResult() { return readJson(root.sessionStorage, KEY.LAST, null); }
  function setLastResult(result) {
    writeJson(root.sessionStorage, KEY.LAST, result);
    var hash = result && result.audit && result.audit.doc_hash;
    if (hash) {
      var all = readJson(root.sessionStorage, KEY.BY_HASH, {});
      all[hash] = result;
      var keys = Object.keys(all);
      if (keys.length > 20) delete all[keys[0]];
      writeJson(root.sessionStorage, KEY.BY_HASH, all);
    }
  }
  function resultForHash(hash) { return (readJson(root.sessionStorage, KEY.BY_HASH, {}) || {})[hash] || null; }

  /* ---------- checks and history ---------- */
  async function verifyDocument(blob, opts) {
    if (!blob) throw new Error('No document was provided.');
    opts = opts || {};
    var form = new FormData();
    form.append('file', blob, opts.name || blob.name || 'document');
    form.append('case_id', (opts.caseId || '').slice(0, 64));
    form.append('purpose', opts.purpose || '');
    if (opts.fresh) form.append('fresh', '1');
    var result;
    try {
      result = await request('/verify', { method: 'POST', form: form });
    } catch (e) {
      if (e.status === 401) { root.location.replace('signin.html'); return new Promise(function () {}); }
      throw e;
    }
    result._fileName = opts.name || blob.name || '';
    result._fileSize = blob.size || 0;
    setLastResult(result);
    return result;
  }

  async function fetchHistory(limit) {
    return request('/api/history?limit=' + (limit || 50));
  }

  root.PramanikAPI = {
    getMe: getMe, requireSession: requireSession, signup: signup, login: login, logout: logout, saveProfile: saveProfile,
    authOptions: authOptions, fetchUiConfig: fetchUiConfig, readBuffer: readBuffer,
    setPendingFile: setPendingFile, getPendingMeta: getPendingMeta, getPendingBlob: getPendingBlob, clearPendingFile: clearPendingFile,
    getCaseId: getCaseId, setCaseId: setCaseId,
    getLastResult: getLastResult, setLastResult: setLastResult, resultForHash: resultForHash,
    verifyDocument: verifyDocument, fetchHistory: fetchHistory,
  };
})(window);
