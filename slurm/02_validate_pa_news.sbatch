#!/bin/bash
#SBATCH --job-name=pa-validate
#SBATCH --output=logs/pa-validate-%j.out
#SBATCH --error=logs/pa-validate-%j.err
#SBATCH --time=00:30:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G

set -euo pipefail
cd "${SLURM_SUBMIT_DIR:-$PWD}"
mkdir -p logs
source slurm/common_env.sh
pytest -q
python src/validate_pa_news.py --root outputs/pa_news
