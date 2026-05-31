"""DE adapter tests — synthetic BKA-shaped XLSX fixture.

BKA PKS Standardtabellen are XLSX workbooks with one table per sheet. The
parser scans for ``T62`` (Bundesländer breakdown) and ``T81``/``T82``
(Nichtdeutsche Tatverdächtige) sheets, identifies the header row by the
first six-digit Schlüssel, and melts wide → long.
"""

from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path

import openpyxl
import pytest

from adapters.common.base import REPO_ROOT, SourceFile
from adapters.de.adapter import DEAdapter


def _build_fake_pks_xlsx() -> bytes:
    """Build a fake BKA PKS workbook with one T62 + one T81 sheet."""
    wb = openpyxl.Workbook()
    default = wb.active
    if default is not None:
        wb.remove(default)

    # === T62: cases (Fälle) by Bundesland ===
    t62 = wb.create_sheet("T62")
    # Boilerplate
    for r in range(1, 5):
        t62.cell(row=r, column=1, value="boilerplate")
    # Header row (row 5)
    headers = [
        "Schlüssel",
        "Straftat",
        "Baden-Württemberg",
        "Bayern",
        "Berlin",
        "Nordrhein-Westfalen",
        "Sachsen",
    ]
    for c, h in enumerate(headers, start=1):
        t62.cell(row=5, column=c, value=h)
    # Data
    rows = [
        ("010000", "Mord und Totschlag", 90, 120, 70, 200, 50),
        ("892100", "Mord, Totschlag, Tötung auf Verlangen", 88, 118, 68, 195, 48),
        ("892200", "Vergewaltigung u. besondere Fälle", 1500, 2100, 1800, 4200, 900),
        ("892300", "Raubdelikte", 4500, 5500, 6200, 12000, 2800),
        ("892400", "Gefährliche/schwere KV", 12000, 15000, 8500, 28000, 7000),
        ("892000", "Gewaltkriminalität", 25000, 31000, 22000, 60000, 14500),
        # Skipped offence — not in schluessel_to_category
        ("510000", "Diebstahl", 500000, 700000, 600000, 1300000, 320000),
    ]
    for ri, row in enumerate(rows, start=6):
        for ci, val in enumerate(row, start=1):
            t62.cell(row=ri, column=ci, value=val)

    # === T81: Nichtdeutsche Tatverdächtige by Bundesland ===
    t81 = wb.create_sheet("T81")
    for r in range(1, 5):
        t81.cell(row=r, column=1, value="boilerplate")
    for c, h in enumerate(headers, start=1):
        t81.cell(row=5, column=c, value=h)
    # Foreign suspects — smaller counts than totals.
    rows_foreign = [
        ("010000", "Mord und Totschlag", 35, 50, 40, 80, 18),
        ("892100", "Mord, Totschlag, Tötung auf Verlangen", 33, 49, 39, 78, 17),
        ("892400", "Gefährliche/schwere KV", 4800, 6500, 4200, 12500, 2700),
    ]
    for ri, row in enumerate(rows_foreign, start=6):
        for ci, val in enumerate(row, start=1):
            t81.cell(row=ri, column=ci, value=val)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture()
def fake_source() -> SourceFile:
    content = _build_fake_pks_xlsx()
    target = REPO_ROOT / "data" / "raw" / "de" / "test-fixture" / "pks-faelle.xlsx"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return SourceFile(
        url="manual",
        local_path=str(target.relative_to(REPO_ROOT)),
        fetched_at=datetime.utcnow(),
        sha256="fake-de-sha",
    )


def test_parse_extracts_both_sheets(fake_source: SourceFile) -> None:
    a = DEAdapter()
    df = a.parse(fake_source)
    assert not df.empty
    # We expect rows from both sheets
    assert set(df["sheet"]) == {"T62", "T81"}
    assert set(df["suspect_dim"]) == {"total", "foreign"}
    # Schlüssel 510000 (Diebstahl) is in the input but should be parsed (it's
    # filtered at normalise stage, not parse).
    assert "510000" in set(df["schluessel"])


def test_normalise_emits_suspect_dim_rows(fake_source: SourceFile) -> None:
    a = DEAdapter()
    df = a.normalise(a.parse(fake_source), fake_source)
    assert not df.empty
    # Must have both total and foreign rows
    assert set(df["suspect_dim"]) == {"total", "foreign"}
    # Diebstahl (510000) is not in the harmonised mapping — must not appear
    assert "Diebstahl" not in str(df["crime_category_native"].tolist())
    # NUTS-1 codes
    assert all(c.startswith("DE") for c in df["region_code"].unique())


def test_normalise_aggregates_homicide_correctly(fake_source: SourceFile) -> None:
    a = DEAdapter()
    df = a.normalise(a.parse(fake_source), fake_source)
    # Two Schlüssel (010000, 892100) both map to homicide → they collapse
    # under groupby.
    bavaria = df[(df["region_code"] == "DE2") & (df["crime_category"] == "homicide")]
    # Total (T62): 120 (010000) + 118 (892100) = 238
    total = bavaria[bavaria["suspect_dim"] == "total"]
    assert int(total["count"].iloc[0]) == 238
    # Foreign (T81): 50 + 49 = 99
    foreign = bavaria[bavaria["suspect_dim"] == "foreign"]
    assert int(foreign["count"].iloc[0]) == 99
