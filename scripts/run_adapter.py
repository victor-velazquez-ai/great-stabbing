"""Run one country adapter by ISO-2 code.

Usage:
    uv run python scripts/run_adapter.py UK
    uv run python scripts/run_adapter.py DE FR  # multiple, sequential

Each adapter writes/upserts to data/parquet/crime_aggregates.parquet.
"""

from __future__ import annotations

import argparse
import importlib
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


ADAPTERS = {
    "UK": ("adapters.uk.adapter", "UKAdapter"),
    "DE": ("adapters.de.adapter", "DEAdapter"),
    "FR": ("adapters.fr.adapter", "FRAdapter"),
    "SE": ("adapters.se.adapter", "SEAdapter"),
    "ES": ("adapters.es.adapter", "ESAdapter"),
    "IT": ("adapters.it.adapter", "ITAdapter"),
    "DK": ("adapters.dk.adapter", "DKAdapter"),
    "IE": ("adapters.ie.adapter", "IEAdapter"),
    "NL": ("adapters.nl.adapter", "NLAdapter"),
    "AT": ("adapters.at.adapter", "ATAdapter"),
    "PT": ("adapters.pt.adapter", "PTAdapter"),
    "NO": ("adapters.no.adapter", "NOAdapter"),
    "BE": ("adapters.be.adapter", "BEAdapter"),
}


def run(country: str) -> int:
    if country.upper() not in ADAPTERS:
        log.error("unknown country %s. Known: %s", country, sorted(ADAPTERS))
        return 2
    mod_name, cls_name = ADAPTERS[country.upper()]
    mod = importlib.import_module(mod_name)
    cls = getattr(mod, cls_name)
    adapter = cls()
    result = adapter.run()
    log.info(
        "[%s] done: %d rows, %d regions, %.1fs",
        result.country,
        result.n_rows_written,
        result.n_regions,
        result.duration_s,
    )
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("countries", nargs="+", help="ISO-2 codes")
    args = p.parse_args()
    rc = 0
    for c in args.countries:
        try:
            rc = run(c) or rc
        except NotImplementedError as e:
            log.warning("[%s] stub: %s", c.upper(), e)
            rc = rc or 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
