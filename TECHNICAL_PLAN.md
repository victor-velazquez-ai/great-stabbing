# The Great Stabbing — Technical Plan

Companion to [PROJECT_PLAN.md](./PROJECT_PLAN.md). This is the build plan: stack, repo layout, schemas, schedules, and exactly what runs where.

Design principles for a solo build:
- **Boringly composable.** Each adapter is one Python file you can run standalone. No frameworks where a script suffices.
- **Static-first.** The whole site is files. A backend only enters the picture once a backend earns its keep.
- **Reproducible.** Re-running any adapter on any date produces the same Parquet (modulo upstream changes).
- **Auditable.** Every row carries `source_url` + `retrieved_at`. Raw source files are archived, not just parsed.

---

## 1. Stack at a glance

| Layer | Choice | Why |
|---|---|---|
| Adapter language | Python 3.12 + `uv` for deps | Standard for data work; `uv` is faster than poetry/pip and gives us lockfiles for free |
| Data store | DuckDB + Parquet files in repo (Git LFS for >50MB) | No server. Parquet is the canonical format; DuckDB queries them in-process. Works in Python, in CI, and in the browser via DuckDB-WASM |
| PDF parsing | `pdfplumber` first, Claude as fallback for stubborn tables | ES Balances trimestrales and IT Polizia di Stato are PDF-only |
| Geography | Eurostat NUTS 2021 GeoJSON → PMTiles via `tippecanoe` | Single boundary system; PMTiles serve cheaply from R2 without a tile server |
| News ingest | GDELT 2.0 GKG + per-country RSS + police press-release feeds | GDELT is free and multilingual; RSS plugs the gaps |
| LLM extraction | **Manual monthly Claude Desktop / Claude Code session** on the user's existing subscription. No API at MVP. | Keeps cost at $0. Auto-API path documented for later. |
| Site framework | Astro + MapLibre GL JS + Observable Plot + DuckDB-WASM | Static-first; client-side DuckDB lets users query without a backend |
| Hosting | Cloudflare Pages (free) + R2 (free 10GB) | Zero-cost; targets ≤ $5/mo total |
| Scheduling | GitHub Actions cron | Free for a public repo |
| Railway | **Deferred indefinitely.** Only if a real backend earns its keep later. | Avoid the spend |
| Domain | Optional — `*.pages.dev` free subdomain works at launch | Custom domain ~€10/yr if added |

Total monthly cost at launch: **$0** (free tiers across the board). Cap: **$5/month** if/when a domain is added.

---

## 2. Repo layout

Single repo. Polyglot but flat — Python for data, Node/Astro for site.

