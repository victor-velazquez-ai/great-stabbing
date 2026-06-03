"""Italy adapter — ISTAT SDMX *Delitti violenti, sesso, età - reg.*

**Source:** Istituto Nazionale di Statistica (ISTAT), SDMX REST API.
Dataflow ``73_230_DF_DCCV_AUTVITTPS_6`` exposes annual counts of violent
crimes (homicide, assault/blows, rape, stalking) by region, sex, age,
victim/offender, citizenship. We pull VICTIM totals at NUTS-2.

**Foreign-background published?** Not in this dataflow (it has CITIZENSHIP
but only TOTAL is populated). A sibling dataflow
``73_230_DF_DCCV_AUTVITTPS_5`` carries the citizenship breakdown — wiring
that up is a follow-up.

**Cadence:** annual.

**Stable URL:**
``https://esploradati.istat.it/SDMXWS/rest/data/73_230_DF_DCCV_AUTVITTPS_6/?format=csv``

ISTAT updates this dataflow annually (typically Q4 with prior calendar
year data).
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
IT_DIR = REPO_ROOT / "adapters" / "it"

SDMX_URL = (
    "https://esploradati.istat.it/SDMXWS/rest/data/"
    "73_230_DF_DCCV_AUTVITTPS_6/?format=csv&dimensionAtObservation=AllDimensions"
)
# Sibling dataflow — same TYPE_CRIME but with CITIZENSHIP populated
# (ITL = Italian / FRG = foreigner / TOTAL). National level only.
SDMX_URL_FB = (
    "https://esploradati.istat.it/SDMXWS/rest/data/"
    "73_230_DF_DCCV_AUTVITTPS_5/?format=csv&dimensionAtObservation=AllDimensions"
)

CITIZENSHIP_TO_SUSPECT_DIM = {
    "TOTAL": "total",
    "ITL": "national",
    "FRG": "foreign",
}


class ITAdapter(Adapter):
    country = "IT"
    authority = "ISTAT"
    cadence = "annual"

    def discover(self) -> list[SourceFile]:
        srcs: list[SourceFile] = []
        for url, fname in [
            (SDMX_URL, "istat-violent-crimes.csv"),
            (SDMX_URL_FB, "istat-violent-crimes-citizenship.csv"),
        ]:
            log.info("[IT] fetching %s", url)
            try:
                src = fetch_to_raw(url, country="it", filename=fname)
            except Exception as e:  # noqa: BLE001
                log.error("[IT] fetch failed for %s: %s", fname, e)
                continue
            srcs.append(src)
            log.info("[IT] discovered %s (%s)", src.local_path, src.sha256[:12])
        return srcs

    def parse(self, src: SourceFile) -> pd.DataFrame:
        path = REPO_ROOT / src.local_path
        log.info("[IT] parsing %s", path.relative_to(REPO_ROOT))

        df = pd.read_csv(
            path,
            dtype={"REF_AREA": str, "TYPE_CRIME": str, "DATA_TYPE": str,
                   "AGE": str, "CITIZENSHIP": str, "COUNTRY_CITIZEN": str,
                   "TIME_PERIOD": str},
            low_memory=False,
        )

        is_fb_file = "citizenship" in path.name.lower()
        if is_fb_file:
            # FB sibling: AGE has no TOTAL, REF_AREA only IT, CITIZENSHIP populated.
            df = df[
                (df["DATA_TYPE"] == "VICTIM")
                & (df["COUNTRY_CITIZEN"] == "WORLD")
                & (df["CITIZENSHIP"].isin(CITIZENSHIP_TO_SUSPECT_DIM.keys()))
            ].copy()
        else:
            # Main dataflow with regional breakdown (CITIZENSHIP only TOTAL).
            df = df[
                (df["DATA_TYPE"] == "VICTIM")
                & (df["AGE"] == "TOTAL")
                & (df["CITIZENSHIP"] == "TOTAL")
                & (df["COUNTRY_CITIZEN"] == "WORLD")
            ].copy()

        df["TIME_PERIOD"] = df["TIME_PERIOD"].astype(int)
        df["OBS_VALUE"] = pd.to_numeric(df["OBS_VALUE"], errors="coerce").fillna(0).astype(int)
        df["__is_fb__"] = is_fb_file

        log.info(
            "[IT] parsed %d rows from %s (years %d-%d, %d ref-areas)",
            len(df), path.name, df["TIME_PERIOD"].min(), df["TIME_PERIOD"].max(),
            df["REF_AREA"].nunique(),
        )
        return df.reset_index(drop=True)

    def normalise(self, df: pd.DataFrame, src: SourceFile) -> pd.DataFrame:
        cat_map_path = IT_DIR / "category_map.yaml"
        with cat_map_path.open(encoding="utf-8") as f:
            cat = yaml.safe_load(f) or {}
        mapping: dict[str, str] = cat.get("mapping", {}) or {}

        df = df.copy()
        df["category"] = df["TYPE_CRIME"].map(mapping)
        df = df.dropna(subset=["category"])

        is_fb_file = bool(df["__is_fb__"].iloc[0]) if "__is_fb__" in df.columns and len(df) else False
        if is_fb_file:
            return self._normalise_fb(df, src)
        return self._normalise_regional(df, src)

    def _normalise_regional(self, df: pd.DataFrame, src: SourceFile) -> pd.DataFrame:
        nuts_map = load_region_map("IT")
        df = df[df["REF_AREA"].isin(set(nuts_map.keys()))].copy()
        df["nuts_code"] = df["REF_AREA"].map(nuts_map)

        agg = (
            df.groupby(["nuts_code", "REF_AREA", "category", "TIME_PERIOD"], as_index=False)
            .agg(
                count=("OBS_VALUE", "sum"),
                native_examples=("TYPE_CRIME", lambda s: ", ".join(sorted(set(s))[:3])),
            )
        )
        # Last 10 years of regional history (years before that are likely
        # under NUTS-2013 boundaries that don't match our 2021 maps cleanly).
        latest_year = int(agg["TIME_PERIOD"].max())
        agg = agg[agg["TIME_PERIOD"] >= latest_year - 9]

        retrieved_at = pd.Timestamp.now(tz="UTC").tz_localize(None)
        rows: list[dict] = []
        for _, r in agg.iterrows():
            nuts = str(r["nuts_code"])
            pop = population(nuts)
            count = int(r["count"])
            rate = (count / pop * 100_000) if pop else None
            row_year = int(r["TIME_PERIOD"])
            rows.append(self._row(
                period_year=row_year, nuts=nuts, level=2, category=str(r["category"]),
                native_examples=str(r["native_examples"]), suspect_dim="total",
                count=count, pop=pop, rate=rate, retrieved_at=retrieved_at, src=src,
                source_url=SDMX_URL,
                notes="ISTAT dataflow AUTVITTPS_6, VICTIM count summed across SEX.",
            ))
        out = pd.DataFrame(rows)
        if not out.empty:
            out["count"] = out["count"].astype(int)
            out["region_level"] = out["region_level"].astype(int)
            out["denominator_population"] = out["denominator_population"].astype("Int64")
        log.info("[IT/regional] %d rows across %d regions (year %d)",
                 len(out), out["region_code"].nunique() if not out.empty else 0, latest_year)
        return out

    def _normalise_fb(self, df: pd.DataFrame, src: SourceFile) -> pd.DataFrame:
        # FB file is IT-only (REF_AREA=IT) with CITIZENSHIP populated.
        # AGE has no TOTAL; sum across all age bands too.
        df = df[df["REF_AREA"] == "IT"].copy()
        df["suspect_dim"] = df["CITIZENSHIP"].map(CITIZENSHIP_TO_SUSPECT_DIM)

        agg = (
            df.groupby(["category", "suspect_dim", "TIME_PERIOD"], as_index=False)
            .agg(
                count=("OBS_VALUE", "sum"),
                native_examples=("TYPE_CRIME", lambda s: ", ".join(sorted(set(s))[:3])),
            )
        )
        latest_year = int(agg["TIME_PERIOD"].max())
        agg = agg[agg["TIME_PERIOD"] == latest_year]

        retrieved_at = pd.Timestamp.now(tz="UTC").tz_localize(None)
        pop_it = population("IT")

        rows: list[dict] = []
        for _, r in agg.iterrows():
            count = int(r["count"])
            rate = (count / pop_it * 100_000) if pop_it else None
            rows.append(self._row(
                period_year=latest_year, nuts="IT", level=0, category=str(r["category"]),
                native_examples=str(r["native_examples"]), suspect_dim=str(r["suspect_dim"]),
                count=count, pop=pop_it, rate=rate, retrieved_at=retrieved_at, src=src,
                source_url=SDMX_URL_FB,
                notes=(
                    "ISTAT dataflow AUTVITTPS_5 — VICTIM count summed across SEX + AGE "
                    "bands. CITIZENSHIP: ITL→national, FRG→foreign, TOTAL→total. "
                    "National-level only (regional FB not published in this dataflow)."
                ),
            ))
        out = pd.DataFrame(rows)
        if not out.empty:
            out["count"] = out["count"].astype(int)
            out["region_level"] = out["region_level"].astype(int)
            out["denominator_population"] = out["denominator_population"].astype("Int64")
        log.info("[IT/fb] %d rows at NUTS-0 (year %d)", len(out), latest_year)
        return out

    @staticmethod
    def _row(*, period_year: int, nuts: str, level: int, category: str,
             native_examples: str, suspect_dim: str, count: int, pop: int | None,
             rate: float | None, retrieved_at: pd.Timestamp, src: SourceFile,
             source_url: str, notes: str) -> dict:
        return {
            "source_country": "IT",
            "source_authority": "ISTAT",
            "source_url": source_url,
            "source_file_hash": src.sha256,
            "retrieved_at": retrieved_at,
            "period_start": pd.Timestamp(date(period_year, 1, 1)),
            "period_end": pd.Timestamp(date(period_year, 12, 31)),
            "period_type": "year",
            "region_code": nuts,
            "region_level": level,
            "crime_category": category,
            "crime_category_native": native_examples,
            "suspect_dim": suspect_dim,
            "suspect_dim_value": None,
            "count": count,
            "denominator_population": pop,
            "denominator_source": "Eurostat / ISTAT mid-2024" if pop else None,
            "rate_per_100k": rate,
            "notes": notes,
        }
