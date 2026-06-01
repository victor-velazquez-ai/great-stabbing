"""Germany adapter — BKA *Polizeiliche Kriminalstatistik* (PKS) Zeitreihen.

**Source:** Bundeskriminalamt (BKA). PKS publishes annual *Zeitreihen* (time
series) at the federal level as XLSX workbooks. Three of them carry the
foreign-background dimension this project advertises:

- **T20-ZR-insg** (``T20_ZR insg``): all suspects (Tatverdächtige insgesamt)
- **T40-ZR-insg-deutsch**: **German** suspects (deutsche Tatverdächtige)
- **T50-ZR-insg-nichtdeutsch**: **non-German** suspects (nichtdeutsche
  Tatverdächtige) — the *Nichtdeutsche Tatverdächtige* dimension that makes
  Germany the headline country at MVP

Plus optional T01 for federal cases (Fälle).

**Granularity:** NUTS-0 (Germany as a whole). The Bundesländer breakdown
(T62, T81, T82) lives behind a 303-redirect protection layer that requires
JS-rendered nav we can't run from a script — that's a separate annual
manual drop. For MVP, federal-level with the foreign-background dimension
is the bigger win.

**Cadence:** annual, released ~late April / early May.

**URLs probed and confirmed working (PKS 2024 release, 2025-03-19 / 04-23):**
``https://www.bka.de/SharedDocs/Downloads/DE/Publikationen/PolizeilicheKriminalstatistik/2024/Interpretation/Tatverdaechtige/<file>.xlsx?__blob=publicationFile&v=N``

Each year's release republishes with a new ``v=N`` cache-buster. We probe
the Zeitreihen catalog page to discover the latest version (rather than
hard-coding the v=N).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd
import requests

from adapters.common.base import Adapter, SourceFile
from adapters.common.http import fetch_to_raw
from adapters.common.nuts import population

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DE_DIR = REPO_ROOT / "adapters" / "de"

# Page that lists every PKS Zeitreihen XLSX with its current ?v=N suffix.
ZEITREIHEN_INDEX = (
    "https://www.bka.de/DE/AktuelleInformationen/StatistikenLagebilder/"
    "PolizeilicheKriminalstatistik/PKS2024/PKSTabellen/Zeitreihen/zeitreihen_node.html"
)
BKA_BASE = "https://www.bka.de"

# Filenames (URL-encoded as published) we care about — federal totals + the
# Tatverdächtige insgesamt / deutsche / nichtdeutsche split.
ZR_FILES: dict[str, tuple[str, str]] = {
    # local-filename  ->  (filename-pattern, suspect_dim)
    "T20-tv-insg.xlsx":            ("ZR-TV-01-T20-TV-insg",          "total"),
    "T40-tv-deutsch.xlsx":         ("ZR-TV-04-T40-TV-insg-deutsch",  "national"),
    "T50-tv-nichtdeutsch.xlsx":    ("ZR-TV-07-T50-TV-insg-nichtdeutsch", "foreign"),
}

# PKS Straftatenschlüssel → harmonised crime category.
# Source: BKA Schlüsselverzeichnis 2024. 6-digit codes (BKA's full encoding).
# Picks are deliberately narrow — the umbrella "892000 Gewaltkriminalität"
# already aggregates many sub-categories; we don't double-count by also
# emitting its children. For each harmonised category we map a single
# leaf-most code to keep counts comparable.
SCHLUESSEL_TO_CATEGORY: dict[str, str] = {
    "892000": "violent_total",     # Gewaltkriminalität — top-level umbrella
    "010000": "homicide",          # Mord
    "020000": "homicide",          # Totschlag
    "110000": "sexual_assault",    # Vergewaltigung u. sexuelle Nötigung
    "210000": "robbery_violent",   # Raub, räuberische Erpressung
    "222000": "assault_serious",   # Gefährliche und schwere Körperverletzung
    # (note: 221000 = Körperverletzung mit Todesfolge is a much narrower
    #  sub-category covering only fatal-outcome assault — not used here.)
}


@dataclass(frozen=True)
class _ZRFile:
    local_filename: str
    suspect_dim: str
    discovered_url: str


def _discover_zr_urls() -> dict[str, _ZRFile]:
    """Scrape the Zeitreihen index page for the current XLSX URLs (with v=N)."""
    try:
        r = requests.get(
            ZEITREIHEN_INDEX,
            timeout=30,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        r.raise_for_status()
    except Exception as e:  # noqa: BLE001
        log.warning("[DE] failed to fetch Zeitreihen index: %s", e)
        return {}

    html = r.text
    out: dict[str, _ZRFile] = {}
    for local_name, (pattern, suspect_dim) in ZR_FILES.items():
        # The href in the page is URL-encoded; match by the pattern at the
        # start of the basename and capture everything up to the closing quote.
        m = re.search(
            rf'href="(/SharedDocs/Downloads/DE/[^"]*{re.escape(pattern)}[^"]*\.xlsx[^"]*)"',
            html,
        )
        if not m:
            continue
        href = m.group(1).replace("&amp;", "&")
        out[local_name] = _ZRFile(
            local_filename=local_name,
            suspect_dim=suspect_dim,
            discovered_url=BKA_BASE + href,
        )
    return out


class DEAdapter(Adapter):
    country = "DE"
    authority = "BKA"
    cadence = "annual"

    def discover(self) -> list[SourceFile]:
        urls = _discover_zr_urls()
        if not urls:
            log.error(
                "[DE] could not discover BKA PKS Zeitreihen XLSX URLs. "
                "Manual fallback: download from %s and place under "
                "data/raw/de/<yyyy-mm>/ with filenames "
                "T20-tv-insg.xlsx, T40-tv-deutsch.xlsx, T50-tv-nichtdeutsch.xlsx.",
                ZEITREIHEN_INDEX,
            )
            return self._discover_manual_fallback()

        srcs: list[SourceFile] = []
        for local_name, info in urls.items():
            try:
                src = fetch_to_raw(info.discovered_url, country="de", filename=local_name)
            except Exception as e:  # noqa: BLE001
                log.warning("[DE] %s failed: %s", local_name, e)
                continue
            srcs.append(src)
            log.info("[DE] discovered %s (%s)", local_name, src.sha256[:12])
        return srcs

    def _discover_manual_fallback(self) -> list[SourceFile]:
        srcs: list[SourceFile] = []
        import hashlib
        from datetime import datetime, timezone

        for name in ZR_FILES.keys():
            for candidate in (REPO_ROOT / "data" / "raw" / "de").rglob(name):
                srcs.append(
                    SourceFile(
                        url="manual",
                        local_path=str(candidate.relative_to(REPO_ROOT)),
                        fetched_at=datetime.now(timezone.utc),
                        sha256=hashlib.sha256(candidate.read_bytes()).hexdigest(),
                    )
                )
        return srcs

    def parse(self, src: SourceFile) -> pd.DataFrame:
        """Parse one BKA Zeitreihe XLSX → long DataFrame.

        Output: ``schluessel, straftat, jahr, count, suspect_dim``.

        BKA layout: row 5 has the column headers, rows 6-10 are spurious
        header rows (age band names, numeric column labels), data starts
        at row 11. Column 3 is "Tatverdächtige insgesamt" (total suspects
        for that offence/year).
        """
        path = REPO_ROOT / src.local_path
        filename = path.name

        # Determine which suspect dim this file carries.
        info = ZR_FILES.get(filename)
        suspect_dim = info[1] if info else self._guess_dim_from_filename(filename)
        log.info("[DE] parsing %s as suspect_dim=%r", path.relative_to(REPO_ROOT), suspect_dim)

        xl = pd.ExcelFile(path)
        # Sheet is "T20_ZR insg", "T40_ZR insg", "T50_ZR insg".
        sheet = next((s for s in xl.sheet_names if "ZR" in s), xl.sheet_names[0])

        # Read with header=5 to get Schlüssel/Straftat/Jahr/insg, then drop
        # the next ~4 rows which are sub-headers.
        df = pd.read_excel(xl, sheet_name=sheet, header=5, dtype=object)
        # Force the canonical first 4 columns.
        df = df.rename(columns={df.columns[0]: "schluessel", df.columns[1]: "straftat",
                                df.columns[2]: "jahr", df.columns[3]: "count"})

        # Keep only rows whose Schlüssel is a 6-digit numeric string.
        # BKA Schlüsselverzeichnis uses 6 digits (xxxxxx); the first non-data
        # rows have Schlüssel='------' (cross-offence total marker) and the
        # very first row is a numeric column-position marker (1, 2, 3...).
        df = df.dropna(subset=["schluessel"])
        df["schluessel"] = df["schluessel"].astype(str).str.strip()
        df = df[df["schluessel"].str.match(r"^\d{6}$")]

        df["jahr"] = pd.to_numeric(df["jahr"], errors="coerce")
        df = df.dropna(subset=["jahr"])
        df["jahr"] = df["jahr"].astype(int)
        df["count"] = pd.to_numeric(df["count"], errors="coerce").fillna(0).astype(int)
        df["straftat"] = df["straftat"].astype(str).str.strip()
        df["suspect_dim"] = suspect_dim

        log.info(
            "[DE] %s → %d rows (%d Schlüssel × %d years), dim=%s",
            filename, len(df), df["schluessel"].nunique(),
            df["jahr"].nunique(), suspect_dim,
        )
        return df[["schluessel", "straftat", "jahr", "count", "suspect_dim"]].reset_index(drop=True)

    @staticmethod
    def _guess_dim_from_filename(filename: str) -> str:
        f = filename.lower()
        if "nichtdeutsch" in f:
            return "foreign"
        if "deutsch" in f:
            return "national"
        return "total"

    def normalise(self, df: pd.DataFrame, src: SourceFile) -> pd.DataFrame:
        """Map Schlüssel → harmonised category; emit one row per (category, dim) for the latest year."""
        if df.empty:
            return df

        df = df.copy()
        df["category"] = df["schluessel"].map(SCHLUESSEL_TO_CATEGORY)
        df = df.dropna(subset=["category"])

        latest_year = int(df["jahr"].max())
        df = df[df["jahr"] == latest_year]

        agg = (
            df.groupby(["category", "suspect_dim"], as_index=False)
            .agg(
                count=("count", "sum"),
                native_examples=(
                    "straftat",
                    lambda s: ", ".join(sorted({str(x) for x in s})[:3]),
                ),
            )
        )

        retrieved_at = pd.Timestamp.now(tz="UTC").tz_localize(None)
        pop_de = population("DE")  # NUTS-0 Germany population

        rows: list[dict] = []
        for _, r in agg.iterrows():
            count = int(r["count"])
            rate = (count / pop_de * 100_000) if pop_de else None
            rows.append(
                {
                    "source_country": "DE",
                    "source_authority": self.authority,
                    "source_url": ZEITREIHEN_INDEX,
                    "source_file_hash": src.sha256,
                    "retrieved_at": retrieved_at,
                    "period_start": pd.Timestamp(date(latest_year, 1, 1)),
                    "period_end": pd.Timestamp(date(latest_year, 12, 31)),
                    "period_type": "year",
                    "region_code": "DE",
                    "region_level": 0,
                    "crime_category": str(r["category"]),
                    "crime_category_native": str(r["native_examples"]),
                    "suspect_dim": str(r["suspect_dim"]),
                    "suspect_dim_value": None,
                    "count": count,
                    "denominator_population": pop_de,
                    "denominator_source": "Eurostat NUTS 2021" if pop_de else None,
                    "rate_per_100k": rate,
                    "notes": (
                        "BKA PKS Zeitreihen (federal-level). T20 → total, "
                        "T40 → national (deutsche Tatverdächtige), "
                        "T50 → foreign (Nichtdeutsche Tatverdächtige). "
                        "Bundesländer-level requires the deeper Standardtabellen, "
                        "wired as a manual drop only."
                    ),
                }
            )

        out = pd.DataFrame(rows)
        if not out.empty:
            out["count"] = out["count"].astype(int)
            out["region_level"] = out["region_level"].astype(int)
            out["denominator_population"] = out["denominator_population"].astype("Int64")

        log.info(
            "[DE] normalised %d rows (year %d) for suspect_dim=%s",
            len(out), latest_year, df["suspect_dim"].iloc[0] if len(df) else "?"
        )
        return out
