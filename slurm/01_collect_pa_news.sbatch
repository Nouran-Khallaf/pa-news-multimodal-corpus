#!/bin/bash
#SBATCH --job-name=pa-news
#SBATCH --output=logs/pa-news-%j.out
#SBATCH --error=logs/pa-news-%j.err
#SBATCH --time=12:00:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G

set -euo pipefail
cd "${SLURM_SUBMIT_DIR:-$PWD}"
mkdir -p logs
: "${CRAWLER_CONTACT_EMAIL:?Export CRAWLER_CONTACT_EMAIL before sbatch --export=ALL}"

source slurm/common_env.sh

# Single process only. The collector is resumable and will skip completed URLs.
# It stops with exit code 75 on HTTP 401/403/429; do not launch parallel jobs or
# attempt to work around the block. Resume later with the same command.
set +e
python src/collect_pa_news.py all --config config/pa_news.yml
status=$?
set -e

if [[ "$status" -eq 75 ]]; then
  echo "The site requested that collection stop. State was saved; resume later without changing identity or concurrency." >&2
  exit 75
fi
exit "$status"
