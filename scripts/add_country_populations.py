"""Backfill NUTS-0 (country-level) populations in nuts_regions.parquet.

Eurostat's NUTS GeoJSON carries the geometry but not population. Several
adapters (DE Zeitreihen, future country-level views) need a country
denominator. Hand-curated from official mid-2024 estimates.

Idempotent.
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

# (code, population_latest mid-2024 estimate, area_km2, centroid lat/lon)
COUNTRY_POPS = [
    ("DE", 83_577_140, 357_596, 51.10, 10.40),
    ("FR", 68_400_000, 643_801, 46.50,  2.40),
    ("IT", 58_950_000, 301_340, 42.50, 12.50),
    ("ES", 48_610_000, 505_990, 40.20, -3.70),
    ("SE", 10_550_000, 450_295, 62.00, 15.00),
    # UK is added by add_uk_to_nuts.py

    # DE Bundesländer (NUTS-1) — Destatis mid-2024 estimates.
    ("DE1", 11_320_000,  35_751, 48.66, 9.35),  # Baden-Württemberg
    ("DE2", 13_440_000,  70_550, 48.85, 11.50), # Bayern
    ("DE3",  3_846_000,     891, 52.52, 13.40), # Berlin
    ("DE4",  2_586_000,  29_654, 52.40, 13.00), # Brandenburg
    ("DE5",    682_000,     419, 53.08, 8.80),  # Bremen
    ("DE6",  1_910_000,     755, 53.55, 10.00), # Hamburg
    ("DE7",  6_390_000,  21_115, 50.65, 9.16),  # Hessen
    ("DE8",  1_613_000,  23_295, 53.61, 12.71), # Mecklenburg-Vorpommern
    ("DE9",  8_138_000,  47_710, 52.63, 9.85),  # Niedersachsen
    ("DEA", 18_185_000,  34_113, 51.43, 7.66),  # Nordrhein-Westfalen
    ("DEB",  4_158_000,  19_853, 49.75, 7.51),  # Rheinland-Pfalz
    ("DEC",    993_000,   2_570, 49.39, 7.02),  # Saarland
    ("DED",  4_087_000,  18_450, 51.05, 13.20), # Sachsen
    ("DEE",  2_186_000,  20_454, 51.99, 11.62), # Sachsen-Anhalt
    ("DEF",  2_953_000,  15_802, 54.20, 9.70),  # Schleswig-Holstein
    ("DEG",  2_103_000,  16_172, 50.90, 11.04), # Thüringen
]


def main() -> None:
    if not NUTS_PARQUET.exists():
        raise SystemExit(f"{NUTS_PARQUET} missing.")

    con = duckdb.connect()
    existing = con.execute(
        f"SELECT * FROM read_parquet('{NUTS_PARQUET.as_posix()}')"
    ).df()

    by_code = {r["code"]: dict(r) for _, r in existing.iterrows()}
    for code, pop, area, lat, lon in COUNTRY_POPS:
        if code not in by_code:
            log.warning("[country-pop] %s not in nuts_regions.parquet — skipping", code)
            continue
        by_code[code]["population_latest"] = pop
        by_code[code]["area_km2"] = float(area)
        if pd.isna(by_code[code].get("centroid_lat")):
            by_code[code]["centroid_lat"] = lat
            by_code[code]["centroid_lon"] = lon

    out = pd.DataFrame(by_code.values())
    out["population_latest"] = out["population_latest"].astype("Int64")
    out["area_km2"] = out["area_km2"].astype("Float64")

    con.register("out", out)
    con.execute(
        f"COPY out TO '{NUTS_PARQUET.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    log.info("[country-pop] updated %d NUTS-0 country rows", len(COUNTRY_POPS))


if __name__ == "__main__":
    main()
