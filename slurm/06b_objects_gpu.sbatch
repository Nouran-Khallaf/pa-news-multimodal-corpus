#!/bin/bash
#SBATCH --job-name=pa-objects
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=6
#SBATCH --mem=48G
#SBATCH --time=16:00:00
#SBATCH --output=logs/pa-objects-%j.out
#SBATCH --error=logs/pa-objects-%j.err
set -euo pipefail
cd "${SLURM_SUBMIT_DIR}"
source slurm/common_env.sh
python src/analyse_images.py --config config/analysis.yml --device 0 --detect
