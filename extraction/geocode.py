"""City → (lat, lon, NUTS-3) geocoder.

Uses a local CSV cache to avoid hammering external APIs. Built incrementally
as new cities are seen. First lookup of a new city falls back to Nominatim
(OpenStreetMap) with rate-limiting; result is then cached.

Stub: cache layer + fallback implemented in Week 11+.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
GEOCODE_CACHE = REPO_ROOT / "extraction" / "geocode_cache.csv"


def geocode_city(city: str, country: str) -> tuple[float | None, float | None, str | None]:
    """Return (lat, lon, nuts_code) or (None, None, None) if unknown."""
    raise NotImplementedError("Geocoder — implement in Week 11")
