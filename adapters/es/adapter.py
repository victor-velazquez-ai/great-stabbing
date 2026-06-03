"""Spain adapter — Ministerio del Interior *Sistema Estadístico de Criminalidad* (SEC).

**Source:** Portal Estadístico de Criminalidad, https://estadisticasdecriminalidad.ses.mir.es.
The SEC publishes PC-Axis tables exported as TSV (Latin-9 encoded) under stable
URLs: ``/sec/jaxiPx/files/_px/es/csv/Datos3/l0/<NNNNN>.csv``.

**Table 03002** — *Detenciones e investigados por provincias, tipología penal
y periodo*. Annual, 2010–latest, 52 provincias + Total Nacional + autonomous
community subtotals.

**Foreign-background published?** Yes, in sibling tables (03004 minors,
03006/03008 foreign-by-crime) — wired as a follow-up. For MVP we ship the
provincia × crime totals from 03002.

**Cadence:** annual (latest year published in October of the following year).

**Quantity caveat:** SEC counts "Detenciones e investigados" (arrests +
persons under investigation) rather than victims or recorded offences,
which differs from how ONS (UK) and Interstats (FR) count. Methodology
page documents this difference.
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
ES_DIR = REPO_ROOT / "adapters" / "es"

SEC_URL_03002 = (
    "https://estadisticasdecriminalidad.ses.mir.es/sec/jaxiPx/files/_px/es/csv/"
    "Datos3/l0/03002.csv?nocab=1"
)

# Province name normalisation. SEC publishes some province names with
# spellings, parentheticals, and reorderings that don't exactly match our
# region_map.csv `native_name`. We normalize aggressively: strip accents +
# lowercase + map known special cases.

import unicodedata

def _strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )

# Manual aliases for SEC's specific spellings that don't normalize to our
# region_map entries via accent-strip alone.
PROVINCE_ALIASES = {
    # SEC reorders some names with parentheticals
    "balears (illes)": "Illes Balears",
    "coruna (a)": "A Coruña",
    "palmas (las)": "Las Palmas",
    "rioja (la)": "La Rioja",
    # Compound Basque / Euskara names
    "araba/alava": "Álava",
    "alava": "Álava",
    "araba": "Álava",
    "bizkaia": "Bizkaia",
    "gipuzkoa": "Gipuzkoa",
    "vizcaya": "Bizkaia",
    "guipuzcoa": "Gipuzkoa",
    # Valencia / Castellón / Alicante compound names
    "alicante/alacant": "Alicante/Alacant",
    "alicante": "Alicante/Alacant",
    "alacant": "Alicante/Alacant",
    "castellon/castello": "Castellón/Castelló",
    "castellon": "Castellón/Castelló",
    "castello": "Castellón/Castelló",
    "valencia/valencia": "Valencia/València",
    "valencia": "Valencia/València",
    "valencia/valùncia": "Valencia/València",
    # Other
    "santa cruz de tenerife": "Santa Cruz de Tenerife",
    "ceuta": "Ceuta",
    "melilla": "Melilla",
}


class ESAdapter(Adapter):
    country = "ES"
    authority = "Ministerio del Interior"
    cadence = "annual"

    def discover(self) -> list[SourceFile]:
        log.info("[ES] fetching SEC table 03002")
        try:
            src = fetch_to_raw(SEC_URL_03002, country="es", filename="sec-03002-detenciones.csv")
        except Exception as e:  # noqa: BLE001
            log.error("[ES] fetch failed: %s", e)
            return []
        log.info("[ES] discovered %s (%s)", src.local_path, src.sha256[:12])
        return [src]

    def parse(self, src: SourceFile) -> pd.DataFrame:
        """Parse SEC's hierarchical PC-Axis TSV.

        Layout (1-indexed for clarity):
          1-4: title/metadata
          5:   empty
          6:   ``\\t YYYY \\t YYYY-1 \\t ... \\t YYYY-old``
          7+:  alternating
              ``<Province name>\\t``         (section header, no data)
              ``    <Crime category>\\t v1\\t v2\\t ...``  (indented data row)
        """
        path = REPO_ROOT / src.local_path
        log.info("[ES] parsing %s", path.relative_to(REPO_ROOT))

        # SEC's HTTP response advertises ISO-8859-15 but the actual file is
        # UTF-8 (double-encoded characters like "Agresión" prove it). Try
        # UTF-8 first, fall back to ISO-8859-15 if it fails.
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("iso-8859-15", errors="replace")
        lines = text.split("\n")

        # Find the year header row.
        year_row = None
        for i, line in enumerate(lines[:30]):
            parts = line.split("\t")
            if any(p.strip().isdigit() and len(p.strip()) == 4 for p in parts):
                year_row = i
                years = [p.strip() for p in parts if p.strip().isdigit() and len(p.strip()) == 4]
                break
        if year_row is None:
            raise ValueError(f"could not find year header in {path.name}")
        log.info("[ES] year columns: %s", years)

        records: list[dict] = []
        current_province: str | None = None
        for line in lines[year_row + 1:]:
            if not line.strip():
                continue
            # Section header rows have no leading whitespace.
            if not line.startswith((" ", "\t")):
                # Header line is "Province name\t" — strip the trailing tab.
                current_province = line.rstrip("\t").strip()
                continue
            # Indented data row.
            parts = line.split("\t")
            # First non-empty part is the crime category label.
            label = parts[0].strip()
            if not label:
                continue
            values = parts[1:]
            for year_str, val_str in zip(years, values, strict=False):
                if not val_str or val_str.strip() in {"", "-", "."}:
                    continue
                # SEC uses Spanish thousand separator (.) — strip dots.
                num_str = val_str.replace(".", "").replace(",", "").strip()
                if not num_str.isdigit():
                    continue
                records.append({
                    "province": current_province or "",
                    "category_native": label,
                    "year": int(year_str),
                    "count": int(num_str),
                })

        df = pd.DataFrame(records)
        log.info(
            "[ES] parsed %d rows across %d provinces, %d categories, years %d-%d",
            len(df), df["province"].nunique(), df["category_native"].nunique(),
            df["year"].min() if len(df) else 0, df["year"].max() if len(df) else 0,
        )
        return df

    def normalise(self, df: pd.DataFrame, src: SourceFile) -> pd.DataFrame:
        if df.empty:
            return df

        cat_map = yaml.safe_load((ES_DIR / "category_map.yaml").read_text(encoding="utf-8")) or {}
        mapping = cat_map.get("mapping", {})

        df = df.copy()
        # Normalise province name: strip accents + lowercase + try alias map.
        df["province_ascii"] = df["province"].apply(_strip_accents).str.lower().str.strip()
        df["province_canonical"] = df["province_ascii"].map(PROVINCE_ALIASES).fillna(df["province"])
        df["category"] = df["category_native"].map(mapping)
        df = df.dropna(subset=["category"])

        # Build province → NUTS: accent-stripped name from our region_map.
        nuts_by_code = load_region_map("ES")  # native_code → nuts_code
        rm_df = pd.read_csv(ES_DIR / "region_map.csv", dtype=str, comment="#").fillna("")
        name_to_nuts: dict[str, str] = {}
        for _, r in rm_df.iterrows():
            key = _strip_accents(r["native_name"]).strip().lower()
            name_to_nuts[key] = r["nuts_code"]
            # Also store the canonical form for the alias path.
            name_to_nuts[r["native_name"].strip().lower()] = r["nuts_code"]

        # First try: directly via accent-stripped lookup. Then fallback via alias.
        df["nuts"] = df["province_ascii"].map(name_to_nuts)
        unmatched_mask = df["nuts"].isna()
        df.loc[unmatched_mask, "nuts"] = (
            df.loc[unmatched_mask, "province_canonical"]
            .apply(_strip_accents).str.lower().map(name_to_nuts)
        )
        # Drop national/CCAA aggregate rows (they have no NUTS-3 mapping).
        df_matched = df.dropna(subset=["nuts"])
        log.info(
            "[ES] matched %d/%d rows to NUTS-3 (unmapped includes Total Nacional + CCAA totals)",
            len(df_matched), len(df),
        )

        # Last 10 years of history.
        latest_year = int(df_matched["year"].max())
        df_recent = df_matched[df_matched["year"] >= latest_year - 9]

        agg = (
            df_recent.groupby(["nuts", "category", "year"], as_index=False)
            .agg(
                count=("count", "sum"),
                native_examples=("category_native", lambda s: ", ".join(sorted(set(s))[:3])),
            )
        )

        retrieved_at = pd.Timestamp.now(tz="UTC").tz_localize(None)
        rows: list[dict] = []
        for _, r in agg.iterrows():
            nuts = str(r["nuts"])
            pop = population(nuts)
            count = int(r["count"])
            rate = (count / pop * 100_000) if pop else None
            yr = int(r["year"])
            rows.append({
                "source_country": "ES",
                "source_authority": self.authority,
                "source_url": SEC_URL_03002,
                "source_file_hash": src.sha256,
                "retrieved_at": retrieved_at,
                "period_start": pd.Timestamp(date(yr, 1, 1)),
                "period_end": pd.Timestamp(date(yr, 12, 31)),
                "period_type": "year",
                "region_code": nuts,
                "region_level": 3,
                "crime_category": str(r["category"]),
                "crime_category_native": str(r["native_examples"]),
                "suspect_dim": "total",
                "suspect_dim_value": None,
                "count": count,
                "denominator_population": pop,
                "denominator_source": "Eurostat NUTS 2021" if pop else None,
                "rate_per_100k": rate,
                "notes": (
                    "SEC table 03002 — Detenciones e investigados (arrests + persons "
                    "under investigation), not the same as victims/incidents. "
                    "Foreign-background dimension is in sibling tables (03006/03008) "
                    "and will be wired separately."
                ),
            })

        out = pd.DataFrame(rows)
        if not out.empty:
            out["count"] = out["count"].astype(int)
            out["region_level"] = out["region_level"].astype(int)
            out["denominator_population"] = out["denominator_population"].astype("Int64")

        log.info(
            "[ES] normalised %d rows across %d provincias (year %d)",
            len(out), out["region_code"].nunique() if not out.empty else 0, latest_year,
        )
        return out
