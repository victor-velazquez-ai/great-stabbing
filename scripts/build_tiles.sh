#!/usr/bin/env bash
# Build data/tiles/nuts.pmtiles from Eurostat NUTS 2021 GeoJSON.
#
# Requires:
#   - mapshaper  (npm install -g mapshaper)
#   - tippecanoe (https://github.com/felt/tippecanoe)
#
# Output is committed to the repo (small) and served from Cloudflare Pages.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NUTS_DIR="$ROOT/data/nuts"
TILES_DIR="$ROOT/data/tiles"
mkdir -p "$TILES_DIR"

GEOJSON_URL="https://gisco-services.ec.europa.eu/distribution/v2/nuts/geojson/NUTS_RG_01M_2021_4326.geojson"
RAW="$NUTS_DIR/NUTS_RG_01M_2021_4326.geojson"

if [ ! -f "$RAW" ]; then
  echo "fetching $GEOJSON_URL"
  mkdir -p "$NUTS_DIR"
  curl -L --fail -o "$RAW" "$GEOJSON_URL"
fi

# Split + simplify per level.
mapshaper "$RAW" \
  -filter 'LEVL_CODE === 0' -simplify 5%  -o "$NUTS_DIR/level0.geojson" force
mapshaper "$RAW" \
  -filter 'LEVL_CODE === 1' -simplify 10% -o "$NUTS_DIR/level1.geojson" force
mapshaper "$RAW" \
  -filter 'LEVL_CODE === 2' -simplify 20% -o "$NUTS_DIR/level2.geojson" force
mapshaper "$RAW" \
  -filter 'LEVL_CODE === 3' -simplify 30% -o "$NUTS_DIR/level3.geojson" force

# Stitch into one PMTiles archive with per-level zoom ranges.
tippecanoe \
  -o "$TILES_DIR/nuts.pmtiles" \
  -Z3 -z11 --force \
  -L"$(printf '{"file":"%s","layer":"nuts0","minzoom":3,"maxzoom":5}' "$NUTS_DIR/level0.geojson")" \
  -L"$(printf '{"file":"%s","layer":"nuts1","minzoom":4,"maxzoom":7}' "$NUTS_DIR/level1.geojson")" \
  -L"$(printf '{"file":"%s","layer":"nuts2","minzoom":6,"maxzoom":9}' "$NUTS_DIR/level2.geojson")" \
  -L"$(printf '{"file":"%s","layer":"nuts3","minzoom":8,"maxzoom":11}' "$NUTS_DIR/level3.geojson")"

echo "wrote $TILES_DIR/nuts.pmtiles"
ls -lh "$TILES_DIR/nuts.pmtiles"
