"""GDELT 2.0 article fetcher — via the DOC API.

We use the GDELT DOC 2.0 search API (https://api.gdeltproject.org/api/v2/doc/doc)
rather than bulk GKG file processing. The DOC API takes a query string with
filters (sourcecountry, theme, domain, language) and returns matching articles
in JSON, capped at 250 per request.

Quotas: free, no auth needed. Reasonable to call 10-30 times/month per country.

GDELT theme codes we target (violent bodily-harm related):
- ``KILL`` — generic killing/death
- ``MURDER`` — murder language
- ``ATTACK`` — attack/assault
- ``TAX_FNCACT_VICTIM`` — victim of crime

Country codes: GDELT uses ISO 3166-1 alpha-2 (uppercase) in `sourcecountry`.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

import requests
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from adapters.common.http import DEFAULT_UA, _is_retryable

log = logging.getLogger(__name__)

DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"

# Country code in GDELT (ISO-3166-1 alpha-2 uppercase, but historical quirks
# for UK — GDELT accepts "UK" or "GB"; we send both for safety).
_COUNTRY_GDELT_CODES = {
    "UK": ("UK", "GB"),
    "FR": ("FR",),
    "DE": ("GE",),  # GDELT uses GE for Germany historically; some flows use DE
    "IT": ("IT",),
    "ES": ("SP",),  # GDELT uses SP for Spain
    "SE": ("SW",),  # GDELT uses SW for Sweden
}

THEMES = ("KILL", "MURDER", "ATTACK", "TAX_FNCACT_VICTIM")


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=2, max=20),
    retry=retry_if_exception(_is_retryable),
    reraise=True,
)
def _get_json(url: str, params: dict[str, Any], timeout: int = 60) -> dict:
    r = requests.get(url, params=params, timeout=timeout, headers={"User-Agent": DEFAULT_UA})
    r.raise_for_status()
    # GDELT sometimes returns empty body for "no results" — handle gracefully.
    if not r.text.strip():
        return {"articles": []}
    return r.json()


def _gdelt_date(d: date) -> str:
    """GDELT datetime format: YYYYMMDDHHMMSS."""
    return datetime(d.year, d.month, d.day).strftime("%Y%m%d%H%M%S")


def fetch_gdelt(country_iso: str, since: date, until: date) -> list[dict]:
    """Return GDELT DOC API hits for country, between since and until.

    Each record: ``{url, outlet, published_at, language, title, lead, source}``.
    """
    out: list[dict] = []
    codes = _COUNTRY_GDELT_CODES.get(country_iso.upper(), (country_iso.upper(),))

    for code in codes:
        theme_filter = " OR ".join(f"theme:{t}" for t in THEMES)
        query = f"sourcecountry:{code} ({theme_filter})"
        params = {
            "query": query,
            "mode": "ArtList",
            "format": "JSON",
            "maxrecords": 250,
            "sort": "DateDesc",
            "startdatetime": _gdelt_date(since),
            "enddatetime": _gdelt_date(until),
        }
        try:
            payload = _get_json(DOC_API, params)
        except Exception as e:  # noqa: BLE001
            log.warning("[gdelt] %s/%s → %s: %s", country_iso, code, type(e).__name__, e)
            continue

        arts = payload.get("articles", []) or []
        log.info("[gdelt] %s/%s: %d articles", country_iso, code, len(arts))

        for a in arts:
            out.append(
                {
                    "url": a.get("url"),
                    "outlet": a.get("domain") or a.get("sourcecountry"),
                    "published_at": a.get("seendate"),
                    "language": (a.get("language") or "").lower() or None,
                    "title": a.get("title") or "",
                    "lead": "",  # DOC API doesn't return article body
                    "source": "gdelt",
                    "country": country_iso.upper(),
                }
            )
    return out
