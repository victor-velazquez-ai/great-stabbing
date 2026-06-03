# The Great Stabbing

> Europe-wide, interactive map and dashboard of violent crime — stabbings, shootings, fatal beatings — with regional granularity. Inspired by [hoyodecrimen.com](https://hoyodecrimen.com).

**Status:** 6/6 MVP countries live. ES at NUTS-3 (last in), DE at NUTS-1 (16 Bundesländer) + NUTS-0 with foreign-background, IT with foreign-background at NUTS-0. Public URL pending CF Pages token.

See [PROJECT_PLAN.md](./PROJECT_PLAN.md) for the product plan and [TECHNICAL_PLAN.md](./TECHNICAL_PLAN.md) for the build plan.

---

## What this is (and what it is not)

**It is:**
- A federation of per-country adapters that pull violent-crime statistics from each country's official statistical / police authority.
- A monthly news-incident layer extracted from European news media.
- A static map + dashboards rendered from canonical Parquet datasets.
- Methodologically strict: every figure cites its official source; gaps are shown as gaps, never imputed.

**It is not:**
- A breaking-news site.
- A clearinghouse for guesses, opinion, or rumor.
- A vehicle for editorial commentary on the data.

---

## Repo layout

```
adapters/          # per-country Tier 1 data pulls
  common/          # shared schema, NUTS lookup, HTTP cache, validators
  uk/ de/ fr/ ...  # one folder per country with adapter.py + region_map.csv
extraction/        # Tier 2 monthly news → incidents pipeline
  prompts/         # versioned LLM extraction prompt
  keywords/        # per-language keyword filters
data/
  raw/             # archived source files (gitignored)
  parquet/         # canonical outputs (COMMITTED)
  nuts/            # Eurostat NUTS GeoJSON
  tiles/           # PMTiles for the map
site/              # Astro frontend
scripts/           # operational entry points
tests/             # adapter fixture tests
.github/workflows/ # scheduled CI runs
```

---

## Costs

Target: **≤ $5/month**. At MVP we run on free tiers across the board:

| Item | Cost |
|---|---|
| Cloudflare Pages (hosting) | $0 |
| Cloudflare R2 (10GB tile/data storage) | $0 |
| GitHub Actions (public repo) | $0 |
| Domain | optional (~€10/yr if added) |
| LLM extraction | $0 — **manual monthly run on existing Claude subscription** |

The Anthropic API path exists in code as a one-flag switch (~$3/mo on Haiku 4.5) for when we want hands-off automation. Not used at MVP.

---

## Setup

Prerequisites: Python 3.12+, [uv](https://github.com/astral-sh/uv), Node 20+, git.

```bash
git clone https://github.com/victor-velazquez-ai/great-stabbing.git
cd great-stabbing
uv sync                    # install Python deps
cd site && npm install     # install site deps (when site is initialised)
```

For tile rebuilds (optional, only needed if NUTS GeoJSON changes):
```bash
npm install -g mapshaper
# tippecanoe: https://github.com/felt/tippecanoe (no Windows binaries — use WSL or CI)
./scripts/build_tiles.sh
```

---

## Running adapters

```bash
# One country
uv run python scripts/run_adapter.py UK

# Multiple
uv run python scripts/run_adapter.py UK FR DE

# All seven
uv run python scripts/run_all.py
```

Each adapter writes to `data/parquet/crime_aggregates.parquet` (idempotent upsert).

**Status:**

| Country | Authority | Status | Latest data |
|---|---|---|---|
| 🇬🇧 UK | ONS PFA tables | **live** | year ending December 2025 |
| 🇫🇷 FR | SSMSI Interstats | **live** | year 2025 |
| 🇩🇪 DE | BKA PKS Zeitreihen + Land-XLSX | **live** | year 2024, NUTS-0 + NUTS-1 |
| 🇮🇹 IT | ISTAT (dataflows AUTVITTPS_6 + _5 for FB) | **live** | year 2024, NUTS-2 + NUTS-0 |
| 🇸🇪 SE | BRÅ Anmälda brott (national XLSX) | **live** | year 2025, NUTS-0 |
| 🇪🇸 ES | Min. Interior SEC (table 03002) | **live** | year 2024, NUTS-3 (52 provincias) |

---

## Monthly extraction workflow (manual, MVP)

Once a month:

1. GitHub Actions runs `extraction/pipeline.py fetch YYYY-MM` and commits `extraction/_inbox/candidate_articles_YYYY-MM.jsonl`. Auto-opens a GH issue: *"Monthly extraction ready."*
2. You pull `main`, open this folder in **Claude Desktop** or **Claude Code**.
3. You point Claude at [`extraction/prompts/incident_extraction.md`](./extraction/prompts/incident_extraction.md) and the inbox file. Claude writes `extraction/_outbox/extracted_incidents_YYYY-MM.jsonl`.
4. You run `uv run python -m extraction.pipeline finalize YYYY-MM` — dedupes, geocodes, scores confidence, upserts to `data/parquet/incidents.parquet`.
5. Commit and push. Site rebuilds.

If a month is skipped, the next run picks up two months of candidates. No data is lost — the inbox accumulates and dedupe handles overlap.

---

## Methodology, ethics, transparency

- **Foreign-background variable**: shown only where the official source publishes it (Germany BKA, Denmark Statbank, Austria BMI, sometimes Sweden BRÅ). Never imputed, never inferred. Each country's exact terminology and definition is linked on the methodology page.
- **News pins**: never aggregated into rates. They are illustrative, not statistical. Aggregate counts come from Tier 1 only.
- **No PII**: victims and suspects are never identified by name on the map, even if the news source names them.
- **Source-quote display**: suspect descriptions on news pins are verbatim quotes, linked to the source article.
- **Right of reply**: outlets can request corrections via the issue tracker.

See [`docs/methodology.md`](./docs/methodology.md) for the full statement.

---

## Contributing

Solo build at the moment. Issues welcome (data corrections especially). PRs for new country adapters: see [`docs/adding-a-country.md`](./docs/adding-a-country.md).

---

## License

Code: MIT. Each data source retains its own license — see per-row `source_url` in the Parquet files and the methodology pages.
