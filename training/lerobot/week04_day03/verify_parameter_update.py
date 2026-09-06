#!/usr/bin/env python3
"""Compare the trained ACT state with its same-seed reconstructed initialization."""

from copy import deepcopy
import json
from pathlib import Path

import torch
from lerobot.datasets.lerobot_dataset import LeRobotDatasetMetadata
from lerobot.policies.act.modeling_act import ACTPolicy
from lerobot.policies.factory import make_policy
from lerobot.utils.random_utils import set_seed


ARTIFACT_DIR = Path(__file__).resolve().parent
MODEL_DIR = (ARTIFACT_DIR / "run/checkpoints/last/pretrained_model").resolve()

trained_policy = ACTPolicy.from_pretrained(MODEL_DIR, device="cpu")
train_config = json.loads((MODEL_DIR / "train_config.json").read_text())
initial_config = deepcopy(trained_policy.config)
initial_config.pretrained_path = None
initial_config.device = "cpu"

set_seed(train_config["seed"])
dataset_meta = LeRobotDatasetMetadata(
    train_config["dataset"]["repo_id"],
    root=Path(train_config["dataset"]["root"]).resolve(),
    revision=train_config["dataset"]["revision"],
)
initial_policy = make_policy(initial_config, ds_meta=dataset_meta)

changed_values = 0
total_values = 0
squared_difference = 0.0
max_abs_difference = 0.0
for (initial_name, initial), (trained_name, trained) in zip(
    initial_policy.state_dict().items(), trained_policy.state_dict().items(), strict=True
):
    if initial_name != trained_name:
        raise RuntimeError(f"State key mismatch: {initial_name} != {trained_name}")
    difference = (initial.cpu() - trained.cpu()).float()
    total_values += difference.numel()
    changed_values += int(torch.count_nonzero(difference))
    squared_difference += float(torch.sum(difference * difference))
    max_abs_difference = max(max_abs_difference, float(difference.abs().max()))

result = {
    "comparison": "same-seed reconstructed initialization vs trained checkpoint",
    "seed": train_config["seed"],
    "changed_state_values": changed_values,
    "total_state_values": total_values,
    "l2_difference": squared_difference**0.5,
    "max_abs_difference": max_abs_difference,
    "changed": changed_values > 0,
}
if not result["changed"]:
    raise RuntimeError("No model state values changed during training")

(ARTIFACT_DIR / "parameter_update.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
