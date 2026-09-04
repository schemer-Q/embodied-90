#!/usr/bin/env bash
set -euo pipefail

BASE_PYTHON="${BASE_PYTHON:-/home/nvidia/miniconda3/envs/RoboDojo/bin/python}"
ENV_DIR="${LEROBOT_ENV_DIR:-/tmp/embodied90-week04-day02-lerobot}"

uv venv --clear --system-site-packages --python "${BASE_PYTHON}" "${ENV_DIR}"
uv pip install --python "${ENV_DIR}/bin/python" --no-deps \
  lerobot==0.4.4 datasets==4.8.5 huggingface-hub==0.35.3 \
  pyarrow==25.0.1 av==15.1.0 deepdiff==8.6.2 jsonlines==4.0.0 \
  accelerate==1.14.0 termcolor==3.3.0 safetensors==0.8.0 socksio==1.0.0 \
  aiohttp==3.14.3 dill==0.4.1 filelock==3.32.5 fsspec==2026.2.0 \
  multiprocess==0.70.19 orderly-set==5.5.0 packaging==25.0 pandas==3.0.5 \
  psutil==7.2.2 requests==2.34.2 tqdm==4.70.0 xxhash==4.0.1

"${ENV_DIR}/bin/python" - <<'PY'
import torch
import torchvision
from lerobot.datasets.lerobot_dataset import LeRobotDataset

assert torch.__version__.startswith("2.7.0")
assert torchvision.__version__.startswith("0.22.0")
assert hasattr(torchvision.io, "VideoReader")
print("LeRobotDataset import and PyAV-compatible VideoReader: OK")
PY
