"""Germany adapter — BKA *Polizeiliche Kriminalstatistik* (PKS).

**Source:** Bundeskriminalamt (BKA). Annual PKS publication includes
*Standardtabellen* (standard tables) as XLSX workbooks. Key tables for our
purposes:

- **Tabelle 01** — Übersicht (federal totals).
- **Tabelle 62** — Aufschlüsselung nach Bundesländern (state breakdown).
- **Tabelle 81/82** — Nichtdeutsche Tatverdächtige (non-German suspects),
  which is what makes Germany distinct among MVP countries.

**Foreign-background published?** **YES** — ``Nichtdeutsche Tatverdächtige``.
This is the headline reason to include Germany at MVP.

**Cadence:** annual, released ~late April / early May.

**Status:** scaffolding complete (Bundesland → NUTS-1 map already populated).
Live BKA fetcher deferred — URLs are published on the PKS yearly landing page
and aren't strictly URL-pattern-predictable (BKA reorganises every few years).
Manual fallback documented below.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from adapters.common.base import Adapter, SourceFile

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DE_DIR = REPO_ROOT / "adapters" / "de"

# Landing page URL (stable across years; the actual XLSX paths are linked
# from here and need to be discovered each May):
PKS_LANDING = (
    "https://www.bka.de/DE/AktuelleInformationen/StatistikenLagebilder/"
    "PolizeilicheKriminalstatistik/pks_node.html"
)


class DEAdapter(Adapter):
    country = "DE"
    authority = "BKA"
    cadence = "annual"

    def discover(self) -> list[SourceFile]:
        log.info(
            "[DE] live BKA fetch not yet wired. "
            "Manual fallback: download the PKS Tabelle 62 (Bundesländer) and "
            "T81/T82 (Nichtdeutsche Tatverdächtige) XLSX files from %s "
            "and place under data/raw/de/<yyyy-mm>/pks-t62.xlsx and pks-t81.xlsx.",
            PKS_LANDING,
        )
        srcs: list[SourceFile] = []
        for pattern in ("pks-t62.xlsx", "pks-t81.xlsx"):
            for candidate in (REPO_ROOT / "data" / "raw" / "de").rglob(pattern):
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
        path = REPO_ROOT / src.local_path
        df = pd.read_excel(path, header=None, dtype=object)
        log.info("[DE] parsed %s (%d rows)", path.relative_to(REPO_ROOT), len(df))
        return df

    def normalise(self, df: pd.DataFrame, src: SourceFile) -> pd.DataFrame:
        raise NotImplementedError(
            "[DE] normalise() not implemented. Wire up after confirming the "
            "exact T62 / T81 column layout of the latest PKS release. The "
            "non-German-suspect dimension lives in T81 (overview) and T82 "
            "(by Bundesland) — emit suspect_dim='national', 'foreign', and "
            "by_origin_country rows distinguished by the source's "
            "'Nationalität' axis."
        )
