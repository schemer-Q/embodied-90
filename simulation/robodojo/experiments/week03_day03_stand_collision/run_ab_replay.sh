#!/usr/bin/env bash
set -euo pipefail

ROBODOJO_ROOT=/home/nvidia/RoboDojo
PROJECT_ROOT=/home/nvidia/embodied-90
HERE="${PROJECT_ROOT}/simulation/robodojo/experiments/week03_day03_stand_collision"
DAY5="${PROJECT_ROOT}/simulation/robodojo/validation/week02_day05"
DAY2="${PROJECT_ROOT}/simulation/robodojo/validation/week02_day02"
DAY2_EXPERIMENT="${PROJECT_ROOT}/simulation/robodojo/experiments/week03_day02_temporal_agg"
CHECKPOINT=RoboDojo-deposit_coin-arx_x5-joint-0
CHECKPOINT_DIR="${ROBODOJO_ROOT}/XPolicyLab/policy/ACT/checkpoints/${CHECKPOINT}"
RESULT_ROOT="${ROBODOJO_ROOT}/eval_result/RoboDojo/deposit_coin/ACT/arx_x5/0_ckpt_name=${CHECKPOINT},action_type=joint"
PYTHON=/home/nvidia/miniconda3/envs/RoboDojo/bin/python

export PYTHONPATH="${HERE}:${DAY2_EXPERIMENT}:${DAY5}:${DAY2}:${PYTHONPATH:-}"

run_condition() {
  local condition="$1"
  local categories="$2"
  local output="${HERE}/${condition}"
  local run_id="week03_day03_seed0_layout0_${condition}"
  local result_dir="${RESULT_ROOT}/${run_id}"
  test ! -e "${output}/full_episode_trace.jsonl"
  test ! -e "${result_dir}"
  mkdir -p "${output}"

  export ROBODOJO_STAND_COLLISION_REPLAY=1
  export ROBODOJO_FULL_EPISODE_TRACE=1
  export ROBODOJO_FULL_EPISODE_TRACE_DIR="${output}"
  export ROBODOJO_ACT_CHECKPOINT_DIR="${CHECKPOINT_DIR}"
  export ROBODOJO_RUN_ID="${run_id}"
  export ROBODOJO_FULL_LAUNCH_COMMAND="ACT_GT_REPLAY=1 ACT_REPLAY_JSONL=${HERE}/replay_actions.jsonl ACT_GEOMETRY_MESH_CATEGORIES=${categories} bash scripts/robodojo.sh eval ..."
  export ACT_GT_REPLAY=1
  export ACT_REPLAY_JSONL="${HERE}/replay_actions.jsonl"
  export ACT_REPLAY_MANIFEST="${HERE}/replay_manifest.json"
  export ACT_GT_REPLAY_LAYOUT_ID=0
  export ACT_GEOMETRY_MESH_CATEGORIES="${categories}"
  export STAND_COLLISION_CONDITION="${condition}"
  export ACT_INPUT_COLOR_ORDER=rgb
  export EVAL_NUM=1
  export ROBODOJO_SAVE_VIDEO=0
  export PYTHONHASHSEED=0
  export CUBLAS_WORKSPACE_CONFIG=:4096:8
  unset ACT_TEMPORAL_AGG ACT_STAND_DISABLE_SOLID ACT_GT_REPLAY_DIRECT ACT_NO_INTERP
  : > /tmp/gt_replay_actions.log

  cd "${ROBODOJO_ROOT}"
  set +e
  bash scripts/robodojo.sh eval \
    --policy-dir XPolicyLab/policy/ACT --task deposit_coin --ckpt "${CHECKPOINT}" \
    --env-cfg arx_x5 --action-type joint --seed 0 --policy-gpu 0 --env-gpu 0 \
    --policy-env RoboDojo --eval-env RoboDojo > "${output}/full_episode.log" 2>&1
  local rc=$?
  set -e
  printf '%s\n' "${rc}" > "${output}/exit_code.txt"
  cp /tmp/gt_replay_actions.log "${output}/replay_exec.log"
  test "${rc}" -eq 0
  cp "${result_dir}/_result.json" "${output}/result.json"
  test "$(wc -l < "${output}/full_episode_trace.jsonl")" -eq 300
  test "$(wc -l < "${output}/full_episode_internal.jsonl")" -eq 3000
  test "$(wc -l < "${output}/object_trace.jsonl")" -eq 3000
  test "$(wc -l < "${output}/replay_exec.log")" -eq 300
}

if [[ "${1:-}" == "--a-only" ]]; then
  unset ACT_DEBUG_STOP_STEP
  run_condition triangle_mesh "vertical_coin_stand,piggy_bank"
  exit 0
fi
if [[ "${1:-}" == "--b-only" ]]; then
  unset ACT_DEBUG_STOP_STEP
  run_condition official "piggy_bank"
  exit 0
fi

unset ACT_DEBUG_STOP_STEP
run_condition triangle_mesh "vertical_coin_stand,piggy_bank"
run_condition official "piggy_bank"
cd "${PROJECT_ROOT}"
"${PYTHON}" "${HERE}/analyze_ab.py"
