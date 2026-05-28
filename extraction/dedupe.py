"""Two-pass dedupe of extracted incidents.

Hard pass: hash (date, country, city, weapon, victim_fatal).
Soft pass: TODO — embedding similarity on (city + weapon + summary). For MVP
the hard pass is enough; soft pass added when news layer is real.
"""

from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
from datetime import date
from typing import Any

log = logging.getLogger(__name__)


def hard_key(rec: dict[str, Any]) -> str:
    parts = [
        str(rec.get("date_incident") or rec.get("date_reported") or ""),
        rec.get("country", ""),
        (rec.get("city") or "").strip().lower(),
        rec.get("weapon", ""),
        str(rec.get("victim_fatal", 0)),
    ]
    return hashlib.md5("|".join(parts).encode("utf-8")).hexdigest()


def dedupe_hard(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse exact-match records, merging their sources arrays."""
    by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in records:
        by_key[hard_key(r)].append(r)

    out: list[dict[str, Any]] = []
    for key, group in by_key.items():
        if len(group) == 1:
            out.append(group[0])
            continue
        merged = dict(group[0])
        all_sources = []
        seen_urls = set()
        earliest_reported: date | None = None
        for r in group:
            for s in r.get("sources", []):
                if s.get("url") and s["url"] not in seen_urls:
                    all_sources.append(s)
                    seen_urls.add(s["url"])
            dr = r.get("date_reported")
            if dr and (earliest_reported is None or dr < earliest_reported):
                earliest_reported = dr
            merged["victim_count"] = max(
                merged.get("victim_count", 0), r.get("victim_count", 0)
            )
            merged["victim_fatal"] = max(
                merged.get("victim_fatal", 0), r.get("victim_fatal", 0)
            )
            if not merged.get("suspect_description_verbatim") and r.get(
                "suspect_description_verbatim"
            ):
                merged["suspect_description_verbatim"] = r["suspect_description_verbatim"]
            if not merged.get("suspect_origin_as_reported") and r.get(
                "suspect_origin_as_reported"
            ):
                merged["suspect_origin_as_reported"] = r["suspect_origin_as_reported"]
        merged["sources"] = all_sources
        if earliest_reported:
            merged["date_reported"] = earliest_reported
        out.append(merged)

    log.info("dedupe: %d → %d records", len(records), len(out))
    return out
