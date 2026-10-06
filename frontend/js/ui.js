/**
 * Shared display helpers. Everything that reaches the page goes through textContent / createElement:
 * values read from an uploaded document must never be treated as HTML.
 */
(function (root) {
  'use strict';

  /* One entry per verdict the backend can return. Class names are written out in full on purpose (the stylesheet
     is built by scanning these files). Unknown verdicts fall back to the neutral entry. */
  var TONES = {
    green:  { text: 'text-emerald-400', dot: 'bg-emerald-400', badge: 'border-emerald-500/70 bg-emerald-500/15 shadow-[0_0_15px_rgba(16,185,129,0.3)]', glow: 'bg-emerald-950/20', bar: 'bg-emerald-400' },
    yellow: { text: 'text-yellow-300',  dot: 'bg-yellow-300',  badge: 'border-yellow-500/60 bg-yellow-500/10 shadow-[0_0_15px_rgba(234,179,8,0.2)]', glow: 'bg-yellow-950/20', bar: 'bg-yellow-300' },
    amber:  { text: 'text-amber-400',  dot: 'bg-amber-400',  badge: 'border-amber-600/60 bg-amber-600/15 shadow-[0_0_15px_rgba(217,119,6,0.25)]', glow: 'bg-amber-950/25', bar: 'bg-amber-500' },
    orange: { text: 'text-orange-400', dot: 'bg-orange-400', badge: 'border-orange-600/70 bg-orange-600/15 shadow-[0_0_15px_rgba(234,88,12,0.25)]', glow: 'bg-orange-950/25', bar: 'bg-orange-500' },
    rose:   { text: 'text-rose-400',   dot: 'bg-rose-400',   badge: 'border-rose-600/70 bg-rose-600/15 shadow-[0_0_15px_rgba(225,29,72,0.25)]', glow: 'bg-red-950/25', bar: 'bg-rose-500' },
    sky:    { text: 'text-sky-400',    dot: 'bg-sky-400',    badge: 'border-sky-600/60 bg-sky-600/15 shadow-[0_0_15px_rgba(2,132,199,0.25)]', glow: 'bg-sky-950/25', bar: 'bg-sky-400' },
    slate:  { text: 'text-slate-400',  dot: 'bg-slate-400',  badge: 'border-slate-600/60 bg-slate-800/40', glow: 'bg-slate-900/30', bar: 'bg-slate-400' },
  };
  var VERDICTS = {
    VERIFIED:                          { tone: 'green',  card: 'state-verified',   group: 'verified',   mark: '✓' },
    VERIFIED_WITH_WARNINGS:            { tone: 'yellow', card: 'state-suspicious', group: 'verified',   mark: '!' },
    MATCHES_RECORD_INTEGRITY_CONCERNS: { tone: 'orange', card: 'state-suspicious', group: 'suspicious', mark: '!' },
    MISMATCH:                          { tone: 'rose',   card: 'state-suspicious', group: 'mismatch',   mark: '✕' },
    SUSPICIOUS:                        { tone: 'amber',  card: 'state-suspicious', group: 'suspicious', mark: '!' },
    UNVERIFIABLE:                      { tone: 'slate',  card: '',                 group: 'unverified', mark: '?' },
    RESCAN:                            { tone: 'sky',    card: '',                 group: 'unverified', mark: '↻' },
    INCONCLUSIVE:                      { tone: 'slate',  card: '',                 group: 'unverified', mark: '?' },
  };
  var NEUTRAL = { tone: 'slate', card: '', group: 'unverified', mark: '?' };

  var RECOMMENDATION = {
    VERIFIED: 'The document matches the issuer\'s record. That confirms it is genuine, not that what it says is true or that the applicant is eligible. The decision stays with you.',
    VERIFIED_WITH_WARNINGS: 'The document matches the issuer\'s record, but review the points listed before relying on it.',
    MATCHES_RECORD_INTEGRITY_CONCERNS: 'The content matches the record, but a check on the document itself failed. Do not rely on this copy: ask for the original or confirm with the issuer.',
    MISMATCH: 'A value on the document differs from the issuer\'s record. That can be an edit or a clerical error. Hold the decision and ask for the original or confirm with the issuer.',
    SUSPICIOUS: 'The issuer has no valid record for this document. Hold the decision and escalate to a verification officer.',
    UNVERIFIABLE: 'This could not be decided (see the reasons). Not being able to verify is not the same as fake. Try again later or inspect it manually.',
    RESCAN: 'Nothing was checked. Retake the photo or scan as advised, or upload the original PDF.',
    INCONCLUSIVE: 'The document could not be read reliably, so nothing is claimed about it. Rescan as advised, or upload the original PDF.',
  };
  var INPUT_LABELS = { pdf: 'Digital PDF', scan: 'Photo or scan', scanned_pdf: 'Scanned PDF (read by OCR)' };

  function info(verdict) { return VERDICTS[verdict] || NEUTRAL; }
  function tone(verdict) { return TONES[info(verdict).tone]; }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }
  function byId(id) { return document.getElementById(id); }
  function setText(id, text) { var n = byId(id); if (n) n.textContent = text; return n; }

  function formatBytes(n) {
    if (!n) return '0 B';
    var u = ['B', 'KB', 'MB', 'GB'], i = Math.min(3, Math.floor(Math.log(n) / Math.log(1024)));
    return parseFloat((n / Math.pow(1024, i)).toFixed(1)) + ' ' + u[i];
  }
  function formatWhen(ts) {
    var d = new Date(ts);
    if (!ts || isNaN(d.getTime())) return 'Recently';
    var mins = Math.floor((Date.now() - d.getTime()) / 60000);
    if (mins < 1) return 'Just now';
    var time = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    if (mins < 24 * 60 && d.toDateString() === new Date().toDateString()) return 'Today, ' + time;
    return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' }) + ', ' + time;
  }
  function verdictLabel(cfg, verdict) { return (cfg && cfg.verdict_labels && cfg.verdict_labels[verdict]) || verdict || 'Unknown'; }

  /** A plain-text report of what the check actually found (used by the result page and the history list). */
  function buildReport(cfg, result, entry) {
    var L = [];
    var line = '='.repeat(60);
    var verdict = (result && result.verdict) || (entry && entry.verdict);
    var audit = (result && result.audit) || {};
    L.push(line, 'PRAMANIK: DOCUMENT VERIFICATION REPORT', line);
    if (result && result._fileName) L.push('Document:       ' + result._fileName);
    if (result && result.document_title) L.push('Type:           ' + result.document_title);
    if (result && result.issuer) L.push('Issuer:         ' + result.issuer.name);
    L.push('Result:         ' + verdictLabel(cfg, verdict) + ' (' + verdict + ')');
    if (result && result.risk && result.risk.score !== null && result.risk.score !== undefined) L.push('Risk (triage):  ' + result.risk.score + '/100, ' + ((cfg.risk_labels || {})[result.risk.level] || result.risk.level));
    L.push('Checked at:     ' + new Date(audit.timestamp || (entry && entry.timestamp) || Date.now()).toLocaleString());
    L.push('Officer ID:     ' + (audit.officer_id || (entry && entry.officer_id) || ''));
    L.push('Document hash:  SHA-256 ' + (audit.doc_hash || (entry && entry.doc_hash) || ''));
    if (result) {
      L.push('Input:          ' + (INPUT_LABELS[result.input_type] || result.input_type));
      if (result.checks && result.checks.issuer_lookup) L.push('Issuer answer:  ' + (result.checks.issuer_lookup === 'cache' ? 'reused from a recent check' : 'asked live'));
      L.push('', 'Why:');
      (result.reasons || []).forEach(function (r) { L.push('  - ' + r); });
      (result.signals || []).filter(function (s) { return s.severity !== 'ok'; }).forEach(function (s) { L.push('  - ' + s.detail); });
      if (result.rescan_guidance) L.push('', 'What to do: ' + result.rescan_guidance);
      if (result.fields && result.fields.length) {
        L.push('', 'Fields (' + (result.coverage || '') + '):');
        result.fields.forEach(function (f) {
          L.push('  ' + (f.label || f.field) + ': ' + (f.document || '(not read)') + '   [' + (f.match ? 'matches issuer' : 'issuer: ' + (f.issuer || 'n/a')) + ']');
        });
      }
    } else {
      L.push('', 'Details are only kept in the browser for checks made in the current session. Re-upload the document to see them.');
    }
    L.push('', line, 'This report says whether the document matches the issuer\'s record. It does not say the facts it', 'states are true. Decisions remain with the responsible officer.', line);
    return L.join('\n');
  }
  function download(filename, text) {
    var url = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' }));
    var a = document.createElement('a');
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }
  function safeName(name) { return String(name || 'document').replace(/\.[^/.]+$/, '').replace(/[^A-Za-z0-9_-]+/g, '_').slice(0, 60) || 'document'; }

  root.PramanikUI = {
    TONES: TONES, VERDICTS: VERDICTS, RECOMMENDATION: RECOMMENDATION, INPUT_LABELS: INPUT_LABELS,
    info: info, tone: tone, el: el, byId: byId, setText: setText, formatBytes: formatBytes, formatWhen: formatWhen,
    verdictLabel: verdictLabel, buildReport: buildReport, download: download, safeName: safeName,
  };
})(window);
