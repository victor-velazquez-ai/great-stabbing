"""Denmark adapter — Danmarks Statistik (Statbank) STRAF11.

**Source:** Danmarks Statistik public API at api.statbank.dk. Table STRAF11
publishes reported criminal offences quarterly by region × offence type ×
time. 5 NUTS-2 regions: Hovedstaden, Sjælland, Syddanmark, Midtjylland,
Nordjylland. Coverage: 2007 Q1 to current.

**Foreign-background published?** Yes, in table STRAF12 (suspects with
herkomst dimension). Not wired in this revision — STRAF11 only.

**Cadence:** quarterly. We aggregate to annual.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import pandas as pd
import yaml

from adapters.common.base import Adapter, SourceFile
from adapters.common.http import fetch_to_raw
from adapters.common.nuts import load_region_map, population

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DK_DIR = REPO_ROOT / "adapters" / "dk"

STRAF11_URL = (
    "https://api.statbank.dk/v1/data/STRAF11/CSV"
    "?TID=*&OMR%C3%85DE=000,081,082,083,084,085&OVERTR%C3%86D=*"
)


class DKAdapter(Adapter):
    country = "DK"
    authority = "Danmarks Statistik"
    cadence = "quarterly"

    def discover(self) -> list[SourceFile]:
        try:
            src = fetch_to_raw(STRAF11_URL, country="dk", filename="straf11.csv")
        except Exception as e:  # noqa: BLE001
            log.error("[DK] Statbank fetch failed: %s", e)
            return []
        log.info("[DK] discovered %s", src.local_path)
        return [src]

    def parse(self, src: SourceFile) -> pd.DataFrame:
        path = REPO_ROOT / src.local_path
        df = pd.read_csv(path, sep=";", encoding="utf-8-sig", dtype=str)
        # TID format "2007K1" — extract year + quarter
        df["year"] = df["TID"].str[:4].astype(int)
        df["quarter"] = df["TID"].str[5].astype(int)
        df["count"] = pd.to_numeric(df["INDHOLD"], errors="coerce").fillna(0).astype(int)
        log.info("[DK] parsed %d rows (years %d-%d, %d regions, %d categories)",
                 len(df), df["year"].min(), df["year"].max(),
                 df["OMRÅDE"].nunique(), df["OVERTRÆD"].nunique())
        return df

    def normalise(self, df: pd.DataFrame, src: SourceFile) -> pd.DataFrame:
        cat_map = yaml.safe_load((DK_DIR / "category_map.yaml").read_text(encoding="utf-8")) or {}
        mapping = cat_map.get("mapping", {})
        nuts_map = load_region_map("DK")

        df = df.copy()
        df["category"] = df["OVERTRÆD"].map(mapping)
        df = df.dropna(subset=["category"])
        df["nuts"] = df["OMRÅDE"].map(nuts_map)
        df = df.dropna(subset=["nuts"])

        # Aggregate quarters to annual.
        annual = (
            df.groupby(["nuts", "category", "year"], as_index=False)
            .agg(
                count=("count", "sum"),
                quarters=("quarter", "nunique"),
                native_examples=("OVERTRÆD", lambda s: ", ".join(sorted(set(s))[:3])),
            )
        )
        # Drop incomplete latest year (less than 4 quarters).
        latest_complete = int(annual[annual["quarters"] == 4]["year"].max())
        annual = annual[
            (annual["year"] <= latest_complete) & (annual["year"] >= latest_complete - 9)
        ]

        retrieved_at = pd.Timestamp.now(tz="UTC").tz_localize(None)
        rows: list[dict] = []
        for _, r in annual.iterrows():
            nuts = str(r["nuts"])
            pop = population(nuts)
            count = int(r["count"])
            rate = (count / pop * 100_000) if pop else None
            yr = int(r["year"])
            rows.append({
                "source_country": "DK",
                "source_authority": self.authority,
                "source_url": STRAF11_URL,
                "source_file_hash": src.sha256,
                "retrieved_at": retrieved_at,
                "period_start": pd.Timestamp(date(yr, 1, 1)),
                "period_end": pd.Timestamp(date(yr, 12, 31)),
                "period_type": "year",
                "region_code": nuts,
                "region_level": 2,
                "crime_category": str(r["category"]),
                "crime_category_native": str(r["native_examples"]),
                "suspect_dim": "total",
                "suspect_dim_value": None,
                "count": count,
                "denominator_population": pop,
                "denominator_source": "Eurostat NUTS 2021" if pop else None,
                "rate_per_100k": rate,
                "notes": (
                    "Danmarks Statistik STRAF11 — quarterly reported offences "
                    "aggregated to annual. Foreign-background available in "
                    "STRAF12 (not yet wired)."
                ),
            })
        out = pd.DataFrame(rows)
        if not out.empty:
            out["count"] = out["count"].astype(int)
            out["region_level"] = out["region_level"].astype(int)
            out["denominator_population"] = out["denominator_population"].astype("Int64")
        log.info("[DK] normalised %d rows × %d regions, years %d-%d",
                 len(out), out["region_code"].nunique() if not out.empty else 0,
                 latest_complete - 9, latest_complete)
        return out
