#!/bin/bash
#SBATCH --job-name=pa-reparse
#SBATCH --output=logs/pa-reparse-%j.out
#SBATCH --error=logs/pa-reparse-%j.err
#SBATCH --time=12:00:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G

set -euo pipefail
cd "${SLURM_SUBMIT_DIR:-$PWD}"
mkdir -p logs
: "${CRAWLER_CONTACT_EMAIL:?Export CRAWLER_CONTACT_EMAIL before sbatch --export=ALL}"

source slurm/common_env.sh

# Reuses article HTML already saved under outputs/pa_news/data/raw/html.
# It does not refetch article pages. Image requests remain polite and single-threaded.
args=(reparse --config config/pa_news.yml)
if [[ -n "${LIMIT_ARTICLES:-}" ]]; then
  args+=(--limit-articles "$LIMIT_ARTICLES")
fi
if [[ "${SKIP_IMAGES:-0}" == "1" ]]; then
  args+=(--skip-images)
fi

set +e
python src/collect_pa_news.py "${args[@]}"
status=$?
set -e

if [[ "$status" -eq 75 ]]; then
  echo "Image retrieval was stopped by HTTP 401/403/429. Parsed progress was preserved; resume later." >&2
  exit 75
fi
exit "$status"
