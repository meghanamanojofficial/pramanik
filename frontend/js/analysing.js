(function () {
  'use strict';
  var API = window.PramanikAPI, UI = window.PramanikUI, $ = UI.byId;
  var cfg = null;

  var ROW = { active: 'flex items-center justify-between text-slate-100 transition-all step-row', done: 'flex items-center justify-between text-slate-300 transition-all step-row',
              failed: 'flex items-center justify-between text-rose-300 transition-all step-row', skipped: 'flex items-center justify-between text-slate-500 transition-all step-row' };
  var IND = {
    active: 'w-5 h-5 rounded-full border-2 border-indigo-400 bg-indigo-500/20 flex items-center justify-center shrink-0 step-indicator animate-pulse',
    done: 'w-5 h-5 rounded-full bg-emerald-500 flex items-center justify-center shrink-0 step-indicator shadow-[0_0_8px_rgba(16,185,129,0.4)]',
    failed: 'w-5 h-5 rounded-full bg-rose-600 flex items-center justify-center shrink-0 step-indicator',
    skipped: 'w-5 h-5 rounded-full border border-slate-600 flex items-center justify-center shrink-0 step-indicator',
  };
  var TXT = { active: 'text-xs font-mono step-status text-indigo-400', done: 'text-xs font-mono step-status text-emerald-400',
              failed: 'text-xs font-mono step-status text-rose-400', skipped: 'text-xs font-mono step-status text-slate-500' };
  var MARK = { done: '✓', failed: '✕', skipped: '–' };

  function step(id, state, text) {
    var row = $(id); if (!row) return;
    var ind = row.querySelector('.step-indicator'), st = row.querySelector('.step-status');
    row.className = ROW[state]; ind.className = IND[state]; ind.textContent = '';
    if (state === 'active') ind.appendChild(UI.el('span', 'w-2 h-2 rounded-full bg-indigo-400'));
    else ind.appendChild(UI.el('span', 'text-white text-[11px] font-bold', MARK[state]));
    if (st) { st.textContent = text; st.className = TXT[state]; }
  }
  function delay(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  function showError(title, detail) {
    $('pipelineHeading').textContent = 'Check interrupted';
    $('pipelineSubheading').textContent = 'The check could not be completed.';
    $('errorTitle').textContent = title; $('errorDetail').textContent = detail;
    $('errorCard').classList.remove('hidden');
  }

  /** What the file's first bytes say it is, so the first step reports something real. */
  async function sniff(blob) {
    var b = new Uint8Array(await API.readBuffer(blob.slice(0, 12)));
    var s = String.fromCharCode.apply(null, b);
    if (s.indexOf('%PDF') === 0) return 'PDF';
    if (b[0] === 0xFF && b[1] === 0xD8 && b[2] === 0xFF) return 'JPEG photo';
    if (s.indexOf('\x89PNG') === 0) return 'PNG image';
    if (s.slice(0, 4) === 'RIFF' && s.slice(8, 12) === 'WEBP') return 'WebP image';
    return null;
  }

  function paintBadge(verdict) {
    var t = UI.tone(verdict), badge = $('previewBadge');
    badge.textContent = '';
    badge.appendChild(UI.el('span', 'w-1.5 h-1.5 rounded-full ' + t.dot));
    badge.appendChild(document.createTextNode(' ' + UI.verdictLabel(cfg, verdict)));
    badge.className = 'inline-flex items-center gap-1 font-medium ' + t.text;
    var vs = $('previewVerifiedStatus');
    vs.textContent = UI.verdictLabel(cfg, verdict).toUpperCase();
    vs.className = 'text-[9px] font-mono mt-1 uppercase tracking-wider font-semibold ' + t.text;
  }

  /** Set every step from what actually happened. */
  async function showOutcome(r) {
    var scanned = r.input_type !== 'pdf', checks = r.checks || {}, rows = r.fields || [];
    var seq = [];
    if (r.verdict === 'RESCAN') {
      seq = [['step-file', 'failed', 'Image quality'], ['step-text', 'skipped', 'Skipped'], ['step-qr', 'skipped', 'Skipped'],
             ['step-fields', 'skipped', 'Skipped'], ['step-issuer', 'skipped', 'Not asked']];
    } else {
      seq.push(['step-file', 'done', scanned ? 'Image accepted' : 'PDF accepted']);
      seq.push(['step-text', 'done', r.input_type === 'pdf' ? 'Text layer' : 'OCR']);
      var sig = checks.digital_signature;
      if (sig === 'invalid') seq.push(['step-qr', 'failed', 'Signature invalid']);
      else if (checks.qr_consistency === 'fail') seq.push(['step-qr', 'failed', 'QR differs']);
      else if (sig === 'valid') seq.push(['step-qr', 'done', 'Signed QR valid']);
      else if (checks.qr_consistency === 'pass') seq.push(['step-qr', 'done', 'QR matches']);
      else seq.push(['step-qr', 'done', 'No QR to compare']);
      if (r.verdict === 'INCONCLUSIVE') {
        seq.push(['step-fields', 'failed', 'Not reliable'], ['step-issuer', 'skipped', 'Not asked']);
      } else if (!r.document_type) {
        seq.push(['step-fields', 'failed', 'Not recognised'], ['step-issuer', 'skipped', 'Not asked']);
      } else {
        seq.push(['step-fields', 'done', rows.length + ' fields']);
        seq.push(r.route === 'none' ? ['step-issuer', 'failed', 'Unavailable']
                                    : ['step-issuer', 'done', checks.issuer_lookup === 'cache' ? 'Saved answer' : 'Answered']);
      }
    }
    seq.push(['step-decision', 'done', UI.verdictLabel(cfg, r.verdict)]);
    for (var i = 0; i < seq.length; i++) { step(seq[i][0], seq[i][1], seq[i][2]); await delay(140); }
  }

  async function run(meta, blob) {
    $('errorCard').classList.add('hidden');
    $('pipelineHeading').textContent = 'Analysing document...';
    ['step-file', 'step-text', 'step-qr', 'step-fields', 'step-issuer', 'step-decision'].forEach(function (id) { step(id, 'skipped', 'Waiting'); });

    step('step-file', 'active', 'Checking');
    var kind = await sniff(blob);
    await delay(150);
    if (!kind) { step('step-file', 'failed', 'Unsupported'); return showError('Unsupported file', 'Use a PDF, or a JPG, PNG or WebP photo or scan.'); }
    step('step-file', 'done', kind);
    step('step-text', 'active', 'Working');   // the server does the rest in one request; no step is claimed until it answers

    var result;
    try {
      result = await API.verifyDocument(blob, { caseId: meta.caseId, purpose: meta.purpose, fresh: meta.fresh, name: meta.name });
    } catch (err) {
      step('step-text', 'failed', 'Stopped');
      return showError('Verification failed', err.message || 'The server could not be reached.');
    }

    var rows = result.fields || [];
    var nameRow = rows.find(function (f) { return f.field === 'holder_name'; });
    var certRow = rows.find(function (f) { return f.field === 'certificate_number'; });
    if (nameRow && nameRow.document) $('previewName').textContent = nameRow.document;
    $('previewDocType').textContent = (result.document_title || 'Document').toUpperCase();
    if (result.issuer) $('previewIssuer').textContent = result.issuer.name;
    $('previewHashStatus').textContent = 'SHA-256 RECORDED';
    $('previewSecureId').textContent = certRow && certRow.document ? 'CERT: ' + certRow.document : 'HASH: ' + ((result.audit && result.audit.doc_hash) || '').slice(0, 10) + '...';
    paintBadge(result.verdict);

    await showOutcome(result);
    $('pipelineHeading').textContent = 'Analysis complete';
    $('pipelineSubheading').textContent = UI.verdictLabel(cfg, result.verdict) + '. Opening the result...';
    await API.clearPendingFile();
    setTimeout(function () { location.href = 'result.html'; }, 600);
  }

  (async function init() {
    await API.requireSession(true);
    cfg = await API.fetchUiConfig();
    var meta = API.getPendingMeta(), blob = await API.getPendingBlob();
    if (!meta || !blob) {
      $('pipelineHeading').textContent = 'No document selected';
      $('pipelineSubheading').textContent = 'Choose a document on the dashboard to begin.';
      showError('No document found', 'No file is waiting to be checked. Go back to the dashboard and upload one.');
      $('retryBtn').classList.add('hidden');
      return;
    }
    $('previewFileName').textContent = meta.name || 'document';
    $('previewFileSize').textContent = UI.formatBytes(meta.size);
    $('previewCaseId').textContent = '#' + (meta.caseId || '');
    $('previewDate').textContent = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    $('retryBtn').addEventListener('click', function () { run(meta, blob); });
    run(meta, blob);
  })();
})();
