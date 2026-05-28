"""Build data/parquet/nuts_regions.parquet from Eurostat GISCO.

Source: NUTS 2021 boundaries, 1:1M scale, EPSG:4326.

Population denominators come from Eurostat `demo_r_pjangrp3` (population on
1 January, by NUTS-3 region). For MVP we leave population_latest NULL — it
can be backfilled later from the bulk download at
https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/demo_r_pjangrp3
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import duckdb
import pandas as pd
import requests

NUTS_GEOJSON_URL = (
    "https://gisco-services.ec.europa.eu/distribution/v2/nuts/geojson/"
    "NUTS_RG_01M_2021_4326.geojson"
)

REPO_ROOT = Path(__file__).resolve().parents[1]
NUTS_DIR = REPO_ROOT / "data" / "nuts"
PARQUET_DIR = REPO_ROOT / "data" / "parquet"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def fetch_geojson() -> dict:
    NUTS_DIR.mkdir(parents=True, exist_ok=True)
    local = NUTS_DIR / "NUTS_RG_01M_2021_4326.geojson"
    if local.exists():
        log.info("using cached %s", local.relative_to(REPO_ROOT))
        with local.open(encoding="utf-8") as f:
            return json.load(f)

    log.info("downloading %s", NUTS_GEOJSON_URL)
    r = requests.get(NUTS_GEOJSON_URL, timeout=120)
    r.raise_for_status()
    local.write_bytes(r.content)
    return json.loads(r.content)


def _centroid(coords: list, geom_type: str) -> tuple[float, float]:
    """Cheap bbox-centre centroid. Good enough for label placement; not for area math."""
    flat: list[tuple[float, float]] = []

    def walk(c: list) -> None:
        if not c:
            return
        if isinstance(c[0], (int, float)):
            flat.append((float(c[0]), float(c[1])))
        else:
            for sub in c:
                walk(sub)

    walk(coords)
    if not flat:
        return (0.0, 0.0)
    xs = [p[0] for p in flat]
    ys = [p[1] for p in flat]
    return ((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0)


def to_dataframe(geo: dict) -> pd.DataFrame:
    rows = []
    for feat in geo.get("features", []):
        props = feat.get("properties", {})
        code = props.get("NUTS_ID") or props.get("id")
        if not code:
            continue
        geom = feat.get("geometry", {}) or {}
        lon, lat = _centroid(geom.get("coordinates", []), geom.get("type", ""))
        rows.append(
            {
                "code": code,
                "name_en": props.get("NAME_LATN") or props.get("NUTS_NAME") or code,
                "name_native": props.get("NUTS_NAME") or code,
                "parent_code": code[:-1] if len(code) > 2 else None,
                "level": int(props.get("LEVL_CODE", max(0, len(code) - 2))),
                "country": props.get("CNTR_CODE") or code[:2],
                "population_latest": None,
                "area_km2": None,
                "centroid_lat": lat,
                "centroid_lon": lon,
            }
        )
    df = pd.DataFrame(rows)
    df["population_latest"] = df["population_latest"].astype("Int64")
    df["area_km2"] = df["area_km2"].astype("Float64")
    return df


def main() -> None:
    geo = fetch_geojson()
    df = to_dataframe(geo)
    log.info("parsed %d regions across %d countries", len(df), df["country"].nunique())

    PARQUET_DIR.mkdir(parents=True, exist_ok=True)
    out = PARQUET_DIR / "nuts_regions.parquet"
    con = duckdb.connect()
    con.register("df", df)
    con.execute(f"COPY df TO '{out.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    log.info("wrote %s (%d rows)", out.relative_to(REPO_ROOT), len(df))


if __name__ == "__main__":
    main()
