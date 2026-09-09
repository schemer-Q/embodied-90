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

"${PYTHON}" -m unittest \
  "${ROOT_DIR}/training/lerobot/week04_day06/test_health_checks.py" -v \
  2>&1 | tee "${ROOT_DIR}/training/lerobot/week04_day06/negative_tests.log"

"${PYTHON}" "${ROOT_DIR}/training/lerobot/week04_day06/check_dataset.py" \
  --root "${ROOT_DIR}/training/lerobot/week04_day02/dataset/lerobot_pusht" \
  --repo-id "lerobot/pusht" \
  --revision "b1c3ecbae7f244acc039a3dbc255a00dad1372b9" \
  --expected-state-dim 2 \
  --expected-action-dim 2 \
  --expected-camera observation.image \
  --action-window 10 \
  --output "${ROOT_DIR}/training/lerobot/week04_day06" \
  2>&1 | tee "${ROOT_DIR}/training/lerobot/week04_day06/health_check.log"

