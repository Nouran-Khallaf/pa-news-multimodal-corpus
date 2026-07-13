#!/bin/bash
set -euo pipefail
mkdir -p logs
qc=$(sbatch --parsable slurm/02b_normalise_deduplicate.sbatch)
cpu=$(sbatch --parsable --dependency=afterok:${qc} slurm/03_preprocess_and_cpu_analysis.sbatch)
topics=$(sbatch --parsable --dependency=afterok:${cpu} slurm/04_topics_gpu.sbatch)
frames=$(sbatch --parsable --dependency=afterok:${cpu} slurm/05_political_zero_shot_gpu.sbatch)
images=$(sbatch --parsable --dependency=afterok:${cpu} slurm/06_images_gpu.sbatch)
multi=$(sbatch --parsable --dependency=afterok:${images} slurm/07_multimodal_gpu.sbatch)
echo "QC=$qc CPU=$cpu TOPICS=$topics FRAMES=$frames IMAGES=$images MULTIMODAL=$multi"
