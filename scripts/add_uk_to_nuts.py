"""Append UK ITL regions to data/parquet/nuts_regions.parquet.

After Brexit, Eurostat dropped the UK from NUTS 2021. ONS adopted ITL
(International Territorial Levels) with the same hierarchical structure and
codes. We keep using the `UK*` codes — they are stable and match what ONS
publishes — but we have to add them to our lookup manually.

For MVP we add NUTS-0 (UK) and NUTS-1 (UKC..UKN). NUTS-2/3 can come later.

Population denominators from ONS mid-2023 estimates (publicly available).
Centroid lat/lon are approximate region centres for label placement.
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
NUTS_PARQUET = REPO_ROOT / "data" / "parquet" / "nuts_regions.parquet"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# UK NUTS-0 + NUTS-1. Populations from ONS mid-2023 estimates.
UK_REGIONS = [
    {
        "code": "UK",
        "name_en": "United Kingdom",
        "name_native": "United Kingdom",
        "parent_code": None,
        "level": 0,
        "country": "UK",
        "population_latest": 68265209,
        "area_km2": 243610.0,
        "centroid_lat": 54.0,
        "centroid_lon": -2.5,
    },
    {
        "code": "UKC",
        "name_en": "North East (England)",
        "name_native": "North East",
        "parent_code": "UK",
        "level": 1,
        "country": "UK",
        "population_latest": 2657898,
        "area_km2": 8581.0,
        "centroid_lat": 55.0,
        "centroid_lon": -1.8,
    },
    {
        "code": "UKD",
        "name_en": "North West (England)",
        "name_native": "North West",
        "parent_code": "UK",
        "level": 1,
        "country": "UK",
        "population_latest": 7516113,
        "area_km2": 14165.0,
        "centroid_lat": 53.8,
        "centroid_lon": -2.7,
    },
    {
        "code": "UKE",
        "name_en": "Yorkshire and The Humber",
        "name_native": "Yorkshire and The Humber",
        "parent_code": "UK",
        "level": 1,
        "country": "UK",
        "population_latest": 5556470,
        "area_km2": 15420.0,
        "centroid_lat": 53.9,
        "centroid_lon": -1.1,
    },
    {
        "code": "UKF",
        "name_en": "East Midlands (England)",
        "name_native": "East Midlands",
        "parent_code": "UK",
        "level": 1,
        "country": "UK",
        "population_latest": 4934939,
        "area_km2": 15627.0,
        "centroid_lat": 52.9,
        "centroid_lon": -1.0,
    },
    {
        "code": "UKG",
        "name_en": "West Midlands (England)",
        "name_native": "West Midlands",
        "parent_code": "UK",
        "level": 1,
        "country": "UK",
        "population_latest": 6031184,
        "area_km2": 13003.0,
        "centroid_lat": 52.5,
        "centroid_lon": -2.0,
    },
    {
        "code": "UKH",
        "name_en": "East of England",
        "name_native": "East of England",
        "parent_code": "UK",
        "level": 1,
        "country": "UK",
        "population_latest": 6398497,
        "area_km2": 19120.0,
        "centroid_lat": 52.2,
        "centroid_lon": 0.5,
    },
    {
        "code": "UKI",
        "name_en": "London",
        "name_native": "London",
        "parent_code": "UK",
        "level": 1,
        "country": "UK",
        "population_latest": 8866180,
        "area_km2": 1572.0,
        "centroid_lat": 51.5,
        "centroid_lon": -0.1,
    },
    {
        "code": "UKJ",
        "name_en": "South East (England)",
        "name_native": "South East",
        "parent_code": "UK",
        "level": 1,
        "country": "UK",
        "population_latest": 9379024,
        "area_km2": 19096.0,
        "centroid_lat": 51.3,
        "centroid_lon": -0.7,
    },
    {
        "code": "UKK",
        "name_en": "South West (England)",
        "name_native": "South West",
        "parent_code": "UK",
        "level": 1,
        "country": "UK",
        "population_latest": 5764881,
        "area_km2": 23837.0,
        "centroid_lat": 51.0,
        "centroid_lon": -3.5,
    },
    {
        "code": "UKL",
        "name_en": "Wales",
        "name_native": "Cymru / Wales",
        "parent_code": "UK",
        "level": 1,
        "country": "UK",
        "population_latest": 3164470,
        "area_km2": 20779.0,
        "centroid_lat": 52.3,
        "centroid_lon": -3.7,
    },
    {
        "code": "UKM",
        "name_en": "Scotland",
        "name_native": "Scotland / Alba",
        "parent_code": "UK",
        "level": 1,
        "country": "UK",
        "population_latest": 5479900,
        "area_km2": 77933.0,
        "centroid_lat": 56.5,
        "centroid_lon": -4.2,
    },
    {
        "code": "UKN",
        "name_en": "Northern Ireland",
        "name_native": "Northern Ireland",
        "parent_code": "UK",
        "level": 1,
        "country": "UK",
        "population_latest": 1910543,
        "area_km2": 14130.0,
        "centroid_lat": 54.7,
        "centroid_lon": -6.7,
    },
]


def main() -> None:
    if not NUTS_PARQUET.exists():
        raise SystemExit(
            f"{NUTS_PARQUET} missing. Run scripts/refresh_nuts_lookup.py first."
        )

    con = duckdb.connect()
    existing = con.execute(
        f"SELECT * FROM read_parquet('{NUTS_PARQUET.as_posix()}')"
    ).df()
    log.info("loaded %d existing regions", len(existing))

    new_df = pd.DataFrame(UK_REGIONS)
    new_df["population_latest"] = new_df["population_latest"].astype("Int64")
    new_df["area_km2"] = new_df["area_km2"].astype("Float64")

    # Drop any pre-existing UK rows (idempotent re-run).
    existing = existing[~existing["code"].isin(new_df["code"])]

    combined = pd.concat([existing, new_df], ignore_index=True)
    log.info("writing %d total regions (added %d UK rows)", len(combined), len(new_df))

    con.register("combined", combined)
    con.execute(
        f"COPY combined TO '{NUTS_PARQUET.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)"
    )


if __name__ == "__main__":
    main()
