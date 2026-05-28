"""Schema for incidents.parquet (Tier 2)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

Weapon = Literal[
    "knife",
    "firearm",
    "vehicle",
    "blunt_object",
    "fists",
    "other",
    "unknown",
]

LocationPrecision = Literal["exact", "city", "region"]
Confidence = Literal["HIGH", "MEDIUM", "LOW"]
ReviewStatus = Literal["unreviewed", "verified", "flagged", "removed"]
VictimSexSummary = Literal["male", "female", "mixed", "unknown"]
VictimAgeSummary = Literal["child", "teen", "adult", "elderly", "mixed", "unknown"]


class IncidentSource(BaseModel):
    url: str
    outlet: str
    published_at: datetime | None = None
    quote_snippet: str


class Incident(BaseModel):
    """One incident — output of extraction + dedupe."""

    incident_id: str
    date_incident: date | None = None
    date_reported: date
    country: str = Field(min_length=2, max_length=2)
    region_code: str | None = None
    city: str | None = None
    lat: float | None = None
    lon: float | None = None
    location_precision: LocationPrecision = "region"
    weapon: Weapon = "unknown"
    victim_count: int = Field(ge=0, default=0)
    victim_fatal: int = Field(ge=0, default=0)
    victim_sex_summary: VictimSexSummary = "unknown"
    victim_age_summary: VictimAgeSummary = "unknown"
    suspect_count: int | None = None
    suspect_description_verbatim: str | None = None
    suspect_origin_as_reported: str | None = None
    sources: list[IncidentSource]
    confidence: Confidence = "LOW"
    extracted_at: datetime
    extractor_version: str
    last_reviewed_at: datetime | None = None
    review_status: ReviewStatus = "unreviewed"
