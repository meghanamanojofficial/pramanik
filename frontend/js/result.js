(function () {
  'use strict';
  var API = window.PramanikAPI, UI = window.PramanikUI, $ = UI.byId, el = UI.el;
  var cfg = null, current = null;

  function iconRow(icon, text, toneClass) {
    var li = el('li', 'flex items-start gap-3 ' + toneClass);
    li.appendChild(el('span', 'font-bold select-none', icon));
    li.appendChild(el('span', null, text));
    return li;
  }

  function renderEmpty() {
    $('flashcard-border').className = 'glare-card-wrapper';
    var b = $('status-badge'); b.textContent = 'NO RESULT';
    b.className = 'inline-flex items-center px-4 py-1.5 rounded-full text-xs font-bold tracking-wider text-white border ' + UI.TONES.slate.badge + ' uppercase';
    $('status-subtitle').textContent = 'There is no result to show. Upload a document from the dashboard.';
    $('evidence-count').textContent = '0 CHECKS';
    $('extracted-fields-badge').textContent = '—';
    ['issuer-meta-text', 'issuer-match-text', 'forensics-text', 'audit-hashes-text'].forEach(function (id) { $(id).textContent = '—'; });
    $('recommendation-text').textContent = '';
    $('downloadBtn').classList.add('hidden');
  }

  function render(res) {
    current = res;
    var verdict = res.verdict, vi = UI.info(verdict), tone = UI.tone(verdict);
    var fields = Array.isArray(res.fields) ? res.fields : [], checks = res.checks || {}, audit = res.audit || {};
    var reasons = Array.isArray(res.reasons) ? res.reasons : [], signals = Array.isArray(res.signals) ? res.signals : [];

    /* header */
    $('flashcard-border').className = ('glare-card-wrapper ' + vi.card).trim();
    var badge = $('status-badge');
    badge.textContent = UI.verdictLabel(cfg, verdict).toUpperCase();
    badge.className = 'inline-flex items-center px-4 py-1.5 rounded-full text-xs font-bold tracking-wider text-white border uppercase ' + tone.badge;
    $('ambient-glow').className = 'fixed top-1/4 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[850px] h-[550px] rounded-full blur-[140px] pointer-events-none transition-all duration-700 ' + tone.glow;
    $('status-subtitle').textContent = res.rescan_guidance || reasons[0] || '';

    /* evidence and checks */
    var list = $('evidence-list'); list.textContent = '';
    var seen = {}, count = 0;
    function add(icon, text, toneClass) {
      if (!text || seen[text]) return;
      seen[text] = true; count++;
      list.appendChild(iconRow(icon, text, toneClass));
    }
    var reasonIcon = vi.group === 'verified' && verdict === 'VERIFIED' ? '✓' : vi.mark;
    var reasonTone = vi.tone === 'green' ? 'text-gray-300' : (vi.tone === 'rose' || vi.tone === 'orange') ? 'text-rose-300 font-medium' : 'text-amber-300';
    reasons.forEach(function (t) { add(reasonIcon, t, reasonTone); });
    signals.forEach(function (s) {
      if (s.severity === 'fail' || s.severity === 'strong') add('✕', s.detail, 'text-rose-300 font-medium');
      else if (s.severity === 'weak') add('!', s.detail, 'text-amber-300');
      else add('✓', s.detail, 'text-gray-300');
    });
    if (checks.qr_consistency === 'pass') add('✓', 'The QR code matches the printed certificate number.', 'text-gray-300');
    if (checks.qr_consistency === 'fail') add('✕', 'The QR code number differs from the printed certificate number.', 'text-rose-300 font-medium');
    if (res.coverage) add('ℹ', res.coverage, 'text-gray-400');
    $('evidence-count').textContent = count + (count === 1 ? ' CHECK' : ' CHECKS');

    /* fields */
    var box = $('extracted-fields-container'); box.textContent = '';
    $('extracted-fields-badge').textContent = (res.document_title || 'Not recognised').toUpperCase();
    function row(label, valueNode) {
      var r = el('div', 'data-row py-2.5 flex items-start justify-between gap-4');
      r.appendChild(el('span', 'text-gray-500 font-sans', label)); r.appendChild(valueNode); return r;
    }
    box.appendChild(row('Issuing Authority', el('span', 'text-right text-gray-100 font-medium text-[13px] tracking-tight', res.issuer ? res.issuer.name : '—')));
    if (!fields.length) box.appendChild(row('Fields', el('span', 'text-right text-gray-400', 'None were compared')));
    fields.forEach(function (f) {
      var v = el('span', 'text-right ' + (f.match ? 'text-gray-200' : 'text-rose-400 font-semibold'));
      v.appendChild(document.createTextNode(f.document || '—'));
      if (!f.match && f.issuer) v.appendChild(el('span', 'block text-xs text-rose-400 font-normal', '(' + f.issuer + ')'));
      if (typeof f.confidence === 'number') v.appendChild(el('span', 'block text-[10px] font-normal ' + (f.confidence < 60 ? 'text-amber-400' : 'text-gray-500'), 'read with ' + f.confidence + '% confidence'));
      box.appendChild(row(f.label || f.field, v));
    });

    /* issuer card */
    var when = audit.timestamp ? new Date(audit.timestamp).toLocaleString() : 'recently';
    var source = checks.issuer_lookup === 'cache' ? 'saved answer from a recent check' : checks.issuer_lookup === 'live' ? 'asked live' : 'not asked';
    $('issuer-meta-text').textContent = 'Route: ' + (res.route || 'none') + ' · ' + source + ' · ' + when;
    var matched = fields.filter(function (f) { return f.match; }).map(function (f) { return f.label || f.field; });
    var wrong = fields.filter(function (f) { return !f.match; }).map(function (f) { return f.label || f.field; });
    var im = $('issuer-match-text'); im.textContent = '';
    if (!fields.length) im.textContent = 'No fields were compared with the issuer.';
    else {
      im.appendChild(document.createTextNode('Match: ' + (matched.join(', ') || 'none')));
      if (wrong.length) { im.appendChild(document.createTextNode(' · ')); im.appendChild(el('span', 'text-rose-400 font-medium', 'Differs or not confirmed: ' + wrong.join(', '))); }
    }

    /* integrity checks and risk */
    var CHECK_NAMES = { qr_consistency: 'QR', digital_signature: 'QR signature', issuer_lookup: 'Issuer answer', reuse_check: 'Reuse', quality_gate: 'Image quality', ocr_confidence: 'OCR', pdf_metadata: null };
    var parts = ['Input: ' + (UI.INPUT_LABELS[res.input_type] || res.input_type || '—')];
    Object.keys(checks).forEach(function (k) {
      if (CHECK_NAMES[k] === null || checks[k] === 'not_applicable') return;
      parts.push((CHECK_NAMES[k] || k.replace(/_/g, ' ')) + ': ' + String(checks[k]).replace(/_/g, ' '));
    });
    $('forensics-text').textContent = parts.join(' · ');

    var rb = $('risk-box'); rb.textContent = '';
    var risk = res.risk;
    if (risk) {
      var d = el('details', 'rounded-lg border border-white/10 px-3 py-2 text-xs');
      var sum = el('summary', 'cursor-pointer text-gray-200 font-medium');
      var label = (cfg.risk_labels || {})[risk.level] || risk.level;
      sum.textContent = (risk.score === null || risk.score === undefined) ? 'Risk: ' + label : 'Risk ' + risk.score + '/100 · ' + label;
      d.appendChild(sum);
      if ((risk.factors || []).length) {
        var ul = el('ul', 'mt-2 space-y-1.5');
        risk.factors.forEach(function (f) {
          var li = el('li', 'flex gap-2 text-gray-400');
          li.appendChild(el('b', 'w-9 shrink-0 text-right font-mono ' + (f.points > 0 ? 'text-rose-400' : 'text-emerald-400'), (f.points > 0 ? '+' : '') + f.points));
          li.appendChild(el('span', null, f.detail));
          ul.appendChild(li);
        });
        d.appendChild(ul);
      }
      d.appendChild(el('p', 'mt-2 text-[11px] text-gray-500', 'A triage aid built from the checks listed here. It does not change the result and is not proof of anything.'));
      rb.appendChild(d);
    }

    /* recommendation and audit line */
    var rec = $('recommendation-text'); rec.textContent = '';
    rec.appendChild(el('span', 'text-white font-semibold', 'Suggested next step: '));
    rec.appendChild(document.createTextNode(UI.RECOMMENDATION[verdict] || 'Review the reasons above before deciding.'));
    $('audit-hashes-text').textContent = 'SHA-256 [' + (audit.doc_hash ? audit.doc_hash.slice(0, 32) + '...' : 'n/a') + '] · Officer [' + (audit.officer_id || 'n/a') + ']';
  }

  $('closeModalBtn').addEventListener('click', function () { location.href = 'maindash.html'; });
  $('nextBtn').addEventListener('click', function () { location.href = 'maindash.html'; });
  $('downloadBtn').addEventListener('click', function () {
    if (!current) return;
    UI.download('PRAMANIK_report_' + UI.safeName(current._fileName) + '_' + ((current.audit && current.audit.doc_hash) || '').slice(0, 8) + '.txt', UI.buildReport(cfg, current, null));
  });

  (async function init() {
    await API.requireSession(true);
    cfg = await API.fetchUiConfig();
    var res = API.getLastResult();
    if (res) render(res); else renderEmpty();
  })();
})();
