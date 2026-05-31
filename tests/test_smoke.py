"""Smoke tests — imports and shared module structure."""

from __future__ import annotations


def test_adapters_common_imports() -> None:
    from adapters.common import Adapter, AdapterRun, SourceFile  # noqa: F401
    from adapters.common.schema import (  # noqa: F401
        CRIME_CATEGORIES,
        SUSPECT_DIMS,
        AggregateRow,
        aggregates_schema,
    )


def test_country_adapters_class_attrs() -> None:
    """Each MVP adapter declares country/authority/cadence at class level."""
    from adapters.de.adapter import DEAdapter
    from adapters.es.adapter import ESAdapter
    from adapters.fr.adapter import FRAdapter
    from adapters.it.adapter import ITAdapter
    from adapters.se.adapter import SEAdapter
    from adapters.uk.adapter import UKAdapter

    for cls in (UKAdapter, DEAdapter, FRAdapter, SEAdapter, ESAdapter, ITAdapter):
        assert cls.country, f"{cls.__name__} missing country"
        assert cls.authority, f"{cls.__name__} missing authority"
        assert cls.cadence in {"monthly", "quarterly", "annual"}, f"{cls.__name__} bad cadence"


def test_schema_enums() -> None:
    from adapters.common.schema import CRIME_CATEGORIES, SUSPECT_DIMS

    assert "homicide" in CRIME_CATEGORIES
    assert "by_origin_country" in SUSPECT_DIMS
    assert len(set(CRIME_CATEGORIES)) == len(CRIME_CATEGORIES)


def test_extraction_imports() -> None:
    from extraction import dedupe, filter as filt, confidence  # noqa: F401
    from extraction.schema import Incident, IncidentSource  # noqa: F401


def test_dedupe_hard_collapses_duplicates() -> None:
    from datetime import datetime

    from extraction.dedupe import dedupe_hard

    base = {
        "date_incident": "2026-05-12",
        "country": "DE",
        "city": "Mannheim",
        "weapon": "knife",
        "victim_count": 1,
        "victim_fatal": 1,
        "date_reported": "2026-05-13",
        "extracted_at": datetime.utcnow().isoformat(),
        "extractor_version": "test",
    }
    a = {**base, "sources": [{"url": "https://a.example/x", "outlet": "a"}]}
    b = {**base, "sources": [{"url": "https://b.example/y", "outlet": "b"}]}
    out = dedupe_hard([a, b])
    assert len(out) == 1
    assert len(out[0]["sources"]) == 2


def test_confidence_scoring() -> None:
    from extraction.confidence import score

    police = {
        "sources": [
            {"url": "https://www.presseportal.de/blaulicht/123"},
            {"url": "https://example.com/x"},
        ]
    }
    assert score(police) == "HIGH"

    two_outlets = {
        "sources": [
            {"url": "https://outlet-a.example/x"},
            {"url": "https://outlet-b.example/y"},
        ]
    }
    assert score(two_outlets) == "MEDIUM"

    one_outlet = {"sources": [{"url": "https://outlet-a.example/x"}]}
    assert score(one_outlet) == "LOW"
