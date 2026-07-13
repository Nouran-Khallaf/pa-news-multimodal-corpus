#!/bin/bash
#SBATCH --job-name=pa-qc
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=04:00:00
#SBATCH --output=logs/pa-qc-%j.out
#SBATCH --error=logs/pa-qc-%j.err
set -euo pipefail
cd "${SLURM_SUBMIT_DIR}"
source slurm/common_env.sh
python src/normalise.py --config config/analysis.yml
python src/extract.py --config config/analysis.yml
python src/deduplicate.py --config config/analysis.yml
python src/capture_environment.py