```
great-stabbing/
├── PROJECT_PLAN.md
├── TECHNICAL_PLAN.md
├── README.md
├── LICENSE                          # MIT for code, data per-source
├── pyproject.toml                   # uv-managed deps
├── uv.lock
├── adapters/
│   ├── common/
│   │   ├── base.py                  # Adapter ABC, AdapterRun dataclass
│   │   ├── schema.py                # Tier 1 column contract
│   │   ├── nuts.py                  # NUTS code mapping + lookups
│   │   ├── http.py                  # Cached HTTP with retry, archives raw to data/raw/
│   │   └── validate.py              # pydantic / pandera row-level checks
│   ├── de/                          # one folder per country
│   │   ├── adapter.py               # implements Adapter
│   │   ├── region_map.csv           # Bundesland → NUTS-1
│   │   └── fixtures/                # captured source files for tests
│   ├── uk/ ...
│   ├── se/ ...
│   ├── dk/ ...
│   ├── fr/ ...
│   ├── es/ ...
│   └── it/ ...
├── extraction/                      # Tier 2 news → incidents pipeline
│   ├── fetch/
│   │   ├── gdelt.py
│   │   ├── rss.py
│   │   └── police_pr/               # per-country press release scrapers
│   ├── filter.py                    # keyword + lang classifier, pre-LLM
│   ├── extract.py                   # Claude batched extraction
│   ├── prompts/
│   │   └── incident_extraction.md   # versioned, in source control
│   ├── dedupe.py                    # cluster by (date, region, weapon) + embedding sim
│   ├── geocode.py                   # city → (lat, lon, NUTS-3)
│   ├── confidence.py                # HIGH/MEDIUM/LOW scoring
│   └── pipeline.py                  # orchestrator: monthly entrypoint
├── data/
│   ├── raw/                         # archived source files (PDFs, CSVs, JSONs), gitignored except small fixtures
│   ├── interim/                     # intermediate cleans, gitignored
│   ├── parquet/                     # CANONICAL output, committed (LFS if big)
│   │   ├── crime_aggregates.parquet
│   │   ├── incidents.parquet
│   │   └── nuts_regions.parquet
│   ├── nuts/                        # source GeoJSON
│   ├── tiles/                       # generated PMTiles, committed (or in R2)
│   └── duckdb.db                    # convenience bundle, regenerated
├── site/                            # Astro
│   ├── astro.config.mjs
│   ├── package.json
│   ├── public/
│   │   ├── tiles/                   # NUTS PMTiles (or fetched from R2)
│   │   └── data/                    # Parquet files copied here at build
│   └── src/
│       ├── components/
│       │   ├── Map.astro
│       │   ├── ChoroplethLayer.ts
│       │   ├── IncidentLayer.ts
│       │   └── charts/
│       ├── pages/
│       │   ├── index.astro          # Europe map
│       │   ├── country/[iso].astro  # country page
│       │   ├── region/[nuts].astro  # NUTS-2/3 page
│       │   └── methodology/[iso].astro
│       ├── lib/
│       │   ├── duckdb.ts            # DuckDB-WASM init + query helpers
│       │   └── format.ts
│       └── styles/
├── scripts/
│   ├── run_adapter.py               # `uv run scripts/run_adapter.py de`
│   ├── run_all.py
│   ├── build_tiles.sh               # NUTS → PMTiles
│   └── refresh_nuts_lookup.py
├── tests/
│   ├── adapters/                    # one test per adapter using fixtures/
│   └── extraction/
├── .github/
│   └── workflows/
│       ├── adapter-monthly.yml      # UK + FR (monthly sources)
│       ├── adapter-quarterly.yml    # ES + SE + DK
│       ├── adapter-annual.yml       # DE + IT
│       ├── extraction-monthly.yml   # news pipeline
│       ├── build-site.yml           # on data change or push
│       └── deploy.yml               # CF Pages deploy
└── docs/
    ├── adding-a-country.md
    └── methodology.md
```

---

## 3. Data schemas

DuckDB-readable Parquet, one file per logical table. Stable schemas — additive changes only.

### `crime_aggregates.parquet` (Tier 1)

| column | type | notes |
|---|---|---|
| `source_country` | VARCHAR(2) | ISO-3166-1 alpha-2 |
| `source_authority` | VARCHAR | e.g. "BKA", "data.police.uk" |
| `source_url` | VARCHAR | direct link to the file/release |
| `source_file_hash` | VARCHAR | sha256 of archived raw file |
| `retrieved_at` | TIMESTAMP | UTC |
| `period_start` | DATE | inclusive |
| `period_end` | DATE | inclusive |
| `period_type` | VARCHAR | `month` / `quarter` / `year` |
| `region_code` | VARCHAR | NUTS code, e.g. `DE1`, `UKD3` |
| `region_level` | TINYINT | 0–3 |
| `crime_category` | VARCHAR | harmonised: `homicide`, `knife_offence`, `firearm_offence`, `sexual_assault`, `robbery_violent`, `violent_total`, `attempted_homicide` |
| `crime_category_native` | VARCHAR | source's own term, e.g. "Gefährliche Körperverletzung" |
| `suspect_dim` | VARCHAR | `total` / `national` / `foreign` / `by_origin_country` / `unknown` |
| `suspect_dim_value` | VARCHAR | NULL except when `suspect_dim = by_origin_country`, then ISO country |
| `count` | INTEGER | raw count |
| `denominator_population` | INTEGER | NULL if no denom available |
| `denominator_source` | VARCHAR | e.g. "Eurostat demo_r_pjangrp3 2024" |
| `rate_per_100k` | DOUBLE | computed when denom available |
| `notes` | VARCHAR | free text, methodology caveats |

### `incidents.parquet` (Tier 2)

