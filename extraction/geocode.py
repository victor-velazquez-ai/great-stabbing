"""City → (lat, lon, NUTS-3) geocoder with disambiguation and local cache.

Uses Nominatim's *structured* search (separate city/state/country fields)
rather than free-text ``q=``. Free-text matches the first plausible hit;
structured queries respect the geographic hierarchy and avoid common
mis-disambiguation (e.g. "Denton" → Yorkshire instead of Greater Manchester;
"Vienne" → small town in Poitou-Charentes instead of Isère).

The cache key includes ``region_hint`` so two incidents in different
homonymous cities don't collide.

Cache lives at ``extraction/geocode_cache.csv`` and is committed to the repo
so re-runs and new operators don't re-hit the Nominatim API for known cities.
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

_NOMINATIM_COUNTRY_OVERRIDE = {
    # Nominatim uses ISO 3166-1 alpha-2 lowercase. Our pipeline carries "UK"
    # for the United Kingdom (matching ONS/the rest of our data); Nominatim's
    # canonical alpha-2 is "gb".
    "UK": "gb",
}

# Cache schema. Older cache files may have fewer columns — we read them
# defensively below.
_CACHE_FIELDS = ("country", "city", "region_hint", "lat", "lon", "nuts_code")

_cache: dict[tuple[str, str, str], tuple[float | None, float | None, str | None]] | None = None


def _load_cache() -> dict[tuple[str, str, str], tuple[float | None, float | None, str | None]]:
    global _cache
    if _cache is not None:
        return _cache
    _cache = {}
    if not GEOCODE_CACHE.exists():
        return _cache
    with GEOCODE_CACHE.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            key = (
                r["country"].upper(),
                r["city"].strip().lower(),
                (r.get("region_hint") or "").strip().lower(),
            )
            lat = float(r["lat"]) if r.get("lat") else None
            lon = float(r["lon"]) if r.get("lon") else None
            nuts = r.get("nuts_code") or None
            _cache[key] = (lat, lon, nuts)
    log.info("geocode cache: %d entries", len(_cache))
    return _cache


def _save_cache_row(country: str, city: str, region_hint: str, lat: float | None, lon: float | None, nuts: str | None) -> None:
    GEOCODE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    new_file = not GEOCODE_CACHE.exists()
    # If the file exists but with old schema (missing region_hint), rewrite it.
    if not new_file:
        with GEOCODE_CACHE.open(encoding="utf-8") as f:
            header = f.readline().strip().split(",")
        if header != list(_CACHE_FIELDS):
            # Rewrite the whole file with the new schema, preserving existing rows.
            rows = []
            with GEOCODE_CACHE.open(encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    rows.append({
                        "country": r.get("country", "").upper(),
                        "city": r.get("city", ""),
                        "region_hint": r.get("region_hint", ""),
                        "lat": r.get("lat", ""),
                        "lon": r.get("lon", ""),
                        "nuts_code": r.get("nuts_code", ""),
                    })
            with GEOCODE_CACHE.open("w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=_CACHE_FIELDS)
                w.writeheader()
                for r in rows:
                    w.writerow(r)
            new_file = False
    with GEOCODE_CACHE.open("a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(_CACHE_FIELDS)
        w.writerow([country.upper(), city, region_hint, lat or "", lon or "", nuts or ""])


def _nominatim_structured_lookup(
    city: str, country: str, region_hint: str | None = None
) -> tuple[float | None, float | None]:
    """Hit Nominatim with structured city/state/country params."""
    cc = _NOMINATIM_COUNTRY_OVERRIDE.get(country.upper(), country.lower())
    params: dict[str, str | int] = {
        "city": city,
        "countrycodes": cc,
        "format": "json",
        "limit": 1,
    }
    if region_hint:
        # Nominatim's "state" parameter covers regions / Bundesländer /
        # départements / régioni — appropriate for our region_hint use case.
        params["state"] = region_hint
    try:
        r = requests.get(
            NOMINATIM, params=params, timeout=20, headers={"User-Agent": DEFAULT_UA}
        )
        r.raise_for_status()
        data = r.json()
        if not data and region_hint:
            # If structured-with-hint returned nothing, retry without the hint —
            # better a fuzzy match than no match.
            del params["state"]
            r = requests.get(
                NOMINATIM, params=params, timeout=20, headers={"User-Agent": DEFAULT_UA}
            )
            r.raise_for_status()
            data = r.json()
        if not data:
            return (None, None)
        return (float(data[0]["lat"]), float(data[0]["lon"]))
    except Exception as e:  # noqa: BLE001
        log.warning("[geocode] nominatim %s/%s/%s → %s", country, city, region_hint or "-", e)
        return (None, None)
    finally:
        time.sleep(1.1)  # respect Nominatim 1 req/sec ceiling


def geocode_city(
    city: str,
    country: str,
    region_hint: str | None = None,
    use_network: bool = True,
) -> tuple[float | None, float | None, str | None]:
    """Return ``(lat, lon, nuts_code)`` for ``city`` in ``country``.

    ``region_hint`` (e.g. "Greater Manchester", "Isère") narrows the search
    when a city name is ambiguous. NUTS-3 assignment is left blank for MVP;
    a future revision can point-in-polygon the result against NUTS geometry.
    """
    if not city:
        return (None, None, None)
    cache = _load_cache()
    key = (country.upper(), city.strip().lower(), (region_hint or "").strip().lower())
    if key in cache:
        return cache[key]
    if not use_network:
        return (None, None, None)

    lat, lon = _nominatim_structured_lookup(city, country, region_hint)
    nuts = None
    _save_cache_row(country, city, region_hint or "", lat, lon, nuts)
    cache[key] = (lat, lon, nuts)
    return (lat, lon, nuts)


def reset_cache_test_only() -> None:
    """Test helper — drop the in-memory cache so a fresh load happens."""
    global _cache
    _cache = None
