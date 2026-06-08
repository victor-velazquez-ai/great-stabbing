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
INCIDENTS_PARQUET = REPO_ROOT / "data" / "parquet" / "incidents.parquet"
NUTS_PARQUET = REPO_ROOT / "data" / "parquet" / "nuts_regions.parquet"
OUT_DIR = REPO_ROOT / "site" / "src" / "data"
SITE_PUBLIC_DATA = REPO_ROOT / "site" / "public" / "data"

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

    # ---- multi-year history per region per metric ----
    # Shape: {region_code: {year: {metric: rate, "count": ...}}}
    # Drives the homepage time slider. Latest-year summaries below remain
    # for the static initial render.
    hist_rows = con.execute(
        f"""
        SELECT
            region_code,
            EXTRACT(year FROM period_end) AS yr,
            crime_category,
            count,
            rate_per_100k
        FROM read_parquet('{PARQUET.as_posix()}')
        WHERE suspect_dim = 'total'
        ORDER BY region_code, yr, crime_category
        """
    ).fetchall()
    history: dict[str, dict[int, dict[str, dict[str, float | int | None]]]] = {}
    for region, yr, cat, cnt, rate in hist_rows:
        history.setdefault(region, {}).setdefault(int(yr), {})[cat] = {
            "count": int(cnt) if cnt is not None else None,
            "rate": float(rate) if rate is not None else None,
        }

    # Compute violent_total where the source doesn't publish an umbrella
    # category directly. Sum of homicide + attempted_homicide +
    # assault_serious + sexual_assault + robbery_violent. We flag this
    # as derived so the methodology page can disclose it.
    DERIVED_PARTS = ("homicide", "attempted_homicide", "assault_serious",
                     "sexual_assault", "robbery_violent")
    for region, by_year in history.items():
        for yr, cats in by_year.items():
            if "violent_total" in cats:
                continue
            count_sum = 0; rate_sum = 0.0
            have_any_rate = False; have_any_count = False
            for p in DERIVED_PARTS:
                entry = cats.get(p)
                if not entry:
                    continue
                if entry.get("count") is not None:
                    count_sum += entry["count"]; have_any_count = True
                if entry.get("rate") is not None:
                    rate_sum += entry["rate"]; have_any_rate = True
            if have_any_count or have_any_rate:
                cats["violent_total"] = {
                    "count": count_sum if have_any_count else None,
                    "rate": rate_sum if have_any_rate else None,
                    "derived": True,
                }
    (OUT_DIR / "history.json").write_text(
        json.dumps(history, default=str, separators=(",", ":")), encoding="utf-8"
    )
    yr_min = min((y for r in history.values() for y in r.keys()), default=2024)
    yr_max = max((y for r in history.values() for y in r.keys()), default=2024)
    log.info("wrote history.json (%d regions × %d-%d)", len(history), yr_min, yr_max)

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
                    max(CASE WHEN crime_category = 'robbery_violent' THEN count END) AS robbery_count,
                    max(CASE WHEN crime_category = 'robbery_violent' THEN rate_per_100k END) AS robbery_rate,
                    max(CASE WHEN crime_category = 'sexual_assault' THEN count END) AS sexual_assault_count,
                    max(CASE WHEN crime_category = 'sexual_assault' THEN rate_per_100k END) AS sexual_assault_rate,
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
            "robbery_count", "robbery_rate",
            "sexual_assault_count", "sexual_assault_rate",
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

    # ---- foreign-background side-panel data (where published) ----
    fb_rows = con.execute(
        f"""
        WITH base AS (
            SELECT *
            FROM read_parquet('{PARQUET.as_posix()}')
            WHERE suspect_dim IN ('total', 'national', 'foreign')
        ),
        latest AS (
            SELECT source_country, max(period_end) AS pe
            FROM base GROUP BY source_country
        )
        SELECT
            b.source_country AS country,
            b.region_code,
            b.crime_category,
            max(CASE WHEN b.suspect_dim = 'total' THEN b.count END) AS total,
            max(CASE WHEN b.suspect_dim = 'national' THEN b.count END) AS national,
            max(CASE WHEN b.suspect_dim = 'foreign' THEN b.count END) AS foreign,
            max(b.period_end) AS period_end
        FROM base b
        INNER JOIN latest l ON b.source_country = l.source_country AND b.period_end = l.pe
        GROUP BY b.source_country, b.region_code, b.crime_category
        HAVING max(CASE WHEN b.suspect_dim = 'foreign' THEN b.count END) IS NOT NULL
        ORDER BY b.source_country, b.region_code, b.crime_category
        """
    ).fetchall()
    fb_data: dict[str, list[dict]] = {}
    for r in fb_rows:
        country = r[0]
        period = r[6].isoformat() if r[6] is not None else None
        fb_data.setdefault(country, []).append({
            "region_code": r[1],
            "crime_category": r[2],
            "total": int(r[3]) if r[3] is not None else None,
            "national": int(r[4]) if r[4] is not None else None,
            "foreign": int(r[5]) if r[5] is not None else None,
            "foreign_share_pct": round(100.0 * r[5] / r[3], 1) if r[3] and r[5] else None,
            "period_end": period,
        })
    (OUT_DIR / "foreign_background.json").write_text(
        json.dumps(fb_data, indent=2, default=str), encoding="utf-8"
    )
    log.info("wrote foreign_background.json (%d countries with FB data)", len(fb_data))

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

    # ---- incidents (Tier 2) ----
    SITE_PUBLIC_DATA.mkdir(parents=True, exist_ok=True)
    if INCIDENTS_PARQUET.exists():
        # Use Python-side null handling — DuckDB COALESCE can stumble on
        # columns whose Parquet logical type differs from expected.
        rows = con.execute(
            f"""
            SELECT incident_id, country, city,
                   lat, lon, location_precision,
                   weapon, victim_count, victim_fatal,
                   suspect_description_verbatim,
                   suspect_origin_as_reported,
                   confidence, sources_json,
                   date_incident, date_reported
            FROM read_parquet('{INCIDENTS_PARQUET.as_posix()}')
            WHERE lat IS NOT NULL AND lon IS NOT NULL
            """
        ).fetchall()
        cols = [
            "incident_id", "country", "city",
            "lat", "lon", "location_precision",
            "weapon", "victim_count", "victim_fatal",
            "suspect_description_verbatim", "suspect_origin_as_reported",
            "confidence", "sources_json",
            "date_incident", "date_reported",
        ]
        features = []
        for row in rows:
            d = dict(zip(cols, row, strict=True))
            for k in ("date_incident", "date_reported"):
                v = d.get(k)
                if v is not None:
                    d[k] = v.isoformat() if hasattr(v, "isoformat") else str(v)
            # sources_json comes back as a string; parse for the popup.
            try:
                d["sources"] = json.loads(d.pop("sources_json") or "[]")
            except Exception:
                d["sources"] = []
            features.append(
                {
                    "type": "Feature",
                    "properties": d,
                    "geometry": {"type": "Point", "coordinates": [d["lon"], d["lat"]]},
                }
            )
        out_geo = {"type": "FeatureCollection", "features": features}
        (SITE_PUBLIC_DATA / "incidents.geojson").write_text(
            json.dumps(out_geo, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )
        log.info("wrote incidents.geojson (%d features)", len(features))
    else:
        # Empty placeholder so the homepage fetch doesn't 404.
        (SITE_PUBLIC_DATA / "incidents.geojson").write_text(
            '{"type":"FeatureCollection","features":[]}', encoding="utf-8"
        )


if __name__ == "__main__":
    main()
