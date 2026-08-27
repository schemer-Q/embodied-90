#!/usr/bin/env bash
set -euo pipefail

ROBODOJO_ROOT="/home/nvidia/RoboDojo"
PROJECT_ROOT="/home/nvidia/embodied-90"
EXPERIMENT_DIR="${PROJECT_ROOT}/simulation/robodojo/experiments/week03_day02_temporal_agg"
DAY5_DIR="${PROJECT_ROOT}/simulation/robodojo/validation/week02_day05"
DAY2_DIR="${PROJECT_ROOT}/simulation/robodojo/validation/week02_day02"
PYTHON="/home/nvidia/miniconda3/envs/RoboDojo/bin/python"
CHECKPOINT="RoboDojo-deposit_coin-arx_x5-joint-0"
CHECKPOINT_DIR="${ROBODOJO_ROOT}/XPolicyLab/policy/ACT/checkpoints/${CHECKPOINT}"
RESULT_ROOT="${ROBODOJO_ROOT}/eval_result/RoboDojo/deposit_coin/ACT/arx_x5/0_ckpt_name=${CHECKPOINT},action_type=joint"

export PYTHONPATH="${EXPERIMENT_DIR}:${DAY5_DIR}:${DAY2_DIR}:${PYTHONPATH:-}"

run_condition() {
  local temporal_mode="$1"
  local output_dir="${EXPERIMENT_DIR}/${temporal_mode}"
  local run_id="week03_day02_seed0_layout0_temporal_${temporal_mode}"
  local result_dir="${RESULT_ROOT}/${run_id}"
  local launch_command
  launch_command="ACT_INPUT_COLOR_ORDER=rgb ACT_TEMPORAL_AGG=${temporal_mode} ACT_MAX_TIMESTEPS=300 bash scripts/robodojo.sh eval --policy-dir XPolicyLab/policy/ACT --task deposit_coin --ckpt ${CHECKPOINT} --env-cfg arx_x5 --action-type joint --seed 0 --policy-gpu 0 --env-gpu 0 --policy-env RoboDojo --eval-env RoboDojo"

  if [[ -e "${output_dir}/full_episode_trace.jsonl" || -e "${result_dir}" ]]; then
    echo "Refusing to overwrite existing run: ${temporal_mode}" >&2
    return 2
  fi
  mkdir -p "${output_dir}"

  export ROBODOJO_FULL_EPISODE_TRACE=1
  export ROBODOJO_FULL_EPISODE_TRACE_DIR="${output_dir}"
  export ROBODOJO_ACT_CHECKPOINT_DIR="${CHECKPOINT_DIR}"
  export ROBODOJO_FULL_LAUNCH_COMMAND="${launch_command}"
  export ROBODOJO_RUN_ID="${run_id}"
  export ACT_INPUT_COLOR_ORDER=rgb
  export ACT_MAX_TIMESTEPS=300
  export ACT_GEOMETRY_MESH_CATEGORIES="vertical_coin_stand,piggy_bank"
  export ACT_GT_REPLAY_LAYOUT_ID=0
  export ACT_DEBUG_LOG=1
  export ACT_REWARD_DEBUG=1
  export EVAL_NUM=1
  export ROBODOJO_SAVE_VIDEO=1
  export PYTHONHASHSEED=0
  export CUBLAS_WORKSPACE_CONFIG=:4096:8
  if [[ "${temporal_mode}" == "true" ]]; then
    export ACT_TEMPORAL_AGG=1
  else
    unset ACT_TEMPORAL_AGG
  fi
  unset ACT_DEBUG_STOP_STEP
  unset ACT_QUERY_FREQ
  unset ACT_NO_INTERP
  unset GRIPPER_EPS
  unset ACT_GRIPPER_MIN_POSITION
  : > /tmp/act_pred_log.txt
  : > /tmp/act_exec_log.txt

  cd "${ROBODOJO_ROOT}"
  set +e
  bash scripts/robodojo.sh eval \
    --policy-dir XPolicyLab/policy/ACT \
    --task deposit_coin \
    --ckpt "${CHECKPOINT}" \
    --env-cfg arx_x5 \
    --action-type joint \
    --seed 0 \
    --policy-gpu 0 \
    --env-gpu 0 \
    --policy-env RoboDojo \
    --eval-env RoboDojo \
    > "${output_dir}/full_episode.log" 2>&1
  local eval_rc=$?
  set -e
  printf '%s\n' "${eval_rc}" > "${output_dir}/exit_code.txt"
  cp /tmp/act_pred_log.txt "${output_dir}/act_pred_log.txt"
  cp /tmp/act_exec_log.txt "${output_dir}/act_exec_log.txt"
  if [[ "${eval_rc}" -ne 0 ]]; then
    return "${eval_rc}"
  fi

  "${PYTHON}" "${DAY5_DIR}/analyze_full_episode.py" \
    --dir "${output_dir}" \
    --result-dir "${result_dir}" \
    --exit-code "${eval_rc}"

  test "$(wc -l < "${output_dir}/full_episode_internal.jsonl")" -eq 3000
  test "$(wc -l < "${output_dir}/full_episode_trace.jsonl")" -eq 300
  jq -e '
    .policy_steps == 300 and
    .internal_records == 3000 and
    .missing_policy_steps == [] and
    .incorrect_internal_step_counts == {} and
    .incorrect_internal_step_sequences == {} and
    .invalid_values == 0 and
    .validation_failures == 0 and
    .exit_code == 0 and
    .result_consistent == true and
    .video_count == 3 and
    .videos_complete == true
  ' "${output_dir}/full_episode_summary.json" >/dev/null
}

run_condition false
run_condition true

cd "${PROJECT_ROOT}"
"${PYTHON}" "${EXPERIMENT_DIR}/analyze_ab.py"
