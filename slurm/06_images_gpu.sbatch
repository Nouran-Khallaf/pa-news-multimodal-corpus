#!/bin/bash
#SBATCH --job-name=pa-images
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=16:00:00
#SBATCH --output=logs/pa-images-%j.out
#SBATCH --error=logs/pa-images-%j.err
set -euo pipefail
cd "${SLURM_SUBMIT_DIR}"
source slurm/common_env.sh
python src/analyse_images.py --config config/analysis.yml --device 0 --ocr --caption --classify
python src/embed_and_cluster_images.py --config config/analysis.yml --device cuda
