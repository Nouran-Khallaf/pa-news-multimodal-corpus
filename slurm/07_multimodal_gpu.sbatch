#!/bin/bash
#SBATCH --job-name=pa-multimodal
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=6
#SBATCH --mem=48G
#SBATCH --time=12:00:00
#SBATCH --output=logs/pa-multimodal-%j.out
#SBATCH --error=logs/pa-multimodal-%j.err
set -euo pipefail
cd "${SLURM_SUBMIT_DIR}"
source slurm/common_env.sh
python src/analyse_multimodal.py --config config/analysis.yml --device cuda
python src/analyse_temporal.py --config config/analysis.yml
python src/build_analysis_summary.py --config config/analysis.yml
