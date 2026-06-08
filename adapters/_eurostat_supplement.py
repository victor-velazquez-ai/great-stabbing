"""Eurostat-supplement adapters for countries where the native source
covers most but not all harmonised categories.

We emit Eurostat-only rows at NUTS-0 for the specific (country, category)
pairs listed below. The native-source rows (often at NUTS-2/3) remain
canonical; the Eurostat row is a national fallback that lets the homepage
metric selector show shading on that country instead of grey.
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

# country → list of (iccs_code, harmonised_category) we want to add
COVERAGE_GAPS: dict[str, list[tuple[str, str]]] = {
    "IT": [("ICCS0401", "robbery_violent")],
    "NL": [("ICCS0101", "homicide")],
}


class EurostatSupplementAdapter(Adapter):
    """Pulls Eurostat crim_off_cat for the categories listed in
    COVERAGE_GAPS[self.country]. NUTS-0 rows only."""

    country = ""
    authority = "Eurostat (CRIM_OFF_CAT, supplement)"
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

    def parse(self, src: SourceFile) -> pd.DataFrame:
        gaps = COVERAGE_GAPS.get(self.country, [])
        if not gaps:
            return pd.DataFrame()
        wanted_iccs = {code for code, _ in gaps}
        path = REPO_ROOT / src.local_path
        df = pd.read_csv(path, low_memory=False)
        df = df[
            (df["geo"] == self.country)
            & (df["iccs"].isin(wanted_iccs))
            & (df["unit"] == "NR")
        ]
        df["count"] = pd.to_numeric(df["OBS_VALUE"], errors="coerce").fillna(0).astype(int)
        df["year"] = df["TIME_PERIOD"].astype(int)
        iccs_to_cat = dict(gaps)
        df["category"] = df["iccs"].map(iccs_to_cat)
        log.info(
            "[%s/supp] parsed %d rows across %s",
            self.country, len(df), sorted(df["iccs"].unique()),
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
                "crime_category_native": f"Eurostat {r['iccs']} (supplement)",
                "suspect_dim": "total",
                "suspect_dim_value": None,
                "count": count,
                "denominator_population": pop,
                "denominator_source": "Eurostat / hand-curated" if pop else None,
                "rate_per_100k": rate,
                "notes": (
                    f"Eurostat supplement — native source for {self.country} doesn't "
                    f"publish this category in a comparable form."
                ),
            })
        out = pd.DataFrame(rows)
        if not out.empty:
            out["count"] = out["count"].astype(int)
            out["region_level"] = out["region_level"].astype(int)
            out["denominator_population"] = out["denominator_population"].astype("Int64")
        return out
