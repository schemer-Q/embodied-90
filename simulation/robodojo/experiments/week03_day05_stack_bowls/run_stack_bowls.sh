#!/usr/bin/env bash
set -euo pipefail

ROBODOJO_ROOT=/home/nvidia/RoboDojo
PROJECT_ROOT=/home/nvidia/embodied-90
HERE="${PROJECT_ROOT}/simulation/robodojo/experiments/week03_day05_stack_bowls"
PYTHON=/home/nvidia/miniconda3/envs/RoboDojo/bin/python
CHECKPOINT=RoboDojo-stack_bowls-arx_x5-joint-0
CHECKPOINT_DIR="${ROBODOJO_ROOT}/XPolicyLab/policy/ACT/checkpoints/${CHECKPOINT}"

run_eval() {
  local mode=$1
  local run_id=$2
  local stop_step=$3
  local save_video=$4
  local output="${HERE}/${mode}"
  local result_dir="${ROBODOJO_ROOT}/eval_result/RoboDojo/stack_bowls/ACT/arx_x5/0_ckpt_name=${CHECKPOINT},action_type=joint/${run_id}"

  test ! -e "${result_dir}"
  mkdir -p "${output}"
  export ROBODOJO_RUN_ID="${run_id}"
  export ACT_INPUT_COLOR_ORDER=rgb
  export ACT_GEOMETRY_MESH_CATEGORIES=piggy_bank
  export ACT_GT_REPLAY_LAYOUT_ID=0
  export ACT_MAX_TIMESTEPS=800
  export ACT_DEBUG_LOG=1
  export EVAL_NUM=1
  export ROBODOJO_SAVE_VIDEO="${save_video}"
  export PYTHONHASHSEED=0
  export CUBLAS_WORKSPACE_CONFIG=:4096:8
  unset ACT_TEMPORAL_AGG ACT_QUERY_FREQ ACT_NO_INTERP
  unset GRIPPER_EPS ACT_GRIPPER_MIN_POSITION ACT_GT_REPLAY ACT_GT_REPLAY_DIRECT
  if [[ "${stop_step}" -gt 0 ]]; then
    export ACT_DEBUG_STOP_STEP="${stop_step}"
  else
    unset ACT_DEBUG_STOP_STEP
  fi
  : > /tmp/act_pred_log.txt
  : > /tmp/act_exec_log.txt

  cd "${ROBODOJO_ROOT}"
  set +e
  bash scripts/robodojo.sh eval \
    --policy-dir XPolicyLab/policy/ACT --task stack_bowls --ckpt "${CHECKPOINT}" \
    --env-cfg arx_x5 --action-type joint --seed 0 --policy-gpu 0 --env-gpu 0 \
    --policy-env RoboDojo --eval-env RoboDojo > "${output}/episode.log" 2>&1
  local rc=$?
  set -e
  printf '%s\n' "${rc}" > "${output}/exit_code.txt"
  cp /tmp/act_pred_log.txt "${output}/act_pred_log.txt"
  cp /tmp/act_exec_log.txt "${output}/act_exec_log.txt"
  test "${rc}" -eq 0

  cd "${PROJECT_ROOT}"
  "${PYTHON}" "${HERE}/analyze_stack_bowls.py" \
    --mode "${mode}" --result-dir "${result_dir}" --expected-steps "${stop_step:-0}"
}

mkdir -p "${HERE}"
case "${1:-all}" in
  smoke) run_eval smoke week03_day05_stack_bowls_smoke_seed0_layout0 60 0 ;;
  full) run_eval full week03_day05_stack_bowls_official_seed0_layout0 0 1 ;;
  all)
    run_eval smoke week03_day05_stack_bowls_smoke_seed0_layout0 60 0
    run_eval full week03_day05_stack_bowls_official_seed0_layout0 0 1
    ;;
  *) echo "usage: $0 [smoke|full|all]" >&2; exit 2 ;;
esac
