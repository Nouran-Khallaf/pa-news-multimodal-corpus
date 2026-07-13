#!/bin/bash
set -euo pipefail
mkdir -p logs
module purge 2>/dev/null || true
if command -v conda >/dev/null 2>&1; then
  CONDA_BASE="$(conda info --base)"
elif [[ -f "${HOME}/miniforge3/etc/profile.d/conda.sh" ]]; then
  CONDA_BASE="${HOME}/miniforge3"
elif [[ -f "${HOME}/miniconda3/etc/profile.d/conda.sh" ]]; then
  CONDA_BASE="${HOME}/miniconda3"
elif [[ -f "${HOME}/anaconda3/etc/profile.d/conda.sh" ]]; then
  CONDA_BASE="${HOME}/anaconda3"
else
  echo "Conda was not found. Set PATH or edit slurm/common_env.sh for Aire." >&2
  exit 2
fi
source "${CONDA_BASE}/etc/profile.d/conda.sh"
conda activate "${CONDA_ENV:-mlenv}"
export PYTHONUNBUFFERED=1
export TOKENIZERS_PARALLELISM=false
