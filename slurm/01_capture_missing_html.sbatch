#!/bin/bash
#SBATCH --job-name=pa-html
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=12:00:00
#SBATCH --output=logs/pa-html-%j.out
#SBATCH --error=logs/pa-html-%j.err

set -euo pipefail

PROJECT_DIR="/mnt/scratch/smlnkh/pa_news_multimodal_corpus"
OUTPUT_DIR="$PROJECT_DIR/outputs/pa_news"
URL_MANIFEST="$OUTPUT_DIR/manifests/article_urls.jsonl"
HTML_DIR="$OUTPUT_DIR/data/raw/html"
COLLECTOR="$PROJECT_DIR/src/collect_pa_news.py"
CONFIG="$PROJECT_DIR/config/pa_news.yml"

cd "$PROJECT_DIR"

mkdir -p \
  logs \
  "$HTML_DIR" \
  "$OUTPUT_DIR/manifests"

# Activate Conda inside the Slurm shell.
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate mlenv

# Require a transparent institutional contact address.
: "${CRAWLER_CONTACT_EMAIL:?Set CRAWLER_CONTACT_EMAIL before submitting}"

echo "============================================================"
echo "PA HTML-only capture"
echo "Started: $(date -u +'%Y-%m-%dT%H:%M:%SZ')"
echo "Host: $(hostname)"
echo "Project: $PROJECT_DIR"
echo "============================================================"

# Check required files.
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
    echo "Run the discovery stage first." >&2
    exit 1
fi

# Important version check.
HELP_OUTPUT="$(python "$COLLECTOR" --help 2>&1)"

if ! grep -q "capture" <<< "$HELP_OUTPUT"; then
    echo "ERROR: src/collect_pa_news.py is still the old version." >&2
    echo "Its available commands are:" >&2
    echo "$HELP_OUTPUT" >&2
    echo >&2
    echo "Replace it with the version containing the capture command." >&2
    exit 2
fi

echo
echo "Collector command check: PASS"
echo

# Print exact counts before collection.
python - "$URL_MANIFEST" "$HTML_DIR" <<'PY'
import json
import sys
from pathlib import Path

manifest = Path(sys.argv[1])
html_dir = Path(sys.argv[2])

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

html_files = list(html_dir.glob("*.html"))

print("===== Before capture =====")
print(f"Unique discovered URLs: {len(urls)}")
print(f"Saved HTML files:       {len(html_files)}")
print(f"Approx. still missing:  {max(len(urls) - len(html_files), 0)}")
PY

echo
echo "===== Starting HTML-only capture ====="
echo

# This command:
# - downloads only missing article HTML;
# - skips existing HTML files;
# - does not parse the article body;
# - does not download article images;
# - stops safely on HTTP 401, 403 or 429.
python "$COLLECTOR" capture \
  --config "$CONFIG"

echo
echo "===== After capture ====="

python - "$URL_MANIFEST" "$HTML_DIR" <<'PY'
import json
import sys
from pathlib import Path

manifest = Path(sys.argv[1])
html_dir = Path(sys.argv[2])

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

html_files = list(html_dir.glob("*.html"))
missing = max(len(urls) - len(html_files), 0)

print(f"Unique discovered URLs: {len(urls)}")
print(f"Saved HTML files:       {len(html_files)}")
print(f"Approx. still missing:  {missing}")

if missing == 0:
    print("HTML capture appears complete.")
else:
    print("HTML remains missing.")
    print("Resubmit the same Slurm job to resume safely.")
PY

echo
echo "Finished: $(date -u +'%Y-%m-%dT%H:%M:%SZ')"