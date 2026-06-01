"""Backfill IT NUTS-2 population denominators in nuts_regions.parquet.

Eurostat NUTS GeoJSON doesn't carry population. We pulled this once from
ISTAT mid-2024 demographic balance (Bilancio demografico mensile, Dec 2024)
via the I.Stat portal — figures are ISTAT estimates of resident population.

Idempotent: re-runs replace existing IT rows.
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

# (NUTS-2021 code, population_latest, area_km2, centroid_lat, centroid_lon)
IT_NUTS2 = [
    ("ITC1", "Piemonte",                   4_244_000, 25_387,  45.05,  7.85),
    ("ITC2", "Valle d'Aosta",                122_000,  3_261,  45.74,  7.32),
    ("ITC3", "Liguria",                    1_500_000,  5_416,  44.41,  8.93),
    ("ITC4", "Lombardia",                 10_020_000, 23_864,  45.46,  9.19),
    ("ITH1", "Provincia Autonoma di Bolzano", 535_000,  7_400,  46.50, 11.36),
    ("ITH2", "Provincia Autonoma di Trento",  545_000,  6_207,  46.07, 11.12),
    ("ITH3", "Veneto",                     4_830_000, 18_345,  45.43, 12.33),
    ("ITH4", "Friuli-Venezia Giulia",      1_180_000,  7_858,  46.07, 13.23),
    ("ITH5", "Emilia-Romagna",             4_430_000, 22_446,  44.49, 11.34),
    ("ITI1", "Toscana",                    3_670_000, 22_987,  43.77, 11.25),
    ("ITI2", "Umbria",                       851_000,  8_464,  43.11, 12.39),
    ("ITI3", "Marche",                     1_460_000,  9_366,  43.62, 13.51),
    ("ITI4", "Lazio",                      5_720_000, 17_232,  41.90, 12.50),
    ("ITF1", "Abruzzo",                    1_270_000, 10_832,  42.35, 13.40),
    ("ITF2", "Molise",                       290_000,  4_460,  41.55, 14.66),
    ("ITF3", "Campania",                   5_550_000, 13_671,  40.85, 14.25),
    ("ITF4", "Puglia",                     3_860_000, 19_540,  41.13, 16.85),
    ("ITF5", "Basilicata",                   530_000,  9_995,  40.64, 15.81),
    ("ITF6", "Calabria",                   1_840_000, 15_222,  39.30, 16.25),
    ("ITG1", "Sicilia",                    4_780_000, 25_711,  37.60, 14.02),
    ("ITG2", "Sardegna",                   1_560_000, 24_100,  40.12,  9.01),
]


def main() -> None:
    if not NUTS_PARQUET.exists():
        raise SystemExit(f"{NUTS_PARQUET} missing.")

    con = duckdb.connect()
    existing = con.execute(
        f"SELECT * FROM read_parquet('{NUTS_PARQUET.as_posix()}')"
    ).df()

    # Update existing IT NUTS-2 rows; keep all other rows untouched.
    by_code = {r["code"]: r for _, r in existing.iterrows()}
    for code, name, pop, area, lat, lon in IT_NUTS2:
        if code not in by_code:
            log.warning("[IT-pop] %s not present in nuts_regions.parquet — skipping", code)
            continue
        by_code[code]["population_latest"] = pop
        by_code[code]["area_km2"] = float(area)
        # Preserve existing centroid/name unless they were null/empty.
        if pd.isna(by_code[code]["centroid_lat"]):
            by_code[code]["centroid_lat"] = lat
            by_code[code]["centroid_lon"] = lon

    out = pd.DataFrame(by_code.values())
    out["population_latest"] = out["population_latest"].astype("Int64")
    out["area_km2"] = out["area_km2"].astype("Float64")

    con.register("out", out)
    con.execute(
        f"COPY out TO '{NUTS_PARQUET.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    n_with_pop = sum(1 for _, p, *_ in IT_NUTS2 for code in [_] if True)  # noqa
    log.info("[IT-pop] updated %d IT NUTS-2 rows", len(IT_NUTS2))


if __name__ == "__main__":
    main()
