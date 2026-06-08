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

    # NL provinces (NUTS-2), CBS mid-2024 estimates.
    ("NL11",   598_000,  2_960, 53.22,  6.57),  # Groningen
    ("NL12",   661_000,  5_749, 53.20,  5.78),  # Fryslân
    ("NL13",   504_000,  2_680, 52.95,  6.62),  # Drenthe
    ("NL21", 1_173_000,  3_421, 52.42,  6.50),  # Overijssel
    ("NL22", 2_154_000,  5_136, 52.05,  5.90),  # Gelderland
    ("NL23",   458_000,  2_412, 52.50,  5.45),  # Flevoland
    ("NL31", 1_412_000,  1_485, 52.09,  5.12),  # Utrecht
    ("NL32", 2_955_000,  4_092, 52.50,  4.85),  # Noord-Holland (Amsterdam)
    ("NL33", 3_870_000,  3_419, 51.95,  4.42),  # Zuid-Holland (Rotterdam, The Hague)
    ("NL34",   391_000,  2_934, 51.50,  3.85),  # Zeeland
    ("NL41", 2_640_000,  5_082, 51.55,  5.05),  # Noord-Brabant
    ("NL42", 1_133_000,  2_209, 51.20,  6.00),  # Limburg

    # DK regions (NUTS-2).
    ("DK01", 1_891_000,  2_561, 55.65, 12.55),  # Hovedstaden
    ("DK02",   850_000,  7_217, 55.25, 11.92),  # Sjælland
    ("DK03", 1_239_000, 12_206, 55.40,  9.78),  # Syddanmark
    ("DK04", 1_352_000, 13_124, 56.20,  9.55),  # Midtjylland
    ("DK05",   589_000,  7_876, 57.05,  9.92),  # Nordjylland

    # IE NUTS-0.
    ("IE",   5_281_000, 69_797, 53.40, -8.00),
    # IE NUTS-1 (Northern + Eastern, Southern).
    ("IE0",  5_281_000, 69_797, 53.40, -8.00),

    # AT Bundesländer (NUTS-2), Statistik Austria mid-2024.
    ("AT", 9_153_000, 83_879, 47.60, 13.30),
    ("AT11",  290_000,  3_965, 47.85, 16.55),  # Burgenland
    ("AT12", 1_700_000, 19_186, 48.30, 15.55),  # Niederösterreich
    ("AT13", 2_006_000,     415, 48.20, 16.37),  # Wien
    ("AT21",  566_000,  9_536, 46.65, 14.30),  # Kärnten
    ("AT22", 1_268_000, 16_401, 47.10, 15.10),  # Steiermark
    ("AT31", 1_530_000, 11_982, 48.30, 14.27),  # Oberösterreich
    ("AT32",  570_000,  7_154, 47.80, 13.05),  # Salzburg
    ("AT33",  773_000, 12_647, 47.27, 11.40),  # Tirol
    ("AT34",  402_000,  2_601, 47.27,  9.85),  # Vorarlberg

    # BE Provinces (NUTS-2), Statbel mid-2024.
    ("BE", 11_785_000, 30_528, 50.50,  4.50),
    ("BE10", 1_226_000,    161, 50.85,  4.35),  # Région de Bruxelles
    ("BE21", 1_953_000,  2_867, 51.20,  4.40),  # Antwerpen
    ("BE22", 1_205_000,  2_421, 50.95,  5.50),  # Limburg (BE)
    ("BE23", 1_550_000,  3_007, 51.05,  3.73),  # Oost-Vlaanderen
    ("BE24", 1_196_000,  2_106, 50.88,  4.70),  # Vlaams-Brabant
    ("BE25", 1_226_000,  3_125, 51.00,  3.18),  # West-Vlaanderen
    ("BE31",   413_000,  2_106, 50.65,  4.62),  # Brabant wallon
    ("BE32", 1_360_000,  3_786, 50.45,  3.95),  # Hainaut
    ("BE33", 1_117_000,  3_862, 50.65,  5.55),  # Liège
    ("BE34",   289_000,  4_440, 49.97,  5.30),  # Luxembourg (BE)
    ("BE35",   500_000,  3_660, 50.45,  4.85),  # Namur

    # PT distritos (NUTS-3 mapping is complex; use NUTS-2 for now).
    ("PT", 10_640_000, 92_212, 39.50, -8.00),
    ("PT11", 3_686_000, 21_278, 41.15, -8.62),  # Norte
    ("PT15",   441_000,  4_996, 37.10, -7.94),  # Algarve
    ("PT16", 2_226_000, 28_199, 40.20, -8.40),  # Centro (PT)
    ("PT17", 2_865_000,  3_001, 38.74, -9.14),  # Área Metropolitana de Lisboa
    ("PT18",  696_000, 31_605, 38.57, -7.91),  # Alentejo
    ("PT20",  236_000,  2_322, 38.66, -27.22),  # Açores
    ("PT30",  253_000,    802, 32.74, -16.96),  # Madeira
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
