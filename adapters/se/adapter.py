"""Sweden adapter — BRÅ Statistikdatabasen (PXweb API).

Source: https://statistik.bra.se/api/v1/sv/...
Foreign-background published? Occasionally, in special reports.
Incident-level? No.

Stub.
"""

from __future__ import annotations

import pandas as pd

from adapters.common.base import Adapter, SourceFile


class SEAdapter(Adapter):
    country = "SE"
    authority = "BRÅ"
    cadence = "quarterly"

    def discover(self) -> list[SourceFile]:
        raise NotImplementedError("SE discover()")

    def parse(self, src: SourceFile) -> pd.DataFrame:
        raise NotImplementedError("SE parse()")

    def normalise(self, df: pd.DataFrame, src: SourceFile) -> pd.DataFrame:
        raise NotImplementedError("SE normalise()")
