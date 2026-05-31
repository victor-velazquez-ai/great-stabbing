"""Per-country RSS feed fetcher.

Feeds are configured at ``extraction/fetch/feeds_<iso>.yaml`` as a list of
``{name, url, lang}`` records. We hand-curate ~5–15 regional outlets per
country — typically mid-market press where local stabbings actually get
reported (national press tends to skip them).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import yaml

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
FEED_DIR = REPO_ROOT / "extraction" / "fetch"


def feeds_for(country_iso: str) -> list[dict]:
    """Load extraction/fetch/feeds_<iso>.yaml → list of feed dicts."""
    path = FEED_DIR / f"feeds_{country_iso.lower()}.yaml"
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("feeds", []) or []


def fetch_rss(country_iso: str) -> list[dict]:
    """Pull all RSS feeds for a country and return article records.

    Each record: ``{url, outlet, published_at, language, title, lead, source}``.
    """
    out: list[dict] = []
    feeds = feeds_for(country_iso)
    log.info("[rss] %s: %d feeds", country_iso, len(feeds))

    for feed in feeds:
        url = feed.get("url")
        if not url:
            continue
        name = feed.get("name", url)
        lang = (feed.get("lang") or "").lower() or None

        try:
            d = feedparser.parse(url)
        except Exception as e:  # noqa: BLE001
            log.warning("[rss] %s → %s: %s", name, type(e).__name__, e)
            continue

        # feedparser sets bozo=1 when the feed has parse warnings; we still
        # use the entries it managed to extract.
        n_entries = len(d.entries)
        log.info("[rss] %s (%s): %d entries", name, lang or "?", n_entries)

        for e in d.entries:
            link = getattr(e, "link", None) or ""
            if not link:
                continue
            title = getattr(e, "title", "") or ""
            lead = (
                getattr(e, "summary", None)
                or getattr(e, "description", None)
                or ""
            )
            # Strip HTML tags from summary in a lightweight way.
            import re

            lead = re.sub(r"<[^>]+>", " ", lead).strip()

            published = (
                getattr(e, "published_parsed", None)
                or getattr(e, "updated_parsed", None)
            )
            if published:
                published_at = datetime(*published[:6], tzinfo=timezone.utc).isoformat()
            else:
                published_at = None

            out.append(
                {
                    "url": link,
                    "outlet": name,
                    "published_at": published_at,
                    "language": lang,
                    "title": title,
                    "lead": lead[:1500],  # cap to keep extraction batches reasonable
                    "source": "rss",
                    "country": country_iso.upper(),
                }
            )

    return out
