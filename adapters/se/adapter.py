"""Sweden adapter — BRÅ *Anmälda brott* (reported offences), national level.

**Source:** Brottsförebyggande rådet (BRÅ). Annual XLSX "Tabell 10. Anmälda
brott efter brottstyp, i hela landet" published directly on bra.se. Covers
the last 10 calendar years.

**Granularity:** NUTS-0 (Sweden as a whole). BRÅ does publish län-level
breakdowns in their Statistikdatabasen but it requires a PXweb 2.0 query
against a table whose ID we haven't located yet. For MVP, national-level
gives us Sweden on the map with full violent-category coverage.

**Foreign-background?** Not in this dataset. Available only via BRÅ's
occasional "Misstänkta för brott"-style special reports — not integrated.

**Cadence:** annual.

**URL:** https://bra.se/.../10La_anm_10_ar.xlsx (stable resource ID on
the BRÅ download CDN).
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

REPO_ROOT = Path(__file__).resolve().parents[2]
SE_DIR = REPO_ROOT / "adapters" / "se"

ANMALDA_BROTT_URL = (
    "https://bra.se/download/18.11dab50419d723e44d315606/"
    "1776153587771/10La_anm_10_ar.xlsx"
)

# BRÅ "Brottstyp" labels (verbatim Swedish) → harmonised category.
# Only "totalt" rows are matched (we want the rolled-up totals per crime
# family, not the granular sex/weapon sub-breakdowns).
NAME_TO_CATEGORY: dict[str, str] = {
    "Fullbordat mord och dråp samt misshandel med dödlig utgång, totalt": "homicide",
    "Misshandel, ej med dödlig utgång, totalt": "assault_serious",
    "Våldtäkt, våldtäkt mot barn, oaktsam våldtäkt, totalt": "sexual_assault",
    "Rån, totalt": "robbery_violent",
}


class SEAdapter(Adapter):
    country = "SE"
    authority = "BRÅ"
    cadence = "annual"

    def discover(self) -> list[SourceFile]:
        try:
            src = fetch_to_raw(
                ANMALDA_BROTT_URL, country="se", filename="anmalda-brott-10ar.xlsx"
            )
        except Exception as e:  # noqa: BLE001
            log.error(
                "[SE] BRÅ fetch failed (%s: %s). Manual fallback: download "
                "from https://bra.se/statistik/kriminalstatistik/anmalda-brott.html "
                "and place at data/raw/se/<yyyy-mm>/anmalda-brott-10ar.xlsx",
                type(e).__name__, e,
            )
            return []
        log.info("[SE] discovered %s (%s)", src.local_path, src.sha256[:12])
        return [src]

    def parse(self, src: SourceFile) -> pd.DataFrame:
        path = REPO_ROOT / src.local_path
        log.info("[SE] parsing %s", path.relative_to(REPO_ROOT))

        # Sheet "Statistik" has title in row 0, headers in row 1 (Lagrum,
        # Brottstyp, 2016..2025), data from row 2.
        df = pd.read_excel(path, sheet_name="Statistik", header=1, dtype=object)
        df = df.rename(columns={df.columns[0]: "lagrum", df.columns[1]: "brottstyp"})
        df = df.dropna(subset=["brottstyp"])
        df["brottstyp"] = df["brottstyp"].astype(str).str.strip()

        # Year columns are everything after lagrum/brottstyp that's a 4-digit
        # integer-stringifiable header.
        year_cols = [c for c in df.columns if str(c).isdigit() and len(str(c)) == 4]
        latest_year = max(int(c) for c in year_cols)

        keep = df[df["brottstyp"].isin(NAME_TO_CATEGORY.keys())].copy()
        keep[str(latest_year)] = pd.to_numeric(keep[str(latest_year)], errors="coerce")
        keep = keep.dropna(subset=[str(latest_year)])
        keep["count"] = keep[str(latest_year)].astype(int)
        keep["year"] = latest_year

        log.info(
            "[SE] parsed %d category rows (year %d)",
            len(keep), latest_year,
        )
        return keep[["brottstyp", "count", "year"]].reset_index(drop=True)

    def normalise(self, df: pd.DataFrame, src: SourceFile) -> pd.DataFrame:
        if df.empty:
            return df

        df = df.copy()
        df["category"] = df["brottstyp"].map(NAME_TO_CATEGORY)
        df = df.dropna(subset=["category"])

        # Already aggregated to category × year by BRÅ; no further groupby.
        latest_year = int(df["year"].max())
        df = df[df["year"] == latest_year]

        retrieved_at = pd.Timestamp.now(tz="UTC").tz_localize(None)
        pop_se = population("SE")

        rows: list[dict] = []
        for _, r in df.iterrows():
            count = int(r["count"])
            rate = (count / pop_se * 100_000) if pop_se else None
            rows.append(
                {
                    "source_country": "SE",
                    "source_authority": self.authority,
                    "source_url": ANMALDA_BROTT_URL,
                    "source_file_hash": src.sha256,
                    "retrieved_at": retrieved_at,
                    "period_start": pd.Timestamp(date(latest_year, 1, 1)),
                    "period_end": pd.Timestamp(date(latest_year, 12, 31)),
                    "period_type": "year",
                    "region_code": "SE",
                    "region_level": 0,
                    "crime_category": str(r["category"]),
                    "crime_category_native": str(r["brottstyp"]),
                    "suspect_dim": "total",
                    "suspect_dim_value": None,
                    "count": count,
                    "denominator_population": pop_se,
                    "denominator_source": "Eurostat NUTS 2021" if pop_se else None,
                    "rate_per_100k": rate,
                    "notes": (
                        "BRÅ Tabell 10. National total (NUTS-0). Län-level "
                        "breakdown is published in BRÅ's Statistikdatabasen "
                        "(PXweb 2.0) — wiring deferred. Foreign-background "
                        "not in this dataset."
                    ),
                }
            )

        out = pd.DataFrame(rows)
        if not out.empty:
            out["count"] = out["count"].astype(int)
            out["region_level"] = out["region_level"].astype(int)
            out["denominator_population"] = out["denominator_population"].astype("Int64")

        log.info("[SE] normalised %d rows (year %d)", len(out), latest_year)
        return out
