# Methodology

The Great Stabbing presents violent-crime statistics for European countries. This document explains how the numbers are derived, what the limits are, and the editorial rules we follow.

## Crime categories (harmonised)

Each country reports crime in its own way. We map every native category into one of eight harmonised categories:

| Harmonised | Definition |
|---|---|
| `homicide` | Completed killing of a human being (murder + manslaughter, intentional). |
| `attempted_homicide` | Attempted killing where the victim survived. |
| `knife_offence` | Offence involving a knife or sharp object as the primary weapon. |
| `firearm_offence` | Offence involving a firearm. |
| `sexual_assault` | Sexual assault, including rape. |
| `robbery_violent` | Robbery involving violence or threat of violence. |
| `assault_serious` | Grievous bodily harm short of homicide/attempted homicide. |
| `violent_total` | Catch-all violent-crime total as reported by the source. |

Each row in `data/parquet/crime_aggregates.parquet` carries both the harmonised category (`crime_category`) and the source's native term (`crime_category_native`). The native term is authoritative when there is any doubt.

## Foreign-background dimension

This is the variable the project takes most seriously. Rules:

1. **Show only what the source publishes.** No imputation.
2. **Use the source's own terminology**, linked to a definition on each country's methodology page:
   - Germany BKA: *Nichtdeutsche Tatverdächtige* (non-German suspects).
   - Denmark Statbank: *Herkomst* (origin: native / immigrant / descendant).
   - Austria BMI: *Nichtösterreichische Tatverdächtige*.
   - Sweden BRÅ: occasional special reports; the variable is *utländsk bakgrund*.
3. **Always show absolute counts AND rates per 100k** of the relevant population group. Absolute counts in isolation are misleading.
4. **Stats are on suspects, not convictions.** State this on every chart.
5. **France, UK, Spain (general statistics)**: this variable is not published. Show a clear "not published by [source]" tag — never blank, never zero.

For news incidents (Tier 2), `suspect_origin_as_reported` is filled ONLY when the article explicitly states nationality, country of origin, residence status, or asylum status. It is never inferred from names, descriptions, or location.

## Sourcing

Every row in every Parquet file has:
- `source_url` — direct link to the official release.
- `source_file_hash` — sha256 of the archived raw file.
- `retrieved_at` — UTC timestamp.

Raw source files are kept under `data/raw/` (gitignored but archived locally / in CI cache). The hash makes it possible to verify any historical figure.

## Cadence and lag

Different sources publish on different schedules. The site shows the most recent available period per country. Where a country lags more than 9 months, we display a "stale" warning.

| Cadence | Countries (MVP) | Typical lag |
|---|---|---|
| Monthly | UK, FR | ~1 month |
| Quarterly | ES, SE, DK | ~2 months |
| Annual | DE, IT | ~5 months |

## Tier 2 news incidents

News-extracted incidents are **illustrative pins**, not statistics. They are:
- Filtered to violent bodily-harm only.
- Dated to the incident (when stated) or the article (otherwise).
- Tagged with confidence: HIGH = police-confirmed, MEDIUM = ≥2 independent outlets, LOW = single outlet.
- Linked verbatim to source articles.

We never aggregate news pins into incidence rates. That would be junk methodology — coverage of crime varies dramatically by outlet, country, and language.

## Right of correction

If an outlet whose article we ingested issues a retraction or correction, open a GitHub issue and we'll honour it. Each incident row has a `review_status` that can be set to `flagged` or `removed`.

## Limitations we won't try to hide

- **Definitions of "homicide" differ.** Some countries include attempt, some don't. Some include negligent killing, some don't. We use the source's definition and document it per-country.
- **Reporting rates vary.** A change in count can reflect a change in reporting (citizen willingness, police priorities) as much as a change in actual incidence.
- **Region boundaries shift.** NUTS is revised every ~3 years; we use NUTS 2021. Historical comparisons across revisions carry methodological notes.
- **Population denominators** come from Eurostat (`demo_r_pjangrp3`) and lag by 1–2 years. Rates for the most recent period use the latest available denominator.
