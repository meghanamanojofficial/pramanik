(function () {
  'use strict';
  var API = window.PramanikAPI, UI = window.PramanikUI, $ = UI.byId;
  var cfg = null, selectedFile = null, allAudits = [], currentFilter = 'all';

  /* ---------- toast ---------- */
  var toastTimer;
  function toast(message) {
    var t = $('toastNotification'), m = $('toastMessage');
    if (!t || !m) return;
    clearTimeout(toastTimer);
    m.textContent = message;
    t.classList.remove('-translate-y-12', 'opacity-0'); t.classList.add('translate-y-0', 'opacity-100');
    toastTimer = setTimeout(function () { t.classList.remove('translate-y-0', 'opacity-100'); t.classList.add('-translate-y-12', 'opacity-0'); }, 3200);
  }

  /* ---------- drawer ---------- */
  var drawer = $('historyDrawer'), backdrop = $('drawerBackdrop');
  function openDrawer() {
    drawer.classList.remove('translate-x-full'); backdrop.classList.remove('hidden');
    setTimeout(function () { backdrop.classList.remove('opacity-0'); backdrop.classList.add('opacity-100'); }, 10);
    loadAudits();
  }
  function closeDrawer() {
    drawer.classList.add('translate-x-full'); backdrop.classList.remove('opacity-100'); backdrop.classList.add('opacity-0');
    setTimeout(function () { backdrop.classList.add('hidden'); }, 300);
  }
  $('hamburgerBtn').addEventListener('click', openDrawer);
  $('closeDrawerBtn').addEventListener('click', closeDrawer);
  backdrop.addEventListener('click', closeDrawer);

  /* ---------- accepted documents popover ---------- */
  var docsBtn = $('acceptedDocsBtn'), docsModal = $('acceptedDocsModal');
  function toggleDocs(e) {
    if (e) e.stopPropagation();
    if (docsModal.classList.contains('hidden')) {
      docsModal.classList.remove('hidden');
      setTimeout(function () { docsModal.classList.remove('opacity-0', 'scale-95'); docsModal.classList.add('opacity-100', 'scale-100'); }, 10);
    } else {
      docsModal.classList.remove('opacity-100', 'scale-100'); docsModal.classList.add('opacity-0', 'scale-95');
      setTimeout(function () { docsModal.classList.add('hidden'); }, 200);
    }
  }
  docsBtn.addEventListener('click', toggleDocs);
  $('closeAcceptedDocsBtn').addEventListener('click', toggleDocs);
  docsModal.addEventListener('click', function (e) { e.stopPropagation(); });

  /* ---------- upload menu ---------- */
  var trigger = $('uploadDropdownTrigger'), menu = $('uploadMenu'), arrow = $('dropdownArrow');
  function closeMenu() {
    menu.classList.add('scale-95', 'opacity-0'); menu.classList.remove('scale-100', 'opacity-100');
    setTimeout(function () { menu.classList.add('hidden'); }, 150);
    if (arrow) arrow.classList.remove('rotate-180');
  }
  trigger.addEventListener('click', function (e) {
    e.stopPropagation();
    if (menu.classList.contains('hidden')) {
      menu.classList.remove('hidden');
      setTimeout(function () { menu.classList.remove('scale-95', 'opacity-0'); menu.classList.add('scale-100', 'opacity-100'); }, 10);
      if (arrow) arrow.classList.add('rotate-180');
    } else { closeMenu(); }
  });
  document.addEventListener('click', function (e) {
    if (!trigger.contains(e.target) && !menu.contains(e.target) && !menu.classList.contains('hidden')) closeMenu();
    if (!docsModal.classList.contains('hidden') && !docsModal.contains(e.target) && !docsBtn.contains(e.target)) toggleDocs();
  });

  /* ---------- choosing a file ---------- */
  var fileInput = $('realFileInput'), cameraInput = $('cameraInput');
  function pick(input) { closeMenu(); if (needCaseId()) return; input.click(); }
  $('btnSelectFile').addEventListener('click', function () { pick(fileInput); });
  $('btnDragDrop').addEventListener('click', function () { pick(fileInput); });
  $('btnScanDoc').addEventListener('click', function () { pick(cameraInput); });   // opens the camera on phones
  fileInput.addEventListener('change', function (e) { if (e.target.files[0]) handleFile(e.target.files[0]); e.target.value = ''; });
  cameraInput.addEventListener('change', function (e) { if (e.target.files[0]) handleFile(e.target.files[0]); e.target.value = ''; });

  var highlight = $('dropZoneHighlight');
  ['dragenter', 'dragover'].forEach(function (n) { window.addEventListener(n, function (e) { e.preventDefault(); highlight.classList.remove('hidden'); }); });
  window.addEventListener('dragleave', function (e) { e.preventDefault(); if (e.clientX === 0 && e.clientY === 0) highlight.classList.add('hidden'); });
  window.addEventListener('drop', function (e) {
    e.preventDefault(); highlight.classList.add('hidden');
    if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0]) handleFile(e.dataTransfer.files[0]);
  });

  /* ---------- the active card ---------- */
  var card = $('activeProgressCard'), bar = $('progressBarFill');
  var BAR_BASE = 'h-full rounded-full transition-all duration-300 ';
  function showCard(title, meta, percentText, width, barClass, label, statusHtml) {
    card.classList.remove('hidden'); card.style.opacity = '1'; card.style.transform = 'scale(1)';
    $('activeDocTitle').textContent = title; $('activeDocMeta').textContent = meta;
    bar.className = BAR_BASE + barClass; bar.style.width = width;
    $('progressPercent').textContent = percentText; $('progressLabel').textContent = label;
    var s = $('liveStatusScan'); s.textContent = '';
    s.appendChild(UI.el('span', 'w-1.5 h-1.5 rounded-full ' + statusHtml.dot + (statusHtml.pulse ? ' animate-pulse' : '')));
    s.appendChild(document.createTextNode(' ' + statusHtml.text));
    s.onclick = null; s.style.cursor = '';
  }
  function reject(file, why, short) {
    showCard(file.name, UI.formatBytes(file.size) + ' · ' + short, short, '0%', 'bg-rose-500', 'Not sent', { dot: 'bg-rose-400', text: why });
    toast(why);
  }

  function needCaseId() {
    var id = $('caseId').value.trim();
    if (!id) { toast('Enter a case ID first.'); $('caseId').focus(); return true; }
    return false;
  }

  function acceptedTypes() { return (cfg && cfg.accept) || ['application/pdf']; }
  function typeOk(file) {
    var name = file.name.toLowerCase(), t = acceptedTypes();
    if (t.indexOf(file.type) > -1) return true;
    var ext = /\.(pdf|jpe?g|png|webp)$/.test(name);
    return ext && (file.type === '' || file.type === 'application/octet-stream');
  }

  async function handleFile(file) {
    if (!file) return;
    if (needCaseId()) return;
    var limitMb = (cfg && cfg.max_upload_mb) || 10;
    if (!typeOk(file)) return reject(file, 'Unsupported file. Use a PDF, or a JPG, PNG or WebP photo or scan.', 'Unsupported type');
    if (file.size > limitMb * 1024 * 1024) return reject(file, 'The file is larger than ' + limitMb + ' MB.', 'Too large');
    if (file.size === 0) return reject(file, 'The file is empty.', 'Empty');

    selectedFile = file;
    showCard(file.name, UI.formatBytes(file.size), '35%', '35%', 'bg-gradient-to-r from-slate-400 via-primary to-white glow-progress',
      'Preparing', { dot: 'bg-primary', pulse: true, text: 'Preparing the document...' });
    try {
      var caseId = $('caseId').value.trim().slice(0, 64);
      API.setCaseId(caseId);
      await API.setPendingFile(file, { caseId: caseId, purpose: $('purposeSelect').value, fresh: $('freshCheck').checked });
      bar.style.width = '100%'; $('progressPercent').textContent = '100%';
      setTimeout(function () { location.href = 'analysing.html'; }, 250);
    } catch (e) {
      reject(file, 'Could not prepare the file in this browser. ' + (e.message || ''), 'Error');
    }
  }

  $('cancelScanBtn').addEventListener('click', function () {
    API.clearPendingFile(); selectedFile = null;
    card.style.transition = 'all 0.3s ease-out'; card.style.opacity = '0'; card.style.transform = 'scale(0.95)';
    setTimeout(function () { card.classList.add('hidden'); toast('Cancelled.'); }, 300);
  });
  $('rescanBtn').addEventListener('click', function () {
    if (selectedFile) handleFile(selectedFile);
    else if (!needCaseId()) fileInput.click();
  });

  /* ---------- history ---------- */
  var list = $('auditItemsContainer'), emptyState = $('emptyAuditState'), search = $('searchAuditsInput');

  async function loadAudits() {
    try { allAudits = await API.fetchHistory(50); } catch (e) { allAudits = []; if (e.status === 401) location.replace('signin.html'); }
    renderAudits();
  }

  function titleFor(item) {
    var cached = API.resultForHash(item.doc_hash);
    return (cached && cached._fileName) || ('Document ' + (item.doc_hash || '').slice(0, 8));
  }
  function inFilter(item) {
    var q = (search.value || '').toLowerCase().trim();
    var hay = (titleFor(item) + ' ' + UI.verdictLabel(cfg, item.verdict) + ' ' + (item.doc_hash || '')).toLowerCase();
    if (q && hay.indexOf(q) < 0) return false;
    return currentFilter === 'all' || UI.info(item.verdict).group === currentFilter;
  }

  function renderAudits() {
    list.querySelectorAll('.audit-card').forEach(function (c) { c.remove(); });
    var shown = allAudits.filter(inFilter);
    $('auditCountBadge').textContent = shown.length + ' Total';
    emptyState.classList.toggle('hidden', shown.length > 0);
    shown.forEach(function (item) { list.insertBefore(auditCard(item), emptyState); });
  }

  function auditCard(item) {
    var t = UI.tone(item.verdict), cached = API.resultForHash(item.doc_hash);
    var row = UI.el('div', 'glass-card rounded-2xl p-4 transition duration-200 hover:border-white/20 flex items-center justify-between group audit-card');
    var info = UI.el('div', 'min-w-0 pr-3 cursor-pointer');
    info.appendChild(UI.el('h4', 'text-sm font-semibold text-white truncate mb-1', titleFor(item)));
    var sub = UI.el('div', 'text-xs text-gray-400 font-normal flex items-center gap-1.5');
    sub.appendChild(UI.el('span', t.text + ' font-medium', UI.verdictLabel(cfg, item.verdict)));
    sub.appendChild(UI.el('span', null, '·'));
    sub.appendChild(UI.el('span', null, UI.formatWhen(item.timestamp)));
    info.appendChild(sub);
    info.addEventListener('click', function () {
      if (cached) { API.setLastResult(cached); location.href = 'result.html'; }
      else toast('Details are kept for this browser session only. Upload the document again to see them.');
    });
    var dl = UI.el('button', 'p-2 rounded-lg bg-obsidian-850 hover:bg-white/10 text-gray-400 hover:text-white border border-white/[0.06] transition text-xs font-medium', 'Report');
    dl.type = 'button'; dl.title = 'Download a report'; dl.setAttribute('aria-label', 'Download a report');
    dl.addEventListener('click', function (e) {
      e.stopPropagation();
      UI.download('PRAMANIK_report_' + UI.safeName(cached && cached._fileName) + '_' + (item.doc_hash || '').slice(0, 8) + '.txt', UI.buildReport(cfg, cached, item));
      toast('Report downloaded.');
    });
    row.appendChild(info); row.appendChild(dl);
    return row;
  }

  search.addEventListener('input', renderAudits);
  document.querySelectorAll('.audit-filter').forEach(function (pill) {
    pill.addEventListener('click', function () {
      document.querySelectorAll('.audit-filter').forEach(function (p) {
        p.classList.remove('bg-gray-200', 'text-obsidian-950', 'font-semibold', 'active');
        p.classList.add('text-gray-400', 'bg-obsidian-800/80', 'font-medium');
      });
      pill.classList.remove('text-gray-400', 'bg-obsidian-800/80', 'font-medium');
      pill.classList.add('bg-gray-200', 'text-obsidian-950', 'font-semibold', 'active');
      currentFilter = (pill.getAttribute('data-filter') || 'all').toLowerCase();
      renderAudits();
    });
  });

  /* ---------- user and sign-out ---------- */
  $('floatingLogoutBtn').addEventListener('click', async function () {
    var o = $('logoutOverlay'); o.classList.remove('hidden'); setTimeout(function () { o.classList.remove('opacity-0'); }, 10);
    await API.logout();
    setTimeout(function () { location.href = 'signin.html'; }, 700);
  });

  /* ---------- start ---------- */
  function fillConfig() {
    var types = cfg.document_types || [];
    var ul = $('acceptedDocsList'); ul.textContent = '';
    types.forEach(function (d) {
      var li = UI.el('li', 'flex items-start gap-2.5');
      li.appendChild(UI.el('span', 'mt-1.5 w-1.5 h-1.5 rounded-full bg-emerald-400 flex-shrink-0'));
      li.appendChild(UI.el('span', null, d.title + ' (' + d.issuer + ')'));
      ul.appendChild(li);
    });
    $('acceptedDocsIntro').textContent = 'PRAMANIK checks a document against the record its issuer holds. Supported right now:';
    $('acceptedFormat').textContent = 'Format: PDF, or a JPG / PNG / WebP photo or scan';
    var limit = cfg.max_upload_mb || 10;
    $('dropZoneHint').textContent = 'PDF, JPG, PNG or WebP, up to ' + limit + ' MB';
    var sel = $('purposeSelect'); sel.textContent = '';
    (cfg.purposes || []).forEach(function (p) { sel.appendChild(UI.el('option', null, p)); });
    fileInput.setAttribute('accept', acceptedTypes().join(',') + ',.pdf,.jpg,.jpeg,.png,.webp');
    $('sysIssuer').textContent = 'ISSUER: ' + ((cfg.issuers || []).join(', ').toUpperCase() || 'NONE');
  }

  function showLastResult() {
    var last = API.getLastResult();
    if (!last) return;
    var t = UI.tone(last.verdict);
    showCard(last._fileName || 'Last document', UI.verdictLabel(cfg, last.verdict), UI.verdictLabel(cfg, last.verdict), '100%', t.bar + ' glow-progress',
      'Most recent result', { dot: t.dot, text: 'Click to review the result' });
    var s = $('liveStatusScan'); s.style.cursor = 'pointer'; s.onclick = function () { location.href = 'result.html'; };
  }

  async function checkSystem() {
    var ok = false;
    try { ok = (await (await fetch('/health', { cache: 'no-store' })).json()).status === 'ok'; } catch (e) { ok = false; }
    $('sysStatus').textContent = ok ? 'SYSTEM ONLINE' : 'SYSTEM OFFLINE';
    $('routeText').textContent = ok ? 'Issuer link responding' : 'Issuer link not responding';
  }

  (async function init() {
    var user = await API.requireSession(true);
    $('userName').textContent = user.full_name;
    $('userRoleBadge').textContent = user.officer_id;
    $('userInitial').textContent = (user.full_name.trim()[0] || '?').toUpperCase();
    cfg = await API.fetchUiConfig();
    fillConfig();
    $('caseId').value = API.getCaseId();
    checkSystem();
    showLastResult();
    loadAudits();
  })();
})();
