"""France adapter — SSMSI Interstats monthly.

Source: https://www.data.gouv.fr/.../bases-statistiques-communale-departementale-et-regionale-de-la-delinquance
Foreign-background published? NO.
Incident-level? No.

Stub.
"""

from __future__ import annotations

import pandas as pd

from adapters.common.base import Adapter, SourceFile


class FRAdapter(Adapter):
    country = "FR"
    authority = "SSMSI"
    cadence = "monthly"

    def discover(self) -> list[SourceFile]:
        raise NotImplementedError("FR discover()")

    def parse(self, src: SourceFile) -> pd.DataFrame:
        raise NotImplementedError("FR parse()")

    def normalise(self, df: pd.DataFrame, src: SourceFile) -> pd.DataFrame:
        raise NotImplementedError("FR normalise()")
