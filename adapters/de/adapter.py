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

# Filenames (URL-encoded as published) we care about. Two families:
# (a) Zeitreihen federal totals — Schlüssel × year (no Land axis):
#         T20 / T40 / T50 (total / German / non-German)
# (b) Land files — Schlüssel × Bundesland (no year axis, just latest):
#         LA-F-01-T01 (cases by Land) + LA-TV-05-T50 (non-German TV by Land)
# Land files unlock the 16-Bundesland choropleth.
ZR_FILES: dict[str, tuple[str, str]] = {
    # local-filename  ->  (filename-pattern, suspect_dim)
    "T20-tv-insg.xlsx":            ("ZR-TV-01-T20-TV-insg",          "total"),
    "T40-tv-deutsch.xlsx":         ("ZR-TV-04-T40-TV-insg-deutsch",  "national"),
    "T50-tv-nichtdeutsch.xlsx":    ("ZR-TV-07-T50-TV-insg-nichtdeutsch", "foreign"),
    "LA-F-01-T01-laender-faelle.xlsx": ("LA-F-01-T01-Laender-Faelle",    "total"),
    # LA-TV-05 (Land-level non-German Tatverdächtige) intentionally omitted
    # from this turn. Mixing it with LA-F-01-T01 (cases) would compute
    # meaningless suspect/case ratios > 100%. To do FB at Bundesland we need
    # LA-TV-01 (total TV per Land) + LA-TV-05 — wired together — which is
    # tracked as next-turn work in ROADMAP.md section A.
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
        # Try URL discovery for Zeitreihen first; merge with any manually-placed
        # Land-XLSX files (LA-F-01-T01 / LA-TV-05) found under data/raw/de/.
        srcs: list[SourceFile] = []
        urls = _discover_zr_urls()
        if urls:
            for local_name, info in urls.items():
                try:
                    src = fetch_to_raw(info.discovered_url, country="de", filename=local_name)
                except Exception as e:  # noqa: BLE001
                    log.warning("[DE] %s failed: %s", local_name, e)
                    continue
                srcs.append(src)
                log.info("[DE] discovered ZR %s (%s)", local_name, src.sha256[:12])
        else:
            log.warning("[DE] could not discover Zeitreihen URLs; relying on manual fallback only")

        # Always check for Land-XLSX manually placed under data/raw/de/.
        # These give the Bundesland breakdown. Adapter logs and skips quietly
        # if they're not present.
        for land_name in ("LA-F-01-T01-laender-faelle.xlsx",):
            for candidate in (REPO_ROOT / "data" / "raw" / "de").rglob(land_name):
                import hashlib
                from datetime import datetime, timezone
                srcs.append(SourceFile(
                    url="manual",
                    local_path=str(candidate.relative_to(REPO_ROOT)),
                    fetched_at=datetime.now(timezone.utc),
                    sha256=hashlib.sha256(candidate.read_bytes()).hexdigest(),
                ))
                log.info("[DE] discovered Land %s", candidate.name)
                break  # one per name

        if not srcs:
            log.error(
                "[DE] no Zeitreihen URLs discovered and no manual files found. "
                "Manual fallback: see ZEITREIHEN_INDEX docstring.",
            )
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
        """Parse one BKA XLSX → long DataFrame. Two families handled:

        - Zeitreihen (T20/T40/T50): Schlüssel × Jahr, federal-only.
        - Land (LA-F-01-T01 / LA-TV-05): Schlüssel × Bundesland, latest only.

        Output canonicalised columns: ``schluessel, straftat, jahr,
        bundesland, count, suspect_dim``. ``bundesland`` is None for
        federal-only rows; ``jahr`` is filled from the file's metadata
        for Land files (which carry only the current year).
        """
        path = REPO_ROOT / src.local_path
        filename = path.name
        info = ZR_FILES.get(filename)
        suspect_dim = info[1] if info else self._guess_dim_from_filename(filename)
        is_land = "LA-F" in filename or "LA-TV" in filename or "laender" in filename.lower()
        log.info(
            "[DE] parsing %s (is_land=%s, suspect_dim=%r)",
            path.relative_to(REPO_ROOT), is_land, suspect_dim,
        )

        if is_land:
            return self._parse_land(path, suspect_dim)
        return self._parse_zeitreihen(path, suspect_dim, filename)

    def _parse_zeitreihen(self, path: Path, suspect_dim: str, filename: str) -> pd.DataFrame:
        xl = pd.ExcelFile(path)
        sheet = next((s for s in xl.sheet_names if "ZR" in s), xl.sheet_names[0])
        df = pd.read_excel(xl, sheet_name=sheet, header=5, dtype=object)
        df = df.rename(columns={df.columns[0]: "schluessel", df.columns[1]: "straftat",
                                df.columns[2]: "jahr", df.columns[3]: "count"})
        df = df.dropna(subset=["schluessel"])
        df["schluessel"] = df["schluessel"].astype(str).str.strip()
        df = df[df["schluessel"].str.match(r"^\d{6}$")]
        df["jahr"] = pd.to_numeric(df["jahr"], errors="coerce")
        df = df.dropna(subset=["jahr"])
        df["jahr"] = df["jahr"].astype(int)
        df["count"] = pd.to_numeric(df["count"], errors="coerce").fillna(0).astype(int)
        df["straftat"] = df["straftat"].astype(str).str.strip()
        df["suspect_dim"] = suspect_dim
        df["bundesland"] = None
        log.info("[DE/ZR] %s → %d rows", filename, len(df))
        return df[["schluessel", "straftat", "jahr", "bundesland", "count", "suspect_dim"]].reset_index(drop=True)

    def _parse_land(self, path: Path, suspect_dim: str) -> pd.DataFrame:
        """LA-F-01-T01 layout: header at row 4, columns:
           Schlüssel | Straftat | Bundesland | Anzahl erfasste Fälle | ...
           LA-TV-05 layout: header at row 4 too, columns:
           Schlüssel | Straftat | Bundesland | Sexus | Tatverdächtige insgesamt | ...
        """
        xl = pd.ExcelFile(path)
        sheet = xl.sheet_names[0]
        df = pd.read_excel(xl, sheet_name=sheet, header=3, dtype=object)
        # First three columns are stable; the count column is column index 3 for
        # cases (Anzahl erfasste Fälle) and column index 4 for TV (Sexus is 3,
        # Tatverdächtige insgesamt is 4).
        df = df.rename(columns={df.columns[0]: "schluessel",
                                df.columns[1]: "straftat",
                                df.columns[2]: "bundesland"})
        # Detect whether there's a Sexus column (TV-style).
        has_sexus = "Sexus" in str(df.columns[3]) if len(df.columns) > 3 else False
        count_col = df.columns[4] if has_sexus else df.columns[3]
        df = df.rename(columns={count_col: "count"})

        df = df.dropna(subset=["schluessel", "bundesland"])
        df["schluessel"] = df["schluessel"].astype(str).str.strip()
        df = df[df["schluessel"].str.match(r"^\d{6}$")]
        df["count"] = pd.to_numeric(df["count"], errors="coerce").fillna(0).astype(int)
        df["bundesland"] = df["bundesland"].astype(str).str.strip()
        df["straftat"] = df["straftat"].astype(str).str.strip()
        # Sum across Sexus M/W for TV file.
        if has_sexus:
            df = (
                df.groupby(["schluessel", "straftat", "bundesland"], as_index=False)
                .agg(count=("count", "sum"))
            )
        # Latest year is whatever the file ships — extract from path or assume.
        # The BKA Land files are always for the previous calendar year.
        from datetime import datetime, timezone
        try:
            mtime_year = datetime.fromtimestamp(path.stat().st_mtime).year
        except OSError:
            mtime_year = datetime.now(timezone.utc).year
        df["jahr"] = mtime_year - 1
        df["suspect_dim"] = suspect_dim
        log.info("[DE/Land] %s → %d rows × %d Bundesländer",
                 path.name, len(df), df["bundesland"].nunique())
        return df[["schluessel", "straftat", "jahr", "bundesland", "count", "suspect_dim"]].reset_index(drop=True)

    @staticmethod
    def _guess_dim_from_filename(filename: str) -> str:
        f = filename.lower()
        if "nichtdeutsch" in f:
            return "foreign"
        if "deutsch" in f:
            return "national"
        return "total"

    def normalise(self, df: pd.DataFrame, src: SourceFile) -> pd.DataFrame:
        """Map Schlüssel → harmonised category. Two branches:
        - Land rows (bundesland not null) → NUTS-1 rows per Bundesland.
        - Federal rows (bundesland null) → NUTS-0 rows.
        """
        if df.empty:
            return df

        df = df.copy()
        df["category"] = df["schluessel"].map(SCHLUESSEL_TO_CATEGORY)
        df = df.dropna(subset=["category"])

        is_land = df["bundesland"].notna().any()
        latest_year = int(df["jahr"].max())
        df = df[df["jahr"] == latest_year]

        retrieved_at = pd.Timestamp.now(tz="UTC").tz_localize(None)
        rows: list[dict] = []

        if is_land:
            # Map Bundesland names → NUTS codes via region_map.csv. The native_name
            # column already holds proper German names.
            rm_df = pd.read_csv(DE_DIR / "region_map.csv", dtype=str, comment="#").fillna("")
            name_to_nuts = {
                r["native_name"].strip(): r["nuts_code"]
                for _, r in rm_df.iterrows()
            }
            df["nuts"] = df["bundesland"].map(name_to_nuts)
            # Drop rows we couldn't map (sometimes BKA includes an aggregate "Bund")
            unmapped = df[df["nuts"].isna()]["bundesland"].unique().tolist()
            if unmapped:
                log.info("[DE/Land] unmapped Bundesländer dropped: %s", unmapped)
            df = df.dropna(subset=["nuts"])
            agg = (
                df.groupby(["nuts", "category", "suspect_dim"], as_index=False)
                .agg(count=("count", "sum"),
                     native_examples=("straftat", lambda s: ", ".join(sorted({str(x) for x in s})[:3])))
            )
            for _, r in agg.iterrows():
                nuts = str(r["nuts"])
                pop = population(nuts)
                count = int(r["count"])
                rate = (count / pop * 100_000) if pop else None
                rows.append(self._row(
                    period_year=latest_year, nuts=nuts, level=1, category=str(r["category"]),
                    native_examples=str(r["native_examples"]), suspect_dim=str(r["suspect_dim"]),
                    count=count, pop=pop, rate=rate, retrieved_at=retrieved_at, src=src,
                    notes=(
                        "BKA PKS Land-Tabellen (NUTS-1). LA-F-01-T01 = Fälle gesamt; "
                        "LA-TV-05-T50 = nichtdeutsche Tatverdächtige. By-origin-country "
                        "breakdown stays at NUTS-0 (Bund only)."
                    ),
                ))
        else:
            agg = (
                df.groupby(["category", "suspect_dim"], as_index=False)
                .agg(count=("count", "sum"),
                     native_examples=("straftat", lambda s: ", ".join(sorted({str(x) for x in s})[:3])))
            )
            pop_de = population("DE")
            for _, r in agg.iterrows():
                count = int(r["count"])
                rate = (count / pop_de * 100_000) if pop_de else None
                rows.append(self._row(
                    period_year=latest_year, nuts="DE", level=0, category=str(r["category"]),
                    native_examples=str(r["native_examples"]), suspect_dim=str(r["suspect_dim"]),
                    count=count, pop=pop_de, rate=rate, retrieved_at=retrieved_at, src=src,
                    notes=(
                        "BKA PKS Zeitreihen (federal NUTS-0). T20=total, T40=national, "
                        "T50=foreign (Nichtdeutsche Tatverdächtige)."
                    ),
                ))

        out = pd.DataFrame(rows)
        if not out.empty:
            out["count"] = out["count"].astype(int)
            out["region_level"] = out["region_level"].astype(int)
            out["denominator_population"] = out["denominator_population"].astype("Int64")
        log.info("[DE] normalised %d rows (year %d, is_land=%s)", len(out), latest_year, is_land)
        return out

    def _row(self, *, period_year, nuts, level, category, native_examples,
             suspect_dim, count, pop, rate, retrieved_at, src, notes):
        return {
            "source_country": "DE",
            "source_authority": self.authority,
            "source_url": ZEITREIHEN_INDEX,
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
            "denominator_source": "Eurostat / hand-curated mid-2024" if pop else None,
            "rate_per_100k": rate,
            "notes": notes,
        }
