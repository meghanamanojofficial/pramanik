"""UI settings and user-facing message text, read from config/ui.json.

Read on every call (the file is tiny), so editing the JSON takes effect without a restart,
the same as the other config files. Override the location with the UI_CONFIG environment variable.
"""
import json
import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
BODY_OVERHEAD = 1024 * 1024  # multipart form overhead on top of the file limit


def load() -> dict:
    path = Path(os.environ.get("UI_CONFIG", BACKEND_DIR / "config" / "ui.json"))
    return json.loads(path.read_text(encoding="utf-8"))


def max_upload_bytes() -> int:
    return int(load()["max_upload_mb"] * 1024 * 1024)


def message(key: str, **values) -> str:
    """Message text for `key`, with {placeholders} filled from `values`."""
    cfg = load()
    text = cfg["messages"][key]
    values.setdefault("max_mb", f"{cfg['max_upload_mb']:g}")
    return text.format(**values)


def issuer_error_message(code: str, detail: str = "") -> str:
    """Text for an issuer failure code; unknown codes fall back to the generic 'unreachable' text."""
    try:
        return message(code, detail=detail)
    except KeyError:
        return message("unreachable")


def public_config() -> dict:
    """What the page needs to build itself (no message catalogue, nothing secret)."""
    from .services import doctypes

    cfg = load()
    titles = [t.get("title", t["id"]) for t in doctypes.load_types()]
    names = ", ".join(titles) if titles else "none configured"
    return {
        "app_title": cfg["app_title"],
        "subtitle": cfg["subtitle"].format(document_types=names),
        "default_officer_id": cfg["default_officer_id"],
        "officer_id_label": cfg["officer_id_label"],
        "max_upload_mb": cfg["max_upload_mb"],
        "purposes": cfg["purposes"],
        "verdict_labels": cfg["verdict_labels"],
        "samples": cfg["samples"],
    }
