# Cloudflare Pages — deployment runbook

The MVP target is **zero hosting cost**: Cloudflare Pages free tier with site rebuilds driven by GitHub Actions.

There are two viable paths. Below we recommend the **GitHub Actions deploy** path because we've already hit friction with CF's dashboard build pipeline (the new unified Workers+Pages UI tends to default Pages projects into a Workers-style flow that needs wrangler config we don't want to maintain in the dashboard).

---

## Status when you pick this up

A previous attempt configured CF's dashboard build pipeline. It failed for two reasons in sequence:

1. The default deploy command was `npx wrangler deploy` (Workers form, not Pages). Changed to `npx wrangler pages deploy site/dist`.
2. Then `--project-name=great-stabbing` was missing. Added.
3. Then the CF-injected auto-token returned `Authentication error [code: 10000]` against `/accounts/.../pages/projects/great-stabbing` — the project was actually created as a Workers-style project, so the Pages API endpoint rejected the auto-token.

Rather than debugging the dashboard further, **the plan is to disconnect CF's auto-deploy and run the deploy from GitHub Actions** — using the `deploy.yml` workflow already in `.github/workflows/`.

The CF account ID has been captured: `f5fafde3903369e8152e2fb98da326f8`.

---

## Plan — three steps

### Step 1 — Delete the broken Pages project

In Cloudflare dashboard:
1. **Workers & Pages → great-stabbing → Settings** (top-right tabs of the project page).
2. Scroll to the bottom → **Delete project** → confirm by typing the project name.

> Alternative if you don't want to delete: **Settings → Builds & deployments → Production branch** → change to a non-existent branch like `disabled-do-not-deploy`. Stops auto-builds without losing the project. Deleting is cleaner.

### Step 2 — Create a CF API token

In Cloudflare:
1. Top-right → click your email → **Profile**.
2. Left sidebar → **API Tokens** → **Create Token**.
3. Scroll to **Custom token** → **Get started**.
4. Fill in:
   - **Token name**: `great-stabbing-deploy`
   - **Permissions**:
     - `Account` → `Cloudflare Pages` → `Edit`
     - `User` → `User Details` → `Read` *(used by `wrangler whoami`; optional but recommended)*
   - **Account Resources**: `Include` → `Rotciveb@gmail.com's Account`
   - **TTL**: leave default (no expiration) unless you want one.
5. **Continue to summary** → **Create Token** → **copy the token immediately** (shown only once).

### Step 3 — Add GitHub secrets and trigger deploy

From the repo root (`C:\Users\rotci\Documents\AI\great-stabbing`):

```bash
# Will prompt for the token value — paste it
gh secret set CLOUDFLARE_API_TOKEN -R victor-velazquez-ai/great-stabbing

# Account ID is already known
gh secret set CF_ACCOUNT_ID -b "f5fafde3903369e8152e2fb98da326f8" -R victor-velazquez-ai/great-stabbing

# Trigger the deploy workflow manually for the first run
gh workflow run deploy.yml -R victor-velazquez-ai/great-stabbing

# Watch progress
gh run watch -R victor-velazquez-ai/great-stabbing
```

The `wrangler pages deploy` command in `deploy.yml` will **auto-create the Pages project** named `great-stabbing` on its first successful run, so you don't need to pre-create anything in the CF dashboard.

After it succeeds, the URL appears in the workflow logs (and in the Pages dashboard) as `https://great-stabbing.pages.dev`.

---

## Alternative — keep using CF's dashboard build pipeline

If you ever want to go back to CF-managed builds:

1. Re-create the Pages project, **but** explicitly via the "Pages" creation path (not "Workers" or "Create application").
2. The `wrangler.toml` at the repo root now declares the project name + output dir, so the deploy command can stay simple: `npx wrangler pages deploy site/dist`.
3. Build command stays the data-copy + Astro build:
   ```
   mkdir -p site/public/data site/public/tiles && \
     (cp -r data/parquet/. site/public/data/ 2>/dev/null || true) && \
     (cp -r data/tiles/. site/public/tiles/ 2>/dev/null || true) && \
     cd site && npm ci && npm run build
   ```
4. Build output directory: `site/dist`.
5. Add the same two env vars to the project: `CLOUDFLARE_API_TOKEN`, `CF_ACCOUNT_ID` — needed because the auto-token from CF's build env doesn't have permissions on Pages projects it didn't create.

---

## Verifying the deployment

Once the workflow succeeds, the site should be live at `https://great-stabbing.pages.dev`.

Verify:
- Homepage renders with the placeholder map.
- `/about`, `/methodology`, `/data` all return 200.
- Browser dev tools network tab shows static HTML/CSS/JS only — no API calls.

If the map tile doesn't load, that's expected at this stage — the tile layer is a placeholder OpenStreetMap raster; the NUTS PMTiles aren't built yet (requires tippecanoe + mapshaper in CI).

---

## Cost expectations

- CF Pages: free (unlimited bandwidth, 500 builds/month — we'll use ~5).
- CF R2 (if we host PMTiles there later): free 10GB.
- GitHub Actions: free (unlimited minutes on a public repo).
- Domain: optional, not added at MVP.

**Total: $0/month.**

---

## Why the CF dashboard route was abandoned

For the record, in case you ever look at this again wondering "why aren't we using CF's git integration":

1. CF's new unified Workers+Pages UI confusingly defaults Pages projects into a Workers-style flow with a `Deploy command` field pre-filled with `npx wrangler deploy` (Workers command).
2. Even after correcting the deploy command and the project-name flag, the auto-injected token returned auth errors against the Pages API. This is a known issue when projects are created via the unified flow — the token's scope mismatches the project type.
3. Debugging this would require deleting and recreating the project through a specific UI path, with no guarantee CF won't change the default again.

GitHub Actions deploy with an explicit user-issued token sidesteps all of this. The token's permissions are visible and rotatable, the workflow is in source control, and CF's dashboard friction stops mattering.
