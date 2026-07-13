#!/bin/bash
#SBATCH --job-name=pa-extract-img
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=24:00:00
#SBATCH --output=logs/pa-extract-img-%j.out
#SBATCH --error=logs/pa-extract-img-%j.err

set -euo pipefail

PROJECT_DIR="/mnt/scratch/smlnkh/pa_news_multimodal_corpus"
COLLECTOR="$PROJECT_DIR/src/collect_pa_news.py"
CONFIG="$PROJECT_DIR/config/pa_news.yml"
OUTPUT_DIR="$PROJECT_DIR/outputs/pa_news"
HTML_DIR="$OUTPUT_DIR/data/raw/html"
PROCESSED_DIR="$OUTPUT_DIR/data/processed"
MANIFEST_DIR="$OUTPUT_DIR/manifests"
IMAGE_DIR="$OUTPUT_DIR/data/raw/images/objects"

cd "$PROJECT_DIR"
mkdir -p logs "$PROCESSED_DIR" "$MANIFEST_DIR" "$IMAGE_DIR"

source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate mlenv

: "${CRAWLER_CONTACT_EMAIL:?Set CRAWLER_CONTACT_EMAIL before submitting}"

printf '===== PA extraction and image recovery =====\n'
printf 'Started: %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
printf 'Host: %s\n' "$(hostname)"
printf 'Saved HTML: '
find "$HTML_DIR" -type f -name '*.html' | wc -l

if ! grep -q 'allow_explicit_asset_fetch_when_robots_unavailable' "$CONFIG"; then
  echo "ERROR: config lacks allow_explicit_asset_fetch_when_robots_unavailable" >&2
  exit 2
fi

if ! grep -q 'allow_asset_if_unavailable' "$COLLECTOR"; then
  echo "ERROR: collector lacks the explicit-asset robots fix" >&2
  exit 2
fi

# Rebuild the derived layer consistently. Raw HTML and existing image objects are retained.
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="$OUTPUT_DIR/backups/$STAMP"
mkdir -p "$BACKUP"

for FILE in \
  "$PROCESSED_DIR/articles.jsonl" \
  "$PROCESSED_DIR/images.jsonl" \
  "$MANIFEST_DIR/skipped_images.jsonl" \
  "$MANIFEST_DIR/run_summary.json"
do
  if [[ -f "$FILE" ]]; then
    mv "$FILE" "$BACKUP/"
  fi
done

echo "Previous derived files moved to: $BACKUP"

echo "===== Parsing saved HTML and downloading referenced images ====="
python "$COLLECTOR" \
  --config "$CONFIG" \
  reparse

echo "===== Result counts ====="
python - "$PROCESSED_DIR/articles.jsonl" "$PROCESSED_DIR/images.jsonl" "$MANIFEST_DIR/skipped_images.jsonl" "$IMAGE_DIR" <<'PY'
import json
import sys
from pathlib import Path

articles_path, images_path, skipped_path, image_dir = map(Path, sys.argv[1:])

def load_jsonl(path):
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as handle:
        for n, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise SystemExit(f"Invalid JSON at {path}:{n}: {exc}")
    return rows

articles = load_jsonl(articles_path)
images = load_jsonl(images_path)
skipped = load_jsonl(skipped_path)

print(f"Articles written:          {len(articles)}")
print(f"Total words:               {sum(a.get('word_count', 0) for a in articles)}")
print(f"Articles with images:      {sum(bool(a.get('images')) for a in articles)}")
print(f"Image metadata records:    {len(images)}")
print(f"Hero images:               {sum(i.get('image_role') == 'hero' for i in images)}")
print(f"Inline images:             {sum(i.get('image_role') == 'inline' for i in images)}")
print(f"Images with captions:      {sum(bool(i.get('figcaption')) for i in images)}")
print(f"Skipped image records:     {len(skipped)}")
print(f"Downloaded image objects:  {sum(p.is_file() for p in image_dir.rglob('*'))}")

reasons = {}
for row in skipped:
    reasons[row.get('reason', 'UNKNOWN')] = reasons.get(row.get('reason', 'UNKNOWN'), 0) + 1
if reasons:
    print("Skipped reasons:")
    for reason, count in sorted(reasons.items(), key=lambda item: (-item[1], item[0])):
        print(f"  {reason}: {count}")
PY

printf 'Finished: %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
