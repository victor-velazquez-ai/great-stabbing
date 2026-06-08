"""Build a compact GeoJSON for the live MVP countries.

Pulls Eurostat NUTS 03M boundaries (already coarser than 01M, ~10x smaller).
Filters to:
  - UK NUTS-1 (12 regions — matches the granularity of UK data)
  - FR NUTS-3 (101 départements — matches the granularity of FR data)

Simplifies with Shapely's Douglas-Peucker (tolerance tuned to keep ~50KB
total). Writes to ``site/public/data/regions.geojson`` — served as a static
asset, loaded by MapLibre.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
NUTS_DIR = REPO_ROOT / "data" / "nuts"
SITE_DATA = REPO_ROOT / "site" / "public" / "data"

# 03M scale — much smaller than the 01M we use for the lookup, fine for choropleth.
URL = (
    "https://gisco-services.ec.europa.eu/distribution/v2/nuts/geojson/"
    "NUTS_RG_03M_2021_4326.geojson"
)
LOCAL = NUTS_DIR / "NUTS_RG_03M_2021_4326.geojson"

# Per-country filter: keep these (country, level) combos.
# Mixed-level is intentional — adapters publish at the granularity their
# source supports. NUTS-0 countries (DE, SE) get rendered as a single
# country-wide polygon shaded by the national rate.
KEEP = {
    ("UK", 1),
    ("FR", 3),
    ("IT", 2),
    ("DE", 0),
    ("DE", 1),
    ("SE", 0),
    ("ES", 3),
    ("DK", 2),
    ("IE", 0),
    ("NL", 2),
    ("AT", 2),
    ("BE", 2),
    ("PT", 2),
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def fetch_geojson() -> dict:
    NUTS_DIR.mkdir(parents=True, exist_ok=True)
    if LOCAL.exists():
        log.info("using cached %s", LOCAL.relative_to(REPO_ROOT))
        return json.loads(LOCAL.read_text(encoding="utf-8"))
    log.info("downloading %s", URL)
    r = requests.get(URL, timeout=180)
    r.raise_for_status()
    LOCAL.write_bytes(r.content)
    return json.loads(r.content)


def _simplify_coords(coords: list, tolerance: float) -> list:
    """Simple Douglas-Peucker via shapely for each polygon. If shapely isn't
    available, return unchanged."""
    try:
        from shapely.geometry import shape, mapping  # type: ignore
    except ImportError:
        log.warning("shapely not installed — skipping simplification")
        return coords
    return coords  # placeholder; we use shapely on the whole geometry below


def _simplify_geometry(geom: dict, tolerance: float) -> dict:
    try:
        from shapely.geometry import shape, mapping
        s = shape(geom)
        simplified = s.simplify(tolerance, preserve_topology=True)
        if simplified.is_empty:
            return geom
        return mapping(simplified)
    except ImportError:
        return geom


def main() -> None:
    geo = fetch_geojson()
    kept_features = []
    for feat in geo.get("features", []):
        props = feat.get("properties", {})
        country = props.get("CNTR_CODE") or (props.get("NUTS_ID", "")[:2])
        level = int(props.get("LEVL_CODE", -1))
        if (country, level) not in KEEP:
            continue
        # Strip props down to what the site needs.
        slim_props = {
            "code": props.get("NUTS_ID"),
            "name": props.get("NAME_LATN") or props.get("NUTS_NAME"),
            "level": level,
            "country": country,
        }
        # Simplify geometry. tolerance in degrees: 0.01 ≈ 1km at equator.
        geom = _simplify_geometry(feat["geometry"], tolerance=0.02)
        kept_features.append({"type": "Feature", "properties": slim_props, "geometry": geom})

    out = {"type": "FeatureCollection", "features": kept_features}
    SITE_DATA.mkdir(parents=True, exist_ok=True)
    out_path = SITE_DATA / "regions.geojson"
    out_path.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    size_kb = out_path.stat().st_size / 1024
    log.info(
        "wrote %s — %d features, %.1f KB",
        out_path.relative_to(REPO_ROOT), len(kept_features), size_kb,
    )


if __name__ == "__main__":
    main()