| column | type | notes |
|---|---|---|
| `incident_id` | VARCHAR | UUID v5 from (date, country, region, hash(sources)) — stable across runs |
| `date_incident` | DATE | NULL if article only says "this week" |
| `date_reported` | DATE | earliest article publish date |
| `country` | VARCHAR(2) | ISO-2 |
| `region_code` | VARCHAR | NUTS-2 or NUTS-3 |
| `city` | VARCHAR | as reported |
| `lat`, `lon` | DOUBLE | NULL if only city-level |
| `location_precision` | VARCHAR | `exact` / `city` / `region` |
| `weapon` | VARCHAR | `knife` / `firearm` / `vehicle` / `blunt_object` / `fists` / `other` / `unknown` |
| `victim_count` | INTEGER | |
| `victim_fatal` | INTEGER | |
| `victim_sex_summary` | VARCHAR | `male`, `female`, `mixed`, `unknown` |
| `victim_age_summary` | VARCHAR | `child`, `teen`, `adult`, `elderly`, `mixed`, `unknown` |
| `suspect_count` | INTEGER | NULL if not stated |
| `suspect_description_verbatim` | VARCHAR | quoted from source, no paraphrasing |
| `suspect_origin_as_reported` | VARCHAR | NULL unless article states |
| `sources_json` | VARCHAR | JSON: `[{url, outlet, published_at, quote_snippet}]` |
| `confidence` | VARCHAR | `HIGH` (police-confirmed) / `MEDIUM` (≥2 outlets) / `LOW` (1 outlet) |
| `extracted_at` | TIMESTAMP | |
| `extractor_version` | VARCHAR | e.g. `claude-haiku-4-5-20251001@prompt-v3` |
| `last_reviewed_at` | TIMESTAMP | NULL until a human reviews |
| `review_status` | VARCHAR | `unreviewed` / `verified` / `flagged` / `removed` |

### `nuts_regions.parquet` (lookup)

`code, name_en, name_native, parent_code, level (0..3), country, population_latest, area_km2, centroid_lat, centroid_lon`

Sourced once from Eurostat, refreshed annually.

---

## 4. Country adapter pattern

Every Tier 1 adapter is one Python module implementing one class.

```python
# adapters/common/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
import pandas as pd

@dataclass
class SourceFile:
    url: str
    local_path: str           # path under data/raw/
    fetched_at: datetime
    sha256: str

@dataclass
class AdapterRun:
    country: str
    period_start: date
    period_end: date
    n_rows_written: int
    n_regions: int
    source_files: list[SourceFile]
    duration_s: float
    notes: str

class Adapter(ABC):
    country: str           # ISO-2
    authority: str
    cadence: str           # "monthly" | "quarterly" | "annual"

    @abstractmethod
    def discover(self) -> list[SourceFile]:
        """Find new official releases since last run. Archives raw files to data/raw/."""

    @abstractmethod
    def parse(self, src: SourceFile) -> pd.DataFrame:
        """Source-shaped frame. No normalisation yet."""

    @abstractmethod
    def normalise(self, df: pd.DataFrame, src: SourceFile) -> pd.DataFrame:
        """Conform to crime_aggregates schema. Maps native regions → NUTS via region_map.csv."""

    def write(self, df: pd.DataFrame) -> None:
        """Upsert into data/parquet/crime_aggregates.parquet by (source_country, period_start, region_code, crime_category, suspect_dim, suspect_dim_value)."""
        # implemented once in base via DuckDB

    def run(self) -> AdapterRun:
        """Orchestrator. Wrap each step with logging + structured errors."""
```

### Per-country implementation notes (MVP 7)

| Country | Source mechanics | Cadence trigger | Parser | NUTS mapping |
|---|---|---|---|---|
| 🇩🇪 DE | BKA PKS — xlsx workbooks on bka.de | annual, May release | `openpyxl` via pandas | Bundesland (AGS prefix) → NUTS-1 |
| 🇬🇧 UK | data.police.uk — monthly ZIPs (CSV per force) | monthly, ~3rd of month | pandas CSV | Force area → NUTS-1/2/3 via ONS lookup |
| 🇸🇪 SE | BRÅ Statistikdatabasen — PXweb JSON API | quarterly + annual | `requests` → JSON → frame | län codes → NUTS-3 |
| 🇩🇰 DK | Statbank API (statbank.dk/api/v1) | quarterly | JSON | region → NUTS-2 |
| 🇫🇷 FR | SSMSI Interstats — CSV on data.gouv.fr | monthly, ~10th | pandas CSV | département (INSEE) → NUTS-3 |
| 🇪🇸 ES | Min. Interior — quarterly PDF *Balances trimestrales* | quarterly | `pdfplumber` first, Claude PDF fallback | provincia → NUTS-3 |
| 🇮🇹 IT | ISTAT API + Min. Interno PDF | annual (ISTAT) + monthly (MI PDF) | API + `pdfplumber` | regione/provincia → NUTS-2/3 |

