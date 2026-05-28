"""Cached HTTP fetcher.

Every download is hashed (sha256), archived under data/raw/<country>/<yyyy-mm>/,
and a SourceFile descriptor is returned. Re-running an adapter against a source
that hasn't changed is a no-op (same hash → skip).
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from adapters.common.base import SourceFile

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 60
DEFAULT_UA = "great-stabbing/0.0.1 (+https://github.com/victor-velazquez-ai/great-stabbing)"

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "data" / "raw"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=30))
def _get(url: str, timeout: int = DEFAULT_TIMEOUT) -> bytes:
    r = requests.get(url, timeout=timeout, headers={"User-Agent": DEFAULT_UA})
    r.raise_for_status()
    return r.content


def fetch_to_raw(url: str, country: str, filename: str | None = None) -> SourceFile:
    """Download `url`, archive under data/raw/<country>/<yyyy-mm>/, return SourceFile."""
    now = datetime.now(timezone.utc)
    content = _get(url)
    sha = hashlib.sha256(content).hexdigest()

    if filename is None:
        filename = url.rstrip("/").split("/")[-1] or f"{sha[:12]}.bin"

    month = now.strftime("%Y-%m")
    out_dir = RAW_DIR / country.lower() / month
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / filename

    if out_path.exists():
        existing = hashlib.sha256(out_path.read_bytes()).hexdigest()
        if existing == sha:
            log.info("unchanged: %s (sha %s)", out_path.relative_to(REPO_ROOT), sha[:12])
            return SourceFile(
                url=url,
                local_path=str(out_path.relative_to(REPO_ROOT)),
                fetched_at=now,
                sha256=sha,
            )

    out_path.write_bytes(content)
    log.info("fetched: %s (sha %s, %d bytes)", out_path.relative_to(REPO_ROOT), sha[:12], len(content))
    return SourceFile(
        url=url,
        local_path=str(out_path.relative_to(REPO_ROOT)),
        fetched_at=now,
        sha256=sha,
    )
