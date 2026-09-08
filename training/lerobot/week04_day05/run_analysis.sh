#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
VENV_DIR="/tmp/embodied90-week04-day02-lerobot"
PYTHON="${VENV_DIR}/bin/python"

if [[ ! -x "${PYTHON}" ]]; then
  bash "${ROOT_DIR}/training/lerobot/week04_day03/setup_training_environment.sh"
fi

export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export WANDB_MODE=disabled

"${PYTHON}" "${ROOT_DIR}/training/lerobot/week04_day05/analyze_act_timing.py" \
  --dataset-root "${ROOT_DIR}/training/lerobot/week04_day02/dataset/lerobot_pusht" \
  --checkpoint "${ROOT_DIR}/training/lerobot/week04_day03/run/checkpoints/last/pretrained_model" \
  --output "${ROOT_DIR}/training/lerobot/week04_day05" \
  --frames 0 80 160 \
  --queue-frame 80 \
  --seed 20260908 \
  2>&1 | tee "${ROOT_DIR}/training/lerobot/week04_day05/analysis.log"

