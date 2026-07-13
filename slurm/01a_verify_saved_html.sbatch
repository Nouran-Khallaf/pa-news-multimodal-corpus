#!/bin/bash
#SBATCH --job-name=pa-html-audit
#SBATCH --output=logs/pa-html-audit-%j.out
#SBATCH --error=logs/pa-html-audit-%j.err
#SBATCH --time=01:00:00
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G

set -euo pipefail
cd "${SLURM_SUBMIT_DIR:-$PWD}"
mkdir -p logs outputs/pa_news/manifests
source slurm/common_env.sh

python src/verify_saved_html.py \
  --html-dir outputs/pa_news/data/raw/html \
  --output-json outputs/pa_news/manifests/html_extraction_audit.json \
  --output-csv outputs/pa_news/manifests/html_extraction_audit.csv \
  --minimum-words "${MINIMUM_WORDS:-20}"
