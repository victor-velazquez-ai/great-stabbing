# Roadmap — what's next, what's still missing

Snapshot at commit `464e4cb`.

## Where we are now

**6/6 MVP countries LIVE**, including Germany at both NUTS-0 and NUTS-1
levels, Italy at both NUTS-0 (with foreign-background) and NUTS-2, and
Spain at NUTS-3 (last MVP country). The map shows 211 polygons across
Europe with a metric selector, news-pin overlay, and per-country /
per-region drill-down pages.

| Country | Granularity | Foreign-bg |
|---|---|---|
| 🇬🇧 UK | NUTS-1 (10 regions, England & Wales) | — |
| 🇫🇷 FR | NUTS-3 (101 départements) | — |
| 🇮🇹 IT | NUTS-2 (21 regions) + NUTS-0 with FB | yes (national) |
| 🇩🇪 DE | NUTS-1 (16 Bundesländer) + NUTS-0 with FB | yes (national) |
| 🇸🇪 SE | NUTS-0 (national only) | — |
| 🇪🇸 ES | NUTS-3 (52 provincias) | partial (sibling wired) |

## Still missing for "production"

### A · Coverage gaps (live data exists, not yet wired)
- [ ] **🇩🇪 DE Bundesland foreign-background.** LA-F-01-T01 gives cases per
      Land. LA-TV-01 (total TV by Land) + LA-TV-04 (German) + LA-TV-05
      (non-German) would unlock per-Land foreign-suspect share. Discovery
      agent confirmed URLs; download + wire is one session.
- [ ] **🇮🇹 IT foreign-background at regional level.** Sibling SDMX dataflow
      AUTVITTPS_5 is national-only. Per-region citizenship breakdown is
      not published by ISTAT in this dataflow — likely a structural gap.
- [ ] **🇬🇧 UK Scotland live.** gov.scot Recorded Crime XLSX confirmed by
      discovery agent. URL embeds year segment; needs annual scrape.
      Adds Police Scotland = NUTS-1 UKM + 32 Local Authority sub-rows.
- [ ] **🇬🇧 UK Northern Ireland live.** PSNI Police Recorded Crime Tables
      XLSX confirmed. URL token changes per release; needs landing-page
      scrape. Adds UKN at NUTS-1 + 11 Policing District sub-rows.
- [ ] **🇪🇸 ES foreign-background.** SEC tables 03006/03008 carry the
      Española/Extranjera dimension. ROADMAP-tracked.
- [ ] **🇸🇪 SE län-level.** BRÅ Statistikdatabasen PXweb 2.0 — table ID
      still not located. Workflow agent timed out.

### B · UX still missing for "looks complete"
- [ ] **Time slider** for the few countries with multi-year data committed
      (UK has rolling, FR has 2016-2025, IT has 2007-2024). Adapters
      currently emit latest-year only.
- [ ] **DuckDB-WASM** for client-side interactive queries on the Parquet.
- [ ] **PMTiles** via `tippecanoe` — current GeoJSON is 664 KB, fine, but
      won't scale to 30 countries with NUTS-3 polygons.
- [ ] **Mobile pass + accessibility audit** (Lighthouse > 90).
- [ ] **Pin clustering** for high-density Tier 2 areas.

### C · Tier 2 (news pins)
- [x] May 2026 batch live (8 pins).
- [x] June 2026 batch live (added 3 new events).
- [ ] **Run July 2026 onward.** Cron will produce the inbox; one Claude
      session per month to extract.
- [ ] **API mode** — flip extraction from manual Claude Code to
      automated Haiku-via-API (~$3/mo, one config flag).
- [ ] **LOW-confidence toggle** on the map.
- [ ] **Better region hints** — automatic extraction of region from
      article URL or body.

### D · Tier 1 enhancements
- [ ] **Knife- and firearm-specific categories.** UK has them in a
      separate ONS table; DE has Schusswaffenverwendung; FR has Vols
      avec armes. None wired into `knife_offence` / `firearm_offence`
      harmonised categories yet.
- [ ] **Historical time series** per country — flip the latest-year
      filter and ship multi-year.
- [ ] **Year-over-year deltas** on country pages.
- [ ] **NUTS-3 populations from Eurostat** — unlock rate_per_100k for
      all FR départements + future NL/BE provincies.

### E · Infra / operations
- [ ] **★ Cloudflare Pages deploy.** Site builds (212 pages), workflow
      wired. Needs one CF API token + two `gh secret set` + one
      `gh workflow run`. Doc: [docs/cloudflare-deploy.md](./docs/cloudflare-deploy.md).
- [ ] **Custom domain** (`greatstabbing.eu` or similar, ~€10/yr).
- [x] **Source URL health-check workflow** — implemented; opens GH issue
      on 4xx/5xx.

### F · Methodology / editorial
- [x] Per-country methodology cards (on `/methodology`).
- [ ] Per-country dedicated `/methodology/[iso]` pages — only needed
      when a country has unusual disclosures (DE Nichtdeutsche, ES SEC
      caveats, IT NUTS-2013 codes).
- [ ] **Public API docs** — `data/parquet/*.parquet` is fetchable from
      the repo; document the schema and example DuckDB queries.

### G · Code quality / tech debt
- [ ] **Adapter test coverage.** UK + FR + DE have fixture-based tests.
      IT, SE, ES are smoke-only — add fixture tests.
- [ ] **mypy enforcement** in CI.
- [ ] **`Pandas4Warning` / `datetime.utcnow()` deprecation sweep.**

### H · Project plan Phase 4+
- [ ] **v0.2 countries:** Netherlands, Austria, Belgium, Portugal,
      Switzerland.
- [ ] **v0.3:** rest of EU + Norway + Ireland.

## What feels finished

- All 6 MVP countries live with real data and visible on the map.
- Foreign-background dimension visible for the two countries that
  publish it (DE 43% non-German for violent total, IT 25.6% for
  homicide).
- Per-country and per-region drill-down pages.
- Metric selector on the map.
- Tier 2 news pipeline closed end-to-end, two months of pins committed.
- $0/month cost, 31 tests passing.

**The biggest single thing keeping nothing from being public is the CF
deploy.** Once that lands, the project crosses from "private repo
artifact" to "public website".
