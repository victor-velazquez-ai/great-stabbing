# Adding a country

A new country adapter is one folder under `adapters/<iso>/` with:

1. `adapter.py` — implements the `Adapter` ABC from `adapters.common.base`.
2. `region_map.csv` — native region code → NUTS code mapping (hand-verified).
3. `category_map.yaml` — native crime category → harmonised category.
4. `fixtures/` — at least one captured source file per period type, for tests.

## Step-by-step

### 1. Confirm what the country publishes

Before writing code, check:
- Where does the police / statistical authority publish crime data?
- Format: CSV / Excel / JSON API / PDF?
- Cadence: monthly / quarterly / annual?
- Region granularity: NUTS-1 / NUTS-2 / NUTS-3?
- Does it publish a foreign-background dimension? Under what terminology?
- Is the data licensed for redistribution?

Document the answers in the adapter's docstring.

### 2. Build the region map

Find the country's native region codes (e.g. INSEE for France, AGS for Germany).
Use Eurostat correspondence tables to map to NUTS:
- https://ec.europa.eu/eurostat/web/nuts/correspondence-tables

Write `region_map.csv` with `native_code,native_name,nuts_code,notes` columns.
Verify every row by hand against the Eurostat NUTS lookup.

### 3. Implement the adapter

Inherit from `Adapter`:

```python
class XXAdapter(Adapter):
    country = "XX"
    authority = "Source Name"
    cadence = "monthly"  # or "quarterly" / "annual"

    def discover(self) -> list[SourceFile]:
        # Find new official releases. Use adapters.common.http.fetch_to_raw
        # to archive each file under data/raw/.
        ...

    def parse(self, src: SourceFile) -> pd.DataFrame:
        # Read the raw file, return a DataFrame in the source's native shape.
        ...

    def normalise(self, df, src) -> pd.DataFrame:
        # Conform to crime_aggregates schema (see adapters.common.schema).
        # Map native region codes via adapters.common.nuts.load_region_map.
        # Compute rate_per_100k using adapters.common.nuts.population.
        ...
```

### 4. Add fixtures + tests

Capture a representative source file in `fixtures/`. Write a test in
`tests/adapters/test_<iso>.py` that:
- Runs `parse` + `normalise` against the fixture.
- Asserts row count, region coverage, schema validity.
- Asserts no duplicates on the natural key.

### 5. Register in scripts and CI

- Add the adapter to `scripts/run_adapter.py::ADAPTERS`.
- Add it to the relevant `.github/workflows/adapter-*.yml` schedule.
- Add a `methodology/<iso>.astro` page in `site/`.

### 6. Smoke test

```bash
uv run python scripts/run_adapter.py XX
uv run pytest tests/adapters/test_xx.py
```

Then open a PR.
