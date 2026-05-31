"""Italy adapter — ISTAT *Delitti denunciati dalle forze di polizia*.

**Source:** Istituto Nazionale di Statistica (ISTAT). Annual statistics on
crimes reported to the judicial authority by police forces, broken down
by regione (NUTS-2 in Italy's case — regioni already align with NUTS-2).

**Foreign-background published?** Partial. ISTAT publishes a nationality
dimension on some tables but not consistently. For MVP we emit only
``suspect_dim="total"`` rows.

**Cadence:** annual.

**Status:** scaffolding complete (region map + category map). Live SDMX
fetch deferred to next iteration — ISTAT's new exploradati portal requires
discovering the correct dataflow ID + dimension key, which is non-trivial
via REST probing alone. Manual fallback documented below.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from adapters.common.base import Adapter, SourceFile

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
IT_DIR = REPO_ROOT / "adapters" / "it"

# Best-known SDMX endpoint patterns (verify before relying on either).
# 1. New explorer SDMX REST:
#    https://esploradati.istat.it/SDMXWS/rest/data/<DATAFLOW>/<KEY>/?format=csv
# 2. Direct database export pages publish XLSX/CSV at varying URLs.
SDMX_BASE = "https://esploradati.istat.it/SDMXWS/rest"

# Candidate dataflow IDs known to have existed historically. The actual ID
# in the current ISTAT system needs to be confirmed by listing dataflows:
# GET {SDMX_BASE}/dataflow/IT1?detail=allstubs
CANDIDATE_DATAFLOWS: tuple[str, ...] = (
    "JUS_DELITTI_REGIONE",
    "DCCV_DELITTIPS",
    "151_910",  # legacy
)


class ITAdapter(Adapter):
    country = "IT"
    authority = "ISTAT"
    cadence = "annual"

    def discover(self) -> list[SourceFile]:
        log.info(
            "[IT] live SDMX fetch not yet wired. "
            "Manual fallback: download the latest ISTAT *Delitti denunciati* "
            "table from https://esploradati.istat.it/ and place under "
            "data/raw/it/<yyyy-mm>/delitti-denunciati.csv."
        )
        # Probe for a manual drop-in file.
        for candidate in (REPO_ROOT / "data" / "raw" / "it").rglob("delitti-denunciati.csv"):
            log.info("[IT] using manually-placed file %s", candidate.relative_to(REPO_ROOT))
            import hashlib
            from datetime import datetime, timezone

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
        # ISTAT SDMX CSV exports typically include columns like
        # TIME_PERIOD, REF_AREA (region code), TIPO_DATO12, ITTER107 (geo),
        # and an OBS_VALUE column. The exact column set depends on the
        # dataflow — we accept variants by snapping to known names.
        df = pd.read_csv(path)
        log.info("[IT] parsed %d rows from %s", len(df), path.relative_to(REPO_ROOT))
        return df

    def normalise(self, df: pd.DataFrame, src: SourceFile) -> pd.DataFrame:
        raise NotImplementedError(
            "[IT] normalise() not implemented. Run discover() with a manually "
            "placed file first to confirm column shape, then map to canonical."
        )
