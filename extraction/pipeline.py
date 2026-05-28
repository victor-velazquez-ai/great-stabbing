"""Tier 2 pipeline orchestrator.

Two entry points:

  python -m extraction.pipeline fetch YYYY-MM
      Run by GitHub Actions on the 1st of each month. Pulls GDELT + RSS,
      filters, writes extraction/_inbox/candidate_articles_YYYY-MM.jsonl,
      opens a GH issue prompting manual extraction.

  python -m extraction.pipeline finalize YYYY-MM
      Run by the user locally AFTER manual Claude extraction has produced
      extraction/_outbox/extracted_incidents_YYYY-MM.jsonl. Dedupes,
      geocodes, scores confidence, upserts to data/parquet/incidents.parquet.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INBOX = REPO_ROOT / "extraction" / "_inbox"
OUTBOX = REPO_ROOT / "extraction" / "_outbox"

log = logging.getLogger(__name__)


def fetch(month: str) -> None:
    """Stub — implement in Week 11."""
    log.info("fetch %s — not yet implemented", month)
    raise NotImplementedError


def finalize(month: str) -> None:
    """Stub — implement in Week 11."""
    log.info("finalize %s — not yet implemented", month)
    raise NotImplementedError


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
