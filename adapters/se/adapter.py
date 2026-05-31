"""Sweden adapter — BRÅ Statistikdatabasen.

**Source:** Brottsförebyggande rådet (BRÅ), the Swedish National Council for
Crime Prevention. Publishes *Anmälda brott* (reported offences) by län and
crime category via a PXweb 2.0 JSON API.

**Foreign-background published?** Only in occasional special reports (e.g. the
2021 *Misstänkta för brott* report). The main statistical database does not
include this dimension. For MVP we emit only ``suspect_dim="total"``.

**Cadence:** quarterly publication; annual rolling data.

**Status:** scaffolding complete (län → NUTS-3 map, category map).
Live PXweb 2.0 API call deferred — requires negotiating the exact table ID
and query structure. Manual fallback documented below.
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
SE_DIR = REPO_ROOT / "adapters" / "se"

# PXweb 2.0 endpoint base. Specific table IDs need to be confirmed:
# https://www.bra.se/statistik/kriminalstatistik/anmalda-brott.html
PXWEB_BASE = "https://statistik.bra.se/api/v2/sv"


class SEAdapter(Adapter):
    country = "SE"
    authority = "BRÅ"
    cadence = "quarterly"

    def discover(self) -> list[SourceFile]:
        log.info(
            "[SE] live PXweb fetch not yet wired. "
            "Manual fallback: download the latest BRÅ län-level Excel/CSV "
            "from https://www.bra.se/statistik/kriminalstatistik/anmalda-brott.html "
            "and place under data/raw/se/<yyyy-mm>/anmalda-brott.csv."
        )
        for candidate in (REPO_ROOT / "data" / "raw" / "se").rglob("anmalda-brott.csv"):
            log.info("[SE] using manually-placed file %s", candidate.relative_to(REPO_ROOT))
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
        path = REPO_ROOT / src.local_path
        df = pd.read_csv(path)
        log.info("[SE] parsed %d rows from %s", len(df), path.relative_to(REPO_ROOT))
        return df

    def normalise(self, df: pd.DataFrame, src: SourceFile) -> pd.DataFrame:
        raise NotImplementedError(
            "[SE] normalise() not implemented. Run discover() with a manually "
            "placed file first to confirm column shape, then map to canonical."
        )
