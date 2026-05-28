# The Great Stabbing — Project Plan

> A Europe-wide, interactive map and dashboard of violent crime — stabbings, shootings, fatal beatings — with regional granularity and, where officially published, breakdowns by suspect background. Inspired by [hoyodecrimen.com](https://hoyodecrimen.com).

This document is the **product / data plan**, not the technical implementation plan. The tech plan comes after this is agreed.

---

## 1. Vision

A free, public, interactive site that lets anyone:

- See a **map of Europe** with violent-crime incidence shaded by region.
- **Zoom into any region** (country → state/Land/region → city) and see the local picture.
- See **individual incidents** (stabbings, shootings, fatal beatings, vehicle-ramming attacks) where incident-level data exists, with date, weapon, location, and — when the official source publishes it — suspect background.
- Browse **dashboards**: trend lines, rankings, year-over-year comparisons, weapon breakdowns, victim / suspect demographics where published.
- Trust the numbers: every figure cites an official source; gaps are shown as gaps, not guessed.

The product should feel as honest as hoyodecrimen: **"this is what the police published; here it is on a map."**

---

## 2. What the reference project actually is (and how ours differs)

`hoyodecrimen.clean` is a small, focused **data pipeline**:

- One source: the Mexico City Attorney General's office publishes incident-level CSVs.
- Tech: R for cleaning + PostgreSQL for storage + Docker + GitHub Actions for scheduled refresh.
- The website on top is a separate frontend.

This works because **one government publishes one dataset on one schedule** for one city.

**Europe has no equivalent.** This is the single biggest design constraint of the project:

- ~30+ countries, each with its own police statistical office, schedule, format, language, and definition of "violent crime".
- Geographic units differ (Länder vs. départements vs. regiones vs. NUTS-2 vs. NUTS-3).
- "Foreign background" — the variable that makes this project distinctive — is **published openly by some** (Germany BKA, Denmark, Austria, sometimes Sweden), **published partially by others** (Netherlands CBS, Norway SSB), and **explicitly not published** by others (France, UK, Spain).
- Incident-level data with location and weapon is rare in official feeds (UK is the main exception via data.police.uk).

So our pipeline is **not one scraper** — it's a **federation of country adapters** plus an **incident-level layer** built from news media.

---

## 3. Scope and MVP

To avoid the project dying as a 30-country boil-the-ocean exercise, ship in waves.

### MVP (v0.1) — 7 countries covering the full data-availability spectrum
- 🇩🇪 Germany (BKA PKS, annual; Bundesland-level; non-German suspect share published)
- 🇬🇧 United Kingdom (data.police.uk monthly; incident-level with location; knife-crime stats by force area)
- 🇸🇪 Sweden (BRÅ; quarterly violent crime, occasional foreign-background reports)
- 🇩🇰 Denmark (Danmarks Statistik; country-of-origin breakdown published)
- 🇫🇷 France (Interstats monthly; département-level; **no** foreign-background variable)
- 🇪🇸 Spain (Ministerio del Interior, *Balances trimestrales*; provincia-level; partial nationality data on detainees)
- 🇮🇹 Italy (ISTAT annual + Ministero dell'Interno monthly; regione / provincia-level; partial foreign-background)

These 7 span the full data-availability spectrum (full FB published → partial → not published; annual → monthly; aggregate-only → incident-level), so the design has to handle every case honestly from day one. Spain and Italy also give the map a strong southern-European footprint at launch, not just a Germanic / Nordic skew.

### v0.2 — add 5 more
🇳🇱 Netherlands, 🇦🇹 Austria, 🇧🇪 Belgium, 🇵🇹 Portugal, 🇨🇭 Switzerland.

### v0.3 — rest of EU + Norway, Ireland, UK regions full coverage.

### v1.0 — incident-level news layer live across all v0.3 countries.

### Out of scope (for now)
- Russia, Belarus, Turkey, Ukraine, non-EU Balkans (unreliable / wartime / inaccessible data).
- Property crime, fraud, drugs (focus stays on **violent bodily-harm crime** so the product has a clear identity).

---

## 4. Data strategy — the core of the plan

Three tiers, layered. Each tier is a fallback for what the tier above cannot give us.

### Tier 1 — Official statistical feeds (the spine)

Per-country adapters that pull from the national statistical / police authority. This is the trustworthy backbone.

| Country | Source | Cadence | Regional unit | Foreign-background published? | Incident-level? |
|---|---|---|---|---|---|
| 🇩🇪 Germany | BKA Polizeiliche Kriminalstatistik (PKS) | annual | Bundesland | Yes — *Nichtdeutsche Tatverdächtige* | No |
| 🇬🇧 UK (E&W) | data.police.uk, ONS knife-crime tables | monthly | Police force area / LSOA | No | **Yes** (point data) |
| 🇫🇷 France | SSMSI Interstats | monthly | département | No | No |
| 🇪🇸 Spain | Ministerio del Interior, balances trimestrales | quarterly | provincia | Partial (nationality of detainees in some reports) | No |
| 🇮🇹 Italy | ISTAT + Polizia di Stato | annual / monthly | regione / provincia | Partial | No |
| 🇸🇪 Sweden | BRÅ | quarterly / annual | län | Occasionally (special reports) | No |
| 🇩🇰 Denmark | Danmarks Statistik (STRAF tables) | quarterly | region | Yes — by country of origin | No |
| 🇳🇴 Norway | SSB | annual | fylke | Partial | No |
| 🇳🇱 Netherlands | CBS StatLine | quarterly | provincie | Partial | No |
| 🇧🇪 Belgium | Police Fédérale stats | quarterly | province | No | No |
| 🇦🇹 Austria | BMI Kriminalstatistik | annual | Bundesland | Yes — non-Austrian suspects | No |
| EU-wide rollup | Eurostat `crim_off_cat` | annual, lagged 1–2y | country / NUTS-2 | No | No |

**Adapter pattern:** each country has one script (Python) that:
1. Downloads the latest official release (CSV / Excel / PDF / API).
2. Normalises to a common schema (date_period, region_code, crime_category, count, suspect_nationality_status, source_url, retrieved_at).
3. Maps the country's regional codes to **NUTS** (Eurostat's standard nomenclature). This is what lets one map render data from 30 countries.
4. Writes to the central store.

PDFs (France, Austria sometimes) are the worst case — fall back to LLM-assisted table extraction, with the raw PDF archived for audit.

### Tier 2 — Incident-level news layer

For the pins-on-the-map experience (which is the visceral, hoyodecrimen feel), Tier 1 is not enough — most countries don't publish incidents. We build this:

- **Pull**: RSS / news APIs (GDELT, MediaCloud, EventRegistry, country-specific aggregators) filtered by violent-crime keywords in each country's language.
- **Extract**: LLM pass over each article to extract a structured record — date, city, weapon, victim count, victim sex/age if stated, suspect description **as reported** (including nationality/origin if the article states it, otherwise null), source URL.
- **Dedupe**: cluster articles about the same incident (multiple outlets cover one stabbing).
- **Verify**: cross-reference with police press releases where available; flag confidence level (HIGH = police-confirmed, MEDIUM = multiple outlets, LOW = single outlet).
- **Display**: only HIGH and MEDIUM go on the map by default; LOW available via a toggle.

This is the part most amenable to a **scheduled LLM job** — run weekly, ingest ~last 14 days of news, extract incidents, write to DB. Anthropic API or self-hosted model; estimated cost is small (~$10–50/month for a sane ingest volume).

**Critical guardrail**: news ≠ statistics. Tier 2 incidents are illustrative pins, not statistics. Aggregate counts displayed on the map and dashboards come from **Tier 1**. We do not aggregate news pins into incidence rates — that would be junk methodology.

### Tier 3 — Quarterly LLM-driven gap-fill research

For countries where Tier 1 is annual or PDF-only, run a quarterly research pass (Claude / similar) to:
- Check if the official source has released a new report.
- Read any new methodology notes (definitions change — "violence" in Germany was redefined in 2017, etc.).
- Note any new variables published (e.g., a one-off BRÅ report on Sweden's gang shootings).

This is a human-in-the-loop quarterly review, not a scraper. Output is a report card we read, decide if adapters need updating, and commit.

### The "foreign background" variable — design rules

This is the politically charged part. To stay credible:

- **Display only what the official source publishes.** No imputation. No "estimates." Ever.
- When a country doesn't publish it: show a clear "not published by [source]" tag on the dashboard, not a blank or a zero.
- Use the source's own terminology, linked to a definition: Germany's *Nichtdeutsche Tatverdächtige* ≠ Denmark's *herkomst* (origin) ≠ Sweden's *utländsk bakgrund*. They mean different things. The site explains each.
- Always show absolute counts **and** rates per 100k of the relevant population group (you can't say much from absolute counts alone).
- Suspect-background data is on **suspects**, not convictions. State this prominently.
- For Tier 2 (news) incidents, the suspect description is **as reported by the article**, with the source quoted verbatim. Never paraphrased to imply more than the article said.

This isn't political — it's the only way the numbers survive scrutiny. Critics from any side will look for methodological cheating; there should be none.

---

## 5. Geographic units — NUTS

Use **Eurostat NUTS** (Nomenclature of Territorial Units for Statistics):
- NUTS-0 = country
- NUTS-1 = major region (German Länder, French régions, UK NUTS-1)
- NUTS-2 = basic regions (Spanish CCAA, French anciennes régions, German Regierungsbezirke)
- NUTS-3 = small regions (départements, Kreise, provincie, counties)

Eurostat publishes the official **NUTS GeoJSON / shapefiles** at gisco.statbel.fgov.be / ec.europa.eu/eurostat/web/gisco. This gives one consistent boundary set for the whole map. Each country adapter maps its native codes (AGS for Germany, INSEE for France, LAU for cities) to NUTS via Eurostat's correspondence tables.

For UK incident-level pins, use the actual reported lat/lon from data.police.uk (already snapped to ~10m grids by ONS for privacy).

---

## 6. The product

### Map view (the hero)
- Choropleth across NUTS regions, shaded by chosen metric (default: homicide rate per 100k).
- Zoom from continent → country → NUTS-2 → NUTS-3.
- At NUTS-3 + UK incident-level zoom, individual pins appear (Tier 2 news + Tier 1 UK police data).
- Pin click → side panel with date, weapon, source link, "as reported" suspect description.
- Metric selector: homicide / knife / firearm / sexual assault / robbery-with-violence / total violent. Each maps to the harmonised category derived per-country.
- Time slider: rolling 12-month window, with year-over-year toggle.

### Dashboards
- **Country page** per country: trend chart (5–10y), regional ranking, weapon mix, suspect-background panel (with "not published" honest tag if applicable), methodology + source links.
- **Europe overview**: ranking table, top movers (regions with biggest YoY change), continent trendline.
- **Regional page** per NUTS-2: same shape as country, scoped.
- **Methodology page**: per country, what they publish and what they don't, with links and last-fetched dates.

### Transparency surface
- Every chart has a "view source" link to the exact official PDF/CSV used.
- Every dataset row has a `retrieved_at` and `source_url`.
- A public changelog of methodology updates.

---

## 7. Update cadence

| Tier | Frequency | Mechanism |
|---|---|---|
| Tier 1 official (monthly countries: UK, France) | monthly, day after release | Scheduled scraper (cron / GitHub Actions) |
| Tier 1 official (quarterly: Spain, Sweden, Denmark, NL, BE) | quarterly | Scheduled scraper |
| Tier 1 official (annual: Germany, Italy, Austria, Norway, Eurostat) | annual | Scheduled scraper + manual verify |
| Tier 2 news incidents | **monthly** | LLM extraction job run on user's Claude tier |
| Tier 3 gap-fill research | quarterly | Human-triggered LLM session, output reviewed |

**Note on Tier 2 monthly cadence**: A monthly batch means the map is not "live news" — pins lag real events by up to ~5 weeks (worst case: incident on day 2 of a month, ingested at end of next month). That is fine for a statistics-style site and explicitly *not* fine for a breaking-news site, which is the right framing anyway (we are not a news outlet). Each pin will show its article date so users can see the lag. If volume grows we can revisit weekly later, but monthly stays within the existing Claude subscription with margin.

Each adapter has a "last successful run" timestamp shown on the methodology page so users (and we) can see what's stale.

---

## 8. Ethics, legal, editorial

- **GDPR**: only published aggregates and already-public news content. No PII. No victim or suspect names on the map (even when the news story has them — we drop names, keep age/sex/described origin only).
- **No incitement framing**: the site presents data, not commentary. Headlines on the site are descriptive ("Knife offences in West Midlands, monthly"), not editorial.
- **Open methodology**: data + code on GitHub, all derivations reproducible.
- **Right of reply**: if an outlet whose article we ingested issues a correction, we honour it; news pins have a `last_updated` and a way to flag for review.
- **License**: code MIT, data ODbL or CC-BY (whatever lets us redistribute given source licenses — each official source has its own; we record per-row license).

---

## 9. Phased roadmap to "live on the web"

**Phase 0 — Foundations (week 1–2)**
- Lock the data schema (Tier 1 + Tier 2).
- Spike one country end-to-end (UK, because data.police.uk is the easiest and most incident-rich).
- Decide stack (tech plan, separate doc).

**Phase 1 — MVP private alpha (week 3–7)**
- Adapters for the 7 MVP countries (DE, UK, SE, DK, FR, ES, IT).
- NUTS basemap + choropleth working for one metric (homicide).
- Static site, no incident-level pins yet.
- Deployed to a staging URL on free static hosting (Cloudflare Pages).

**Phase 2 — Public beta (week 8–11)**
- Dashboards per country.
- UK incident-level layer (Tier 1 only, no news yet).
- Methodology pages.
- Public URL on free static hosting, no marketing yet, observe quietly.

**Phase 3 — News incident layer (week 12–15)**
- Tier 2 news pipeline for the 7 MVP countries, **monthly manual extraction** via Claude Desktop or Claude Code (no API spend).
- GitHub Actions handles the free-tier work: fetch articles → filter → write `candidate_articles.jsonl`.
- User runs Claude locally once a month to extract incidents; commits `extracted_incidents.jsonl`.
- Confidence levels, dedupe, source-quote display.
- Stays on Cloudflare Pages free tier. Railway not introduced unless a real backend becomes necessary later.
- Soft launch.

**Phase 4 — Coverage expansion (month 4–6)**
- v0.2 countries (NL, AT, BE, IT, ES).
- Performance, mobile, accessibility pass.

**Phase 5 — Full Europe (month 6–12)**
- Remaining EU + EFTA.
- API for researchers / journalists.

A working public URL exists at end of **Phase 2** (~10 weeks).

---

## 10. Risks and how we handle them

| Risk | Mitigation |
|---|---|
| Official sources change formats / break adapters | Each adapter has fixtures + a "last good" cached run; alerts on schema drift. |
| News LLM hallucinates incidents | Require ≥2 sources or police-press-release confirmation for HIGH; show source quote verbatim. |
| Project becomes politically targeted / accused of bias | Methodology transparency + sticking to "only what the source published" + no editorial copy. |
| GDPR complaint over a news pin | No names ever; pre-built take-down workflow. |
| Maintenance burden of 30 adapters | Start small (MVP=5), only expand once cadence is stable. |
| Geographic data licensing | NUTS boundaries from Eurostat are open; UK ONS open; double-check each. |
| The "foreign background" variable invites bad-faith reuse | Force-display the methodology caveat next to every such chart; the variable is meaningless without the population denominator, which we always show. |

---

## 11. Decisions log

These were the open questions before the tech plan. They are now resolved:

1. **Hosting** → **Cloudflare Pages (free static) for the entire MVP**. Target spend is **≤ $5/month**. Railway is deferred indefinitely — only revisit if we genuinely need a public API or authenticated features. The MVP runs on free tiers end-to-end.
2. **Team size** → **Solo build.** Optimise the repo, schemas, and adapter pattern for one person to operate. No premature multi-contributor scaffolding (no monorepo tooling, no over-engineered CI matrices). Adapters must be runnable one-by-one from a laptop.
3. **Public name** → **"The Great Stabbing"** stays for now. Editorial-leaning framing is accepted; we will revisit if we ever pitch the dataset to researchers / journalists who need a neutral citation.
4. **LLM for Tier 2** → **Manual once-a-month run via Claude Desktop or Claude Code on the existing subscription. No Anthropic API at MVP.** GitHub Actions does the free-tier work (fetch articles, filter, prepare a `candidate_articles.jsonl`). Once a month the user opens Claude Desktop/Code, points it at that file, gets `extracted_incidents.jsonl` back, and commits. Zero API spend. The plan keeps an "API path" documented as a one-config-line switch for later — costs ~$3/mo on Haiku 4.5 if we ever want hands-off automation.
5. **Data store** → **DuckDB + Parquet files** in the repo / object storage. Rationale: dead simple, no server to run, queryable from the static site via DuckDB-WASM if we want client-side analytics, and trivially portable to Railway+Postgres later if we outgrow it. Postgres is overkill for a once-a-month-refreshed dataset of this size.
6. **Languages** → **English only at launch.** Source materials stay in original language and are linked verbatim; site UI and methodology copy are English. Multilingual is a v1.0+ consideration.
7. **Country priority** → **DE, UK, SE, DK, FR, ES, IT** (7-country MVP). Adds Spain and Italy to the original 5 for southern-Europe coverage.

---

## 12. Next step

With these decisions locked, the next deliverable is the **technical implementation plan**:

- Repo layout (single repo, adapters/ + site/ + data/ + extraction/).
- DuckDB + Parquet schema for Tier 1 and Tier 2.
- Country adapter template (Python) + how each of the 7 MVP adapters fits.
- The monthly Claude extraction job: prompt design, article-batching strategy, dedupe / confidence pipeline, expected token budget vs. your Claude tier.
- NUTS basemap pipeline (Eurostat GISCO → simplified vector tiles).
- Frontend stack choice (likely Astro or SvelteKit for static-first, with MapLibre GL for the map; to be argued in the tech plan, not assumed here).
- CI / scheduled runs (GitHub Actions cron for free-tier phase, Railway scheduled jobs after migration).
- Migration plan from Cloudflare Pages → Railway in Phase 3.
