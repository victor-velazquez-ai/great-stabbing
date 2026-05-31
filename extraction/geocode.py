"""City → (lat, lon, NUTS-3) geocoder with a local cache.

For MVP we cache aggressively (one row per (country, city) pair) and fall
back to Nominatim only on cache miss. Nominatim is rate-limited to 1 req/sec
per their TOS — we sleep between misses.

Cache lives at ``extraction/geocode_cache.csv`` and is committed to the repo so
new operators don't re-hit the API for known cities.
"""

from __future__ import annotations

import csv
import logging
import time
from pathlib import Path

import requests

from adapters.common.http import DEFAULT_UA

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
GEOCODE_CACHE = REPO_ROOT / "extraction" / "geocode_cache.csv"

NOMINATIM = "https://nominatim.openstreetmap.org/search"

_cache: dict[tuple[str, str], tuple[float | None, float | None, str | None]] | None = None


def _load_cache() -> dict[tuple[str, str], tuple[float | None, float | None, str | None]]:
    global _cache
    if _cache is not None:
        return _cache
    _cache = {}
    if not GEOCODE_CACHE.exists():
        return _cache
    with GEOCODE_CACHE.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            key = (r["country"].upper(), r["city"].strip().lower())
            lat = float(r["lat"]) if r["lat"] else None
            lon = float(r["lon"]) if r["lon"] else None
            nuts = r.get("nuts_code") or None
            _cache[key] = (lat, lon, nuts)
    log.info("geocode cache: %d entries", len(_cache))
    return _cache


def _save_cache_row(country: str, city: str, lat: float | None, lon: float | None, nuts: str | None) -> None:
    GEOCODE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    new_file = not GEOCODE_CACHE.exists()
    with GEOCODE_CACHE.open("a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["country", "city", "lat", "lon", "nuts_code"])
        w.writerow([country.upper(), city, lat or "", lon or "", nuts or ""])


def _nominatim_lookup(city: str, country: str) -> tuple[float | None, float | None]:
    try:
        r = requests.get(
            NOMINATIM,
            params={
                "q": city,
                "countrycodes": country.lower(),
                "format": "json",
                "limit": 1,
            },
            timeout=20,
            headers={"User-Agent": DEFAULT_UA},
        )
        r.raise_for_status()
        data = r.json()
        if not data:
            return (None, None)
        return (float(data[0]["lat"]), float(data[0]["lon"]))
    except Exception as e:  # noqa: BLE001
        log.warning("[geocode] nominatim %s/%s → %s", country, city, e)
        return (None, None)
    finally:
        time.sleep(1.1)  # respect Nominatim 1 req/sec


def geocode_city(
    city: str, country: str, use_network: bool = True
) -> tuple[float | None, float | None, str | None]:
    """Return ``(lat, lon, nuts_code)`` or ``(None, None, None)`` if unknown.

    Always reads the cache first. Falls back to Nominatim only if
    ``use_network`` is True (default). Tests can set False to stay offline.
    NUTS-3 assignment is left blank for MVP; a future revision can use the
    NUTS GeoJSON to point-in-polygon the lat/lon.
    """
    if not city:
        return (None, None, None)
    cache = _load_cache()
    key = (country.upper(), city.strip().lower())
    if key in cache:
        return cache[key]
    if not use_network:
        return (None, None, None)

    lat, lon = _nominatim_lookup(city, country)
    nuts = None
    _save_cache_row(country, city, lat, lon, nuts)
    cache[key] = (lat, lon, nuts)
    return (lat, lon, nuts)
