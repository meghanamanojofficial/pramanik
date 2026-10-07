# Deploying on Render

Render runs the repository's `Dockerfile` as one long-lived web service. Two ways to set it up, and two sizes.

> **Tested:** the container's start-up logic (a root-owned disk, `PORT`, restart persistence, sample documents made in the
> background) in a simulated container, and the app's memory use on realistic phone photos. **Not tested:** the real image
> build and a real Render deploy (no Docker or Render access where this was prepared). Watch the first deploy's log.

## Which size?

| | **Free (demo)** | **Paid (real use)** |
|---|---|---|
| Good for | showing the app to people | officers actually using it |
| Memory | 512 MB: enough with the settings below (measured peak ~380 MB with a 12 MP photo, ~240 MB idle) | 1-2 GB: comfortable |
| Data | **lost** whenever the instance sleeps or restarts: keys, accounts, history. People sign up again with the code. | kept on a persistent disk |
| Speed | slow: a small share of one CPU, so a photo can take many seconds (PDFs are quicker) | normal |
| Idle | sleeps after a quiet spell; the next visit takes a minute to wake it | always on |
| Cost | free (Render may still ask for a card; check) | paid plan + disk |

Free-plan facts above (size, sleeping, no disk) are from memory: check Render's current pricing page.

## A. Free demo, set up by hand (no Blueprint)

If creating a **Blueprint** asks for payment, do this instead; it also works if you simply prefer it.

1. Render dashboard > **New +** > **Web Service** > connect your GitHub repository (`pramanik`), branch `main`.
2. **Language / Runtime: Docker** (Render finds the `Dockerfile`). **Instance type: Free.**
3. Under **Environment**, add these variables:

   | Variable | Value |
   |---|---|
   | `PRAMANIK_SIGNUP_CODE` | a long random string of your own (people need it to sign up) |
   | `PRAMANIK_DEMO` | `1` |
   | `PRAMANIK_SKIP_DEMO_DOCS` | `1` |
   | `PRAMANIK_MAX_SCANS` | `1` |
   | `PRAMANIK_MAX_IMAGE_SIDE` | `2000` |
   | `PRAMANIK_SESSION_HOURS` | `8` |

4. **Advanced > Health Check Path:** `/health`. Create the service. The first build takes several minutes.
5. When it is live, open `https://<name>.onrender.com`.

## B. Free demo through the Blueprint

New + > **Blueprint** > pick the repository. The repository's `render.yaml` is the free version. Enter the sign-up code when
asked. (If Render asks for payment here, use A.)

## C. Real use (paid)

Copy `deploy/render.paid.yaml` over `render.yaml` (or create the service by hand with the same settings): a plan with
**at least 1 GB** of memory, a **persistent disk mounted at `/state`**, **one instance**. Delete `PRAMANIK_DEMO` unless
this is a public demo, and keep `PRAMANIK_MAX_SCANS=1` unless the plan is large. Render's 512 MB paid plans are too small for
large photos: a 12 MP photo needs about 450 MB at the default image size.

## First use

1. Open the URL > **Sign up** > the sign-up code, your e-mail and a password > complete your profile.
2. **Demo mode:** open `https://<your-url>/demo`, download a sample, and upload it on the dashboard. The samples are made by
   this server with its own signing key, so a genuine one verifies and a forged one is flagged. Sample documents made on any
   other machine show as forged here, because their QR signatures belong to a different key. Right after a start the
   page may say they are still being prepared: reload after a minute.
3. Share the sign-up code with the people who need accounts. There is no password reset yet.

## Things to know

- **Updates:** every push to the connected branch redeploys. On the free plan that also resets accounts and keys.
- **One instance only.** The reuse ledger and the login throttle live in one process; never scale out.
- **HTTPS** is provided by Render; the session cookie is marked `Secure` automatically.
- **Keeping a free demo awake:** a free instance sleeps when idle. Visit it a few minutes before showing it, or point a free
  uptime monitor at `/health`. Waking it still resets nothing; only a restart does.
- **Reuse warnings in a demo:** checking the same certificate under many different case IDs correctly raises "already
  presented in other cases" (a warning after one other case, "integrity concerns" after four). Use one case ID per
  application, or restart the instance to reset.
- **Backups (paid):** the disk is the only copy of the signing keys and accounts: use Render's disk snapshots and keep a copy
  of `/state` (see `deploy/README.md`, "What to back up").

## If it does not start or misbehaves

- *Build fails:* paste the build log; the image build is the one part that could not be tested beforehand.
- *"permission denied" on `/state` (paid):* the disk must be mounted at exactly `/state`; the start-up script fixes ownership.
- *Killed or restarting during a scan:* out of memory. Free plan: confirm `PRAMANIK_MAX_SCANS=1` and
  `PRAMANIK_MAX_IMAGE_SIDE=2000` are saved. Otherwise move to a bigger plan.
- *A photo takes very long or the page times out:* free instances have very little CPU. Try a PDF, a smaller photo, or a paid plan.
- *Sign-up says the code is wrong, or sign-up is open to anyone:* `PRAMANIK_SIGNUP_CODE` was not saved; set it and redeploy.
- *Accounts vanished:* expected on the free plan after a sleep or restart.
