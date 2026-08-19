#!/usr/bin/env bash
set -euo pipefail

ROBOdojo_ROOT="/home/nvidia/RoboDojo"
PROJECT_ROOT="/home/nvidia/embodied-90"
OUTPUT_DIR="${PROJECT_ROOT}/simulation/robodojo/validation/week02_day01"
PYTHON="/home/nvidia/miniconda3/envs/RoboDojo/bin/python"

mkdir -p "${OUTPUT_DIR}"
cd "${ROBOdojo_ROOT}"

export CUDA_VISIBLE_DEVICES=0
export ROBODOJO_SAVE_VIDEO=0

set +e
"${PYTHON}" -u "${OUTPUT_DIR}/run_sim_render_validation.py" \
  --output-dir "${OUTPUT_DIR}" \
  --steps 75 \
  --seed 0 \
  --layout 0 \
  --device-id 0 \
  --headless \
  --enable_cameras \
  --kit_args "--enable isaacsim.replicator.behavior --enable isaacsim.sensors.camera" \
  2>&1 | tee "${OUTPUT_DIR}/sim_render.log"
python_status=${PIPESTATUS[0]}
if ! "${PYTHON}" -c 'import json,sys; data=json.load(open(sys.argv[1], encoding="utf-8")); sys.exit(0 if data.get("error") is None and data.get("checks") and all(data["checks"].values()) else 1)' "${OUTPUT_DIR}/observation_stats.json"; then
  python_status=1
fi
set -e
exit "${python_status}"
