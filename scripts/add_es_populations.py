"""Backfill ES NUTS-3 (provincia) populations in nuts_regions.parquet.

Hand-curated from INE Padrón Continuo 2024 (resident population at 1 Jan).
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

# Spanish NUTS-3 (provincia) populations, INE Padrón 2024 estimates.
ES_NUTS3 = [
    ("ES111", "A Coruña",                1_133_540),
    ("ES112", "Lugo",                      324_180),
    ("ES113", "Ourense",                   305_700),
    ("ES114", "Pontevedra",                949_140),
    ("ES120", "Asturias",                1_001_390),
    ("ES130", "Cantabria",                 591_550),
    ("ES211", "Álava",                     342_220),
    ("ES212", "Gipuzkoa",                  728_750),
    ("ES213", "Bizkaia",                 1_153_910),
    ("ES220", "Navarra",                   674_320),
    ("ES230", "La Rioja",                  324_350),
    ("ES241", "Huesca",                    227_590),
    ("ES242", "Teruel",                    134_300),
    ("ES243", "Zaragoza",                  998_530),
    ("ES300", "Madrid",                  6_896_000),
    ("ES411", "Ávila",                     158_140),
    ("ES412", "Burgos",                    361_010),
    ("ES413", "León",                      450_780),
    ("ES414", "Palencia",                  158_580),
    ("ES415", "Salamanca",                 327_280),
    ("ES416", "Segovia",                   156_240),
    ("ES417", "Soria",                      88_990),
    ("ES418", "Valladolid",                522_330),
    ("ES419", "Zamora",                    167_180),
    ("ES421", "Albacete",                  389_660),
    ("ES422", "Ciudad Real",               491_400),
    ("ES423", "Cuenca",                    194_080),
    ("ES424", "Guadalajara",               282_010),
    ("ES425", "Toledo",                    731_800),
    ("ES431", "Badajoz",                   665_180),
    ("ES432", "Cáceres",                   384_660),
    ("ES511", "Barcelona",               5_787_500),
    ("ES512", "Girona",                    809_120),
    ("ES513", "Lleida",                    440_810),
    ("ES514", "Tarragona",                 837_220),
    ("ES521", "Alicante/Alacant",        1_982_290),
    ("ES522", "Castellón/Castelló",        598_780),
    ("ES523", "Valencia/València",       2_640_320),
    ("ES531", "Eivissa, Formentera",       175_780),
    ("ES532", "Illes Balears",           1_220_330),
    ("ES533", "Mallorca",                  942_640),
    ("ES611", "Almería",                   758_980),
    ("ES612", "Cádiz",                   1_271_410),
    ("ES613", "Córdoba",                   790_540),
    ("ES614", "Granada",                   932_400),
    ("ES615", "Huelva",                    536_990),
    ("ES616", "Jaén",                      621_460),
    ("ES617", "Málaga",                  1_753_200),
    ("ES618", "Sevilla",                 1_973_640),
    ("ES620", "Murcia",                  1_581_780),
    ("ES630", "Ceuta",                      83_840),
    ("ES640", "Melilla",                    86_120),
    ("ES703", "Las Palmas",              1_173_690),
    ("ES704", "Santa Cruz de Tenerife",  1_103_410),
]


def main() -> None:
    if not NUTS_PARQUET.exists():
        raise SystemExit(f"{NUTS_PARQUET} missing.")

    con = duckdb.connect()
    existing = con.execute(
        f"SELECT * FROM read_parquet('{NUTS_PARQUET.as_posix()}')"
    ).df()

    by_code = {r["code"]: dict(r) for _, r in existing.iterrows()}
    updated = 0
    for code, name, pop in ES_NUTS3:
        if code not in by_code:
            log.warning("[ES-pop] %s (%s) not in nuts_regions.parquet — skipping", code, name)
            continue
        by_code[code]["population_latest"] = pop
        updated += 1

    out = pd.DataFrame(by_code.values())
    out["population_latest"] = out["population_latest"].astype("Int64")
    out["area_km2"] = out["area_km2"].astype("Float64")

    con.register("out", out)
    con.execute(
        f"COPY out TO '{NUTS_PARQUET.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    log.info("[ES-pop] updated %d/%d ES NUTS-3 rows", updated, len(ES_NUTS3))


if __name__ == "__main__":
    main()
