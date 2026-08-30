#!/usr/bin/env python3
"""Summarize the RGB + official-stand Coin-X5 repair run."""

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


HERE = Path(__file__).resolve().parent
RUN = HERE / "fixed"


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


rows = load_jsonl(RUN / "full_episode_trace.jsonl")
internal = load_jsonl(RUN / "full_episode_internal.jsonl")
metadata = load_json(RUN / "full_episode_metadata.json")
integrity = load_json(RUN / "full_episode_summary.json")
assert len(rows) == 300 and len(internal) == 3000
assert integrity["missing_policy_steps"] == [] and integrity["invalid_values"] == 0
assert integrity["videos_complete"] and integrity["result_consistent"]

actions = np.asarray([row["act_action_14d"] for row in rows], dtype=float)
coin = np.asarray([row["coin_pose"]["position"] for row in rows], dtype=float)
initial_coin = np.asarray(metadata["initial_state"]["coin_pose"]["position"], dtype=float)
surface = np.asarray([row["fingertip_surface"]["minimum_surface_distance_m"] for row in rows], dtype=float)
alignment = np.asarray([row["fingertip_alignment"]["alignment_error_m"] for row in rows], dtype=float)
gripper = np.asarray([row["left_gripper"] for row in rows], dtype=float)
tracking = np.asarray([row["max_internal_tracking_error"] for row in rows], dtype=float)
initial_gripper = float(metadata["initial_state"]["actual_joint_positions_14d"][6])
closing = next((i for i, value in enumerate(gripper) if value < initial_gripper - 0.002), None)
closed = next((i for i, value in enumerate(gripper) if value < 0.01), int(np.argmin(gripper)))
displacement = np.linalg.norm(coin - initial_coin, axis=1)
lift = coin[:, 2] - initial_coin[2]

summary = {
    "run_id": metadata["run_id"],
    "fix": {
        "input_color_order": metadata["randomness_environment"].get("ACT_INPUT_COLOR_ORDER"),
        "geometry_mesh_categories": metadata["randomness_environment"].get("ACT_GEOMETRY_MESH_CATEGORIES"),
        "temporal_agg": False,
    },
    "policy_steps": len(rows),
    "internal_records": len(internal),
    "invalid_values": integrity["invalid_values"],
    "videos_complete": integrity["videos_complete"],
    "final_success": integrity["final_success"],
    "final_score": integrity["final_score"],
    "left_gripper_closing_start": None if closing is None else closing + 1,
    "left_gripper_noticeably_closed": closed + 1,
    "closure_surface_distance_m": float(surface[closed]),
    "closure_alignment_error_m": float(alignment[closed]),
    "minimum_surface_distance_m": float(surface.min()),
    "minimum_surface_distance_step": int(surface.argmin()) + 1,
    "minimum_alignment_error_m": float(alignment.min()),
    "max_coin_displacement_m": float(displacement.max()),
    "max_coin_displacement_step": int(displacement.argmax()) + 1,
    "max_coin_lift_m": float(lift.max()),
    "max_coin_lift_step": int(lift.argmax()) + 1,
    "max_tracking_error_rad": float(tracking.max()),
    "max_tracking_error_step": int(tracking.argmax()) + 1,
    "actions_finite": bool(np.isfinite(actions).all()),
    "lift_threshold_m": 0.08,
    "lift_threshold_reached": bool(lift.max() > 0.08),
}
(HERE / "fixed_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

steps = np.arange(1, 301)
fig, axes = plt.subplots(3, 1, figsize=(11, 9), sharex=True)
axes[0].plot(steps, gripper * 1000)
axes[0].set_ylabel("left gripper (mm)")
axes[1].plot(steps, displacement * 1000, label="displacement")
axes[1].plot(steps, lift * 1000, label="z delta")
axes[1].legend()
axes[1].set_ylabel("coin motion (mm)")
axes[2].plot(steps, surface * 1000, label="surface distance")
axes[2].plot(steps, alignment * 1000, label="alignment error")
axes[2].legend()
axes[2].set_ylabel("geometry (mm)")
axes[2].set_xlabel("policy step")
for axis in axes:
    axis.grid(alpha=0.25)
fig.tight_layout()
fig.savefig(HERE / "fixed_trajectory.png", dpi=160)
print(json.dumps(summary, indent=2))
