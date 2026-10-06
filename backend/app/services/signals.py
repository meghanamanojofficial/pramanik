"""Findings collected while checking a document. A signal never decides a verdict by itself;
verdict.finalize() reads them after the issuer lookup has had its say."""
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional


class Severity(str, Enum):
    OK = "ok"          # informational, shown as a note
    WEAK = "weak"      # worth a look; VERIFIED becomes VERIFIED_WITH_WARNINGS
    STRONG = "strong"  # integrity concern; VERIFIED becomes MATCHES_RECORD_INTEGRITY_CONCERNS
    FAIL = "fail"      # the document contradicts itself or its issuer-signed QR


@dataclass
class Signal:
    name: str
    severity: Severity
    detail: str
    region: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "severity": Severity(self.severity).value, "detail": self.detail, "region": self.region}
