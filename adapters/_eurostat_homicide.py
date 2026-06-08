"""Shared Eurostat adapter for countries where we don't (yet) have a
national-source live pipeline. Pulls dataset CRIM_OFF_CAT for all our
harmonised categories at NUTS-0.

ICCS mapping (UN International Classification of Crime for Statistical
purposes), confirmed against live AT 2024 data:

    ICCS0101    Intentional homicide          → homicide
    ICCS0102    Attempted intentional homicide → attempted_homicide
    ICCS020111  Serious assault                → assault_serious
    ICCS0301    Sexual violence (parent)       → sexual_assault
    ICCS0401    Robbery                        → robbery_violent
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

ICCS_TO_CATEGORY = {
    "ICCS0101":   "homicide",
    "ICCS0102":   "attempted_homicide",
    "ICCS020111": "assault_serious",
    "ICCS0301":   "sexual_assault",
    "ICCS0401":   "robbery_violent",
}


class EurostatHomicideAdapter(Adapter):
    """Subclass needs to set `country` (ISO-2)."""

    country = ""
    authority = "Eurostat (CRIM_OFF_CAT)"
    cadence = "annual"

    def discover(self) -> list[SourceFile]:
        try:
            src = fetch_to_raw(
                EUROSTAT_URL, country=self.country.lower(), filename="crim-off-cat.csv"
            )
        except Exception as e:  # noqa: BLE001
            log.error("[%s] Eurostat fetch failed: %s", self.country, e)
            return []
        return [src]

    def parse(self, src: SourceFile) -> pd.DataFrame:
        path = REPO_ROOT / src.local_path
        df = pd.read_csv(path, low_memory=False)
        df = df[
            (df["geo"] == self.country)
            & (df["iccs"].isin(ICCS_TO_CATEGORY.keys()))
            & (df["unit"] == "NR")
        ]
        df["count"] = pd.to_numeric(df["OBS_VALUE"], errors="coerce").fillna(0).astype(int)
        df["year"] = df["TIME_PERIOD"].astype(int)
        df["category"] = df["iccs"].map(ICCS_TO_CATEGORY)
        log.info(
            "[%s] parsed %d rows across %d ICCS codes",
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
                "crime_category_native": f"Eurostat {r['iccs']}",
                "suspect_dim": "total",
                "suspect_dim_value": None,
                "count": count,
                "denominator_population": pop,
                "denominator_source": "Eurostat / hand-curated" if pop else None,
                "rate_per_100k": rate,
                "notes": (
                    f"Eurostat crim_off_cat, {r['iccs']}, unit=NR. National-level (NUTS-0) only."
                ),
            })
        out = pd.DataFrame(rows)
        if not out.empty:
            out["count"] = out["count"].astype(int)
            out["region_level"] = out["region_level"].astype(int)
            out["denominator_population"] = out["denominator_population"].astype("Int64")
        log.info("[%s] normalised %d rows", self.country, len(out))
        return out