Each adapter ships with:
- `region_map.csv` — native code → NUTS code (committed, hand-verified)
- `fixtures/` — one captured source file per period type, used by tests
- `category_map.yaml` — native crime category → harmonised category, with a `notes` field per row

### Adapter test contract

`tests/adapters/test_<country>.py` runs each adapter against `fixtures/` and asserts:
- Row count in expected range
- All `region_code` values present in `nuts_regions.parquet`
- All `crime_category` values in the harmonised enum
- `period_end >= period_start`
- No duplicates on `(period_start, region_code, crime_category, suspect_dim, suspect_dim_value)`

A failing test blocks deploy. No exceptions.

---

## 5. Tier 2 — Monthly Claude extraction pipeline

This is the part most likely to drift from spec, so be opinionated.

### Pipeline stages

```
                ┌──────────────────┐
GDELT GKG ─────▶│ fetch (per       │
RSS feeds  ────▶│  country, last   │──▶ raw_articles.jsonl
Police PR  ────▶│  ~40 days)       │
                └──────────────────┘
                         │
                         ▼
                ┌──────────────────┐
                │ filter (lang +   │──▶ candidate_articles.jsonl
                │  keyword regex)  │
                └──────────────────┘
                         │
                         ▼
                ┌──────────────────┐
                │ Claude batch     │
                │ extraction       │──▶ extracted_incidents.jsonl
                │ (Haiku 4.5)      │     (one row per article)
                └──────────────────┘
                         │
                         ▼
                ┌──────────────────┐
                │ dedupe / cluster │──▶ deduped_incidents.jsonl
                └──────────────────┘     (one row per real incident)
                         │
                         ▼
                ┌──────────────────┐
                │ geocode +        │
                │ confidence score │──▶ incidents.parquet (upsert)
                └──────────────────┘
```

### Fetch

- **GDELT 2.0 GKG** is the workhorse. Free, ~15min lag, multilingual, returns articles tagged with themes (`KILL`, `ARREST`, `MURDER`, `ATTACK`) and locations. Query by country + theme + date range.
- **Per-country RSS**: 5–15 outlets per country, hand-picked, focus on regional / mid-market press (where local stabbings actually get covered — national press skips most of them). Stored in `extraction/fetch/feeds_<iso>.yaml`.
- **Police press releases**: Polizei.de presseportal-style feeds per Bundesland (DE), Police.UK news (UK), Polizia di Stato (IT). These give us HIGH-confidence anchors for dedupe.

### Filter (pre-LLM, mandatory)

LLM calls are expensive — filter aggressively first.
- Language detection (`fasttext-langdetect`) — keep only the country's primary language(s).
- Keyword regex per language for "violent bodily-harm" terms (knife/stab, gun/shot, beaten/fatal, kill/murder). Lists curated per language in `extraction/keywords/<lang>.yaml`.
- Negative filters: drop fiction reviews, historical articles (date in headline > 12 months ago), foreign-affairs stories about other countries.

Target: cut raw GDELT volume by ~95% before any LLM touches it. Expected post-filter volume across 7 countries: **300–800 articles/month**.

### Extraction prompt (Claude Haiku 4.5)

Versioned at `extraction/prompts/incident_extraction.md`. Sketch:

```
You are extracting structured incident records from European news articles
about violent crime. Output is STRICT JSON matching the schema below.

For each article, extract one record if and only if the article describes
a specific real-world incident of violent bodily-harm crime (stabbing,
shooting, fatal beating, vehicle-ramming attack). Skip:
- Opinion / editorial / analysis pieces
- Statistics articles
- Articles about prior incidents being revisited (court cases, anniversaries)
- Articles about other countries

Schema: { ... incidents.parquet columns ... }

Rules:
- suspect_description_verbatim MUST be a direct quote from the article.
  If the article does not describe the suspect, set to null.
- suspect_origin_as_reported: ONLY fill if the article EXPLICITLY states
  nationality / country of origin / immigration status. Do NOT infer from
  names. Do NOT infer from physical descriptions.
- weapon: use the most specific category. If the article is ambiguous
  ("attacked with sharp object") use `knife`. If unclear, use `unknown`.
- victim_fatal: count only confirmed dead, not "in critical condition".
- date_incident: if the article says "yesterday" relative to its publish
  date, compute the absolute date. If it says "this week" or similar,
  leave null.
- location_precision: `exact` if a specific address/intersection is given,
  `city` if only a town/city, `region` if only a Land/region.

Output: { "extracted": true | false, "skip_reason": "...", "incident": {...} }
```

