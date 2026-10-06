"""Web addresses printed on a document. They are only inspected, never fetched."""
import re
from urllib.parse import urlparse

from .. import config
from ..services.signals import Severity, Signal

_URL = re.compile(r"(?:https?://|www\.)[^\s<>\"']+", re.I)
MAX_LINKS = 20


def _short(url: str) -> str:
    return url if len(url) <= 80 else url[:77] + "..."


def check(text: str) -> list[Signal]:
    cfg = config.scan()["links"]
    allowed = [d.lower() for d in cfg["allowed_domains"]]
    shorteners = {d.lower() for d in cfg["shorteners"]}
    signals: list[Signal] = []
    seen: set[str] = set()

    for raw in _URL.findall(text or "")[:MAX_LINKS]:
        url = raw.rstrip(".,;:)]}")
        try:
            parsed = urlparse(url if "://" in url else "https://" + url)
            host = (parsed.hostname or "").lower()  # hostname drops user@ tricks and ports
        except ValueError:
            continue
        if not host or (host, parsed.scheme) in seen:
            continue
        seen.add((host, parsed.scheme))

        if parsed.scheme == "http":
            signals.append(Signal("insecure_http_link", Severity.STRONG, config.message("link_insecure", url=_short(url))))
        if host in shorteners:
            signals.append(Signal("malicious_link_domain", Severity.STRONG, config.message("link_shortener", host=host)))
        elif any(host == d or host.endswith("." + d) for d in allowed):
            continue
        elif any(d in host.replace("-", ".") for d in allowed):
            signals.append(Signal("malicious_link_domain", Severity.STRONG, config.message("link_lookalike", host=host)))
        else:
            signals.append(Signal("unknown_link_domain", Severity.WEAK, config.message("link_unknown", host=host)))
    return signals
