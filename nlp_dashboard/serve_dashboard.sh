#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python -m http.server "${1:-8000}"
