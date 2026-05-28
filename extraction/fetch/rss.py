"""Per-country RSS feed fetcher.

Feeds are configured in extraction/fetch/feeds_<iso>.yaml. We hand-curate
the list — typically 5–15 mid-market regional outlets per country (where
local stabbings actually get reported).
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def feeds_for(country_iso: str) -> list[dict]:
    """Load extraction/fetch/feeds_<iso>.yaml → list of feed dicts."""
    path = REPO_ROOT / "extraction" / "fetch" / f"feeds_{country_iso.lower()}.yaml"
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("feeds", [])


def fetch_rss(country_iso: str) -> list[dict]:
    """Pull all feeds for country, return raw article records."""
    raise NotImplementedError("RSS fetcher — implement in Week 11")
