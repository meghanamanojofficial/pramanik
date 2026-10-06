# Front end

Plain HTML pages with a little JavaScript, served by the backend at `/app/` (nothing else to run). Design by the team;
wired to the real API.

| Page | Purpose | Script |
|---|---|---|
| `signin.html` | create an account / log in | `js/signin.js` |
| `creds.html` | profile: name, unique officer ID | `js/creds.js` |
| `maindash.html` | case ID, upload (file, drag-and-drop, camera), history drawer | `js/maindash.js` |
| `analysing.html` | runs the check, shows what actually happened to each step | `js/analysing.js` |
| `result.html` | verdict, reasons, values read, risk triage, next step, report download | `js/result.js` |

Shared: `js/api.js` (server calls, session, the pending file kept in IndexedDB) and `js/ui.js` (verdict colours and
wording, safe element helpers, report text).

## Rules for changing things

- **No inline scripts, no inline event handlers, nothing from other sites.** The server sends a Content-Security-Policy
  that blocks them; `backend/tests/test_auth.py` checks the pages.
- **Show document data as text.** Use `textContent` / `UI.el(...)`, never `innerHTML`: values come from uploaded files.
- **Labels and limits come from the server** (`/api/ui-config`): verdict names, risk names, accepted types, upload size,
  purposes, supported documents. Don't hard-code them.
- Unknown verdicts fall back to a neutral style (`UI.info`); add new ones to `js/ui.js` (tone, recommendation).

## Styles and fonts

Tailwind is compiled ahead of time, so the pages work without internet access. The built files (`css/`, `fonts/`) are
committed. Only if you change classes, markup or a page's theme:

```bash
cd frontend && npm install && npm run build
```

Each page keeps its own theme in `tailwind/<page>.config.cjs` (copied from the original design).

## Tests

`npm test` (with both services running, from `frontend/`) drives the real pages in a simulated browser (jsdom) against the
real backend: sign-up, profile, uploads of every kind of document, results, history, report, a hostile document, sign-out.
It checks that the pages **work**; it cannot judge how they **look**, so open them in a browser after any visual change.
