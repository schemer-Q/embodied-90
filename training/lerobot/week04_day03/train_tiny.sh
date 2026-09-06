#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_ENV="${LEROBOT_ENV_DIR:-/tmp/embodied90-week04-day02-lerobot}"
TRAIN_BIN="${PYTHON_ENV}/bin/lerobot-train"
DATASET_ROOT="${SCRIPT_DIR}/../week04_day02/dataset/lerobot_pusht"
RUN_DIR="${SCRIPT_DIR}/run"
GPU_TRACE="${SCRIPT_DIR}/gpu_trace.csv"
LOG_FILE="${SCRIPT_DIR}/train.log"
EXIT_FILE="${SCRIPT_DIR}/exit_code.txt"

if [[ -e "${RUN_DIR}" ]]; then
  echo "Refusing to overwrite existing run directory: ${RUN_DIR}" >&2
  exit 2
fi
if [[ ! -x "${TRAIN_BIN}" ]]; then
  echo "Training environment is missing; run setup_training_environment.sh first" >&2
  exit 2
fi

export WANDB_MODE=disabled
export HF_HUB_OFFLINE=1
export PYTHONUNBUFFERED=1

nvidia-smi \
  --query-gpu=timestamp,utilization.gpu,memory.used,memory.total,power.draw \
  --format=csv,noheader,nounits \
  --loop-ms=200 >"${GPU_TRACE}" &
MONITOR_PID=$!
cleanup() {
  kill "${MONITOR_PID}" 2>/dev/null || true
  wait "${MONITOR_PID}" 2>/dev/null || true
}
trap cleanup EXIT

set +e
"${TRAIN_BIN}" \
  --dataset.repo_id=lerobot/pusht \
  --dataset.root="${DATASET_ROOT}" \
  --dataset.revision=b1c3ecbae7f244acc039a3dbc255a00dad1372b9 \
  --dataset.episodes='[0]' \
  --dataset.video_backend=pyav \
  --policy.type=act \
  --policy.device=cuda \
  --policy.push_to_hub=false \
  --policy.pretrained_backbone_weights=null \
  --policy.chunk_size=10 \
  --policy.n_action_steps=10 \
  --policy.dim_model=128 \
  --policy.n_heads=4 \
  --policy.dim_feedforward=256 \
  --policy.n_encoder_layers=1 \
  --policy.n_decoder_layers=1 \
  --policy.n_vae_encoder_layers=1 \
  --policy.latent_dim=16 \
  --output_dir="${RUN_DIR}" \
  --job_name=week04_day03_tiny_act \
  --seed=20260906 \
  --batch_size=2 \
  --num_workers=0 \
  --steps=50 \
  --eval_freq=0 \
  --log_freq=1 \
  --save_checkpoint=true \
  --save_freq=50 \
  --wandb.enable=false \
  2>&1 | tee "${LOG_FILE}"
STATUS=${PIPESTATUS[0]}
set -e

printf '%s\n' "${STATUS}" >"${EXIT_FILE}"
exit "${STATUS}"
