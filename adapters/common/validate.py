"""Cross-cutting validators applied AFTER normalise() and BEFORE write()."""

from __future__ import annotations

import logging

import pandas as pd

from adapters.common.nuts import is_valid_nuts
from adapters.common.schema import CRIME_CATEGORIES, SUSPECT_DIMS

log = logging.getLogger(__name__)


class ValidationError(Exception):
    pass


def validate_aggregates(df: pd.DataFrame) -> None:
    """Raise ValidationError on any structural problem.

    The pandera schema in schema.py covers types and enum membership.
    This adds business-logic checks that pandera doesn't naturally express.
    """
    errors: list[str] = []

    bad_cats = set(df["crime_category"]) - set(CRIME_CATEGORIES)
    if bad_cats:
        errors.append(f"unknown crime categories: {bad_cats}")

    bad_dims = set(df["suspect_dim"]) - set(SUSPECT_DIMS)
    if bad_dims:
        errors.append(f"unknown suspect dims: {bad_dims}")

    unknown_regions = [r for r in df["region_code"].unique() if not is_valid_nuts(r)]
    if unknown_regions:
        errors.append(
            f"region_code values not in nuts_regions.parquet (first 10): {unknown_regions[:10]}"
        )

    bad_periods = df[df["period_end"] < df["period_start"]]
    if not bad_periods.empty:
        errors.append(f"{len(bad_periods)} rows with period_end < period_start")

    key_cols = [
        "source_country",
        "period_start",
        "region_code",
        "crime_category",
        "suspect_dim",
        "suspect_dim_value",
    ]
    dupes = df[df.duplicated(subset=key_cols, keep=False)]
    if not dupes.empty:
        errors.append(f"{len(dupes)} duplicate rows on natural key")

    if errors:
        raise ValidationError("\n".join(errors))

    log.info("validate_aggregates: OK (%d rows, %d regions)", len(df), df["region_code"].nunique())
