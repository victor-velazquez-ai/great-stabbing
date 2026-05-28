"""Italy adapter — ISTAT (annual) + Ministero dell'Interno (monthly PDF).

Sources:
  - ISTAT API for annual delitti-denunciati series.
  - https://www.interno.gov.it/.../dati-statistici/  (monthly PDF reports).
Foreign-background published? Partial.
Incident-level? No.

Stub.
"""

from __future__ import annotations

import pandas as pd

from adapters.common.base import Adapter, SourceFile


class ITAdapter(Adapter):
    country = "IT"
    authority = "ISTAT + Ministero dell'Interno"
    cadence = "annual"  # also pulls monthly MI PDF when discover() finds new

    def discover(self) -> list[SourceFile]:
        raise NotImplementedError("IT discover()")

    def parse(self, src: SourceFile) -> pd.DataFrame:
        raise NotImplementedError("IT parse()")

    def normalise(self, df: pd.DataFrame, src: SourceFile) -> pd.DataFrame:
        raise NotImplementedError("IT normalise()")
