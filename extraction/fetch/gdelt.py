"""GDELT 2.0 GKG fetcher.

Free, multilingual, ~15-min latency. We pull articles tagged with violence-related
themes (KILL, MURDER, ATTACK, ARREST) for the MVP countries.

Stub: full implementation pulls the GKG CSV.gz files from
http://data.gdeltproject.org/gdeltv2/  and filters by SourceCommonName +
V2Themes + V2Locations.
"""

from __future__ import annotations

from datetime import date


def fetch_gdelt(country_iso: str, since: date, until: date) -> list[dict]:
    """Return raw GDELT records for country_iso between since and until.

    Each record is a dict with at least: url, outlet, published_at, language,
    title, lead (first ~500 chars of article body if available).
    """
    raise NotImplementedError("GDELT fetcher — implement in Week 11")
