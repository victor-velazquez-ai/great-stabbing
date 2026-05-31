"""Pre-render site data: convert canonical Parquet to JSON for the static site.

Runs before `astro build`. Outputs into ``site/src/data/`` so Astro can import
them at build time without DuckDB-WASM (which we'll add for interactive
querying once dashboards arrive).

Output files:
- ``site/src/data/uk_summary.json``: UK NUTS-1 latest-period homicide + violent
  totals with rate_per_100k. Used for the homepage table.
- ``site/src/data/aggregates_meta.json``: list of (country, period_end, n_rows)
  tuples — used to render the "last updated" tag per country.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parents[1]
PARQUET = REPO_ROOT / "data" / "parquet" / "crime_aggregates.parquet"
NUTS_PARQUET = REPO_ROOT / "data" / "parquet" / "nuts_regions.parquet"
OUT_DIR = REPO_ROOT / "site" / "src" / "data"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if not PARQUET.exists():
        log.warning("no %s — writing empty stubs", PARQUET.relative_to(REPO_ROOT))
        (OUT_DIR / "uk_summary.json").write_text("[]", encoding="utf-8")
        (OUT_DIR / "aggregates_meta.json").write_text("[]", encoding="utf-8")
        return

    con = duckdb.connect()

    # UK summary: NUTS-1 rows, latest period, homicide + violent_total.
    uk_rows = con.execute(
        f"""
        WITH base AS (
            SELECT *
            FROM read_parquet('{PARQUET.as_posix()}')
            WHERE source_country = 'UK'
              AND suspect_dim = 'total'
        ),
        latest AS (
            SELECT max(period_end) AS pe FROM base
        ),
        wide AS (
            SELECT
                b.region_code,
                max(CASE WHEN crime_category = 'homicide' THEN count END) AS homicide_count,
                max(CASE WHEN crime_category = 'homicide' THEN rate_per_100k END) AS homicide_rate,
                max(CASE WHEN crime_category = 'violent_total' THEN count END) AS violent_total_count,
                max(CASE WHEN crime_category = 'violent_total' THEN rate_per_100k END) AS violent_total_rate,
                max(denominator_population) AS population,
                max(period_start) AS period_start,
                max(period_end) AS period_end,
                max(source_url) AS source_url
            FROM base b, latest
            WHERE b.period_end = latest.pe
            GROUP BY b.region_code
        )
        SELECT p.*, n.name_en AS region_name
        FROM wide p
        LEFT JOIN read_parquet('{NUTS_PARQUET.as_posix()}') n
          ON p.region_code = n.code
        ORDER BY homicide_rate DESC NULLS LAST
        """
    ).fetchall()

    cols = [
        "region_code", "homicide_count", "homicide_rate",
        "violent_total_count", "violent_total_rate",
        "population", "period_start", "period_end", "source_url", "region_name",
    ]
    uk_summary = [dict(zip(cols, row, strict=True)) for row in uk_rows]
    # Convert dates to ISO strings.
    for r in uk_summary:
        for k in ("period_start", "period_end"):
            if r[k] is not None:
                r[k] = r[k].isoformat() if hasattr(r[k], "isoformat") else str(r[k])

    (OUT_DIR / "uk_summary.json").write_text(
        json.dumps(uk_summary, indent=2, default=str), encoding="utf-8"
    )
    log.info("wrote uk_summary.json (%d rows)", len(uk_summary))

    # Meta: per-country freshness.
    meta_rows = con.execute(
        f"""
        SELECT
            source_country AS country,
            max(period_end) AS latest_period_end,
            max(retrieved_at) AS retrieved_at,
            count(*) AS n_rows,
            count(DISTINCT region_code) AS n_regions,
            max(source_authority) AS authority
        FROM read_parquet('{PARQUET.as_posix()}')
        GROUP BY source_country
        ORDER BY source_country
        """
    ).fetchall()
    meta = [
        {
            "country": r[0],
            "latest_period_end": r[1].isoformat() if r[1] is not None else None,
            "retrieved_at": r[2].isoformat() if r[2] is not None else None,
            "n_rows": int(r[3]),
            "n_regions": int(r[4]),
            "authority": r[5],
        }
        for r in meta_rows
    ]
    (OUT_DIR / "aggregates_meta.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )
    log.info("wrote aggregates_meta.json (%d countries)", len(meta))


if __name__ == "__main__":
    main()
