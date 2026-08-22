#!/usr/bin/env bash
set -euo pipefail

ROBODOJO_ROOT="/home/nvidia/RoboDojo"
PROJECT_ROOT="/home/nvidia/embodied-90"
OUTPUT_DIR="${PROJECT_ROOT}/simulation/robodojo/validation/week02_day04"
PYTHON="/home/nvidia/miniconda3/envs/RoboDojo/bin/python"

mkdir -p "${OUTPUT_DIR}"
rm -f \
  "${OUTPUT_DIR}/action_trace.jsonl" \
  "${OUTPUT_DIR}/action_trace.csv" \
  "${OUTPUT_DIR}/action_trace.log" \
  "${OUTPUT_DIR}/action_trace_metadata.json" \
  "${OUTPUT_DIR}/action_trace_summary.json" \
  "${OUTPUT_DIR}/action_tracking_plot.png" \
  "${OUTPUT_DIR}/plot_error.log" \
  "${OUTPUT_DIR}/act_pred_log.txt" \
  "${OUTPUT_DIR}/act_exec_log.txt"

export PYTHONPATH="${OUTPUT_DIR}:${PYTHONPATH:-}"
export ROBODOJO_ACTION_TRACE=1
export ROBODOJO_ACTION_TRACE_DIR="${OUTPUT_DIR}"
export ROBODOJO_ACTION_TRACE_START=20
export ROBODOJO_ACTION_TRACE_END=60
export ACT_DEBUG_LOG=1
export ACT_DEBUG_STOP_STEP=60
export ACT_GT_REPLAY_LAYOUT_ID=0
export EVAL_NUM=1
export ROBODOJO_SAVE_VIDEO=0
export ROBODOJO_RUN_ID="week02_day04_action_trace_20260822"

cd "${ROBODOJO_ROOT}"
bash scripts/robodojo.sh eval \
  --policy-dir XPolicyLab/policy/ACT \
  --task deposit_coin \
  --ckpt RoboDojo-deposit_coin-arx_x5-joint-0 \
  --env-cfg arx_x5 \
  --action-type joint \
  --seed 0 \
  --policy-gpu 0 \
  --env-gpu 0 \
  --policy-env RoboDojo \
  --eval-env RoboDojo \
  2>&1 | tee "${OUTPUT_DIR}/formal_eval.log"

cp /tmp/act_pred_log.txt "${OUTPUT_DIR}/act_pred_log.txt"
cp /tmp/act_exec_log.txt "${OUTPUT_DIR}/act_exec_log.txt"
"${PYTHON}" "${OUTPUT_DIR}/analyze_action_trace.py" --dir "${OUTPUT_DIR}"

test "$(wc -l < "${OUTPUT_DIR}/action_trace.jsonl")" -eq 410
jq -e '
  .continuous_policy_steps == true and
  .ten_internal_steps_each == true and
  .validation_pass == true and
  .all_values_finite == true and
  .row_count == 410
' "${OUTPUT_DIR}/action_trace_summary.json" >/dev/null
test -s "${OUTPUT_DIR}/action_trace.csv"
test -s "${OUTPUT_DIR}/action_trace.log"
test -s "${OUTPUT_DIR}/action_tracking_plot.png"
