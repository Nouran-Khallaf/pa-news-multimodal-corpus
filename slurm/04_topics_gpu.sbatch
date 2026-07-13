#!/bin/bash
#SBATCH --job-name=pa-topics
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=08:00:00
#SBATCH --output=logs/pa-topics-%j.out
#SBATCH --error=logs/pa-topics-%j.err
set -euo pipefail
cd "${SLURM_SUBMIT_DIR}"
source slurm/common_env.sh
python src/analyse_topics.py --config config/analysis.yml --device cuda
