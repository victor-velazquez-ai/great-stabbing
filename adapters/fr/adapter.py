"""France adapter — SSMSI *Interstats* départemental annual CSV.

**Source:** SSMSI (Service statistique ministériel de la sécurité intérieure),
published on data.gouv.fr as *Bases statistiques communale, départementale et
régionale de la délinquance enregistrée par la police et la gendarmerie
nationales*. The départemental CSV is updated annually with rolling
historical data back to 2016.

**Stable URL:** ``https://www.data.gouv.fr/api/1/datasets/r/<resource-id>``
where the resource ID (``2b27a675-e3bf-41ef-a852-5fb9ab483967``) redirects to
the most recent version. This makes ``discover()`` trivial.

**Foreign-background published?** No. All rows are ``suspect_dim="total"``.

**Cadence:** annual (rolling history); we emit ``period_type="year"``.

**CSV schema (semicolon-delimited, French decimals with comma):**
::
    Code_departement;Code_region;annee;indicateur;unite_de_compte;nombre;
    taux_pour_mille;insee_pop;insee_pop_millesime;insee_log;insee_log_millesime

We use:
- ``unite_de_compte == 'Victime'`` (per-victim count, matches our schema)
- ``Code_departement`` mapped to NUTS-3 via region_map.csv
- ``insee_pop`` as the denominator
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import pandas as pd
import yaml

from adapters.common.base import Adapter, SourceFile
from adapters.common.http import fetch_to_raw
from adapters.common.nuts import load_region_map, population

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
FR_DIR = REPO_ROOT / "adapters" / "fr"

# data.gouv.fr resource ID — stable across new versions of the file.
DEP_CSV_RESOURCE_ID = "2b27a675-e3bf-41ef-a852-5fb9ab483967"
DEP_CSV_URL = f"https://www.data.gouv.fr/api/1/datasets/r/{DEP_CSV_RESOURCE_ID}"


class FRAdapter(Adapter):
    country = "FR"
    authority = "SSMSI"
    cadence = "annual"  # CSV is updated annually; rolling history since 2016

    def discover(self) -> list[SourceFile]:
        log.info("[FR] fetching %s", DEP_CSV_URL)
        try:
            src = fetch_to_raw(DEP_CSV_URL, country="fr", filename="interstats-dep.csv")
        except Exception as e:  # noqa: BLE001 — manual fallback documented in error
            log.error(
                "[FR] failed to fetch Interstats DEP CSV (%s: %s). "
                "Manual fallback: download from "
                "https://www.data.gouv.fr/datasets/bases-statistiques-communale-"
                "departementale-et-regionale-de-la-delinquance-enregistree-par-la-"
                "police-et-la-gendarmerie-nationales/ "
                "and place under data/raw/fr/<yyyy-mm>/interstats-dep.csv",
                type(e).__name__, e,
            )
            return []
        log.info("[FR] discovered %s (%s)", src.local_path, src.sha256[:12])
        return [src]

    def parse(self, src: SourceFile) -> pd.DataFrame:
        path = REPO_ROOT / src.local_path
        log.info("[FR] parsing %s", path.relative_to(REPO_ROOT))

        df = pd.read_csv(
            path,
            sep=";",
            dtype={
                "Code_departement": str,
                "Code_region": str,
                "annee": str,
                "indicateur": str,
                "unite_de_compte": str,
            },
            encoding="utf-8-sig",  # BOM-prefixed
            decimal=",",
        )
        # Keep only "Victime" units (per-victim count). For homicide categories
        # this disambiguates incidents (Faits) from victims (Victimes).
        if "unite_de_compte" in df.columns:
            df = df[df["unite_de_compte"] == "Victime"].copy()

        df["annee"] = df["annee"].astype(int)
        # Coerce numeric columns explicitly — `nombre` is read as string due
        # to our column dtypes, but downstream groupby.sum() would concatenate
        # rather than add unless we cast here.
        df["nombre"] = pd.to_numeric(df["nombre"], errors="coerce").fillna(0).astype(int)
        df["insee_pop"] = pd.to_numeric(df["insee_pop"], errors="coerce")

        log.info("[FR] parsed %d rows (%d years, %d départements, %d indicators)",
                 len(df), df["annee"].nunique(),
                 df["Code_departement"].nunique(), df["indicateur"].nunique())
        return df.reset_index(drop=True)

    def normalise(self, df: pd.DataFrame, src: SourceFile) -> pd.DataFrame:
        cat_map_path = FR_DIR / "category_map.yaml"
        with cat_map_path.open(encoding="utf-8") as f:
            cat = yaml.safe_load(f) or {}
        mapping: dict[str, str] = cat.get("mapping", {}) or {}

        dep_to_nuts = load_region_map("FR")
        if not dep_to_nuts:
            raise RuntimeError("FR region_map.csv is empty")

        df = df.copy()
        df["category"] = df["indicateur"].map(mapping)
        df = df.dropna(subset=["category"])
        df["nuts"] = df["Code_departement"].map(dep_to_nuts)
        df = df.dropna(subset=["nuts"])

        # Use the latest available year unless we want full historical.
        # For MVP we emit the LATEST year only — the homepage shows current
        # snapshot. Historical years can be flipped on later by removing this
        # filter (the schema is year-indexed so older years won't collide).
        latest_year = int(df["annee"].max())
        df = df[df["annee"] == latest_year]

        agg = (
            df.groupby(["nuts", "category", "annee"], as_index=False)
            .agg(
                count=("nombre", "sum"),
                pop=("insee_pop", "max"),
                native_examples=("indicateur", lambda s: ", ".join(sorted(set(s))[:3])),
            )
        )

        retrieved_at = pd.Timestamp.now(tz="UTC").tz_localize(None)
        rows = []
        for _, r in agg.iterrows():
            nuts = str(r["nuts"])
            ons_pop = population(nuts)  # Eurostat denominator
            insee_pop = int(r["pop"]) if not pd.isna(r["pop"]) else None
            denom = ons_pop or insee_pop
            denom_source = "Eurostat NUTS 2021" if ons_pop else "INSEE recensement"
            count = int(r["count"])
            rate = (count / denom * 100_000) if denom else None
            year = int(r["annee"])
            rows.append(
                {
                    "source_country": "FR",
                    "source_authority": self.authority,
                    "source_url": DEP_CSV_URL,
                    "source_file_hash": src.sha256,
                    "retrieved_at": retrieved_at,
                    "period_start": pd.Timestamp(date(year, 1, 1)),
                    "period_end": pd.Timestamp(date(year, 12, 31)),
                    "period_type": "year",
                    "region_code": nuts,
                    "region_level": 3,
                    "crime_category": str(r["category"]),
                    "crime_category_native": str(r["native_examples"]),
                    "suspect_dim": "total",
                    "suspect_dim_value": None,
                    "count": count,
                    "denominator_population": denom,
                    "denominator_source": denom_source if denom else None,
                    "rate_per_100k": rate,
                    "notes": "SSMSI Interstats does not publish a foreign-background dimension.",
                }
            )

        out = pd.DataFrame(rows)
        if not out.empty:
            out["count"] = out["count"].astype(int)
            out["region_level"] = out["region_level"].astype(int)
            out["denominator_population"] = out["denominator_population"].astype("Int64")

        log.info("[FR] normalised %d rows across %d départements (year %d)",
                 len(out), out["region_code"].nunique() if not out.empty else 0,
                 latest_year)
        return out
