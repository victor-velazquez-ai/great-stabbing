"""FR adapter tests — synthetic Interstats-shaped CSV fixture."""

from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from adapters.common.base import REPO_ROOT, SourceFile
from adapters.fr.adapter import FRAdapter


def _build_fake_csv() -> bytes:
    rows = [
        # Two years, four départements, three indicators
        # 75 Paris → FR101, 13 Bouches-du-Rhône → FRL04, 06 Alpes-Maritimes → FRL03,
        # 971 Guadeloupe → FRY10
        ("75", "11", "2025", "Homicides", "Victime", "30", "0,0135"),
        ("75", "11", "2025", "Violences physiques hors cadre familial", "Victime", "10000", "1,5"),
        ("75", "11", "2025", "Violences sexuelles", "Victime", "3500", "0,5"),
        ("13", "93", "2025", "Homicides", "Victime", "55", "0,026"),
        ("13", "93", "2025", "Violences physiques hors cadre familial", "Victime", "8000", "1,3"),
        ("13", "93", "2025", "Violences sexuelles", "Victime", "2500", "0,4"),
        ("06", "93", "2025", "Homicides", "Victime", "12", "0,011"),
        ("971", "01", "2025", "Homicides", "Victime", "44", "0,11"),
        # Prior year — should be filtered out by latest-year logic
        ("75", "11", "2024", "Homicides", "Victime", "28", "0,013"),
        # Also Faits unit — should be filtered out
        ("75", "11", "2025", "Homicides", "Fait", "27", "0,012"),
    ]
    header = "Code_departement;Code_region;annee;indicateur;unite_de_compte;nombre;taux_pour_mille;insee_pop;insee_pop_millesime;insee_log;insee_log_millesime\n"
    body = "\n".join(
        ";".join([*row, "1000000", "2024", "500000", "2024"]) for row in rows
    )
    # Include BOM to mirror the live file.
    return ("﻿" + header + body + "\n").encode("utf-8")


@pytest.fixture()
def fake_source(tmp_path: Path) -> SourceFile:
    content = _build_fake_csv()
    target = REPO_ROOT / "data" / "raw" / "fr" / "test-fixture" / "interstats-dep.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return SourceFile(
        url="https://test/fake",
        local_path=str(target.relative_to(REPO_ROOT)),
        fetched_at=datetime.utcnow(),
        sha256="fake",
    )


def test_parse_filters_victims_only(fake_source: SourceFile) -> None:
    a = FRAdapter()
    parsed = a.parse(fake_source)
    # Faits row should be dropped (10 rows total → 9 after Victime filter)
    assert (parsed["unite_de_compte"] == "Victime").all()
    assert len(parsed) == 9
    assert parsed["nombre"].dtype.kind == "i"  # numeric


def test_normalise_recent_history_only(fake_source: SourceFile) -> None:
    a = FRAdapter()
    parsed = a.parse(fake_source)
    norm = a.normalise(parsed, fake_source)
    # Emits last 10 calendar years. Fixture has 2024 + 2025.
    years = set(norm["period_start"].dt.year)
    assert max(years) == 2025
    # Latest year is well-represented.
    assert (norm["period_start"].dt.year == 2025).any()
    assert set(norm["region_code"]).issubset({"FR101", "FRL04", "FRL03", "FRY10"})


def test_normalise_aggregates_assault_subcategories(fake_source: SourceFile) -> None:
    a = FRAdapter()
    parsed = a.parse(fake_source)
    # Inject a second assault indicator row so we can verify the sum.
    extra = pd.DataFrame(
        [
            {
                "Code_departement": "75",
                "Code_region": "11",
                "annee": 2025,
                "indicateur": "Violences physiques intrafamiliales",
                "unite_de_compte": "Victime",
                "nombre": 4000,
                "taux_pour_mille": 0.6,
                "insee_pop": 1000000.0,
                "insee_pop_millesime": "2024",
                "insee_log": "500000",
                "insee_log_millesime": "2024",
            }
        ]
    )
    parsed = pd.concat([parsed, extra], ignore_index=True)
    norm = a.normalise(parsed, fake_source)
    paris_assault = norm[
        (norm["region_code"] == "FR101") & (norm["crime_category"] == "assault_serious")
    ]
    assert len(paris_assault) == 1
    # 10000 (hors cadre) + 4000 (intrafamiliales) = 14000
    assert int(paris_assault["count"].iloc[0]) == 14000


def test_normalise_emits_total_only(fake_source: SourceFile) -> None:
    a = FRAdapter()
    norm = a.normalise(a.parse(fake_source), fake_source)
    assert (norm["suspect_dim"] == "total").all()
    assert norm["suspect_dim_value"].isna().all()
