"""Denmark adapter — Danmarks Statistik Statbank API.

Source: https://api.statbank.dk/v1/  (table STRAF11/12 etc.)
Foreign-background published? YES — by country of origin (herkomst).
Incident-level? No.

Stub.
"""

from __future__ import annotations

import pandas as pd

from adapters.common.base import Adapter, SourceFile


class DKAdapter(Adapter):
    country = "DK"
    authority = "Danmarks Statistik"
    cadence = "quarterly"

    def discover(self) -> list[SourceFile]:
        raise NotImplementedError("DK discover()")

    def parse(self, src: SourceFile) -> pd.DataFrame:
        raise NotImplementedError("DK parse()")

    def normalise(self, df: pd.DataFrame, src: SourceFile) -> pd.DataFrame:
        raise NotImplementedError("DK normalise()")
