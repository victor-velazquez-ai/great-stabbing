# Roadmap — what's next, what's missing

Snapshot at commit `ea5ed87` (5/6 MVP countries live).

Items grouped by category, ordered within each group by impact / effort.
Anything marked **★** is "biggest unlock per hour of work."

---

## A · MVP completeness

The original 6-country MVP from [PROJECT_PLAN.md](./PROJECT_PLAN.md).

- [ ] **★ Cloudflare Pages deploy.** Site builds, workflow is wired. Needs
      one user-issued CF API token + two `gh secret set` commands + one
      `gh workflow run`. Doc: [docs/cloudflare-deploy.md](./docs/cloudflare-deploy.md).
- [ ] **🇪🇸 ES live.** Last scaffolded country. Min Interior site is JS-rendered
      (same wall BKA's Standardtabellen has), so the easy paths don't work.
      Options:
      1. Playwright-driven discovery of latest Balance PDF URL (~1 day work).
      2. Manual quarterly PDF drop + pdfplumber parse (~2 hours, already
         scaffolded — just needs the first real PDF).
      3. Eurostat fallback for ES homicide data (limited categories, no FB).
- [ ] **🇩🇪 DE Bundesland breakdown.** Currently DE is NUTS-0 only.
      `T62 / T81 / T82` Standardtabellen exist but live behind the same
      JS-rendered nav. Manual drop into `data/raw/de/<yyyy-mm>/pks-faelle.xlsx`
      lights up the Bundesland choropleth + foreign-background per state.
      Adapter's parse() already handles this layout.
- [ ] **🇮🇹 IT foreign-background dimension.** Live ISTAT data is at
      `73_230_DF_DCCV_AUTVITTPS_6` which has CITIZENSHIP dimension but only
      TOTAL populated. Sibling `..._5` ("Violent crimes, age, citizenship")
      has the breakdown. Need to probe its shape and wire a second source
      file in the IT adapter.
- [ ] **🇬🇧 UK Scotland + Northern Ireland.** ONS PFA tables cover E&W only.
      Police Scotland and PSNI publish separately. Both adapters are
      drafted (region_map.csv has SC+NI rows) but never wired live.
- [ ] **🇸🇪 SE län breakdown.** Currently national-only. BRÅ
      Statistikdatabasen has län-level data via PXweb 2.0 — needs the
      right table ID confirmed.

---

## B · Map / UX

The choropleth works but is static. Steps toward the "real" hoyodecrimen-style
map:

- [ ] **★ Metric selector** (currently fixed to homicide rate / 100k). Dropdown
      with: homicide, assault_serious, robbery_violent, sexual_assault,
      violent_total. Pure client-side switch over the existing data.
- [ ] **★ Foreign-background panel** on country pages — where the source
      publishes it (DE so far, IT/SE/AT later), show `total | national |
      foreign` as a side-by-side comparison with the population denominator
      caveat.
- [ ] **Time slider** for the few countries that have multi-year data
      committed (currently we emit latest-year only; would change in
      adapters + schema).
- [ ] **Per-country drill-down pages** at `/country/[iso]` — regional
      ranking, trend, weapon mix, methodology link. Already in PROJECT_PLAN.
- [ ] **Per-region pages** at `/region/[nuts]` — single-region story.
- [ ] **Color scale**: FR overseas territories (Mayotte, Guyane) push
      colors past the natural break; either clip or use a log/quantile
      scale.
- [ ] **DuckDB-WASM** for client-side queries on the Parquet, replacing
      the build-time JSON files. Unlocks "explore this dataset" UX.
- [ ] **PMTiles** vector tiles via `tippecanoe`. We have GeoJSON
      (`regions.geojson`, 468 KB) — fine at this scale but won't scale to
      30 countries with NUTS-3 polygons.
- [ ] **Mobile pass + accessibility audit** (Lighthouse > 90).
- [ ] **Pin clustering** for high-density Tier 2 areas (none yet — but
      with 100+ pins per month this matters).

---

## C · Tier 2 (news incident pins)

Pipeline works end-to-end ($0 cost). Improvements:

- [ ] **Run June 2026 extraction.** The `extraction/_inbox/candidate_articles_2026-06.jsonl`
      file was already auto-committed by the GH Actions cron. Just needs
      the manual Claude run + finalize.
- [ ] **More feeds** per country — currently 9–10 each. The German
      `presseportal.de` Polizei feed is the highest-leverage; could add
      regional Bundesland-specific feeds.
- [ ] **Better region hints** — extract `region` from article URL or body
      automatically so the geocoder disambiguates without manual tagging.
- [ ] **LOW-confidence toggle** on the map (currently only HIGH/MEDIUM
      render; LOW are written to Parquet but hidden).
- [ ] **API mode** — flip the extraction from manual Claude Code to
      automated Haiku-via-API (~$3/mo, one config flag). Plan documented
      but unused.
- [ ] **Prompt v2** — pull a longer article excerpt (currently 1500 chars)
      and ask Claude to also fill an explicit `region` field for the
      geocoder. Would improve auto-disambiguation.
- [ ] **Review workflow** — `incidents.parquet` has a `review_status`
      column we never set. A simple page that lists LOW-confidence pins
      with an "approve / flag / remove" button would close the loop.

---

## D · Tier 1 enhancements

- [ ] **Knife and firearm specific categories.** UK has them in a separate
      ONS table (knife-crime offences by force). DE has `Schusswaffenverwendung`
      data. FR Interstats has `Vols avec armes`. None are wired into our
      `knife_offence` / `firearm_offence` harmonised categories yet.
- [ ] **Historical time series** per country. Adapters currently emit
      latest-year only; the schema supports multi-year. Flipping the
      "latest only" filter and shipping all years is a small change.
- [ ] **Year-over-year deltas** on country pages (e.g. "+12% vs prior year").
- [ ] **Per-Bundesland populations** in `nuts_regions.parquet`. We have
      country-level (NUTS-0) + IT NUTS-2 + UK NUTS-1 hand-curated; Eurostat
      GeoJSON has none. Pull from `demo_r_pjangrp3` API.

---

## E · Infra / operations

- [ ] **CF Pages deploy** (top of section A).
- [ ] **Custom domain** (`greatstabbing.eu` or similar, ~€10/yr).
- [ ] **Source URL health-check workflow** — currently a stub.
      `scripts/check_sources.py` pings each adapter's known source URL,
      opens a GH issue on first failure per source.
- [ ] **Automated monthly adapter runs** for UK + FR are scheduled
      (`.github/workflows/adapter-monthly.yml`) but never observed in
      action. The fetch cron HAS run (proved by `inbox 2026-06` commit
      `995d664`). Should verify the adapter cron too on the next firing
      date.
- [ ] **CI gating** on tests (currently `ci.yml` runs ruff + pytest, but
      deploy.yml doesn't block on CI failure).

---

## F · Methodology / editorial

- [ ] **Per-country methodology pages** at `/methodology/[iso]` —
      currently a summary card on `/methodology`. Each should explain that
      country's specific source choices, what's published vs withheld,
      coverage caveats.
- [ ] **Public API docs** — `data/parquet/*.parquet` is publicly fetchable
      from the repo; document the schema and a few example DuckDB queries.
- [ ] **Definitional notes** per country on homicide / assault.

---

## G · Project plan items not started

From [PROJECT_PLAN.md](./PROJECT_PLAN.md) Phase 4 onward:

- [ ] **v0.2 countries:** Netherlands, Austria, Belgium, Portugal,
      Switzerland.
- [ ] **v0.3:** rest of EU + Norway + Ireland.
- [ ] **Right-of-reply workflow** for outlets requesting corrections.

---

## H · Code quality / tech debt

- [ ] **Adapter test coverage:** UK + FR + DE have fixture-based tests.
      IT, SE, ES are smoke-only.
- [ ] **mypy enforcement.** `pyproject.toml` configures strict mypy but
      CI doesn't run it. Probably need to clean up a handful of typing
      issues first.
- [ ] **`Pandas4Warning` / `datetime.utcnow` deprecation warnings** in
      the test output. Mechanical sweep.
- [ ] **NUTS-3 populations from Eurostat** to unlock rate_per_100k for
      all FR départements + future NL/BE provincies.

---

## Suggested order — three "good next sessions"

1. **Visibility + completeness** (~1 turn):
   - CF deploy
   - Metric selector on map
   - Run June 2026 extraction

2. **Foreign-background depth** (~1 turn):
   - IT foreign-background sibling dataflow
   - Better methodology page per-country
   - Foreign-background side-panel UI

3. **MVP closing** (~1 turn):
   - ES via manual PDF drop + pdfplumber wiring
   - DE Bundesland manual drop (one annual file)
   - UK Scotland + NI live

After those three, MVP is essentially complete and the work shifts to
Phase 4 (v0.2 countries) and Tier 2 polish.
