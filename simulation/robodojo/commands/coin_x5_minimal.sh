#!/usr/bin/env bash
set -uo pipefail

LOG_FILE="/home/nvidia/embodied-90/simulation/robodojo/logs/coin_x5_day03.log"
ROBOdojo_ROOT="/home/nvidia/RoboDojo"
CONDA_SH="/home/nvidia/miniconda3/etc/profile.d/conda.sh"
CONDA_ENV="RoboDojo"

mkdir -p "$(dirname "${LOG_FILE}")"
: > "${LOG_FILE}"
exec > >(tee -a "${LOG_FILE}") 2>&1

echo "===== RoboDojo Coin-X5 Minimal Run: Week 1 Day 3 ====="
echo "recorded_at: $(date -Is)"
echo "host: $(hostname)"
echo "user: $(whoami)"
echo "launch_dir_before_cd: $(pwd)"
echo "robodojo_root: ${ROBOdojo_ROOT}"
echo "conda_env: ${CONDA_ENV}"
echo

echo "===== Git State ====="
git -C "${ROBOdojo_ROOT}" rev-parse HEAD
git -C "${ROBOdojo_ROOT}" status --short
echo

echo "===== System / CUDA / Python Environment ====="
uname -a
command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi || echo "nvidia-smi not found"
command -v nvcc >/dev/null 2>&1 && nvcc --version || echo "nvcc not found"
if [[ -f "${CONDA_SH}" ]]; then
  # shellcheck source=/home/nvidia/miniconda3/etc/profile.d/conda.sh
  source "${CONDA_SH}"
  conda activate "${CONDA_ENV}"
else
  echo "conda activation script not found: ${CONDA_SH}"
fi
echo "active_conda_env: ${CONDA_DEFAULT_ENV:-<none>}"
command -v python || true
python --version || true
python - <<'PY' || true
import os
print("python_executable:", __import__("sys").executable)
try:
    import torch
    print("torch:", torch.__version__)
    print("torch_cuda:", torch.version.cuda)
    print("cuda_available:", torch.cuda.is_available())
    if torch.cuda.is_available():
        print("cuda_device_0:", torch.cuda.get_device_name(0))
except Exception as exc:
    print("torch_probe_error:", repr(exc))
for name in ("isaacsim", "isaaclab", "gymnasium", "numpy"):
    try:
        mod = __import__(name)
        print(f"{name}:", getattr(mod, "__version__", "<no __version__>"))
    except Exception as exc:
        print(f"{name}_probe_error:", repr(exc))
print("PYTHONPATH:", os.environ.get("PYTHONPATH", ""))
PY
echo

echo "===== Launch Command ====="
cd "${ROBOdojo_ROOT}" || exit 1
echo "launch_dir: $(pwd)"
echo "command: EVAL_NUM=1 bash scripts/robodojo.sh eval --policy-dir XPolicyLab/policy/demo_policy --task deposit_coin --ckpt demo --env-cfg arx_x5 --action-type joint --seed 0 --policy-gpu 0 --env-gpu 0 --policy-env RoboDojo --eval-env RoboDojo"
echo

echo "===== Command Output Begins ====="
set +e
EVAL_NUM=1 bash scripts/robodojo.sh eval \
  --policy-dir XPolicyLab/policy/demo_policy \
  --task deposit_coin \
  --ckpt demo \
  --env-cfg arx_x5 \
  --action-type joint \
  --seed 0 \
  --policy-gpu 0 \
  --env-gpu 0 \
  --policy-env RoboDojo \
  --eval-env RoboDojo
exit_code=$?
set -e
echo "===== Command Output Ends ====="
echo "exit_code: ${exit_code}"
echo

echo "===== Day 3 Observation Notes ====="
echo "expected: Launch one deposit_coin Coin-X5 evaluation episode with arx_x5 and demo_policy, or reproduce the current failure deterministically."
echo "actual: Process exit_code=${exit_code}. Inspect the command output above for task-level success/failure counts and generated artifacts."
echo "first_exception_location: No Python traceback is expected here unless the command output above contains one."

exit "${exit_code}"