Batched 10 articles per call to amortise the prompt overhead. JSON mode on.

### Dedupe

Two-pass:
1. **Hard**: hash `(date_incident, country, city, weapon, victim_fatal)` — exact matches collapse.
2. **Soft**: pairwise cosine similarity on a short embedding of `city + weapon + victim_count + 1-sentence summary`, threshold tuned. Collapses "Stabbing in Mannheim leaves 1 dead" reported by 3 outlets.

Merge rule: take MAX of `victim_fatal`/`victim_count`, take union of `sources_json`, take EARLIEST `date_reported`, prefer police-PR for `suspect_description_verbatim`.

### Confidence

- `HIGH` if any source is a police press release.
- `MEDIUM` if ≥2 independent outlets (different domains).
- `LOW` otherwise.

Map renders HIGH + MEDIUM by default. LOW behind a toggle.

### Token budget (theoretical — not actually spent at MVP)

If we ever flip to API mode: 7 countries × ~500 articles/mo, batched 10/call, ~1.5M input + 150k output tokens → **~$3/month on Haiku 4.5**.

But MVP uses **manual extraction** — see below — so this is just the price of automation when we want it later.

### Manual extraction workflow (MVP, $0)

This is the actual MVP plan. The split:

**Automated, runs in GitHub Actions (free):**
1. `extraction/fetch/` pulls GDELT + RSS + police-press feeds for the last ~40 days.
2. `extraction/filter.py` strips down to candidate articles (lang + keyword regex).
3. Output committed to repo as `extraction/_inbox/candidate_articles_YYYY-MM.jsonl`.
4. A GitHub issue is auto-opened: *"Monthly extraction ready for review — N candidates"*.

**Manual, runs in Claude once a month (the user, ~15 min of attention):**
5. User pulls latest `main`, opens **Claude Code** in the repo (or Claude Desktop pointed at the folder).
6. User runs the saved prompt: *"Read `extraction/_inbox/candidate_articles_YYYY-MM.jsonl`, follow `extraction/prompts/incident_extraction.md`, write `extraction/_outbox/extracted_incidents_YYYY-MM.jsonl`."*
7. Claude processes the batch, writes the file.
8. `extraction/pipeline.py finalize YYYY-MM` is run locally — it dedupes, geocodes, scores confidence, upserts to `data/parquet/incidents.parquet`.
9. User commits + pushes. The site rebuilds.

**Why this works for the MVP:**
- 500 articles fits comfortably in one Claude Code or Desktop session (with batching prompts).
- No unattended billing — extraction only happens when the user opens Claude.
- Same prompt template (`incident_extraction.md`) works for both manual and future API modes — switching to API later is a config flag, not a rewrite.

**Operational guardrails:**
- The user's monthly touch can slip a week without breaking anything — `_inbox/` files accumulate, dedupe handles it.
- If the user misses a month entirely, the next extraction picks up 2 months of candidates. Filter step is idempotent.
- Prompt version is stamped in every extracted record (`extractor_version` column), so we can re-extract if the prompt changes meaningfully.

### Switching to API mode later (one-line flip)

When/if the user wants to automate:
1. Add `ANTHROPIC_API_KEY` secret to GitHub.
2. Set `EXTRACTION_MODE=api` in workflow env.
3. `extraction/pipeline.py` already supports both modes; the manual path becomes a no-op.
4. Expected cost: ~$3/month at Haiku rates. Still under the $5 cap.

---

## 6. NUTS basemap pipeline

One-time setup, refreshed annually when Eurostat publishes new NUTS revisions.

