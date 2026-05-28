"""Confidence scoring for incident records.

HIGH: any source is a police press release (outlet in POLICE_PR_OUTLETS).
MEDIUM: ≥2 independent outlets (distinct domains).
LOW: otherwise.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

POLICE_PR_OUTLETS = {
    "presseportal.de",
    "polizei.de",
    "polizia.it",
    "interno.gov.it",
    "interior.gob.es",
    "police.gov.uk",
    "police.uk",
    "interieur.gouv.fr",
    "politi.dk",
    "polisen.se",
}


def _domain(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def score(rec: dict[str, Any]) -> str:
    sources = rec.get("sources", [])
    domains = {_domain(s.get("url", "")) for s in sources if s.get("url")}
    domains.discard("")

    if any(d in POLICE_PR_OUTLETS or any(d.endswith("." + p) for p in POLICE_PR_OUTLETS) for d in domains):
        return "HIGH"
    if len(domains) >= 2:
        return "MEDIUM"
    return "LOW"
