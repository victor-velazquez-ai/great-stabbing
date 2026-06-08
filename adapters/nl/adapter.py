"""Netherlands adapter — CBS 83648NED via OData.

Annual data 2010-2025 by province × crime category.
"""

from __future__ import annotations

import json
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
NL_DIR = REPO_ROOT / "adapters" / "nl"

# OData with $select to keep payload small, $filter for province-level regions
# and our 5 crime categories. CBS returns one row per (RegioS, SoortMisdrijf, Perioden).
# CBS caps at 10,000 rows per request. 12 provinces × 75 categories × N years
# exceeds the limit even with a regional filter, so we slice by year-window and
# concatenate. ge '2015' covers 11 years → 12×75×11 = 9,900, just under.
def _year_filter(start_year: int, end_year: int) -> str:
    return (
        f"startswith(RegioS,'PV') and Perioden ge '{start_year}JJ00' "
        f"and Perioden le '{end_year}JJ00'"
    )

ODATA_BASE = "https://opendata.cbs.nl/ODataApi/odata/83648NED/TypedDataSet"
ODATA_URL = ODATA_BASE  # For provenance only.


class NLAdapter(Adapter):
    country = "NL"
    authority = "CBS"
    cadence = "annual"

    def discover(self) -> list[SourceFile]:
        """Slice by year-window (10k cap is 12×75×11 = 9,900) and concat."""
        import requests
        from datetime import datetime, timezone
        import hashlib, json as _json
        from urllib.parse import quote

        collected: list[dict] = []
        # 2-year windows → ~1800 rows each, safely under CBS 10k cap.
        for window in [(2010, 2011), (2012, 2013), (2014, 2015), (2016, 2017),
                       (2018, 2019), (2020, 2021), (2022, 2023), (2024, 2025)]:
            f = _year_filter(*window)
            safe_chars = ",()' "
            url = (
                f"{ODATA_BASE}?$select=ID,RegioS,SoortMisdrijf,Perioden,"
                f"TotaalGeregistreerdeMisdrijven_1&$filter={quote(f, safe=safe_chars)}"
            )
            try:
                r = requests.get(url, timeout=180, headers={"User-Agent": "Mozilla/5.0"})
                r.raise_for_status()
                payload = r.json()
            except Exception as e:  # noqa: BLE001
                log.warning("[NL] window %s failed: %s", window, e)
                continue
            rows = payload.get("value", []) or []
            collected.extend(rows)
            log.info("[NL] window %s → %d rows (total %d)", window, len(rows), len(collected))
        if not collected:
            return []
        local = REPO_ROOT / "data" / "raw" / "nl" / "2026-06" / "cbs-83648-all.json"
        local.parent.mkdir(parents=True, exist_ok=True)
        text = _json.dumps({"value": collected}, ensure_ascii=False).encode("utf-8")
        local.write_bytes(text)
        return [SourceFile(
            url=ODATA_URL,
            local_path=str(local.relative_to(REPO_ROOT)),
            fetched_at=datetime.now(timezone.utc),
            sha256=hashlib.sha256(text).hexdigest(),
        )]

    def parse(self, src: SourceFile) -> pd.DataFrame:
        path = REPO_ROOT / src.local_path
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        rows = data.get("value", [])
        df = pd.DataFrame(rows)
        if df.empty:
            log.warning("[NL] empty response")
            return df
        df["region_native"] = df["RegioS"].astype(str).str.strip()
        df["category_native"] = df["SoortMisdrijf"].astype(str).str.strip()
        df["count"] = pd.to_numeric(df["TotaalGeregistreerdeMisdrijven_1"], errors="coerce").fillna(0).astype(int)
        # Perioden format like "2024JJ00" = year 2024
        df["year"] = df["Perioden"].str[:4].astype(int)
        # Filter to our 5 categories in Python (CBS OData filter on string-with-trailing-space
        # is finicky).
        keep_cats = {"CRI3400", "CRI3100", "CRI3300", "CRI1110", "CRI3000"}
        df = df[df["category_native"].isin(keep_cats)]
        log.info("[NL] parsed %d rows, years %d-%d, %d regions",
                 len(df), df["year"].min(), df["year"].max(), df["region_native"].nunique())
        return df

    def normalise(self, df: pd.DataFrame, src: SourceFile) -> pd.DataFrame:
        cat = yaml.safe_load((NL_DIR / "category_map.yaml").read_text(encoding="utf-8")) or {}
        mapping = cat.get("mapping", {})
        nuts_map = load_region_map("NL")
        df = df.copy()
        df["category"] = df["category_native"].map(mapping)
        df = df.dropna(subset=["category"])
        df["nuts"] = df["region_native"].map(nuts_map)
        df = df.dropna(subset=["nuts"])
        latest = int(df["year"].max())
        df = df[df["year"] >= latest - 9]
        agg = (df.groupby(["nuts", "category", "year"], as_index=False)
                .agg(count=("count","sum"),
                     native_examples=("category_native", lambda s: ", ".join(sorted(set(s))[:3]))))
        retrieved_at = pd.Timestamp.now(tz="UTC").tz_localize(None)
        rows = []
        for _, r in agg.iterrows():
            nuts = str(r["nuts"]); yr = int(r["year"]); count = int(r["count"])
            pop = population(nuts)
            rate = (count / pop * 100_000) if pop else None
            rows.append({
                "source_country": "NL", "source_authority": self.authority,
                "source_url": ODATA_URL, "source_file_hash": src.sha256,
                "retrieved_at": retrieved_at,
                "period_start": pd.Timestamp(date(yr,1,1)),
                "period_end": pd.Timestamp(date(yr,12,31)),
                "period_type": "year", "region_code": nuts, "region_level": 2,
                "crime_category": str(r["category"]),
                "crime_category_native": str(r["native_examples"]),
                "suspect_dim": "total", "suspect_dim_value": None,
                "count": count, "denominator_population": pop,
                "denominator_source": "Eurostat / hand-curated" if pop else None,
                "rate_per_100k": rate,
                "notes": "CBS 83648NED — counts are Geregistreerde misdrijven (registered crimes), not victims.",
            })
        out = pd.DataFrame(rows)
        if not out.empty:
            out["count"] = out["count"].astype(int)
            out["region_level"] = out["region_level"].astype(int)
            out["denominator_population"] = out["denominator_population"].astype("Int64")
        log.info("[NL] normalised %d rows × %d regions", len(out), out["region_code"].nunique() if not out.empty else 0)
        return out
