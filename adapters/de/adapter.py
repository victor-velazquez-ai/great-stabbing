"""Germany adapter — BKA Polizeiliche Kriminalstatistik (PKS).

Source: https://www.bka.de/.../PKS<year>  (annual xlsx workbooks, T01..T80 tables).
Foreign-background published? YES — *Nichtdeutsche Tatverdächtige*.
Incident-level? No.

Stub — implement in Week 3+.
"""

from __future__ import annotations

import pandas as pd

from adapters.common.base import Adapter, SourceFile


class DEAdapter(Adapter):
    country = "DE"
    authority = "BKA"
    cadence = "annual"

    def discover(self) -> list[SourceFile]:
        raise NotImplementedError("DE discover() — implement after UK is green")

    def parse(self, src: SourceFile) -> pd.DataFrame:
        raise NotImplementedError("DE parse()")

    def normalise(self, df: pd.DataFrame, src: SourceFile) -> pd.DataFrame:
        raise NotImplementedError("DE normalise()")
