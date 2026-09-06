#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DAY02_DIR="${SCRIPT_DIR}/../week04_day02"
ENV_DIR="${LEROBOT_ENV_DIR:-/tmp/embodied90-week04-day02-lerobot}"

LEROBOT_ENV_DIR="${ENV_DIR}" "${DAY02_DIR}/setup_environment.sh"
uv pip install --python "${ENV_DIR}/bin/python" \
  draccus==0.10.0 \
  wandb==0.24.2 \
  diffusers==0.35.2
uv pip install --python "${ENV_DIR}/bin/python" --no-deps \
  pyserial==3.5 \
  pynput==1.8.1

WANDB_MODE=disabled "${ENV_DIR}/bin/lerobot-train" --help >/dev/null
echo "LeRobot ACT training CLI: OK"
