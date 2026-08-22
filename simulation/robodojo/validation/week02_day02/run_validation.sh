#!/usr/bin/env bash
set -euo pipefail

ROBODOJO_ROOT="/home/nvidia/RoboDojo"
PROJECT_ROOT="/home/nvidia/embodied-90"
DAY2_DIR="${PROJECT_ROOT}/simulation/robodojo/validation/week02_day02"
DAY3_DIR="${PROJECT_ROOT}/simulation/robodojo/validation/week02_day03"
PYTHON="/home/nvidia/miniconda3/envs/RoboDojo/bin/python"

mkdir -p "${DAY2_DIR}" "${DAY3_DIR}"
cd "${ROBODOJO_ROOT}"

export CUDA_VISIBLE_DEVICES=0
export ROBODOJO_SAVE_VIDEO=0

"${PYTHON}" -u "${DAY2_DIR}/run_joint_asset_validation.py" \
  --day2-dir "${DAY2_DIR}" \
  --day3-dir "${DAY3_DIR}" \
  --seed 0 \
  --layout 0 \
  --device-id 0 \
  --headless \
  --enable_cameras \
  --kit_args "--enable isaacsim.replicator.behavior --enable isaacsim.sensors.camera" \
  2>&1 | tee "${DAY2_DIR}/combined_validation.log"
required=(
  "${DAY2_DIR}/robot_initial_state.json"
  "${DAY2_DIR}/joint_mapping.csv"
  "${DAY2_DIR}/joint_probe.log"
  "${DAY3_DIR}/asset_snapshot.json"
  "${DAY3_DIR}/coordinate_snapshot.json"
  "${DAY3_DIR}/passive_settle.log"
  "${DAY3_DIR}/collision_probe.log"
  "$DAY3_DIR/contact_probe_repeated.json"
  "$DAY3_DIR/contact_probe_repeated.log"
  "$DAY3_DIR/material_audit.json"
  "${DAY3_DIR}/annotated_scene.png"
)
for artifact in "${required[@]}"; do
  test -s "${artifact}"
done
jq -e '.all_repeats_have_interaction_evidence == true and .successful_interaction_repeats == 3' "$DAY3_DIR/contact_probe_repeated.json" >/dev/null
for repeat in 01 02 03; do
  for stage in before_contact first_collision_limit after_close; do
    for camera in cam_head cam_left_wrist; do
      test -s "$DAY3_DIR/contact_probe_frames/repeat_${repeat}_${stage}_${camera}.jpg"
    done
  done
done
test ! -e "${DAY2_DIR}/probe_error.json"
test ! -e "${DAY3_DIR}/probe_error.json"
