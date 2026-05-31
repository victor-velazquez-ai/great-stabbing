"""UK adapter — ONS Police Force Area data tables (rolling annual, published quarterly).

**Source:** Office for National Statistics, *Police force area data tables*.
Released quarterly as Excel workbooks containing rolling 12-month aggregates
of recorded crime by Police Force Area × offence type.

**URL pattern:**
``https://www.ons.gov.uk/file?uri=/peoplepopulationandcommunity/crimeandjustice/
datasets/policeforceareadatatables/yearending<month><year>/
pfatablesyearending<month><year>.xlsx``

where ``<month>`` is lowercase (``march``, ``june``, ``september``, ``december``).

**Foreign-background published?** No. All rows are ``suspect_dim="total"``.

**Incident-level?** No (that's data.police.uk, added in a later phase).

**Cadence:** quarterly release of rolling-annual data. ``period_type`` is
``year`` because each release covers a 12-month window.

**Implementation notes for parse():**
ONS workbooks contain many sheets. The one we want is typically named ``Table P2``
or ``P2`` — "Police recorded crime by police force area, by offence". Layout:

    Row 1-3:  Title + period
    Row 4:    Offence type column headers
    Row 5+:   One row per PFA, first column is force name, rest are counts.

ONS occasionally tweaks the sheet name and the exact start row. ``parse()`` is
defensive: it scans sheets for ones with a "Police force area" header column
and treats the first matching sheet as P2.
"""

from __future__ import annotations

import logging
import re
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from io import BytesIO
from pathlib import Path

import pandas as pd
import requests
import yaml

from adapters.common.base import Adapter, SourceFile
from adapters.common.http import RAW_DIR, fetch_to_raw
from adapters.common.nuts import load_region_map, population

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
UK_DIR = REPO_ROOT / "adapters" / "uk"

# ONS publishes quarterly, three months after the end of the period.
# Try the last 6 quarter-endings and use the freshest one we can fetch.
#
# URL form (confirmed on https://www.ons.gov.uk/.../policeforceareadatatables):
#   folder: yearending<full-month><year>/  e.g. yearendingdecember2025
#   file:   pfatablesye<3-letter-month><year>.xlsx  e.g. pfatablesyedec2025.xlsx
QUARTER_MONTHS = ("march", "june", "september", "december")
MONTH_ABBR = {"march": "mar", "june": "jun", "september": "sep", "december": "dec"}
URL_TEMPLATE = (
    "https://www.ons.gov.uk/file?uri=/peoplepopulationandcommunity/crimeandjustice/"
    "datasets/policeforceareadatatables/yearending{month}{year}/"
    "pfatablesye{abbr}{year}.xlsx"
)


@dataclass(frozen=True)
class _Release:
    """One ONS release identifier: (month_word, year, period_end_date)."""

    month: str
    year: int

    @property
    def url(self) -> str:
        return URL_TEMPLATE.format(
            month=self.month, abbr=MONTH_ABBR[self.month], year=self.year
        )

    @property
    def filename(self) -> str:
        # Use our own local filename — keeps month full-word so the regex in
        # _release_from_filename stays human-readable.
        return f"pfatables-yearending-{self.month}-{self.year}.xlsx"

    @property
    def period_end(self) -> date:
        month_idx = {"march": 3, "june": 6, "september": 9, "december": 12}[self.month]
        # period_end is the last day of the named month
        if month_idx == 12:
            return date(self.year, 12, 31)
        return date(self.year, month_idx + 1, 1).replace(day=1) - pd.Timedelta(days=1)  # type: ignore[return-value]

    @property
    def period_start(self) -> date:
        # 12 months earlier
        d = self.period_end
        return date(d.year - 1, d.month, d.day) + pd.Timedelta(days=1)  # type: ignore[return-value]


