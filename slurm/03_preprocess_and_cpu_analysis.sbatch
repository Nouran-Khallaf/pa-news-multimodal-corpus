#!/bin/bash
#SBATCH --job-name=pa-nlp-cpu
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=08:00:00
#SBATCH --output=logs/pa-nlp-cpu-%j.out
#SBATCH --error=logs/pa-nlp-cpu-%j.err
set -euo pipefail
cd "${SLURM_SUBMIT_DIR}"
source slurm/common_env.sh
args=(--config config/analysis.yml)
if [[ -n "${COMPARATOR_PATH:-}" ]]; then args+=(--comparator "$COMPARATOR_PATH"); fi
python src/run_pipeline.py "${args[@]}"
python src/analyse_temporal.py --config config/analysis.yml
python src/capture_environment.py
