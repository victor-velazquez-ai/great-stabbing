"""Adapter ABC and shared run orchestration."""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import duckdb
import pandas as pd

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
PARQUET_DIR = REPO_ROOT / "data" / "parquet"
AGGREGATES_PARQUET = PARQUET_DIR / "crime_aggregates.parquet"


@dataclass
class SourceFile:
    url: str
    local_path: str
    fetched_at: datetime
    sha256: str


@dataclass
class AdapterRun:
    country: str
    period_start: date
    period_end: date
    n_rows_written: int
    n_regions: int
    source_files: list[SourceFile]
    duration_s: float
    notes: str = ""
    errors: list[str] = field(default_factory=list)


class Adapter(ABC):
    """Base class for all per-country Tier 1 adapters."""

    country: str = ""  # ISO-2, e.g. "DE"
    authority: str = ""
    cadence: str = ""  # "monthly" | "quarterly" | "annual"

    @abstractmethod
    def discover(self) -> list[SourceFile]:
        """Find new official releases since last run. Archive raws to data/raw/."""

    @abstractmethod
    def parse(self, src: SourceFile) -> pd.DataFrame:
        """Parse a raw source into a source-shaped DataFrame (no normalisation yet)."""

    @abstractmethod
    def normalise(self, df: pd.DataFrame, src: SourceFile) -> pd.DataFrame:
        """Map native columns → canonical schema. Maps native regions → NUTS via region_map.csv."""

    # ---- Shared orchestration below ---------------------------------

    def write(self, df: pd.DataFrame) -> int:
        """Upsert rows into data/parquet/crime_aggregates.parquet.

        Uniqueness key: (source_country, period_start, region_code, crime_category,
        suspect_dim, suspect_dim_value). Existing rows with the same key are replaced.
        """
        from adapters.common.schema import aggregates_schema

        aggregates_schema().validate(df, lazy=True)

        PARQUET_DIR.mkdir(parents=True, exist_ok=True)
        con = duckdb.connect()
        con.register("new_rows", df)

        if AGGREGATES_PARQUET.exists():
            con.execute(f"CREATE TABLE existing AS SELECT * FROM read_parquet('{AGGREGATES_PARQUET.as_posix()}')")
            con.execute(
                """
                CREATE TABLE merged AS
                SELECT * FROM existing
                WHERE NOT EXISTS (
                    SELECT 1 FROM new_rows n
                    WHERE n.source_country = existing.source_country
                      AND n.period_start = existing.period_start
                      AND n.region_code = existing.region_code
                      AND n.crime_category = existing.crime_category
                      AND n.suspect_dim = existing.suspect_dim
                      AND COALESCE(CAST(n.suspect_dim_value AS VARCHAR), '') = COALESCE(CAST(existing.suspect_dim_value AS VARCHAR), '')
                )
                UNION ALL
                SELECT * FROM new_rows
                """
            )
            con.execute(
                f"COPY merged TO '{AGGREGATES_PARQUET.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)"
            )
        else:
            con.execute(
                f"COPY new_rows TO '{AGGREGATES_PARQUET.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)"
            )

        n = len(df)
        log.info("wrote %d rows to %s", n, AGGREGATES_PARQUET.relative_to(REPO_ROOT))
        return n

    def run(self) -> AdapterRun:
        """Orchestrate discover → parse → normalise → write for all new sources."""
        t0 = time.time()
        srcs = self.discover()
        if not srcs:
            log.info("[%s] nothing new to fetch", self.country)
            return AdapterRun(
                country=self.country,
                period_start=date.today(),
                period_end=date.today(),
                n_rows_written=0,
                n_regions=0,
                source_files=[],
                duration_s=time.time() - t0,
                notes="no new sources",
            )

        all_rows: list[pd.DataFrame] = []
        for src in srcs:
            log.info("[%s] parsing %s", self.country, src.local_path)
            raw = self.parse(src)
            norm = self.normalise(raw, src)
            all_rows.append(norm)

        df = pd.concat(all_rows, ignore_index=True)
        n_written = self.write(df)

        return AdapterRun(
            country=self.country,
            period_start=df["period_start"].min(),
            period_end=df["period_end"].max(),
            n_rows_written=n_written,
            n_regions=df["region_code"].nunique(),
            source_files=srcs,
            duration_s=time.time() - t0,
        )
