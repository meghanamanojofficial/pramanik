# Deploying Pramanik

Two ways: **Docker** (one container, one state volume) or **a plain Linux server** (systemd). Either way, put **HTTPS** in
front of it: officers sign in with a password, so the public side must not be plain HTTP.

> What was tested: the application, the reverse-proxy behaviour with nginx (TLS, `Secure` cookies, HSTS, the upload size
> limit, the HTTP to HTTPS redirect), and the container's start-up/persistence logic. What was **not** tested: building the
> Docker image itself and the Caddy config (no Docker or Caddy was available). Try the build once and read its log.

## Before you go live

1. **Decide who may sign up.** Set `PRAMANIK_SIGNUP_CODE` (people need the code) or `PRAMANIK_SIGNUP=closed` and create
   accounts with `python backend/tools/create_user.py`. Open sign-up lets anyone who can reach the server make an account.
2. **Replace the simulated issuer.** `issuer_service/` is a stand-in for a department's registry. Point
   `backend/config/issuers.json` at the real issuer's HTTPS API (it must implement the API described in the README) and
   set its key in `ISSUER_KEY_<NAME>`. Pramanik refuses to send an API key over plain HTTP to anything but localhost.
3. **HTTPS** in front (below). 4. **Back up the state** (below). 5. Run **one** worker process.

## Option A: Docker

```bash
cp deploy/pramanik.env.example .env       # then edit: set PRAMANIK_SIGNUP_CODE
docker compose up -d --build
docker compose logs -f                    # the first start creates keys, accounts and ledger in the volume
```

The container publishes `127.0.0.1:8001` only. Put nginx or Caddy on the host in front of it. All state is in the
`pramanik-state` volume (`/state`): `env` (secrets), `keys.json`, `issuer_keys.json`, `signing_keys/`, `data/` (accounts,
sessions, reuse ledger, issuer-answer cache), `audit.log`, `issuer_audit.jsonl`. Rebuilding or recreating the container
keeps it. **Deleting the volume deletes accounts and keys.**

Create an account when sign-up is closed:
`docker compose exec pramanik python backend/tools/create_user.py officer@dept.gov.in --officer-id OFC-1001 --name "A. Officer"`

## Option B: a Linux server

```bash
sudo apt install -y python3-venv tesseract-ocr libzbar0 libgl1
sudo useradd --system --create-home --home-dir /opt/pramanik pramanik
sudo -u pramanik git clone <your repo> /opt/pramanik && cd /opt/pramanik
sudo -u pramanik python3 -m venv venv && sudo -u pramanik venv/bin/pip install -r backend/requirements.txt
sudo -u pramanik PRAMANIK_SKIP_DEMO_DOCS=1 venv/bin/python issuer_service/setup_keys.py   # keys, once
sudo cp deploy/pramanik.service /etc/systemd/system/ && sudo systemctl enable --now pramanik
```

Edit the unit's `Environment=` lines first (sign-up policy). Logs: `journalctl -u pramanik -f`.

## HTTPS

- **Caddy** (simplest; gets and renews certificates itself): put your host name in `deploy/Caddyfile` and run Caddy.
- **nginx**: use `deploy/nginx.conf` (replace the host name and certificate paths, for example from Let's Encrypt).
  It sends `X-Forwarded-Proto`, which is how the app knows to mark the session cookie `Secure`, and caps uploads at 11 MB.
  Checked against nginx 1.24; on 1.25.1+ you may replace `listen 443 ssl http2;` by `listen 443 ssl;` and `http2 on;`.

Behind a proxy the app should see real client addresses (the login throttle uses them): `run_all.py` starts uvicorn with
`--proxy-headers`, and the Docker image sets `FORWARDED_ALLOW_IPS=*` because the container is only reachable by the proxy.
If you publish the container port to the network directly, set it to the proxy's address instead.

## What to back up

`backend/.env`, `issuer_service/keys.json`, `issuer_service/signing_keys/`, `backend/config/issuer_keys.json`,
`backend/data/` (or your `DATABASE_URL` database), `backend/audit.log`. **Losing the signing keys means certificates the
issuer printed can no longer be checked offline; losing `PRAMANIK_FINGERPRINT_KEY` empties the reuse ledger's memory.**
Treat `backend/.env` and `signing_keys/` as secrets.

## Updating

Pull the new code, `pip install -r backend/requirements.txt`, restart the service (or `docker compose up -d --build`).
Tables are created automatically. If the front end changed, the built `frontend/css` and `frontend/fonts` come with the
repository; rebuild them only if you change markup or styles (`cd frontend && npm install && npm run build`).

## Known limits

Single process only; no password reset, e-mail verification or MFA; roles are informational; the reuse ledger and the
issuer-answer cache are in the same database as accounts; OCR needs the Tesseract program on the server.
