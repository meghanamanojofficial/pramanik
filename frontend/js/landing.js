// Landing page: scroll, swipe or tap to swap the hero for the manifesto (and back).
(function () {
  'use strict';
  var byId = function (id) { return document.getElementById(id); };
  var brandCluster = byId('brand-cluster'), brandTitle = byId('brand-title'), brandTagline = byId('brand-tagline');
  var documentsCloud = byId('documents-cloud'), manifestoPanel = byId('manifesto-panel'), center = byId('stage-center-container');
  var swipeIcon = byId('swipe-icon'), swipeHintBtn = byId('swipe-hint-btn'), swipeHintText = byId('swipe-hint-text');
  var HERO_TITLE = ['text-4xl', 'sm:text-6xl', 'md:text-7xl', 'lg:text-8xl', 'tracking-[0.25em]', 'md:tracking-[0.38em]'];
  var SMALL_TITLE = ['text-3xl', 'sm:text-4xl', 'md:text-5xl', 'tracking-[0.18em]'];
  var PANEL_HIDDEN = ['opacity-0', 'translate-y-10', 'pointer-events-none', 'max-h-0'];
  var PANEL_SHOWN = ['opacity-100', 'translate-y-0', 'pointer-events-auto', 'max-h-[800px]'];
  var stage = 'hero';

  function swap(el, off, on) { el.classList.remove.apply(el.classList, off); el.classList.add.apply(el.classList, on); }

  function apply() {
    var manifesto = stage === 'manifesto';
    swap(brandTitle, manifesto ? HERO_TITLE : SMALL_TITLE, manifesto ? SMALL_TITLE : HERO_TITLE);
    swap(brandCluster, manifesto ? ['items-center'] : ['items-start', 'text-left'], manifesto ? ['items-start', 'text-left'] : ['items-center']);
    swap(center, manifesto ? ['items-center', 'text-center'] : ['items-start', 'text-left'],
      manifesto ? ['items-start', 'text-left'] : ['items-center', 'text-center']);
    brandTagline.classList.toggle('opacity-0', manifesto);
    brandTagline.classList.toggle('h-0', manifesto);
    brandTagline.classList.toggle('overflow-hidden', manifesto);
    brandTagline.classList.toggle('mt-0', manifesto);
    swap(manifestoPanel, manifesto ? PANEL_HIDDEN : PANEL_SHOWN, manifesto ? PANEL_SHOWN : PANEL_HIDDEN);

    // The documents drift back and blur further while the manifesto is open.
    documentsCloud.style.transform = manifesto ? 'translateZ(-280px) scale(0.65)' : '';
    documentsCloud.style.filter = manifesto ? 'blur(8px)' : '';
    documentsCloud.style.opacity = manifesto ? '0.12' : '';

    swipeIcon.style.transform = manifesto ? 'rotate(180deg)' : '';
    swipeHintText.textContent = manifesto ? 'Return to document stage' : 'Scroll or tap to explore manifesto';
    swipeHintBtn.setAttribute('aria-expanded', String(manifesto));
  }

  function setStage(next) { if (next !== stage) { stage = next; apply(); } }

  swipeHintBtn.addEventListener('click', function () { setStage(stage === 'hero' ? 'manifesto' : 'hero'); });

  window.addEventListener('wheel', function (e) {
    if (Math.abs(e.deltaY) <= 35) return;
    if (e.deltaY > 0 && stage === 'hero') setStage('manifesto');
    else if (e.deltaY < 0 && stage === 'manifesto' && window.scrollY === 0) setStage('hero');
  }, { passive: true });

  var touchStartY = 0;
  window.addEventListener('touchstart', function (e) { touchStartY = e.touches[0].clientY; }, { passive: true });
  window.addEventListener('touchend', function (e) {
    var diffY = touchStartY - e.changedTouches[0].clientY;
    if (diffY > 40 && stage === 'hero') setStage('manifesto');
    else if (diffY < -40 && stage === 'manifesto' && window.scrollY === 0) setStage('hero');
  }, { passive: true });
  // Support button: shows the support address from the server's settings.
  var support = byId('support'), supportBtn = byId('support-btn'), popover = byId('support-popover');
  var emailEl = byId('support-email'), copyText = byId('support-copy-text');
  function setPopover(open) { popover.classList.toggle('hidden', !open); supportBtn.setAttribute('aria-expanded', String(open)); }
  supportBtn.addEventListener('click', function () { setPopover(popover.classList.contains('hidden')); });
  byId('support-close').addEventListener('click', function () { setPopover(false); });
  document.addEventListener('click', function (e) { if (!support.contains(e.target)) setPopover(false); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') setPopover(false); });
  byId('support-copy').addEventListener('click', function () {
    if (!navigator.clipboard) return;
    navigator.clipboard.writeText(emailEl.textContent).then(function () {
      copyText.textContent = 'Copied!';
      setTimeout(function () { copyText.textContent = 'Copy'; }, 2000);
    }).catch(function () {});
  });
  fetch('/api/ui-config', { credentials: 'same-origin' }).then(function (r) { return r.ok ? r.json() : {}; }).then(function (cfg) {
    var email = String(cfg.support_email || '').trim();
    if (!/^[^\s@<>"]+@[^\s@<>"]+$/.test(email)) return;
    emailEl.textContent = email;
    byId('support-mail').href = 'mailto:' + email;
    support.classList.remove('hidden');
  }).catch(function () {});
})();
