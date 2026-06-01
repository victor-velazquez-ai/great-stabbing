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


class ITAdapter(Adapter):
    country = "IT"
    authority = "ISTAT"
    cadence = "annual"

    def discover(self) -> list[SourceFile]:
        log.info("[IT] fetching %s", SDMX_URL)
        try:
            src = fetch_to_raw(SDMX_URL, country="it", filename="istat-violent-crimes.csv")
        except Exception as e:  # noqa: BLE001
            log.error(
                "[IT] ISTAT fetch failed (%s: %s). Manual fallback: download "
                "https://esploradati.istat.it/databrowser/#/it/dw/categories/.../73_230 "
                "and place under data/raw/it/<yyyy-mm>/istat-violent-crimes.csv.",
                type(e).__name__, e,
            )
            return []
        log.info("[IT] discovered %s (%s)", src.local_path, src.sha256[:12])
        return [src]

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

        # Filter to the slice we care about.
        df = df[
            (df["DATA_TYPE"] == "VICTIM")
            & (df["AGE"] == "TOTAL")
            & (df["CITIZENSHIP"] == "TOTAL")
            & (df["COUNTRY_CITIZEN"] == "WORLD")
        ].copy()

        df["TIME_PERIOD"] = df["TIME_PERIOD"].astype(int)
        df["OBS_VALUE"] = pd.to_numeric(df["OBS_VALUE"], errors="coerce").fillna(0).astype(int)

        log.info(
            "[IT] parsed %d rows after dimension filter (years %d-%d, %d crime types, %d ref-areas)",
            len(df), df["TIME_PERIOD"].min(), df["TIME_PERIOD"].max(),
            df["TYPE_CRIME"].nunique(), df["REF_AREA"].nunique(),
        )
        return df.reset_index(drop=True)

    def normalise(self, df: pd.DataFrame, src: SourceFile) -> pd.DataFrame:
        cat_map_path = IT_DIR / "category_map.yaml"
        with cat_map_path.open(encoding="utf-8") as f:
            cat = yaml.safe_load(f) or {}
        mapping: dict[str, str] = cat.get("mapping", {}) or {}

        nuts_map = load_region_map("IT")  # native_code (ISTAT NUTS-2013) → NUTS-2021

        df = df.copy()
        df["category"] = df["TYPE_CRIME"].map(mapping)
        df = df.dropna(subset=["category"])
        # ISTAT publishes ref-areas using NUTS-2013 codes (ITD*, ITE*). Filter
        # by native_code (left side of the map), then translate to NUTS-2021
        # for our canonical schema.
        df = df[df["REF_AREA"].isin(set(nuts_map.keys()))]
        df["nuts_code"] = df["REF_AREA"].map(nuts_map)

        # Sum across SEX (the dataflow has SEX=1/2 but no 'TOTAL' code).
        agg = (
            df.groupby(["nuts_code", "REF_AREA", "category", "TIME_PERIOD"], as_index=False)
            .agg(
                count=("OBS_VALUE", "sum"),
                native_examples=("TYPE_CRIME", lambda s: ", ".join(sorted(set(s))[:3])),
            )
        )

        latest_year = int(agg["TIME_PERIOD"].max())
        agg = agg[agg["TIME_PERIOD"] == latest_year]

        retrieved_at = pd.Timestamp.now(tz="UTC").tz_localize(None)
        rows: list[dict] = []
        for _, r in agg.iterrows():
            nuts = str(r["nuts_code"])  # NUTS-2021
            pop = population(nuts)
            count = int(r["count"])
            rate = (count / pop * 100_000) if pop else None
            rows.append(
                {
                    "source_country": "IT",
                    "source_authority": self.authority,
                    "source_url": SDMX_URL,
                    "source_file_hash": src.sha256,
                    "retrieved_at": retrieved_at,
                    "period_start": pd.Timestamp(date(latest_year, 1, 1)),
                    "period_end": pd.Timestamp(date(latest_year, 12, 31)),
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
                        "ISTAT dataflow 73_230_DF_DCCV_AUTVITTPS_6, VICTIM count summed "
                        "across SEX. Foreign-background (citizenship) lives in sibling "
                        "dataflow ...AUTVITTPS_5; not yet integrated."
                    ),
                }
            )

        out = pd.DataFrame(rows)
        if not out.empty:
            out["count"] = out["count"].astype(int)
            out["region_level"] = out["region_level"].astype(int)
            out["denominator_population"] = out["denominator_population"].astype("Int64")

        log.info(
            "[IT] normalised %d rows across %d regions (year %d)",
            len(out), out["region_code"].nunique() if not out.empty else 0,
            latest_year,
        )
        return out
