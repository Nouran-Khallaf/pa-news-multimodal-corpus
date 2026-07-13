#!/bin/bash
#SBATCH --job-name=pa-preflight
#SBATCH --output=logs/pa-preflight-%j.out
#SBATCH --error=logs/pa-preflight-%j.err
#SBATCH --time=00:15:00
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G

set -euo pipefail
cd "${SLURM_SUBMIT_DIR:-$PWD}"
mkdir -p logs

# Use an institutional research contact. Do not use the interview recipient's
# address unless they have explicitly agreed to be the crawler contact.
: "${CRAWLER_CONTACT_EMAIL:?Export CRAWLER_CONTACT_EMAIL before sbatch --export=ALL}"

source slurm/common_env.sh
python src/collect_pa_news.py preflight --config config/pa_news.yml
