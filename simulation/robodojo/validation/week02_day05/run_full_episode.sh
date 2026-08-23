#!/usr/bin/env bash
set -euo pipefail

ROBODOJO_ROOT="/home/nvidia/RoboDojo"
PROJECT_ROOT="/home/nvidia/embodied-90"
OUTPUT_DIR="${PROJECT_ROOT}/simulation/robodojo/validation/week02_day05"
PYTHON="/home/nvidia/miniconda3/envs/RoboDojo/bin/python"
RUN_ID="week02_day05_seed0_layout0_full"
CHECKPOINT="RoboDojo-deposit_coin-arx_x5-joint-0"
CHECKPOINT_DIR="${ROBODOJO_ROOT}/XPolicyLab/policy/ACT/checkpoints/${CHECKPOINT}"
RESULT_DIR="${ROBODOJO_ROOT}/eval_result/RoboDojo/deposit_coin/ACT/arx_x5/0_ckpt_name=${CHECKPOINT},action_type=joint/${RUN_ID}"
LAUNCH_COMMAND="bash scripts/robodojo.sh eval --policy-dir XPolicyLab/policy/ACT --task deposit_coin --ckpt ${CHECKPOINT} --env-cfg arx_x5 --action-type joint --seed 0 --policy-gpu 0 --env-gpu 0 --policy-env RoboDojo --eval-env RoboDojo"

mkdir -p "${OUTPUT_DIR}"
rm -f \
  "${OUTPUT_DIR}/full_episode_internal.jsonl" \
  "${OUTPUT_DIR}/full_episode_trace.jsonl" \
  "${OUTPUT_DIR}/full_episode_trace.csv" \
  "${OUTPUT_DIR}/full_episode_metadata.json" \
  "${OUTPUT_DIR}/full_episode_summary.json" \
  "${OUTPUT_DIR}/full_episode.log" \
  "${OUTPUT_DIR}/result.json" \
  "${OUTPUT_DIR}/trajectory_plot.png" \
  "${OUTPUT_DIR}/video_manifest.json" \
  "${OUTPUT_DIR}/act_pred_log.txt" \
  "${OUTPUT_DIR}/act_exec_log.txt" \
  "${OUTPUT_DIR}/exit_code.txt"
rm -rf "${OUTPUT_DIR}/keyframes"

export PYTHONPATH="${OUTPUT_DIR}:${PYTHONPATH:-}"
export ROBODOJO_FULL_EPISODE_TRACE=1
export ROBODOJO_FULL_EPISODE_TRACE_DIR="${OUTPUT_DIR}"
export ROBODOJO_ACT_CHECKPOINT_DIR="${CHECKPOINT_DIR}"
export ROBODOJO_FULL_LAUNCH_COMMAND="${LAUNCH_COMMAND}"
export ROBODOJO_RUN_ID="${RUN_ID}"
export ACT_GT_REPLAY_LAYOUT_ID=0
export ACT_DEBUG_LOG=1
export ACT_REWARD_DEBUG=1
export EVAL_NUM=1
export ROBODOJO_SAVE_VIDEO=1
unset ACT_DEBUG_STOP_STEP

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
  2>&1 | tee "${OUTPUT_DIR}/full_episode.log"
eval_rc=${PIPESTATUS[0]}
set -e
printf '%s\n' "${eval_rc}" > "${OUTPUT_DIR}/exit_code.txt"

if [[ -f /tmp/act_pred_log.txt ]]; then
  cp /tmp/act_pred_log.txt "${OUTPUT_DIR}/act_pred_log.txt"
fi
if [[ -f /tmp/act_exec_log.txt ]]; then
  cp /tmp/act_exec_log.txt "${OUTPUT_DIR}/act_exec_log.txt"
fi
if [[ "${eval_rc}" -ne 0 ]]; then
  exit "${eval_rc}"
fi

"${PYTHON}" "${OUTPUT_DIR}/analyze_full_episode.py" \
  --dir "${OUTPUT_DIR}" \
  --result-dir "${RESULT_DIR}" \
  --exit-code "${eval_rc}"

test "$(wc -l < "${OUTPUT_DIR}/full_episode_internal.jsonl")" -eq 3000
test "$(wc -l < "${OUTPUT_DIR}/full_episode_trace.jsonl")" -eq 300
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
' "${OUTPUT_DIR}/full_episode_summary.json" >/dev/null
test -s "${OUTPUT_DIR}/trajectory_plot.png"
