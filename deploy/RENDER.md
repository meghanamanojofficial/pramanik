# Deploying on Render

Render runs the repository's `Dockerfile` as one long-lived web service. The repository includes a Blueprint
(`render.yaml`) that sets it up for you.

> **Tested:** the container's start-up logic (a root-owned disk, `PORT`, restart persistence, demo documents) was run in a
> simulated container, and the app on realistic phone photos. **Not tested:** the actual image build and a real Render
> deploy (no Docker or Render access where this was prepared). Watch the first deploy's log.

## Before you start

1. **Choose a plan with enough memory.** Measured: the app idles at about 240 MB and reaches about 500-550 MB while reading a
   12-megapixel phone photo. A 512 MB plan is too small and will be killed in the middle of a scan. Use a plan with at
   least **1 GB** of RAM (in practice Render's 2 GB tier); check Render's current plan list.
2. **You need a persistent disk,** and disks need a paid plan. The disk holds the signing keys, accounts, reuse ledger and
   audit log. Without it, every restart or deploy creates new keys and erases accounts. (A free instance is only good for
   a few minutes of looking around.)
3. **Choose a sign-up code:** a long random string. Anyone who knows it can create an account.

## Deploy (Blueprint)

1. Push the repository to GitHub (it already is).
2. In Render: **New + > Blueprint**, pick the repository. Render reads `render.yaml`.
3. When asked for `PRAMANIK_SIGNUP_CODE`, enter your code.
4. Before applying, open the service's settings and set the **plan** to one with at least 1 GB RAM.
5. Apply. The first build takes a few minutes. When the log says the service is live, open the URL Render gives you
   (`https://<name>.onrender.com`).

### Or by hand (no Blueprint)

New + > Web Service > your repo > **Runtime: Docker** > pick a plan (1 GB+). Add a **Disk**: mount path `/state`, 1 GB.
Set the environment variables below. Health check path: `/health`. Instances: **1**.

## Environment variables

| Variable | Value | Why |
|---|---|---|
| `PRAMANIK_SIGNUP_CODE` | your long random string | who may create an account (required: the app is for officers only) |
| `PRAMANIK_SESSION_HOURS` | `8` | how long a login lasts |
| `PRAMANIK_MAX_SCANS` | `1` | read one photo at a time (low memory); raise it on a big plan |
| `PRAMANIK_SKIP_DEMO_DOCS` | `1` | no sample documents in a real deployment |
| `PRAMANIK_DEMO` | `1` for a **public demo**, otherwise delete it | makes sample documents and serves them at `/demo` |

`PORT` is set by Render itself and the app uses it. Do not set `PRAMANIK_SIGNUP` to `open`.

## First use

1. Open the URL > **Sign up** > enter the sign-up code, your e-mail and a password > fill in your profile.
2. **Demo mode only:** open `https://<your-url>/demo`, download a sample, and upload it on the dashboard. The samples are made
   by this server with its own signing key, so a genuine one verifies and a forged-signature one is flagged. Sample
   documents made on any other machine will show as forged here: their QR signatures belong to a different key.
3. Share the sign-up code with the people who need accounts. There is no password reset yet.

## Things to know

- **Updates:** every push to the connected branch redeploys (`autoDeploy: true`). The disk keeps keys, accounts and
  history across deploys. Deploys restart the app, so people are signed in again only if a restart lost their session
  (sessions are kept on the disk).
- **One instance only.** The reuse ledger's integrity chain and the login throttle live in one process; never scale out.
- **HTTPS** is provided by Render; the session cookie is marked `Secure` automatically.
- **Backups:** the disk is the only copy of the signing keys and accounts. Use Render's disk snapshots, and keep a copy of
  the contents of `/state` somewhere safe (see `deploy/README.md`, "What to back up").
- **Custom domain:** Render > Settings > Custom Domains.
- **Logs:** Render > Logs. Startup prints a warning if sign-up is open; it should not appear.
- **Reuse warnings in a demo:** checking the same certificate under many different case IDs correctly raises "already
  presented in other cases" (a warning after one other case, "integrity concerns" after four). Use one case ID per
  application when showing the demo, or reset with a fresh disk.
- **Cold starts:** on plans that sleep when idle, the first request after a pause can take a while.

## If it does not start

- *"permission denied" on `/state`:* the entrypoint fixes the disk's ownership at start; check the log for the line before
  the error and make sure the disk is mounted at exactly `/state`.
- *Killed / out of memory during a scan:* the plan is too small (see above) or `PRAMANIK_MAX_SCANS` is above 1.
- *The page loads but sign-up says the code is wrong:* the variable was not saved; re-enter it and redeploy.
- *Everything resets after a deploy:* the disk is missing or mounted somewhere else.
