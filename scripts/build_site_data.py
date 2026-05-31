"""Pre-render site data: convert canonical Parquet to JSON for the static site.

Runs before `astro build`. Outputs into ``site/src/data/`` so Astro can import
them at build time without DuckDB-WASM (which we'll add for interactive
querying once dashboards arrive).

Output files:
- ``country_summaries.json``: per-country dictionary of NUTS region rows with
  homicide + violent totals + rates. Keyed by ISO-2 country code.
- ``aggregates_meta.json``: list of (country, period_end, n_rows, n_regions,
  authority) tuples for the freshness banner.
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
        (OUT_DIR / "country_summaries.json").write_text("{}", encoding="utf-8")
        (OUT_DIR / "aggregates_meta.json").write_text("[]", encoding="utf-8")
        # Legacy alias for the previous schema, kept so an older homepage build
        # doesn't crash mid-migration.
        (OUT_DIR / "uk_summary.json").write_text("[]", encoding="utf-8")
        return

    con = duckdb.connect()

    countries = [
        c for (c,) in con.execute(
            f"SELECT DISTINCT source_country FROM read_parquet('{PARQUET.as_posix()}') "
            "ORDER BY source_country"
        ).fetchall()
    ]
    log.info("countries with data: %s", countries)

    summaries: dict[str, list[dict]] = {}
    for country in countries:
        rows = con.execute(
            f"""
            WITH base AS (
                SELECT *
                FROM read_parquet('{PARQUET.as_posix()}')
                WHERE source_country = ?
                  AND suspect_dim = 'total'
            ),
            latest AS (
                SELECT max(period_end) AS pe FROM base
            ),
            wide AS (
                SELECT
                    b.region_code,
                    b.region_level,
                    max(CASE WHEN crime_category = 'homicide' THEN count END) AS homicide_count,
                    max(CASE WHEN crime_category = 'homicide' THEN rate_per_100k END) AS homicide_rate,
                    max(CASE WHEN crime_category = 'violent_total' THEN count END) AS violent_total_count,
                    max(CASE WHEN crime_category = 'violent_total' THEN rate_per_100k END) AS violent_total_rate,
                    max(CASE WHEN crime_category = 'assault_serious' THEN count END) AS assault_count,
                    max(CASE WHEN crime_category = 'assault_serious' THEN rate_per_100k END) AS assault_rate,
                    max(denominator_population) AS population,
                    max(period_start) AS period_start,
                    max(period_end) AS period_end,
                    max(source_url) AS source_url
                FROM base b, latest
                WHERE b.period_end = latest.pe
                GROUP BY b.region_code, b.region_level
            )
            SELECT w.*, n.name_en AS region_name
            FROM wide w
            LEFT JOIN read_parquet('{NUTS_PARQUET.as_posix()}') n
              ON w.region_code = n.code
            ORDER BY homicide_rate DESC NULLS LAST
            """,
            [country],
        ).fetchall()
        cols = [
            "region_code", "region_level",
            "homicide_count", "homicide_rate",
            "violent_total_count", "violent_total_rate",
            "assault_count", "assault_rate",
            "population", "period_start", "period_end", "source_url", "region_name",
        ]
        country_rows = [dict(zip(cols, row, strict=True)) for row in rows]
        for r in country_rows:
            for k in ("period_start", "period_end"):
                v = r.get(k)
                if v is not None:
                    r[k] = v.isoformat() if hasattr(v, "isoformat") else str(v)
        summaries[country] = country_rows
        log.info("  %s: %d region rows", country, len(country_rows))

    (OUT_DIR / "country_summaries.json").write_text(
        json.dumps(summaries, indent=2, default=str), encoding="utf-8"
    )

    # Per-country freshness metadata.
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

    # Backwards-compat alias: keep uk_summary.json populated so older builds
    # don't break if the homepage hasn't fully migrated yet.
    (OUT_DIR / "uk_summary.json").write_text(
        json.dumps(summaries.get("UK", []), indent=2, default=str), encoding="utf-8"
    )

    log.info("wrote summaries (%d countries) and meta (%d rows)", len(summaries), len(meta))


if __name__ == "__main__":
    main()
