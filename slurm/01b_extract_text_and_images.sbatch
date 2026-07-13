#!/bin/bash
#SBATCH --job-name=pa-extract
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=24:00:00
#SBATCH --output=logs/pa-extract-%j.out
#SBATCH --error=logs/pa-extract-%j.err

set -euo pipefail

PROJECT_DIR="/mnt/scratch/smlnkh/pa_news_multimodal_corpus"
CONFIG="$PROJECT_DIR/config/pa_news.yml"
COLLECTOR="$PROJECT_DIR/src/collect_pa_news.py"

OUTPUT_DIR="$PROJECT_DIR/outputs/pa_news"
URL_MANIFEST="$OUTPUT_DIR/manifests/article_urls.jsonl"
HTML_DIR="$OUTPUT_DIR/data/raw/html"
ARTICLE_FILE="$OUTPUT_DIR/data/processed/articles.jsonl"
IMAGE_FILE="$OUTPUT_DIR/data/processed/images.jsonl"

cd "$PROJECT_DIR"

mkdir -p \
  logs \
  "$OUTPUT_DIR/data/processed" \
  "$OUTPUT_DIR/data/raw/images/objects" \
  "$OUTPUT_DIR/manifests"

source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate mlenv

# The reparse stage may contact the image host.
: "${CRAWLER_CONTACT_EMAIL:?Set CRAWLER_CONTACT_EMAIL before submitting}"

echo "============================================================"
echo "PA text and image extraction"
echo "Started: $(date -u +'%Y-%m-%dT%H:%M:%SZ')"
echo "Host: $(hostname)"
echo "Project: $PROJECT_DIR"
echo "============================================================"

if [[ ! -f "$COLLECTOR" ]]; then
    echo "ERROR: collector not found: $COLLECTOR" >&2
    exit 1
fi

if [[ ! -f "$CONFIG" ]]; then
    echo "ERROR: configuration not found: $CONFIG" >&2
    exit 1
fi

if [[ ! -f "$URL_MANIFEST" ]]; then
    echo "ERROR: URL manifest not found: $URL_MANIFEST" >&2
    exit 1
fi

echo
echo "===== Input status ====="

python - "$URL_MANIFEST" "$HTML_DIR" "$CONFIG" <<'PY'
import json
import sys
from pathlib import Path

import yaml

manifest = Path(sys.argv[1])
html_dir = Path(sys.argv[2])
config_path = Path(sys.argv[3])

urls = set()

with manifest.open(encoding="utf-8") as handle:
    for line in handle:
        if not line.strip():
            continue

        row = json.loads(line)
        url = (
            row.get("url")
            or row.get("final_url")
            or row.get("request_url")
        )

        if url:
            urls.add(url)

config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
minimum_words = config.get("scope", {}).get("minimum_body_words")

print(f"Unique discovered URLs: {len(urls)}")
print(f"Saved HTML files:       {len(list(html_dir.glob('*.html')))}")
print(f"Minimum body words:     {minimum_words}")

if minimum_words not in {0, None}:
    print(
        "WARNING: minimum_body_words is not zero; "
        "short or image-only posts may be rejected."
    )
PY

echo
echo "===== Parsing saved HTML and downloading images ====="
echo

# This stage reads the saved HTML rather than downloading article pages again.
# It extracts text and metadata and retrieves the associated images.
python "$COLLECTOR" reparse \
  --config "$CONFIG"

echo
echo "===== Derived corpus counts ====="

python - "$ARTICLE_FILE" "$IMAGE_FILE" "$HTML_DIR" <<'PY'
import json
import sys
from pathlib import Path

articles_path = Path(sys.argv[1])
images_path = Path(sys.argv[2])
html_dir = Path(sys.argv[3])


def load_jsonl(path):
    if not path.exists():
        return []

    rows = []

    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue

            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise SystemExit(
                    f"Invalid JSON in {path}, line {line_number}: {exc}"
                )

    return rows


articles = load_jsonl(articles_path)
images = load_jsonl(images_path)

article_images = sum(
    len(article.get("images", []))
    for article in articles
)

zero_word = sum(
    article.get("word_count", 0) == 0
    for article in articles
)

short_posts = sum(
    0 < article.get("word_count", 0) < 20
    for article in articles
)

with_images = sum(
    bool(article.get("images"))
    for article in articles
)

with_captions = sum(
    bool(
        image.get("figcaption")
        or image.get("caption")
    )
    for image in images
)

print(f"Saved HTML files:          {len(list(html_dir.glob('*.html')))}")
print(f"Extracted article records: {len(articles)}")
print(f"Total article words:       {sum(a.get('word_count', 0) for a in articles)}")
print(f"Zero-word records:         {zero_word}")
print(f"Posts below 20 words:      {short_posts}")
print(f"Articles with images:      {with_images}")
print(f"Article image references:  {article_images}")
print(f"Image manifest records:    {len(images)}")
print(f"Images with captions:      {with_captions}")
PY

echo
echo "Finished: $(date -u +'%Y-%m-%dT%H:%M:%SZ')"