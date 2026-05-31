"""Canonical schema for crime_aggregates.parquet (Tier 1).

Changes here are ADDITIVE only. Renaming or removing columns is a breaking
change that requires a migration script + version bump.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

import pandera as pa
from pandera.typing import Series
from pydantic import BaseModel, Field

CrimeCategory = Literal[
    "homicide",
    "attempted_homicide",
    "knife_offence",
    "firearm_offence",
    "sexual_assault",
    "robbery_violent",
    "assault_serious",
    "violent_total",
]

SuspectDim = Literal[
    "total",
    "national",
    "foreign",
    "by_origin_country",
    "unknown",
]

PeriodType = Literal["month", "quarter", "year"]

CRIME_CATEGORIES: tuple[str, ...] = (
    "homicide",
    "attempted_homicide",
    "knife_offence",
    "firearm_offence",
    "sexual_assault",
    "robbery_violent",
    "assault_serious",
    "violent_total",
)

SUSPECT_DIMS: tuple[str, ...] = (
    "total",
    "national",
    "foreign",
    "by_origin_country",
    "unknown",
)


class AggregateRow(BaseModel):
    """One row of crime_aggregates.parquet. Used in adapters before frame conversion."""

    source_country: str = Field(min_length=2, max_length=2)
    source_authority: str
    source_url: str
    source_file_hash: str
    retrieved_at: datetime
    period_start: date
    period_end: date
    period_type: PeriodType
    region_code: str
    region_level: int = Field(ge=0, le=3)
    crime_category: CrimeCategory
    crime_category_native: str
    suspect_dim: SuspectDim = "total"
    suspect_dim_value: str | None = None
    count: int = Field(ge=0)
    denominator_population: int | None = None
    denominator_source: str | None = None
    rate_per_100k: float | None = None
    notes: str | None = None


def aggregates_schema() -> pa.DataFrameSchema:
    """Pandera schema used to validate any DataFrame before write_parquet.

    `coerce=True` lets pandera auto-cast nullable string columns from `object`
    (pandas default when all values are NULL) to `string[pyarrow]`, which the
    pyarrow Parquet writer expects. Without this, an adapter that emits a
    column with all-NULL values (e.g. suspect_dim_value for sources that don't
    publish a foreign-background dimension) trips a dtype check.
    """
    return pa.DataFrameSchema(
        {
            "source_country": pa.Column(str, pa.Check.str_length(2, 2)),
            "source_authority": pa.Column(str),
            "source_url": pa.Column(str),
            "source_file_hash": pa.Column(str),
            "retrieved_at": pa.Column("datetime64[ns]"),
            "period_start": pa.Column("datetime64[ns]"),
            "period_end": pa.Column("datetime64[ns]"),
            "period_type": pa.Column(str, pa.Check.isin(["month", "quarter", "year"])),
            "region_code": pa.Column(str),
            "region_level": pa.Column(int, pa.Check.in_range(0, 3)),
            "crime_category": pa.Column(str, pa.Check.isin(list(CRIME_CATEGORIES))),
            "crime_category_native": pa.Column(str),
            "suspect_dim": pa.Column(str, pa.Check.isin(list(SUSPECT_DIMS))),
            "suspect_dim_value": pa.Column(str, nullable=True),
            "count": pa.Column(int, pa.Check.ge(0)),
            "denominator_population": pa.Column("Int64", nullable=True),
            "denominator_source": pa.Column(str, nullable=True),
            "rate_per_100k": pa.Column(float, nullable=True),
            "notes": pa.Column(str, nullable=True),
        },
        strict=True,
        coerce=True,
        unique=[
            "source_country",
            "period_start",
            "region_code",
            "crime_category",
            "suspect_dim",
            "suspect_dim_value",
        ],
    )