def _candidate_releases(today: date | None = None) -> list[_Release]:
    """Return up to 6 release candidates, freshest first."""
    if today is None:
        today = datetime.now(timezone.utc).date()
    # Most recent quarter-end ≤ today minus ~3 months publishing lag.
    # We just try the 6 most recent quarter-endings regardless and let HTTP decide.
    cands: list[_Release] = []
    y, m = today.year, today.month
    # Iterate backwards through quarter-endings
    for _ in range(6):
        # Find the most recent quarter end strictly before (y, m)
        q_end_month = ((m - 1) // 3) * 3  # 0, 3, 6, 9 → previous Mar/Jun/Sep/Dec
        if q_end_month == 0:
            year, month_word = y - 1, "december"
        else:
            year = y
            month_word = {3: "march", 6: "june", 9: "september"}[q_end_month]
        cands.append(_Release(month=month_word, year=year))
        # Step back another quarter for next iteration
        if month_word == "december":
            y, m = year, 12
        else:
            y, m = year, {"march": 3, "june": 6, "september": 9}[month_word]
        m -= 1
        if m < 1:
            y -= 1
            m += 12
    return cands


def _http_head_ok(url: str, timeout: int = 30) -> bool:
    try:
        r = requests.head(url, timeout=timeout, allow_redirects=True)
        # ONS sometimes returns 200 only for GET — fall through on other codes
        return r.status_code == 200
    except requests.RequestException:
        return False


class UKAdapter(Adapter):
    country = "UK"
    authority = "ONS"
    cadence = "quarterly"  # rolling-12mo, refreshed quarterly

    def discover(self) -> list[SourceFile]:
        for rel in _candidate_releases():
            log.info("[UK] probing %s", rel.url)
            try:
                src = fetch_to_raw(rel.url, country="uk", filename=rel.filename)
            except requests.HTTPError as e:
                log.info("[UK] %s → %s", rel.url, e.response.status_code if e.response else "?")
                continue
            except requests.RequestException as e:
                log.warning("[UK] %s → %s", rel.url, e)
                continue
            # Tag the SourceFile with release metadata using a stable convention
            # (we recover it via filename in normalise()).
            return [src]
        log.error("[UK] no recent ONS PFA release responded; document the manual fallback")
        return []

    # Area-code prefixes that identify individual police forces (not rollups).
    # E23 = English forces, W15 = Welsh forces. ONS PFA tables only cover E&W;
    # Police Scotland and PSNI are not present here.
    FORCE_AREA_CODE_PREFIXES = ("E23", "W15")

    def parse(self, src: SourceFile) -> pd.DataFrame:
        """Read Table P1 of an ONS PFA workbook.

        Returns a long DataFrame with columns:
        ``force_native, area_code, offence_native, count``.
        """
        path = REPO_ROOT / src.local_path
        log.info("[UK] parsing %s", path.relative_to(REPO_ROOT))

        xl = pd.ExcelFile(path)
        # Prefer the canonical Table P1 sheet. Fall back to any "Table P1*" name
        # since ONS occasionally adds a trailing space.
        candidates = [s for s in xl.sheet_names if s.strip().startswith("Table P1")]
        if not candidates:
            # Last-resort fallback: any sheet starting with "Table P".
            candidates = [s for s in xl.sheet_names if s.strip().startswith("Table P")]
        if not candidates:
            raise ValueError(
                f"no Table P1 sheet in {path.name}; sheets: {xl.sheet_names}"
            )
        sheet = candidates[0]

        # Find the header row by scanning column A for "Area Code".
        raw = pd.read_excel(xl, sheet_name=sheet, header=None, dtype=object)
        col_a = raw.iloc[:, 0].astype(str).str.strip()
        header_idx = col_a[col_a.str.casefold() == "area code"].index
        if len(header_idx) == 0:
            # Test fixtures may use simpler layout — use the first row as header.
            header_row = 0
        else:
            header_row = int(header_idx[0])

        df = pd.read_excel(xl, sheet_name=sheet, header=header_row, dtype=object)
        # Normalise column whitespace (ONS headers contain \n and trailing spaces).
        df.columns = [
            " ".join(str(c).replace("\n", " ").split()) if pd.notna(c) else c
            for c in df.columns
        ]
        # Canonicalise the first two column names.
        df = df.rename(columns={df.columns[0]: "area_code", df.columns[1]: "force_native"})
        log.info("[UK] using sheet %r (header row %d)", sheet, header_row)

        # Filter to individual force rows by area code prefix.
        df["area_code"] = df["area_code"].astype(str).str.strip()
        df = df[df["area_code"].str.startswith(self.FORCE_AREA_CODE_PREFIXES)]
        df["force_native"] = df["force_native"].astype(str).str.strip()
        # Strip any "[note N]" trailing tags.
        df["force_native"] = df["force_native"].str.replace(r"\s*\[note\s+\d+\]\s*$", "", regex=True)

        offence_cols = [c for c in df.columns if c not in {"area_code", "force_native"}]
        long = df.melt(
            id_vars=["area_code", "force_native"],
            value_vars=offence_cols,
            var_name="offence_native",
            value_name="count",
        )
        long["offence_native"] = long["offence_native"].astype(str).str.strip()
        long = long.dropna(subset=["count"])
        long["count"] = pd.to_numeric(long["count"], errors="coerce")
        long = long.dropna(subset=["count"])
        long["count"] = long["count"].astype(int)

        log.info("[UK] parsed %d (force, offence) rows from %d forces",
                 len(long), long["force_native"].nunique())
        return long.reset_index(drop=True)

    def normalise(self, df: pd.DataFrame, src: SourceFile) -> pd.DataFrame:
        """Map native names to NUTS + harmonised categories, fill schema."""
        cat_map_path = UK_DIR / "category_map.yaml"
        with cat_map_path.open(encoding="utf-8") as f:
            cat = yaml.safe_load(f) or {}
        mapping: dict[str, str] = cat.get("mapping", {}) or {}

        force_to_nuts = self._reverse_force_map()
        if not force_to_nuts:
            raise RuntimeError("UK region_map.csv is empty")

        # Recover release from filename (`pfatables-yearending-<month>-<year>.xlsx`).
        rel = self._release_from_filename(Path(src.local_path).name)

        rows: list[dict] = []
        retrieved_at = pd.Timestamp.utcnow().replace(tzinfo=None)

        # Group by force × harmonised-category, sum counts (multiple ONS rows
        # may share a harmonised category, e.g. robbery sub-categories).
        df = df.copy()
        df["force_nuts"] = df["force_native"].str.strip().map(
            lambda n: force_to_nuts.get(n.lower())
        )
        df = df.dropna(subset=["force_nuts"])
        df["category"] = df["offence_native"].map(mapping)
        df = df.dropna(subset=["category"])

        # NUTS-1 aggregation: multiple forces (e.g. Met + City of London) → UKI.
        agg = (
            df.groupby(["force_nuts", "category"], as_index=False)
            .agg(count=("count", "sum"), native_examples=("offence_native", lambda s: ", ".join(sorted(set(s))[:3])))
        )

        for _, r in agg.iterrows():
            nuts = str(r["force_nuts"])
            pop = population(nuts)
            count = int(r["count"])
            rate = (count / pop * 100_000) if pop else None
            rows.append(
                {
                    "source_country": "UK",
                    "source_authority": self.authority,
                    "source_url": rel.url if rel else "",
                    "source_file_hash": src.sha256,
                    "retrieved_at": retrieved_at,
                    "period_start": pd.Timestamp(rel.period_start) if rel else pd.NaT,
                    "period_end": pd.Timestamp(rel.period_end) if rel else pd.NaT,
                    "period_type": "year",
                    "region_code": nuts,
                    "region_level": 1,
                    "crime_category": str(r["category"]),
                    "crime_category_native": str(r["native_examples"]),
                    "suspect_dim": "total",
                    "suspect_dim_value": None,
                    "count": count,
                    "denominator_population": pop,
                    "denominator_source": "ONS mid-2023 estimates" if pop else None,
                    "rate_per_100k": rate,
                    "notes": "ONS does not publish a foreign-background dimension for PFA totals.",
                }
            )

        out = pd.DataFrame(rows)
        if out.empty:
            return out

        # Force expected dtypes.
        out["count"] = out["count"].astype(int)
        out["region_level"] = out["region_level"].astype(int)
        out["denominator_population"] = out["denominator_population"].astype("Int64")
        log.info("[UK] normalised %d rows across %d regions", len(out), out["region_code"].nunique())
        return out

    # ------------------- helpers -------------------

    def _load_force_map(self) -> dict[str, str]:
        """slug → native_name as written in ONS tables (Title Case)."""
        df = pd.read_csv(UK_DIR / "region_map.csv", dtype=str, comment="#").fillna("")
        return dict(zip(df["native_code"], df["native_name"], strict=True))

    def _reverse_force_map(self) -> dict[str, str]:
        """lower-cased native_name → NUTS code."""
        nm = load_region_map("UK")  # native_code → nuts_code
        slugs = self._load_force_map()  # native_code → native_name
        return {slugs[code].strip().lower(): nuts for code, nuts in nm.items() if code in slugs}

    @staticmethod
    def _release_from_filename(filename: str) -> _Release | None:
        m = re.match(
            r"pfatables-yearending-(march|june|september|december)-(\d{4})\.xlsx",
            filename,
            re.IGNORECASE,
        )
        if not m:
            return None
        return _Release(month=m.group(1).lower(), year=int(m.group(2)))
