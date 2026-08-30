#!/usr/bin/env bash
set -euo pipefail

ROBODOJO_ROOT=/home/nvidia/RoboDojo
PROJECT_ROOT=/home/nvidia/embodied-90
HERE="${PROJECT_ROOT}/simulation/robodojo/experiments/week03_day04_fixed_eval"
TRACE_HOOK="${PROJECT_ROOT}/simulation/robodojo/experiments/week03_day02_temporal_agg"
DAY5="${PROJECT_ROOT}/simulation/robodojo/validation/week02_day05"
DAY2="${PROJECT_ROOT}/simulation/robodojo/validation/week02_day02"
PYTHON=/home/nvidia/miniconda3/envs/RoboDojo/bin/python
CHECKPOINT=RoboDojo-deposit_coin-arx_x5-joint-0
CHECKPOINT_DIR="${ROBODOJO_ROOT}/XPolicyLab/policy/ACT/checkpoints/${CHECKPOINT}"
OUTPUT="${HERE}/fixed"
RUN_ID=week03_day04_seed0_layout0_rgb_official_stand
RESULT_DIR="${ROBODOJO_ROOT}/eval_result/RoboDojo/deposit_coin/ACT/arx_x5/0_ckpt_name=${CHECKPOINT},action_type=joint/${RUN_ID}"

test ! -e "${OUTPUT}/full_episode_trace.jsonl"
test ! -e "${RESULT_DIR}"
mkdir -p "${OUTPUT}"
export PYTHONPATH="${TRACE_HOOK}:${DAY5}:${DAY2}:${PYTHONPATH:-}"
export ROBODOJO_FULL_EPISODE_TRACE=1
export ROBODOJO_FULL_EPISODE_TRACE_DIR="${OUTPUT}"
export ROBODOJO_ACT_CHECKPOINT_DIR="${CHECKPOINT_DIR}"
export ROBODOJO_RUN_ID="${RUN_ID}"
export ROBODOJO_FULL_LAUNCH_COMMAND="ACT_INPUT_COLOR_ORDER=rgb ACT_GEOMETRY_MESH_CATEGORIES=piggy_bank bash scripts/robodojo.sh eval --policy-dir XPolicyLab/policy/ACT --task deposit_coin --ckpt ${CHECKPOINT} --env-cfg arx_x5 --action-type joint --seed 0 --policy-gpu 0 --env-gpu 0 --policy-env RoboDojo --eval-env RoboDojo"
export ACT_INPUT_COLOR_ORDER=rgb
export ACT_GEOMETRY_MESH_CATEGORIES=piggy_bank
export ACT_GT_REPLAY_LAYOUT_ID=0
export ACT_MAX_TIMESTEPS=300
export ACT_DEBUG_LOG=1
export ACT_REWARD_DEBUG=1
export EVAL_NUM=1
export ROBODOJO_SAVE_VIDEO=1
export PYTHONHASHSEED=0
export CUBLAS_WORKSPACE_CONFIG=:4096:8
unset ACT_TEMPORAL_AGG ACT_DEBUG_STOP_STEP ACT_QUERY_FREQ ACT_NO_INTERP
unset GRIPPER_EPS ACT_GRIPPER_MIN_POSITION ACT_GT_REPLAY ACT_GT_REPLAY_DIRECT
: > /tmp/act_pred_log.txt
: > /tmp/act_exec_log.txt

cd "${ROBODOJO_ROOT}"
set +e
bash scripts/robodojo.sh eval \
  --policy-dir XPolicyLab/policy/ACT --task deposit_coin --ckpt "${CHECKPOINT}" \
  --env-cfg arx_x5 --action-type joint --seed 0 --policy-gpu 0 --env-gpu 0 \
  --policy-env RoboDojo --eval-env RoboDojo > "${OUTPUT}/full_episode.log" 2>&1
rc=$?
set -e
printf '%s\n' "${rc}" > "${OUTPUT}/exit_code.txt"
cp /tmp/act_pred_log.txt "${OUTPUT}/act_pred_log.txt"
cp /tmp/act_exec_log.txt "${OUTPUT}/act_exec_log.txt"
test "${rc}" -eq 0

"${PYTHON}" "${DAY5}/analyze_full_episode.py" \
  --dir "${OUTPUT}" --result-dir "${RESULT_DIR}" --exit-code "${rc}"
cd "${PROJECT_ROOT}"
"${PYTHON}" "${HERE}/analyze_fixed.py"
