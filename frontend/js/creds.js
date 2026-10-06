(function () {
  'use strict';
  var API = window.PramanikAPI, UI = window.PramanikUI;
  var SELECTED = 'role-pill px-4 py-2 rounded-xl text-xs sm:text-sm font-semibold bg-[#8c94ba] text-[#12141e] border border-transparent shadow-sm transition-all cursor-pointer';
  var PLAIN = 'role-pill px-4 py-2 rounded-xl text-xs sm:text-sm font-medium border border-white/10 text-slate-300 hover:text-white hover:border-white/20 transition-all cursor-pointer';
  var pills = document.querySelectorAll('.role-pill'), roleInput = UI.byId('selectedRole');
  var form = UI.byId('creds-form'), err = UI.byId('formError'), btn = UI.byId('continueBtn');

  function pick(role) {
    roleInput.value = role;
    pills.forEach(function (p) { p.className = p.dataset.role === role ? SELECTED : PLAIN; });
  }
  pills.forEach(function (p) { p.addEventListener('click', function () { roleInput.dataset.touched = '1'; pick(p.dataset.role); }); });

  API.requireSession(false).then(function (user) {
    // fill only what is still empty: never overwrite something the person has already typed
    function fill(id, value) { var input = UI.byId(id); if (input && !input.value) input.value = value || ''; }
    fill('fullName', user.full_name); fill('phone', user.phone); fill('organisation', user.organisation); fill('officerId', user.officer_id);
    if (!roleInput.dataset.touched) pick(user.role || 'Officer');
  });

  form.addEventListener('submit', async function (e) {
    e.preventDefault();
    err.classList.add('hidden');
    btn.disabled = true;
    try {
      await API.saveProfile({
        full_name: UI.byId('fullName').value, phone: UI.byId('phone').value, organisation: UI.byId('organisation').value,
        role: roleInput.value || 'Officer', officer_id: UI.byId('officerId').value,
      });
      location.href = 'maindash.html';
    } catch (ex) {
      if (ex.status === 401) { location.replace('signin.html'); return; }
      err.textContent = ex.message; err.classList.remove('hidden'); btn.disabled = false;
    }
  });
})();
