"""NUTS lookup helpers.

`nuts_regions.parquet` is the single source of truth for region codes, names,
parents, and population denominators. Built once by `scripts/refresh_nuts_lookup.py`
from Eurostat sources, then committed.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import duckdb
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
NUTS_PARQUET = REPO_ROOT / "data" / "parquet" / "nuts_regions.parquet"


@lru_cache(maxsize=1)
def _nuts_df() -> pd.DataFrame:
    if not NUTS_PARQUET.exists():
        raise FileNotFoundError(
            f"{NUTS_PARQUET} not found. Run `python scripts/refresh_nuts_lookup.py` first."
        )
    return duckdb.connect().execute(f"SELECT * FROM read_parquet('{NUTS_PARQUET.as_posix()}')").df()


def is_valid_nuts(code: str) -> bool:
    return code in set(_nuts_df()["code"])


def level_of(code: str) -> int:
    """NUTS-0 = 2-char ISO, NUTS-1 = 3 chars, NUTS-2 = 4, NUTS-3 = 5."""
    return max(0, len(code) - 2)


def parent_of(code: str) -> str | None:
    if level_of(code) == 0:
        return None
    return code[:-1]


def country_of(code: str) -> str:
    return code[:2]


def population(code: str) -> int | None:
    df = _nuts_df()
    row = df[df["code"] == code]
    if row.empty:
        return None
    val = row.iloc[0]["population_latest"]
    return None if pd.isna(val) else int(val)


def load_region_map(country: str) -> dict[str, str]:
    """Read adapters/<country>/region_map.csv → {native_code: nuts_code}."""
    path = REPO_ROOT / "adapters" / country.lower() / "region_map.csv"
    if not path.exists():
        return {}
    df = pd.read_csv(path, dtype=str).fillna("")
    return dict(zip(df["native_code"], df["nuts_code"], strict=True))
