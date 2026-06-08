"""Ireland adapter — CSO Recorded Crime Incidents (CJA01).

National-only annual data via PxStat JSON-stat. NUTS-0 IE.
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
from adapters.common.nuts import population

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
IE_DIR = REPO_ROOT / "adapters" / "ie"

CSO_URL = (
    "https://ws.cso.ie/public/api.restful/PxStat.Data.Cube_API.ReadDataset/"
    "CJA01/JSON-stat/2.0/en"
)


class IEAdapter(Adapter):
    country = "IE"
    authority = "CSO"
    cadence = "annual"

    def discover(self) -> list[SourceFile]:
        try:
            src = fetch_to_raw(CSO_URL, country="ie", filename="cja01.json")
        except Exception as e:  # noqa: BLE001
            log.error("[IE] CSO fetch failed: %s", e)
            return []
        return [src]

    def parse(self, src: SourceFile) -> pd.DataFrame:
        path = REPO_ROOT / src.local_path
        with path.open(encoding="utf-8") as f:
            d = json.load(f)
        # JSON-stat unfolding: 3D array indexed by (STATISTIC, TLIST(A1), C02480V03003)
        times = d["dimension"]["TLIST(A1)"]["category"]["index"]
        time_labels = d["dimension"]["TLIST(A1)"]["category"]["label"]
        offences = d["dimension"]["C02480V03003"]["category"]["index"]
        offence_labels = d["dimension"]["C02480V03003"]["category"]["label"]
        values = d["value"]
        # The flat values array is row-major: stat * (T * O) + t * O + o
        n_stat = len(d["dimension"]["STATISTIC"]["category"]["index"])
        n_t = len(times)
        n_o = len(offences)
        rows: list[dict] = []
        for ti, tid in enumerate(times):
            for oi, oid in enumerate(offences):
                idx = 0 * (n_t * n_o) + ti * n_o + oi  # single STATISTIC
                v = values[idx] if idx < len(values) else None
                if v is None:
                    continue
                rows.append({
                    "year": int(time_labels[tid]),
                    "offence": offence_labels[oid],
                    "count": int(v),
                })
        df = pd.DataFrame(rows)
        log.info("[IE] parsed %d rows (years %d-%d)", len(df), df["year"].min(), df["year"].max())
        return df

    def normalise(self, df: pd.DataFrame, src: SourceFile) -> pd.DataFrame:
        cat = yaml.safe_load((IE_DIR / "category_map.yaml").read_text(encoding="utf-8")) or {}
        mapping = cat.get("mapping", {})
        df = df.copy()
        df["category"] = df["offence"].map(mapping)
        df = df.dropna(subset=["category"])
        latest = int(df["year"].max())
        df = df[df["year"] >= latest - 9]
        agg = (df.groupby(["category", "year"], as_index=False)
                .agg(count=("count","sum"),
                     native_examples=("offence", lambda s: ", ".join(sorted(set(s))[:3]))))
        retrieved_at = pd.Timestamp.now(tz="UTC").tz_localize(None)
        pop_ie = population("IE")
        rows = []
        for _, r in agg.iterrows():
            yr = int(r["year"]); count = int(r["count"])
            rate = (count / pop_ie * 100_000) if pop_ie else None
            rows.append({
                "source_country": "IE", "source_authority": self.authority,
                "source_url": CSO_URL, "source_file_hash": src.sha256,
                "retrieved_at": retrieved_at,
                "period_start": pd.Timestamp(date(yr,1,1)),
                "period_end": pd.Timestamp(date(yr,12,31)),
                "period_type": "year", "region_code": "IE", "region_level": 0,
                "crime_category": str(r["category"]),
                "crime_category_native": str(r["native_examples"]),
                "suspect_dim": "total", "suspect_dim_value": None,
                "count": count, "denominator_population": pop_ie,
                "denominator_source": "Eurostat / hand-curated" if pop_ie else None,
                "rate_per_100k": rate,
                "notes": "CSO CJA01 national-only (NUTS-0).",
            })
        out = pd.DataFrame(rows)
        if not out.empty:
            out["count"] = out["count"].astype(int)
            out["region_level"] = out["region_level"].astype(int)
            out["denominator_population"] = out["denominator_population"].astype("Int64")
        log.info("[IE] normalised %d rows × 1 region", len(out))
        return out
