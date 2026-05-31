"""Tests for the Tier 2 extraction pipeline core logic.

We focus on the pure-Python pieces (filter, dedupe, confidence, incident_id
stability, finalize). Live fetchers (GDELT API, RSS) are tested separately
via integration-style runs, not unit tests, to avoid flaky network calls.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from extraction.confidence import score
from extraction.dedupe import dedupe_hard, hard_key
from extraction.filter import matches_keywords
from extraction.pipeline import _dedupe_by_url, _incident_id, _month_window


# ---- filter ----

def test_keyword_filter_positive() -> None:
    assert matches_keywords("Police arrest man after stabbing in city centre", "en")
    assert matches_keywords("erstochen — Polizei ermittelt", "de")
    assert matches_keywords("homme poignardé à Marseille", "fr")


def test_keyword_filter_negative() -> None:
    # Pure fiction
    assert not matches_keywords("Film review: a thrilling murder mystery novel", "en")
    # Generic non-violence
    assert not matches_keywords("New library opens in Manchester", "en")


# ---- dedupe ----

def test_hard_key_collapses_same_event() -> None:
    a = {"date_incident": "2026-04-12", "country": "DE", "city": "Mannheim",
         "weapon": "knife", "victim_fatal": 1}
    b = {**a}
    assert hard_key(a) == hard_key(b)


def test_dedupe_hard_merges_sources() -> None:
    base = {"date_incident": "2026-04-12", "country": "DE", "city": "Mannheim",
            "weapon": "knife", "victim_count": 1, "victim_fatal": 1, "date_reported": "2026-04-13"}
    a = {**base, "sources": [{"url": "https://a.example/x", "outlet": "a"}]}
    b = {**base, "sources": [{"url": "https://b.example/y", "outlet": "b"}]}
    out = dedupe_hard([a, b])
    assert len(out) == 1
    assert {s["url"] for s in out[0]["sources"]} == {"https://a.example/x", "https://b.example/y"}


# ---- confidence ----

def test_confidence_police_pr_is_high() -> None:
    rec = {"sources": [{"url": "https://www.presseportal.de/blaulicht/123"}]}
    assert score(rec) == "HIGH"


def test_confidence_two_outlets_medium() -> None:
    rec = {"sources": [
        {"url": "https://outlet-a.example/x"},
        {"url": "https://outlet-b.example/y"},
    ]}
    assert score(rec) == "MEDIUM"


def test_confidence_single_outlet_low() -> None:
    rec = {"sources": [{"url": "https://outlet-a.example/x"}]}
    assert score(rec) == "LOW"


# ---- pipeline helpers ----

def test_month_window_spans_40_days() -> None:
    since, until = _month_window("2026-05")
    assert (until - since).days == 40
    assert until.month == 6 and until.day == 1


def test_dedupe_by_url_keeps_first_seen() -> None:
    rows = [
        {"url": "https://a.example/1", "title": "first"},
        {"url": "https://a.example/1", "title": "duplicate"},
        {"url": "https://b.example/2", "title": "second"},
        {"url": "", "title": "no url"},
    ]
    out = _dedupe_by_url(rows)
    assert len(out) == 2
    assert out[0]["title"] == "first"


def test_incident_id_is_stable() -> None:
    rec = {"date_incident": "2026-05-01", "country": "FR", "city": "Marseille",
           "weapon": "knife", "victim_fatal": 1}
    assert _incident_id(rec) == _incident_id(rec)
    rec2 = {**rec, "city": "Lyon"}
    assert _incident_id(rec) != _incident_id(rec2)


# ---- finalize integration (no network) ----

def test_finalize_writes_parquet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end test of finalize() against a manually crafted _outbox file.

    We patch the geocoder to skip network. The test verifies dedupe,
    confidence scoring, stable incident_id, and Parquet write.
    """
    from extraction import pipeline as pl

    # Redirect outputs to tmp_path.
    outbox = tmp_path / "_outbox"
    outbox.mkdir()
    parquet_path = tmp_path / "incidents.parquet"
    monkeypatch.setattr(pl, "OUTBOX", outbox)
    monkeypatch.setattr(pl, "INCIDENTS_PARQUET", parquet_path)
    monkeypatch.setattr(pl, "PARQUET_DIR", tmp_path)

    extracted = [
        {
            "extracted": True,
            "incident": {
                "date_incident": "2026-05-12",
                "date_reported": "2026-05-13",
                "country": "DE",
                "city": "Mannheim",
                "weapon": "knife",
                "victim_count": 1,
                "victim_fatal": 1,
                "sources": [{"url": "https://www.presseportal.de/blaulicht/123", "outlet": "presseportal"}],
            },
        },
        {
            "extracted": True,
            "incident": {  # same event from another outlet — should dedupe
                "date_incident": "2026-05-12",
                "date_reported": "2026-05-13",
                "country": "DE",
                "city": "Mannheim",
                "weapon": "knife",
                "victim_count": 1,
                "victim_fatal": 1,
                "sources": [{"url": "https://rhein-neckar-zeitung.example/x", "outlet": "RNZ"}],
            },
        },
        {"extracted": False, "skip_reason": "opinion piece"},
        {
            "extracted": True,
            "incident": {
                "date_incident": "2026-05-15",
                "date_reported": "2026-05-15",
                "country": "FR",
                "city": "Marseille",
                "weapon": "firearm",
                "victim_count": 2,
                "victim_fatal": 2,
                "sources": [{"url": "https://laprovence.example/x", "outlet": "La Provence"}],
            },
        },
    ]

    src = outbox / "extracted_incidents_2026-05.jsonl"
    with src.open("w", encoding="utf-8") as f:
        for r in extracted:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    pl.finalize("2026-05", use_network_geocode=False)

    import duckdb
    df = duckdb.connect().execute(f"SELECT * FROM read_parquet('{parquet_path.as_posix()}')").df()
    assert len(df) == 2  # Mannheim deduped, Marseille kept
    assert set(df["country"]) == {"DE", "FR"}
    # Mannheim must be HIGH (presseportal source).
    mannheim = df[df["city"] == "Mannheim"].iloc[0]
    assert mannheim["confidence"] == "HIGH"
    # Marseille single-outlet → LOW.
    marseille = df[df["city"] == "Marseille"].iloc[0]
    assert marseille["confidence"] == "LOW"
    # incident_id stable: re-running finalize must upsert in place (no dupes).
    pl.finalize("2026-05", use_network_geocode=False)
    df2 = duckdb.connect().execute(f"SELECT * FROM read_parquet('{parquet_path.as_posix()}')").df()
    assert len(df2) == 2
