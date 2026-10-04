#!/usr/bin/env bash
# Smoke-test: run the station briefly and confirm preview output grows.
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate

rm -f data/preview/broadcast.ts
timeout 45 tiny-station run --no-web || true

if [[ ! -f data/preview/broadcast.ts ]]; then
  echo "FAIL: no preview output"
  exit 1
fi

size=$(wc -c < data/preview/broadcast.ts)
echo "Preview size: $size bytes"
if [[ "$size" -lt 50000 ]]; then
  echo "FAIL: preview too small"
  exit 1
fi

# Confirm it is readable MPEG-TS
ffprobe -v error -show_entries format=format_name -of csv=p=0 data/preview/broadcast.ts | grep -qi mpegts
echo "OK: continuous broadcast produced readable MPEG-TS"
