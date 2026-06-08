"""Eurostat-supplement adapters.

Used in two ways:
1. **Country-level fallback** — write NUTS-0 rows for countries whose
   native source only publishes at NUTS-1/2/3. The homepage map's
   valueFor() falls back to NUTS-0 when a sub-national region has no
   data for the selected metric, so this guarantees no polygon goes
   grey just because a particular country's source slices crime
   differently.

2. **Per-category gap fill** — same mechanism but applied to specific
   country×category pairs where the native source publishes other
   categories.

All rows come from Eurostat dataset CRIM_OFF_CAT with unit=NR.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import pandas as pd

from adapters.common.base import Adapter, SourceFile
from adapters.common.http import fetch_to_raw
from adapters.common.nuts import population

log = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parents[1]

EUROSTAT_URL = (
    "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/"
    "crim_off_cat?format=SDMX-CSV&compressed=false"
)

# Default: all 5 harmonised categories.
ALL_CATEGORIES: list[tuple[str, str]] = [
    ("ICCS0101", "homicide"),
    ("ICCS0102", "attempted_homicide"),
    ("ICCS020111", "assault_serious"),
    ("ICCS0301", "sexual_assault"),
    ("ICCS0401", "robbery_violent"),
]

# Per-country override. If a country isn't listed here, we use ALL_CATEGORIES.
# Listed entries restrict to specific (iccs, category) pairs only.
COUNTRY_OVERRIDES: dict[str, list[tuple[str, str]]] = {
    # Empty list → use ALL_CATEGORIES (default)
}


class EurostatSupplementAdapter(Adapter):
    """Pulls Eurostat crim_off_cat for the country and writes NUTS-0 rows.

    Subclass needs to set `country`.
    """

    country = ""
    authority = "Eurostat (CRIM_OFF_CAT, NUTS-0 supplement)"
    cadence = "annual"

    def discover(self) -> list[SourceFile]:
        try:
            src = fetch_to_raw(
                EUROSTAT_URL, country=self.country.lower(), filename="crim-off-cat.csv"
            )
        except Exception as e:  # noqa: BLE001
            log.error("[%s/supp] fetch failed: %s", self.country, e)
            return []
        return [src]

    def _categories(self) -> list[tuple[str, str]]:
        return COUNTRY_OVERRIDES.get(self.country, ALL_CATEGORIES)

    def parse(self, src: SourceFile) -> pd.DataFrame:
        cats = self._categories()
        wanted_iccs = {c for c, _ in cats}
        iccs_to_cat = dict(cats)
        path = REPO_ROOT / src.local_path
        df = pd.read_csv(path, low_memory=False)
        df = df[
            (df["geo"] == self.country)
            & (df["iccs"].isin(wanted_iccs))
            & (df["unit"] == "NR")
        ]
        if df.empty:
            log.warning(
                "[%s/supp] Eurostat has no data for this country — likely dropped from the dataset (Brexit etc.)",
                self.country,
            )
            return pd.DataFrame(columns=["year", "category", "iccs", "count"])
        df["count"] = pd.to_numeric(df["OBS_VALUE"], errors="coerce").fillna(0).astype(int)
        df["year"] = df["TIME_PERIOD"].astype(int)
        df["category"] = df["iccs"].map(iccs_to_cat)
        log.info(
            "[%s/supp] parsed %d rows × %d cats",
            self.country, len(df), df["iccs"].nunique(),
        )
        return df[["year", "category", "iccs", "count"]].reset_index(drop=True)

    def normalise(self, df: pd.DataFrame, src: SourceFile) -> pd.DataFrame:
        if df.empty:
            return pd.DataFrame()
        latest = int(df["year"].max())
        df = df[df["year"] >= latest - 9]
        retrieved_at = pd.Timestamp.now(tz="UTC").tz_localize(None)
        pop = population(self.country)
        rows: list[dict] = []
        for _, r in df.iterrows():
            yr = int(r["year"]); count = int(r["count"])
            rate = (count / pop * 100_000) if pop else None
            rows.append({
                "source_country": self.country,
                "source_authority": self.authority,
                "source_url": EUROSTAT_URL,
                "source_file_hash": src.sha256,
                "retrieved_at": retrieved_at,
                "period_start": pd.Timestamp(date(yr, 1, 1)),
                "period_end": pd.Timestamp(date(yr, 12, 31)),
                "period_type": "year",
                "region_code": self.country,
                "region_level": 0,
                "crime_category": str(r["category"]),
                "crime_category_native": f"Eurostat {r['iccs']} (NUTS-0)",
                "suspect_dim": "total",
                "suspect_dim_value": None,
                "count": count,
                "denominator_population": pop,
                "denominator_source": "Eurostat / hand-curated" if pop else None,
                "rate_per_100k": rate,
                "notes": (
                    "Eurostat NUTS-0 supplement. The country-level rate is used "
                    "as a fallback for sub-national regions whose native source "
                    "doesn't publish this category."
                ),
            })
        out = pd.DataFrame(rows)
        if not out.empty:
            out["count"] = out["count"].astype(int)
            out["region_level"] = out["region_level"].astype(int)
            out["denominator_population"] = out["denominator_population"].astype("Int64")
            # IT's native parquet stores suspect_dim_value as Int32; if we leave
            # it as object/None DuckDB's UNION ALL chokes with "Could not convert
            # string '' to INT32". Force nullable Int32 dtype.
            out["suspect_dim_value"] = pd.array([None] * len(out), dtype="Int32")
        return out
