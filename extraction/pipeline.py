"""Tier 2 pipeline orchestrator.

Two entry points:

  python -m extraction.pipeline fetch YYYY-MM
      Runs on the 1st of each month (GitHub Actions). Pulls GDELT + RSS for
      the live MVP countries, filters via per-language keyword lists, writes
      extraction/_inbox/candidate_articles_YYYY-MM.jsonl, and exits.

  python -m extraction.pipeline finalize YYYY-MM
      Run locally by the user AFTER manual Claude extraction has produced
      extraction/_outbox/extracted_incidents_YYYY-MM.jsonl. Dedupes,
      geocodes (with cache), scores confidence, computes a stable
      incident_id, upserts to data/parquet/incidents.parquet.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
INBOX = REPO_ROOT / "extraction" / "_inbox"
OUTBOX = REPO_ROOT / "extraction" / "_outbox"
PARQUET_DIR = REPO_ROOT / "data" / "parquet"
INCIDENTS_PARQUET = PARQUET_DIR / "incidents.parquet"

# Countries we attempt monthly extraction for. Aligned to live Tier 1.
LIVE_COUNTRIES = ("UK", "FR", "DE")

# Stable namespace for incident UUID v5 hashes.
INCIDENT_NS = uuid.UUID("8e7eb8a6-3f60-4f51-9efb-f4a4dd5b3b6f")

log = logging.getLogger(__name__)


# ----------------------------- FETCH ------------------------------------


def _month_window(month: str) -> tuple[date, date]:
    """Given 'YYYY-MM', return (since, until) covering last ~40 days through end of that month."""
    y, m = (int(x) for x in month.split("-"))
    end = date(y + (m // 12), (m % 12) + 1, 1)  # first of next month
    if m == 12:
        end = date(y + 1, 1, 1)
    # Start ~40 days before end of month so we capture the trailing weeks
    # of the previous month plus the target month itself.
    from datetime import timedelta

    since = end - timedelta(days=40)
    return (since, end)


def _dedupe_by_url(records: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for r in records:
        url = (r.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(r)
    return out


def fetch(month: str) -> None:
    """Fetch + filter for the target month. Writes _inbox JSONL."""
    from extraction.fetch.gdelt import fetch_gdelt
    from extraction.fetch.rss import fetch_rss
    from extraction.filter import matches_keywords

    since, until = _month_window(month)
    log.info("[pipeline.fetch] %s → window %s to %s", month, since, until)

    INBOX.mkdir(parents=True, exist_ok=True)

    all_articles: list[dict] = []
    for country in LIVE_COUNTRIES:
        log.info("[pipeline.fetch] === %s ===", country)
        gdelt_rows = fetch_gdelt(country, since, until)
        rss_rows = fetch_rss(country)
        merged = _dedupe_by_url(gdelt_rows + rss_rows)
        log.info(
            "[pipeline.fetch] %s: %d gdelt + %d rss = %d unique URLs",
            country, len(gdelt_rows), len(rss_rows), len(merged),
        )
        all_articles.extend(merged)

    # Filter via keywords per language.
    kept = 0
    out_path = INBOX / f"candidate_articles_{month}.jsonl"
    with out_path.open("w", encoding="utf-8") as f:
        for art in all_articles:
            text = " ".join(filter(None, [art.get("title", ""), art.get("lead", "")]))
            lang = (art.get("language") or "en").split("-")[0]
            if matches_keywords(text, lang):
                f.write(json.dumps(art, ensure_ascii=False) + "\n")
                kept += 1

    log.info(
        "[pipeline.fetch] kept %d/%d articles → %s",
        kept, len(all_articles), out_path.relative_to(REPO_ROOT),
    )


# ----------------------------- FINALIZE ---------------------------------


def _incident_id(rec: dict[str, Any]) -> str:
    """Stable UUID v5 from (date, country, city, weapon, victim_fatal)."""
    key = "|".join(
        str(rec.get(k, ""))
        for k in ("date_incident", "country", "city", "weapon", "victim_fatal")
    )
    return str(uuid.uuid5(INCIDENT_NS, key))


def finalize(month: str, use_network_geocode: bool = True) -> None:
    """Read manual extraction output, dedupe, geocode, score, upsert."""
    from extraction.confidence import score
    from extraction.dedupe import dedupe_hard
    from extraction.geocode import geocode_city
    import duckdb
    import pandas as pd

    src = OUTBOX / f"extracted_incidents_{month}.jsonl"
    if not src.exists():
        log.error("[pipeline.finalize] no %s — manual Claude extraction first", src)
        return

    records: list[dict[str, Any]] = []
    with src.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            if not entry.get("extracted"):
                continue
            inc = entry.get("incident")
            if not inc:
                continue
            records.append(inc)

    log.info("[pipeline.finalize] loaded %d incidents from %s", len(records), src.name)

    deduped = dedupe_hard(records)

    finalized: list[dict[str, Any]] = []
    now_iso = datetime.now(timezone.utc).isoformat()
    for r in deduped:
        country = (r.get("country") or "").upper()
        city = r.get("city") or ""
        # region_hint may be set by the extractor in a free-text region field
        # we don't currently model. For now, look for ``region`` or ``state``
        # on the incident dict if present.
        region_hint = r.get("region") or r.get("state") or None
        lat, lon, nuts = (
            geocode_city(city, country, region_hint=region_hint, use_network=use_network_geocode)
            if city else (None, None, None)
        )
        r.setdefault("lat", lat)
        r.setdefault("lon", lon)
        r.setdefault("region_code", nuts)
        if r.get("lat") is None and lat is not None:
            r["lat"], r["lon"], r["region_code"] = lat, lon, nuts
        r["location_precision"] = (
            "exact" if (lat is not None and lon is not None and r.get("location_precision") == "exact")
            else ("city" if city else "region")
        )
        r["confidence"] = score(r)
        r["incident_id"] = _incident_id(r)
        r["extracted_at"] = r.get("extracted_at") or now_iso
        r["extractor_version"] = r.get("extractor_version") or "manual-claude@prompt-v1"
        r["review_status"] = r.get("review_status") or "unreviewed"
        r["last_reviewed_at"] = r.get("last_reviewed_at")
        # sources_json as JSON string for Parquet
        sources = r.get("sources") or []
        r["sources_json"] = json.dumps(sources, ensure_ascii=False)
        finalized.append(r)

    if not finalized:
        log.warning("[pipeline.finalize] nothing to write")
        return

    # Build the canonical incidents DataFrame.
    cols = [
        "incident_id", "date_incident", "date_reported", "country",
        "region_code", "city", "lat", "lon", "location_precision",
        "weapon", "victim_count", "victim_fatal",
        "victim_sex_summary", "victim_age_summary",
        "suspect_count", "suspect_description_verbatim", "suspect_origin_as_reported",
        "sources_json", "confidence",
        "extracted_at", "extractor_version", "last_reviewed_at", "review_status",
    ]
    df = pd.DataFrame([{c: r.get(c) for c in cols} for r in finalized])

    PARQUET_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.register("new_rows", df)
    if INCIDENTS_PARQUET.exists():
        con.execute(
            f"CREATE TABLE existing AS SELECT * FROM read_parquet('{INCIDENTS_PARQUET.as_posix()}')"
        )
        con.execute(
            """
            CREATE TABLE merged AS
            SELECT * FROM existing WHERE incident_id NOT IN (SELECT incident_id FROM new_rows)
            UNION ALL
            SELECT * FROM new_rows
            """
        )
        con.execute(
            f"COPY merged TO '{INCIDENTS_PARQUET.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)"
        )
    else:
        con.execute(
            f"COPY new_rows TO '{INCIDENTS_PARQUET.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)"
        )

    try:
        pretty = INCIDENTS_PARQUET.relative_to(REPO_ROOT)
    except ValueError:
        pretty = INCIDENTS_PARQUET  # monkey-patched in tests; print absolute
    log.info("[pipeline.finalize] wrote %d incidents to %s", len(df), pretty)


# ----------------------------- CLI --------------------------------------


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if len(argv) < 3:
        print(__doc__)
        return 2
    cmd, month = argv[1], argv[2]
    if cmd == "fetch":
        fetch(month)
    elif cmd == "finalize":
        finalize(month)
    else:
        print(f"unknown command: {cmd}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
