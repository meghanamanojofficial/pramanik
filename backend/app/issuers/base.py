from typing import TypedDict


class IssuerResult(TypedDict):
    reachable: bool
    found: bool
    status: str                 # "active" | "revoked" | "expired"
    matches: dict[str, bool]    # per field
    values: dict[str, str]      # issuer's value per field, demo only


def verify(certificate_number: str, fields: dict[str, str]) -> IssuerResult:
    """Ask an issuer whether a certificate exists and whether `fields` match its record.

    `fields` carries the four printed fields: certificate_number, holder_name,
    issue_date, income_amount. Concrete issuers live next to this file.
    """
    raise NotImplementedError
