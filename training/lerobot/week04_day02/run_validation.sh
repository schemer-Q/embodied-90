#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${LEROBOT_PYTHON:-/tmp/embodied90-week04-day02-lerobot/bin/python}"

"${PYTHON_BIN}" "${SCRIPT_DIR}/inspect_dataset.py" \
  --root "${SCRIPT_DIR}/dataset/lerobot_pusht" \
  --output "${SCRIPT_DIR}" \
  --repo-id "lerobot/pusht" \
  --revision "b1c3ecbae7f244acc039a3dbc255a00dad1372b9" \
  --episode 0
