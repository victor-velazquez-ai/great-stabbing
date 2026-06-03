"""Ping every known source URL across the live adapters; print a status line.

Wired into ``.github/workflows/source-health-check.yml`` (Mondays). Exits non-zero
if any of the URLs we depend on returns a non-2xx status, so the workflow can open
a GH issue on first failure.
"""

from __future__ import annotations

import sys
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
UA = "great-stabbing/0.0.1 (+https://github.com/victor-velazquez-ai/great-stabbing)"


def head(url: str) -> tuple[int, int | None]:
    """Return (status_code, content_length-or-None). HEAD first; GET if HEAD blocked."""
    try:
        r = requests.head(url, timeout=30, allow_redirects=True, headers={"User-Agent": UA})
        if r.status_code in (405, 501):
            r = requests.get(url, timeout=30, stream=True, headers={"User-Agent": UA})
            r.close()
        size = int(r.headers.get("content-length", 0)) or None
        return (r.status_code, size)
    except requests.RequestException as e:
        print(f"  ERROR: {e}", file=sys.stderr)
        return (0, None)


URLS = [
    # UK ONS — page that lists the PFA files; specific URL changes per quarter.
    ("UK ONS landing",
     "https://www.ons.gov.uk/peoplepopulationandcommunity/crimeandjustice/datasets/policeforceareadatatables"),

    # FR Interstats — stable resource ID redirect
    ("FR Interstats DEP CSV",
     "https://www.data.gouv.fr/api/1/datasets/r/2b27a675-e3bf-41ef-a852-5fb9ab483967"),

    # IT ISTAT — main + sibling
    ("IT ISTAT AUTVITTPS_6",
     "https://esploradati.istat.it/SDMXWS/rest/dataflow/IT1/73_230_DF_DCCV_AUTVITTPS_6"),
    ("IT ISTAT AUTVITTPS_5",
     "https://esploradati.istat.it/SDMXWS/rest/dataflow/IT1/73_230_DF_DCCV_AUTVITTPS_5"),

    # DE BKA — catalog page (the only stable URL; XLSX URLs have v=N busters)
    ("DE BKA Zeitreihen catalog",
     "https://www.bka.de/DE/AktuelleInformationen/StatistikenLagebilder/PolizeilicheKriminalstatistik/PKS2024/PKSTabellen/Zeitreihen/zeitreihen_node.html"),

    # SE BRÅ — direct XLSX
    ("SE BRÅ Anmälda brott XLSX",
     "https://bra.se/download/18.11dab50419d723e44d315606/1776153587771/10La_anm_10_ar.xlsx"),

    # Eurostat NUTS GeoJSON (used by build_map_geojson.py + refresh_nuts_lookup.py)
    ("Eurostat NUTS 03M GeoJSON",
     "https://gisco-services.ec.europa.eu/distribution/v2/nuts/geojson/NUTS_RG_03M_2021_4326.geojson"),
]


def main() -> int:
    failures: list[str] = []
    print(f"{'Source':<40} {'Status':>6} {'Bytes':>12}")
    print("-" * 60)
    for name, url in URLS:
        code, size = head(url)
        size_str = f"{size:>12,}" if size else "          —"
        marker = "✓" if 200 <= code < 300 else "✗"
        print(f"{name:<40} {code:>5}{marker} {size_str}")
        if not (200 <= code < 300):
            failures.append(f"{name} → HTTP {code}  ({url})")

    if failures:
        print("\nFAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nAll sources healthy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
