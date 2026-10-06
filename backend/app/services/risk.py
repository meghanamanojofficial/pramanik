"""A 0-100 risk score for triage. It is advice for the officer, never a verdict and never an input to one.

The score is the sum of listed factors (weights in config/risk.json), clamped to 0-100, and every factor
is returned with its points and a plain-language reason, so the number can always be explained and
challenged. When nothing was actually judged (RESCAN, INCONCLUSIVE, UNVERIFIABLE) there is no score:
inventing one would hide the fact that the document has not been checked.
"""
from .. import config
from .signals import Severity, Signal


def level_for(score: int, cfg: dict) -> str:
    if score >= cfg["levels"]["high"]:
        return "high"
    return "medium" if score >= cfg["levels"]["medium"] else "low"


def assess(verdict: str, signals: list[Signal], input_type: str, confidences: dict, digital_signature: str) -> dict:
    cfg = config.risk()
    if verdict in cfg["not_assessed_verdicts"]:
        return {"score": None, "level": "not_assessed", "factors": []}

    factors: list[dict] = []

    def add(name: str, points: int, detail: str) -> None:
        if points:
            factors.append({"name": name, "points": points, "detail": detail})

    labels = config.load()["verdict_labels"]
    add("verdict", cfg["verdict_points"].get(verdict, 0), config.message("risk_verdict", verdict=labels.get(verdict, verdict)))

    for s in signals:
        sev = Severity(s.severity)
        if sev == Severity.OK:
            continue
        add(s.name, cfg["signal_points"].get(s.name, cfg["severity_points"][sev.value]), s.detail)

    if input_type != "pdf":
        add("read_by_ocr", cfg["read_by_ocr_points"], config.message("risk_ocr"))
        low = [c for c in confidences.values() if c < cfg["low_ocr_confidence_below"]]
        if low:
            add("low_ocr_confidence", cfg["low_ocr_confidence_points"], config.message("risk_low_confidence", conf=min(low)))

    if digital_signature == "valid" and verdict in ("VERIFIED", "VERIFIED_WITH_WARNINGS"):
        add("valid_signature", cfg["valid_signature_points"], config.message("risk_signature_valid"))

    score = max(0, min(100, sum(f["points"] for f in factors)))
    factors.sort(key=lambda f: -abs(f["points"]))
    return {"score": score, "level": level_for(score, cfg), "factors": factors}
