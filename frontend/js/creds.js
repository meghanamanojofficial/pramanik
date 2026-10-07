(function () {
  'use strict';
  var API = window.PramanikAPI, UI = window.PramanikUI;
  var form = UI.byId('creds-form'), err = UI.byId('formError'), btn = UI.byId('continueBtn');

  API.requireSession(false).then(function (user) {
    // fill only what is still empty: never overwrite something the person has already typed
    function fill(id, value) { var input = UI.byId(id); if (input && !input.value) input.value = value || ''; }
    fill('fullName', user.full_name); fill('phone', user.phone); fill('organisation', user.organisation); fill('officerId', user.officer_id);
  });

  form.addEventListener('submit', async function (e) {
    e.preventDefault();
    err.classList.add('hidden');
    btn.disabled = true;
    try {
      // every account is an officer's: the server's default role applies, so none is sent
      await API.saveProfile({
        full_name: UI.byId('fullName').value, phone: UI.byId('phone').value, organisation: UI.byId('organisation').value,
        officer_id: UI.byId('officerId').value,
      });
      location.href = 'maindash.html';
    } catch (ex) {
      if (ex.status === 401) { location.replace('signin.html'); return; }
      err.textContent = ex.message; err.classList.remove('hidden'); btn.disabled = false;
    }
  });
})();
