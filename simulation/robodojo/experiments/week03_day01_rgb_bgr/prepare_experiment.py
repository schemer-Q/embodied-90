#!/usr/bin/env python3
"""Record immutable inputs and current worktree state for the A/B run."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess


PROJECT_ROOT = Path("/home/nvidia/embodied-90")
ROBODOJO_ROOT = Path("/home/nvidia/RoboDojo")
EXPERIMENT_DIR = PROJECT_ROOT / "simulation/robodojo/experiments/week03_day01_rgb_bgr"
CHECKPOINT_DIR = ROBODOJO_ROOT / "XPolicyLab/policy/ACT/checkpoints/RoboDojo-deposit_coin-arx_x5-joint-0"


def command(args, cwd):
    return subprocess.check_output(args, cwd=cwd, text=True, stderr=subprocess.STDOUT).strip()


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    model_patch = command(
        ["git", "diff", "--", "policy/ACT/model.py"],
        ROBODOJO_ROOT / "XPolicyLab",
    )
    (EXPERIMENT_DIR / "xpolicylab_model_worktree.patch").write_text(
        model_patch + ("\n" if model_patch else ""),
        encoding="utf-8",
    )
    payload = {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "experiment": "Week 3 Day 1 RGB/BGR single-variable A/B",
        "conditions": {
            "A": {"name": "bgr", "ACT_INPUT_COLOR_ORDER": "bgr"},
            "B": {"name": "rgb", "ACT_INPUT_COLOR_ORDER": "rgb"},
        },
        "fixed": {
            "task": "deposit_coin",
            "env_cfg": "arx_x5",
            "action_type": "joint",
            "checkpoint": CHECKPOINT_DIR.name,
            "seed": 0,
            "layout": 0,
            "num_envs": 1,
            "policy_steps": 300,
            "internal_controls_per_policy_step": 10,
            "temporal_agg": False,
            "camera_order": ["cam_head", "cam_right_wrist", "cam_left_wrist"],
            "stand_piggy_collision": "triangle mesh",
            "ACT_GEOMETRY_MESH_CATEGORIES": "vertical_coin_stand,piggy_bank",
        },
        "checkpoint_files": {
            name: {
                "path": str(CHECKPOINT_DIR / name),
                "size_bytes": (CHECKPOINT_DIR / name).stat().st_size,
                "sha256": sha256(CHECKPOINT_DIR / name),
            }
            for name in ("policy_last.ckpt", "dataset_stats.pkl")
        },
        "repositories": {
            "experiment": {
                "commit": command(["git", "rev-parse", "HEAD"], PROJECT_ROOT),
                "status_short": command(["git", "status", "--short"], PROJECT_ROOT).splitlines(),
            },
            "robodojo": {
                "commit": command(["git", "rev-parse", "HEAD"], ROBODOJO_ROOT),
                "status_short": command(["git", "status", "--short"], ROBODOJO_ROOT).splitlines(),
                "submodules": command(["git", "submodule", "status", "--recursive"], ROBODOJO_ROOT).splitlines(),
            },
            "xpolicylab": {
                "commit": command(["git", "rev-parse", "HEAD"], ROBODOJO_ROOT / "XPolicyLab"),
                "status_short": command(
                    ["git", "status", "--short"], ROBODOJO_ROOT / "XPolicyLab"
                ).splitlines(),
            },
        },
        "run_order": ["bgr", "rgb"],
        "single_variable": "ACT_INPUT_COLOR_ORDER",
        "result_interpretation": (
            "Action differences prove policy sensitivity only; H1 requires improved grasp geometry "
            "or repeatable coin motion."
        ),
    }
    (EXPERIMENT_DIR / "experiment_config.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )
    print("Experiment configuration recorded")


if __name__ == "__main__":
    main()
