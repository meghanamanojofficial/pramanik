# One container runs both services (the simulated issuer and Pramanik). Everything that must survive a restart
# (keys, accounts, the reuse ledger, audit logs) lives in the /state volume; the code and the built front end do not.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 \
    PRAMANIK_SKIP_DEMO_DOCS=1 \
    FORWARDED_ALLOW_IPS=*

# tesseract: reading photos and scans; libzbar0: QR fallback; libgl1 + libglib2.0-0: OpenCV
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr libzbar0 libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt

COPY . .

# Point every place the code writes state at the /state volume.
RUN useradd --create-home --uid 10001 pramanik \
 && mkdir /state && chown pramanik /state \
 && rm -rf backend/data issuer_service/signing_keys \
 && ln -s /state/data backend/data \
 && ln -s /state/signing_keys issuer_service/signing_keys \
 && ln -s /state/env backend/.env \
 && ln -s /state/keys.json issuer_service/keys.json \
 && ln -s /state/issuer_keys.json backend/config/issuer_keys.json \
 && ln -s /state/audit.log backend/audit.log \
 && ln -s /state/issuer_audit.jsonl issuer_service/audit.jsonl \
 && mkdir -p demo_docs/pdfs demo_docs/scans && chown -R pramanik demo_docs \
 && chmod +x docker/entrypoint.sh

# No USER line on purpose: the entrypoint starts as root only to fix the disk's ownership, then runs the app as
# the unprivileged user (see docker/entrypoint.sh).
EXPOSE 8001
VOLUME /state
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT', '8001'), timeout=4)"
ENTRYPOINT ["/app/docker/entrypoint.sh"]
