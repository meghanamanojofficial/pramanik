(function () {
  'use strict';
  var API = window.PramanikAPI, UI = window.PramanikUI;
  var form = UI.byId('signup-form'), email = UI.byId('email'), password = UI.byId('password');
  var pwError = UI.byId('password-error'), formError = UI.byId('formError'), submit = UI.byId('submitBtn');
  var link = UI.byId('loginLink'), codeGroup = UI.byId('codeGroup'), code = UI.byId('signupCode');
  var mode = new URLSearchParams(location.search).get('mode') === 'login' ? 'login' : 'signup';
  var signupPolicy = 'open';

  function showError(msg) { formError.textContent = msg; formError.classList.remove('hidden'); }
  function clearErrors() { formError.classList.add('hidden'); pwError.classList.add('hidden'); password.classList.remove('input-error'); }

  function render() {
    var signup = mode === 'signup';
    UI.setText('heading', signup ? 'Create your account' : 'Log in');
    UI.setText('subheading', signup ? 'Verify the document, not the person.' : 'Welcome back. Sign in to check documents.');
    submit.textContent = signup ? 'Sign up' : 'Log in';
    password.setAttribute('autocomplete', signup ? 'new-password' : 'current-password');
    codeGroup.classList.toggle('hidden', !(signup && signupPolicy === 'code'));
    if (signupPolicy === 'closed') {
      UI.byId('switchPrompt').classList.add('hidden'); link.classList.add('hidden');
    } else {
      UI.setText('switchPrompt', signup ? 'Already have an account? ' : 'New here? ');
      link.textContent = signup ? 'Log in' : 'Sign up';
    }
  }

  link.addEventListener('click', function (e) { e.preventDefault(); mode = mode === 'signup' ? 'login' : 'signup'; clearErrors(); render(); });
  password.addEventListener('input', clearErrors);

  form.addEventListener('submit', async function (e) {
    e.preventDefault();
    clearErrors();
    var signup = mode === 'signup';
    if (signup && password.value.length < 8) {
      password.classList.add('input-error'); pwError.classList.remove('hidden'); return;
    }
    submit.disabled = true;
    try {
      var user = signup ? await API.signup(email.value.trim(), password.value, code.value.trim())
                        : await API.login(email.value.trim(), password.value);
      location.href = user.profile_complete ? 'maindash.html' : 'creds.html';
    } catch (err) {
      showError(err.message || 'Something went wrong. Try again.');
      submit.disabled = false;
    }
  });

  API.authOptions().then(function (o) {
    signupPolicy = o.signup;
    if (signupPolicy === 'closed') mode = 'login';
    render();
  }).catch(function () { render(); });
  render();
})();
