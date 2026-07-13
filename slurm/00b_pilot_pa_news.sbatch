#!/bin/bash
#SBATCH --job-name=pa-pilot
#SBATCH --output=logs/pa-pilot-%j.out
#SBATCH --error=logs/pa-pilot-%j.err
#SBATCH --time=00:45:00
#SBATCH --cpus-per-task=1
#SBATCH --mem=3G

set -euo pipefail
cd "${SLURM_SUBMIT_DIR:-$PWD}"
mkdir -p logs
: "${CRAWLER_CONTACT_EMAIL:?Export CRAWLER_CONTACT_EMAIL before sbatch --export=ALL}"
source slurm/common_env.sh

# Bounded source-verification run: two listing pages and five articles with images.
python src/collect_pa_news.py all --config config/pa_news.yml \
  --limit-pages 2 --limit-articles 5
python src/validate_pa_news.py --root outputs/pa_news
