"""UK adapter — data.police.uk monthly archive.

Source: https://data.police.uk/data/archive/  (monthly ZIPs, one CSV per force).
Foreign-background published? No.
Incident-level? Yes (point data, ~10m grid).

This stub establishes the pattern; full implementation lands in Week 2.
"""

from __future__ import annotations

import pandas as pd

from adapters.common.base import Adapter, SourceFile


class UKAdapter(Adapter):
    country = "UK"
    authority = "data.police.uk"
    cadence = "monthly"

    def discover(self) -> list[SourceFile]:
        raise NotImplementedError("UK discover() — implement in Week 2")

    def parse(self, src: SourceFile) -> pd.DataFrame:
        raise NotImplementedError("UK parse() — implement in Week 2")

    def normalise(self, df: pd.DataFrame, src: SourceFile) -> pd.DataFrame:
        raise NotImplementedError("UK normalise() — implement in Week 2")
