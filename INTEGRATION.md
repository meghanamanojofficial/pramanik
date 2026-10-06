# Wiring the issuer service into Pramanik

## What this changes
Before: `router.py` imported the mock issuer directly, so the "issuer" was just a Python import.
Now: the issuer is its own service (port 8002). Pramanik calls it over HTTP with an API key.
Which issuer handles which certificate series lives in `backend/config/issuers.json`, not in code.

```
Officer browser -> Pramanik backend :8001 -> issuer_service :8002 -> registries.json -> mock_records.json
                   (issuer_client.py)  X-API-Key header    (key checked, hashed)
```

## Copy these into the repo (same folder layout)
- `issuer_service/` (new folder at the repo root, next to `backend/`)
- `backend/app/issuer_client.py`
- `backend/config/issuers.json`
- append `.gitignore.additions` to your `.gitignore`

No new pip packages: the client uses the standard library, and the service uses fastapi/uvicorn, which you already have.

## Run it
```bash
python issuer_service/setup_keys.py                       # once: creates keys
cd issuer_service && uvicorn main:app --reload --port 8002   # terminal 1
cd backend && uvicorn app.main:app --reload --port 8001      # terminal 2
python -m unittest discover -s issuer_service/tests -v       # from repo root
```
Teammates run `setup_keys.py` once on their own machine. Keys are never committed.

## The one code change in your backend
Wherever the router currently looks up the record via the mock issuer, replace it with:

```python
from app.issuer_client import lookup

result = lookup(certificate_number)
if result.outcome == "found":
    record = result.record          # same dict as in mock_records.json
    # ...existing compare + verdict logic...
elif result.outcome == "not_found":
    ...  # existing "number not in registry" path (SUSPICIOUS)
elif result.outcome == "unconnected":
    ...  # UNVERIFIABLE
else:  # "unavailable"
    ...  # NEEDS REVIEW (never TAMPERED/SUSPICIOUS: it's our plumbing, not the document)
```
If that route is `async def`, call it as `await run_in_threadpool(lookup, certificate_number)`
(`from starlette.concurrency import run_in_threadpool`), since the client is blocking.

## Adding a second department (shows routing in the demo)
1. `issuer_service/registries.json`: add `{"issuer_id": "land_dept", "prefix": "LND-", "file": "../backend/data/land_records.json"}`
2. `backend/config/issuers.json`: add an entry with `"prefixes": ["LND-"]` and `"api_key_env": "ISSUER_KEY_LAND_DEPT"`
3. Run `python issuer_service/setup_keys.py`. No code changes.

## What to tell the judge
- Registry data, issuer routing, URLs and key names are all JSON config; secrets are in `.env`.
- Keys are random 256-bit values; the issuer stores only SHA-256 hashes, compares in constant time,
  supports revocation and rotation (`--rotate`), and scopes each key to one issuer.
- Per-key rate limit and an audit log with no certificate numbers, names or amounts.
- Issuer down / key rejected maps to "needs review", unconfigured series maps to "unverifiable".
- In production the issuer service is the department's own system; only `base_url` and the key change.

## Assumptions I couldn't check (I can't read your repo)
- `mock_records.json` records each have a `certificate_number` field (list, `{"records": [...]}`, or keyed object all work).
- The FastAPI wrapper `main.py` is untested here (no FastAPI in my sandbox); the logic behind it is tested.
  First check: open http://localhost:8002/health, then `curl -H "X-API-Key: <value from backend/.env>" http://localhost:8002/v1/records/<a real number>`.
