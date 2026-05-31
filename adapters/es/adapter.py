"""Spain adapter — Ministerio del Interior *Balances trimestrales*.

**Source:** Ministerio del Interior, quarterly PDF reports broken down by
provincia and main crime indicator.

**Foreign-background published?** Partial. Nationality of detainees appears
in some MI tables but not consistently. For MVP we emit only
``suspect_dim="total"``.

**Cadence:** quarterly.

**Status:** scaffolding complete (provincia → NUTS-3 map, category map).
Live PDF fetch + table extraction deferred. The bulk of the work is finding
the most recent Balance PDF on a dynamically-generated MI page and then
extracting tables reliably across layout changes.

**Approach when wired up:** ``pdfplumber`` first; Claude fallback on
parsing failures (logged and rate-limited to one fallback per source file).
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
ES_DIR = REPO_ROOT / "adapters" / "es"

MI_LANDING = (
    "https://www.interior.gob.es/opencms/es/servicios-al-ciudadano/"
    "estadisticas/balances-trimestrales-de-criminalidad/"
)


class ESAdapter(Adapter):
    country = "ES"
    authority = "Ministerio del Interior"
    cadence = "quarterly"

    def discover(self) -> list[SourceFile]:
        log.info(
            "[ES] live MI fetch not yet wired. "
            "Manual fallback: download the latest Balance trimestral PDF from "
            "%s and place it at data/raw/es/<yyyy-mm>/balance-trimestral.pdf.",
            MI_LANDING,
        )
        for candidate in (REPO_ROOT / "data" / "raw" / "es").rglob("balance-trimestral.pdf"):
            log.info("[ES] using manually-placed file %s", candidate.relative_to(REPO_ROOT))
            return [
                SourceFile(
                    url="manual",
                    local_path=str(candidate.relative_to(REPO_ROOT)),
                    fetched_at=datetime.now(timezone.utc),
                    sha256=hashlib.sha256(candidate.read_bytes()).hexdigest(),
                )
            ]
        return []

    def parse(self, src: SourceFile) -> pd.DataFrame:
        import pdfplumber  # heavy import; defer

        path = REPO_ROOT / src.local_path
        rows: list[dict] = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables() or []
                for t in tables:
                    if not t or not t[0]:
                        continue
                    headers = [str(c).strip() if c else "" for c in t[0]]
                    for body_row in t[1:]:
                        rec = {
                            h: (body_row[i] if i < len(body_row) else None)
                            for i, h in enumerate(headers)
                        }
                        rows.append(rec)
        log.info("[ES] parsed %d table rows from %s", len(rows), path.relative_to(REPO_ROOT))
        return pd.DataFrame(rows)

    def normalise(self, df: pd.DataFrame, src: SourceFile) -> pd.DataFrame:
        raise NotImplementedError(
            "[ES] normalise() not implemented. Run discover() with a manually "
            "placed PDF first to confirm table layouts (vary by Balance edition), "
            "then map provincia column to native_code in region_map.csv."
        )
