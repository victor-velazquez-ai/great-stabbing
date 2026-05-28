"""Run every adapter in sequence. Used for local full refresh."""

from __future__ import annotations

import sys

from scripts.run_adapter import ADAPTERS, run

if __name__ == "__main__":
    rc = 0
    for c in ADAPTERS:
        rc = run(c) or rc
    sys.exit(rc)
