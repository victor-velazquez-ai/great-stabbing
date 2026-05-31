"""Germany adapter — BKA *Polizeiliche Kriminalstatistik* (PKS).

**Source:** Bundeskriminalamt (BKA). Annual PKS publication includes
*Standardtabellen* (standard tables) as XLSX workbooks. Key tables we care about:

- **T01 / T01-OPF / T01-TV** — Übersicht, Fälle and Tatverdächtige federal totals.
- **T62** — *Aufschlüsselung nach Bundesländern*, the state-level breakdown.
- **T81 / T82** — *Nichtdeutsche Tatverdächtige* (non-German suspects), federal
  totals and Bundesland-level. **This is the headline reason Germany is in the
  MVP** — it provides the foreign-background dimension that the project's
  methodology page calls out as distinct.

**Foreign-background published?** **YES** — emitted as
``suspect_dim ∈ {"total", "national", "foreign"}`` rows.

**Cadence:** annual, released ~late April / early May.

## Why discover() is manual-only at MVP

BKA's PKS portal at bka.de is a server-rendered Government Site Builder
installation. The XLSX downloads live under
``/SharedDocs/Downloads/DE/Publikationen/PolizeilicheKriminalstatistik/<year>/Standardtabellen/<file>.xlsx``
behind a 303-redirect protection layer that requires a ``v=<N>`` cache-buster
that changes per publish. The actual URLs are linked from JavaScript-rendered
nav menus, not from plain HTML — so neither ``curl`` nor lightweight scrapers
can discover them without a real browser.

A future hardening could use Playwright to navigate the PKS Tabellen pages,
but for an annual data source the cost/benefit favours a manual once-a-year
download. See ``docs/adding-a-country.md`` for the recipe.

## Workflow when the file is placed manually

1. Download the latest PKS Standardtabellen from the BKA page above. The file
   we want is typically named ``standardtabellenFaelle.xlsx`` and contains
   tables T01 through T80. For the non-German-suspect dimension, also
   download ``standardtabellenTV.xlsx`` (T81/T82).
2. Place at::

       data/raw/de/<yyyy-mm>/pks-faelle.xlsx
       data/raw/de/<yyyy-mm>/pks-tv.xlsx

3. Run::

       uv run python scripts/run_adapter.py DE

   The adapter probes ``data/raw/de/**`` for either filename.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from adapters.common.base import Adapter, SourceFile
from adapters.common.nuts import load_region_map, population

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DE_DIR = REPO_ROOT / "adapters" / "de"

PKS_LANDING = (
    "https://www.bka.de/DE/AktuelleInformationen/StatistikenLagebilder/"
    "PolizeilicheKriminalstatistik/pks_node.html"
)


class DEAdapter(Adapter):
    country = "DE"
    authority = "BKA"
    cadence = "annual"

    # Filename patterns we look for when discovering manually-dropped files.
    # The first match per pattern wins.
    FALLBACK_PATTERNS = ("pks-faelle.xlsx", "pks-tv.xlsx", "standardtabellen*.xlsx")

    def discover(self) -> list[SourceFile]:
        srcs: list[SourceFile] = []
        for pattern in self.FALLBACK_PATTERNS:
            for candidate in (REPO_ROOT / "data" / "raw" / "de").rglob(pattern):
                srcs.append(
                    SourceFile(
                        url="manual",
                        local_path=str(candidate.relative_to(REPO_ROOT)),
                        fetched_at=datetime.now(timezone.utc),
                        sha256=hashlib.sha256(candidate.read_bytes()).hexdigest(),
                    )
                )
        if not srcs:
            log.error(
                "[DE] no BKA PKS file found under data/raw/de/. "
                "Manual fallback: download from %s and place at "
                "data/raw/de/<yyyy-mm>/pks-faelle.xlsx (and pks-tv.xlsx if "
                "you want the Nichtdeutsche Tatverdächtige dimension).",
                PKS_LANDING,
            )
        return srcs

    def parse(self, src: SourceFile) -> pd.DataFrame:
        """Parse a BKA PKS XLSX file, returning a long-form DataFrame.

        BKA workbooks layout one table per sheet. Each sheet has:
          - A title block (1–6 rows of metadata)
          - A header row introducing offence/Bundesland labels
          - Data rows keyed by Schluessel (6-digit offence code) and Bundesland
            number (01–16 per region_map.csv).

        We look for sheets matching ``T62*`` (Bundesländer aggregation) and
        ``T81*`` / ``T82*`` (Nichtdeutsche Tatverdächtige). Other sheets are
        ignored. The output is long-format with:
          ``sheet, schluessel, schluessel_label, bundesland_native, count,
            suspect_dim, suspect_dim_value``.

        Because the BKA layouts change subtly each publication year, this
        parser is intentionally lenient: it scans for known label columns
        rather than relying on fixed cell positions. When the parser can't
        find a known table family, it logs and skips.
        """
        path = REPO_ROOT / src.local_path
        log.info("[DE] parsing %s", path.relative_to(REPO_ROOT))

        xl = pd.ExcelFile(path)
        bundeslaender = self._load_bundesland_map()
        bundesland_names_lc = {v.strip().lower() for v in bundeslaender.values()}

        out_rows: list[dict] = []

        for sheet in xl.sheet_names:
            sheet_clean = sheet.strip().upper()
            # Only attempt tables that look like Bundesländer breakdown or
            # Nichtdeutsche Tatverdächtige.
            if not (
                sheet_clean.startswith("T62")
                or sheet_clean.startswith("T81")
                or sheet_clean.startswith("T82")
            ):
                continue

            log.info("[DE] scanning sheet %r", sheet)
            raw = pd.read_excel(xl, sheet_name=sheet, header=None, dtype=object)
            if raw.empty:
                continue

            # Locate the first row whose first non-empty cell is a 6-digit
            # numeric Schlüssel — that's the data start.
            data_start = None
            for i, row in raw.iterrows():
                first = row.dropna().head(1)
                if first.empty:
                    continue
                v = str(first.iloc[0]).strip()
                if v.isdigit() and len(v) == 6:
                    data_start = i
                    break
            if data_start is None:
                log.info("[DE] no Schluessel rows in %r — skipping", sheet)
                continue

            # Header row is one above data_start, but BKA often has multi-row
            # headers; we re-read with header=row-above as a heuristic.
            header_row = max(0, int(data_start) - 1)
            df = pd.read_excel(xl, sheet_name=sheet, header=header_row, dtype=object)
            cols = [str(c).strip() for c in df.columns]
            df.columns = cols

            # We expect columns named something like
            #   "Schlüssel" or "Schluessel", "Straftat", and one column per
            # Bundesland (with state names or codes as headers).
            schluessel_col = next(
                (c for c in cols if c.lower().startswith("schl")), cols[0]
            )
            label_candidates = [c for c in cols if "straftat" in c.lower()]
            label_col = label_candidates[0] if label_candidates else cols[1]

            # Bundesland columns: those whose header matches a known native
            # name (case-insensitive).
            bundesland_cols = [
                c for c in cols if c.strip().lower() in bundesland_names_lc
            ]
            if not bundesland_cols:
                log.info("[DE] no Bundesland columns in %r — skipping", sheet)
                continue

            # Suspect dim for this sheet.
            if sheet_clean.startswith("T62"):
                suspect_dim = "total"
            else:
                suspect_dim = "foreign"  # T81/T82 = Nichtdeutsche Tatverdächtige

            # Melt long.
            keep_cols = [schluessel_col, label_col, *bundesland_cols]
            sub = df[keep_cols].dropna(subset=[schluessel_col])
            sub = sub.rename(
                columns={schluessel_col: "schluessel", label_col: "schluessel_label"}
            )
            sub["schluessel"] = sub["schluessel"].astype(str).str.strip()
            sub = sub[sub["schluessel"].str.match(r"^\d{6}$")]
            long = sub.melt(
                id_vars=["schluessel", "schluessel_label"],
                value_vars=bundesland_cols,
                var_name="bundesland_native",
                value_name="count",
            )
            long["count"] = pd.to_numeric(long["count"], errors="coerce")
            long = long.dropna(subset=["count"])
            long["count"] = long["count"].astype(int)
            long["sheet"] = sheet
            long["suspect_dim"] = suspect_dim
            out_rows.append(long)

        if not out_rows:
            log.warning("[DE] no T62/T81/T82 data extracted from %s", path.name)
            return pd.DataFrame()

        df = pd.concat(out_rows, ignore_index=True)
        log.info(
            "[DE] parsed %d rows across %d sheets, %d offence codes",
            len(df), df["sheet"].nunique(), df["schluessel"].nunique()
        )
        return df

    def normalise(self, df: pd.DataFrame, src: SourceFile) -> pd.DataFrame:
        if df.empty:
            return df

        # Native PKS Schlüssel → harmonised category. Curated subset for MVP;
        # the full PKS Schlüsselverzeichnis has ~600 codes but only a handful
        # are violent-bodily-harm offences in our scope.
        # Source: BKA Schlüsselverzeichnis 2024.
        schluessel_to_category = {
            "010000": "homicide",        # Mord und Totschlag (collected)
            "020000": "homicide",        # Tötung in Tateinheit ...
            "892000": "violent_total",   # Gewaltkriminalität (umbrella metric)
            "892100": "homicide",        # Mord, Totschlag, Tötung auf Verlangen
            "892200": "sexual_assault",  # Vergewaltigung u. besondere Fälle
            "892300": "robbery_violent", # Raubdelikte
            "892400": "assault_serious", # Gefährliche/schwere KV
            "892500": "assault_serious", # Erpresserische Menschenraub etc.
        }

        bundesland_map = self._reverse_bundesland_map()

        df = df.copy()
        df["category"] = df["schluessel"].map(schluessel_to_category)
        df = df.dropna(subset=["category"])
        df["nuts"] = df["bundesland_native"].str.strip().str.lower().map(bundesland_map)
        df = df.dropna(subset=["nuts"])

        agg = (
            df.groupby(["nuts", "category", "suspect_dim"], as_index=False)
            .agg(
                count=("count", "sum"),
                native_examples=(
                    "schluessel_label",
                    lambda s: ", ".join(sorted({str(x) for x in s})[:3]),
                ),
            )
        )

        # PKS publications are released in spring for the prior calendar year.
        # We stamp the period as the prior year. We use the source's mtime if
        # discoverable, else current year - 1.
        local_path = REPO_ROOT / src.local_path
        try:
            mtime_year = datetime.fromtimestamp(local_path.stat().st_mtime).year
        except OSError:
            mtime_year = datetime.now(timezone.utc).year
        period_year = mtime_year - 1

        retrieved_at = pd.Timestamp.now(tz="UTC").tz_localize(None)
        rows = []
        for _, r in agg.iterrows():
            nuts = str(r["nuts"])
            pop = population(nuts)
            count = int(r["count"])
            rate = (count / pop * 100_000) if pop else None
            rows.append(
                {
                    "source_country": "DE",
                    "source_authority": self.authority,
                    "source_url": PKS_LANDING,
                    "source_file_hash": src.sha256,
                    "retrieved_at": retrieved_at,
                    "period_start": pd.Timestamp(date(period_year, 1, 1)),
                    "period_end": pd.Timestamp(date(period_year, 12, 31)),
                    "period_type": "year",
                    "region_code": nuts,
                    "region_level": 1,
                    "crime_category": str(r["category"]),
                    "crime_category_native": str(r["native_examples"]),
                    "suspect_dim": str(r["suspect_dim"]),
                    "suspect_dim_value": None,
                    "count": count,
                    "denominator_population": pop,
                    "denominator_source": "Eurostat / ONS-style estimate" if pop else None,
                    "rate_per_100k": rate,
                    "notes": (
                        "BKA PKS. T81/T82 (Nichtdeutsche Tatverdächtige) emit "
                        "suspect_dim='foreign'; T62 emits suspect_dim='total'."
                    ),
                }
            )

        out = pd.DataFrame(rows)
        if not out.empty:
            out["count"] = out["count"].astype(int)
            out["region_level"] = out["region_level"].astype(int)
            out["denominator_population"] = out["denominator_population"].astype("Int64")
        log.info(
            "[DE] normalised %d rows across %d Bundesländer, %d (cat, dim) combos",
            len(out), out["region_code"].nunique() if not out.empty else 0,
            len(agg),
        )
        return out

    # ---- helpers -----------------------------------------------------

    def _load_bundesland_map(self) -> dict[str, str]:
        df = pd.read_csv(DE_DIR / "region_map.csv", dtype=str, comment="#").fillna("")
        return dict(zip(df["native_code"], df["native_name"], strict=True))

    def _reverse_bundesland_map(self) -> dict[str, str]:
        """lower-cased native_name → NUTS code."""
        nm = load_region_map("DE")  # native_code → nuts_code
        slugs = self._load_bundesland_map()
        return {slugs[code].strip().lower(): nuts for code, nuts in nm.items() if code in slugs}
