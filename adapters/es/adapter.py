"""Spain adapter — Ministerio del Interior, *Balances trimestrales*.

Source: https://www.interior.gob.es/.../balances-de-criminalidad/  (quarterly PDFs).
Foreign-background published? Partial — nationality of detainees in some tables.
Incident-level? No.

Stub. PDF parsing via pdfplumber first; Claude fallback for stubborn pages.
"""

from __future__ import annotations

import pandas as pd

from adapters.common.base import Adapter, SourceFile


class ESAdapter(Adapter):
    country = "ES"
    authority = "Ministerio del Interior"
    cadence = "quarterly"

    def discover(self) -> list[SourceFile]:
        raise NotImplementedError("ES discover()")

    def parse(self, src: SourceFile) -> pd.DataFrame:
        raise NotImplementedError("ES parse() — pdfplumber, Claude fallback")

    def normalise(self, df: pd.DataFrame, src: SourceFile) -> pd.DataFrame:
        raise NotImplementedError("ES normalise()")
