#!/bin/bash
#SBATCH --job-name=pa-frames
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=08:00:00
#SBATCH --output=logs/pa-frames-%j.out
#SBATCH --error=logs/pa-frames-%j.err
set -euo pipefail
cd "${SLURM_SUBMIT_DIR}"
source slurm/common_env.sh
python src/analyse_political_discourse.py --config config/analysis.yml --zero-shot --device 0