```bash
# scripts/build_tiles.sh
# Pull official NUTS 2021 boundaries, 1:1M scale (smallest)
curl -L -o data/nuts/raw.geojson \
  https://gisco-services.ec.europa.eu/distribution/v2/nuts/geojson/NUTS_RG_01M_2021_4326.geojson

# Simplify per level (NUTS-0 needs less detail at zoom 4 than NUTS-3 at zoom 10)
mapshaper data/nuts/raw.geojson \
  -filter 'LEVL_CODE === 0' -simplify 5% -o data/nuts/level0.geojson \
  -filter 'LEVL_CODE === 1' -simplify 10% -o data/nuts/level1.geojson \
  -filter 'LEVL_CODE === 2' -simplify 20% -o data/nuts/level2.geojson \
  -filter 'LEVL_CODE === 3' -simplify 30% -o data/nuts/level3.geojson

# Stitch into one tileset with per-level minzoom/maxzoom
tippecanoe -o data/tiles/nuts.pmtiles \
  -Z3 -z11 \
  -L'{"file":"data/nuts/level0.geojson","layer":"nuts0","minzoom":3,"maxzoom":5}' \
  -L'{"file":"data/nuts/level1.geojson","layer":"nuts1","minzoom":4,"maxzoom":7}' \
  -L'{"file":"data/nuts/level2.geojson","layer":"nuts2","minzoom":6,"maxzoom":9}' \
  -L'{"file":"data/nuts/level3.geojson","layer":"nuts3","minzoom":8,"maxzoom":11}' \
  --force
```

Output: a single `nuts.pmtiles` (~10–25MB). Served from Cloudflare R2 (free tier 10GB) and read directly by MapLibre via the PMTiles protocol — **no tile server needed**.

---

## 7. Frontend

### Stack
- **Astro 5** — static-first, fast builds, good DX, MDX for methodology pages.
- **MapLibre GL JS** — open-source, vector tiles, PMTiles protocol via `pmtiles` plugin.
- **Observable Plot** — for trend lines, ranking bars, distributions.
- **DuckDB-WASM** — the magic: load `crime_aggregates.parquet` + `incidents.parquet` in the browser, run SQL client-side. Zero backend.
- **TypeScript** throughout the site/ folder.
- **Tailwind** for styling (keeps me from yak-shaving CSS as a solo dev).

### Pages

| Route | Purpose | Data source |
|---|---|---|
| `/` | Europe choropleth, metric selector, time slider | DuckDB-WASM querying aggregates |
| `/country/[iso]` | Country trend, regional ranking, weapon mix, suspect-bg panel | aggregates filtered |
| `/region/[nuts]` | Region detail incl. incident pins where available | aggregates + incidents |
| `/methodology/[iso]` | What this country publishes, what it doesn't, sources, last-fetched timestamps | static MDX + metadata JSON |
| `/methodology` | Project-wide methodology | static MDX |
| `/about` | What this site is and isn't | static MDX |
| `/data` | Download links to Parquet files; brief API docs | static |

### Performance budget

- Initial page JS < 200KB gzipped.
- Parquet files served gzipped from CF; total dataset <30MB at MVP (well within DuckDB-WASM memory).
- LCP < 2.5s on a throttled 4G connection.

### Mobile

- Tap-to-pin, not hover.
- Region drill-down via a slide-up sheet, not a hover tooltip.
- Test on a real mid-range Android before each release.

---

## 8. CI / scheduled runs

All GitHub Actions, all in `.github/workflows/`. Public repo → unlimited minutes.

| Workflow | Schedule | What it does |
|---|---|---|
| `adapter-monthly.yml` | `0 6 5 * *` (5th, 06:00 UTC) | Runs UK + FR adapters. On success: commits updated Parquet, triggers build. |
| `adapter-quarterly.yml` | `0 6 5 1,4,7,10 *` | ES + SE + DK adapters. |
| `adapter-annual.yml` | `0 6 5 5 *` (May) | DE + IT adapters. |
| `extraction-fetch.yml` | `0 8 1 * *` (1st, 08:00 UTC) | Fetch + filter only (no LLM). Commits `extraction/_inbox/candidate_articles_YYYY-MM.jsonl` and opens a GH issue prompting the manual extraction step. |
| `build-site.yml` | on push to `main`, on workflow_run from any adapter | `astro build` + deploy to CF Pages via `wrangler`. |
| `weekly-health-check.yml` | `0 12 * * 1` | Checks each source URL is alive; opens a GH issue if any breaks. |

Each adapter workflow commits the updated `crime_aggregates.parquet` back to `main` via a bot-authored PR (auto-merged if tests pass). This gives us a free audit log via git history.

### Secrets needed in GitHub
- `CLOUDFLARE_API_TOKEN` (for `wrangler pages deploy`)
- `CF_ACCOUNT_ID`
- `ANTHROPIC_API_KEY` *(only if/when switching to API extraction mode — not needed at MVP)*

---

## 9. Hosting plan

### Launch (Phases 1–2)
- **Site**: Cloudflare Pages, free tier (unlimited bandwidth, 500 builds/month).
- **Tiles + Parquet**: Cloudflare R2, free tier (10GB storage, 10M reads/month). Or just bundle in the site if under ~30MB total.
- **Domain**: register `greatstabbing.eu` (or similar) — ~€15/yr at Cloudflare or Namecheap.
- **Email** for source-correction requests: Cloudflare Email Routing (free) → forwards to your gmail.

### Railway (deferred indefinitely)
Per the $5/mo budget, Railway is **not** part of the MVP or Phase 3. Cloudflare Pages free tier carries the entire site. We only revisit if we genuinely need a public API or authenticated features — and even then, Cloudflare Workers (free tier) is the cheaper first stop before Railway.

---

## 10. Build sequence (Phase 1 in detail)

Here's the literal first-three-weeks task list once we start building.

### Week 1 — foundations
1. Repo init, `uv init`, Astro init, pre-commit hooks (ruff, mypy, prettier).
2. Implement `adapters/common/` (base, schema, NUTS, HTTP, validate).
3. Pull NUTS 2021 GeoJSON, run `build_tiles.sh`, commit `nuts.pmtiles`.
4. Build `nuts_regions.parquet` lookup from Eurostat demography tables.
5. Get a "hello world" Astro page rendering a NUTS-0 map of Europe.

### Week 2 — first adapter end-to-end (UK)
6. Implement `adapters/uk/adapter.py` against data.police.uk.
7. Write `tests/adapters/test_uk.py` against committed fixture.
8. Map police-force-area → NUTS via ONS lookup.
9. Set up `adapter-monthly.yml` (UK only for now).
10. Render UK NUTS-2 choropleth on the site, single metric (homicide rate).

### Week 3 — fan out to the remaining 6
11. DE, FR adapters (both well-structured sources).
12. SE, DK adapters (both clean JSON APIs).
13. ES, IT adapters (PDF parsing — hardest, save for last).
14. Per-country `methodology/[iso].astro` pages auto-generated from adapter metadata.

### Weeks 4–7 — flesh out MVP
15. Country pages with trend lines + ranking + weapon mix.
16. Suspect-background panel with the "not published" honest tag where applicable.
17. Time slider, metric selector wired through DuckDB-WASM.
18. Mobile pass, accessibility pass, Lighthouse > 90.
19. Deploy to staging URL on CF Pages.

Public URL at end of Week 7. (Plan section 9 calls this Phase 1 end / Phase 2 start.)

---

## 11. Risks specific to the technical build

| Risk | Mitigation |
|---|---|
| PDF parsing breaks on ES / IT layout changes | `pdfplumber` first; on parse failure, fallback to Claude with the PDF as input; alert on fallback used (it costs more, signals format change). |
| DuckDB-WASM memory limits on large Parquet | Pre-aggregate at build time into `crime_aggregates_summary.parquet` for the Europe overview; full data only loaded on country drill-down. |
| MapLibre + PMTiles edge cases on Safari iOS | Lock to a tested PMTiles version; test on real iPhone before launch (TestFlight not needed — Safari is enough). |
| Claude extraction prompt drift after Haiku version bumps | Pin model ID (`claude-haiku-4-5-20251001`); version the prompt; smoke-test extraction nightly on a fixed 10-article set; alert on output schema diff. |
| GDELT downtime | Fall back to RSS-only; pipeline degrades gracefully, doesn't crash. |
| NUTS revision (every ~3 years) breaks region codes | `region_map.csv` per adapter is the single point of update; covered by tests. |
| Source URL changes silently (e.g. BKA reorganises) | Weekly health-check workflow opens a GH issue; adapter still runs against last archived file. |

---

## 12. Confirmations (resolved)

- **Anthropic API**: not used at MVP. Manual Claude Desktop/Code extraction once a month.
- **Domain**: skipped at launch — use the free `*.pages.dev` Cloudflare subdomain. Add a custom domain later if it ever justifies the ~€10/yr.
- **Repo visibility**: **public** on `github.com/victor-velazquez-ai/great-stabbing` (unlocks free GH Actions minutes + Cloudflare Pages git integration).
