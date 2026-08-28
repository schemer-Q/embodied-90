#!/usr/bin/env python3
"""Validate the stand-collision single variable and summarize replay outcomes."""

import csv
import hashlib
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


HERE = Path(__file__).resolve().parent


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def summarize(condition):
    directory = HERE / condition
    policy = read_jsonl(directory / "full_episode_trace.jsonl")
    internal = read_jsonl(directory / "full_episode_internal.jsonl")
    objects = read_jsonl(directory / "object_trace.jsonl")
    contacts = read_jsonl(directory / "contact_trace.jsonl")
    result = read_json(directory / "result.json")
    snapshot = read_json(directory / "stage_snapshot.json")
    initial = np.asarray(snapshot["assets"]["coin0"]["pose"]["position_m"], dtype=float)
    positions = np.asarray([row["coin_pose"]["position_m"] for row in objects], dtype=float)
    displacement = np.linalg.norm(positions - initial, axis=1)
    lift = positions[:, 2] - initial[2]
    surface = np.asarray([row["fingertip_surface"]["minimum_surface_distance_m"] for row in policy])
    tracking = []
    for row in internal:
        target = row.get("written_joint_targets_14d")
        actual = row.get("actual_joint_positions_14d")
        if target is not None and actual is not None:
            tracking.append(float(np.max(np.abs(np.asarray(actual) - np.asarray(target)))))
    pair_counts = {}
    max_impulse = 0.0
    min_separation = None
    first_contacts = {}
    for row in contacts:
        pair = row["pair"]
        pair_counts[pair] = pair_counts.get(pair, 0) + 1
        first_contacts.setdefault(pair, {"policy_step": row["policy_step"], "internal_step": row["internal_step"]})
        for point in row["contacts"]:
            max_impulse = max(max_impulse, abs(point["impulse_ns"]))
            separation = point["separation_m"]
            min_separation = separation if min_separation is None else min(min_separation, separation)
    return {
        "condition": condition,
        "policy_steps": len(policy),
        "internal_records": len(internal),
        "replay_actions": len((directory / "replay_exec.log").read_text(encoding="utf-8").splitlines()),
        "invalid_values": sum(not np.all(np.isfinite(row["act_action_14d"])) for row in policy),
        "final_success": bool(result.get("success_rate", 0.0)),
        "final_score": float(result.get("score", 0.0)),
        "initial_coin_position_m": initial.tolist(),
        "initial_robot_qpos_14d": read_json(directory / "stage_snapshot.json")["robot"]["actual_joint_positions_14d"],
        "minimum_fingertip_surface_distance_m": float(surface.min()),
        "minimum_surface_distance_policy_step": int(policy[int(surface.argmin())]["policy_step"]),
        "max_coin_displacement_m": float(displacement.max()),
        "max_coin_lift_m": float(lift.max()),
        "max_coin_drop_m": float(lift.min()),
        "max_tracking_error_rad": max(tracking),
        "contact_event_count": len(contacts),
        "contact_pair_counts": pair_counts,
        "first_contacts": first_contacts,
        "max_contact_impulse_ns": max_impulse,
        "minimum_reported_separation_m": min_separation,
        "coin_positions": positions,
    }


manifest = read_json(HERE / "replay_manifest.json")
assert manifest["replay_sha256"] == sha256(HERE / "replay_actions.jsonl")
a = summarize("triangle_mesh")
b = summarize("official")
for result in (a, b):
    assert result["policy_steps"] == 300
    assert result["internal_records"] == 3000
    assert result["replay_actions"] == 300
    assert result["invalid_values"] == 0

snap_a = read_json(HERE / "triangle_mesh/stage_snapshot.json")
snap_b = read_json(HERE / "official/stage_snapshot.json")
initial_coin_equal = np.allclose(a["initial_coin_position_m"], b["initial_coin_position_m"], atol=1e-6, rtol=0)
initial_robot_equal = np.allclose(a["initial_robot_qpos_14d"], b["initial_robot_qpos_14d"], atol=1e-6, rtol=0)
piggy_equal = snap_a["assets"]["piggy_bank"] == snap_b["assets"]["piggy_bank"]
coin_equal = snap_a["assets"]["coin0"] == snap_b["assets"]["coin0"]
stand_a = snap_a["assets"]["vertical_coin_stand"]["colliders"]
stand_b = snap_b["assets"]["vertical_coin_stand"]["colliders"]
stand_changed = stand_a != stand_b
stage_diff = {
    "only_intended_variable": bool(initial_coin_equal and initial_robot_equal and piggy_equal and coin_equal and stand_changed),
    "initial_coin_equal_atol_1e-6": bool(initial_coin_equal),
    "initial_robot_equal_atol_1e-6": bool(initial_robot_equal),
    "coin_asset_snapshot_equal": coin_equal,
    "piggy_bank_snapshot_equal": piggy_equal,
    "stand_collider_snapshot_changed": stand_changed,
    "triangle_mesh_stand_colliders": stand_a,
    "official_stand_colliders": stand_b,
}
(HERE / "stage_diff.json").write_text(json.dumps(stage_diff, indent=2) + "\n", encoding="utf-8")
assert stage_diff["only_intended_variable"], json.dumps(stage_diff, indent=2)

compact = []
for result in (a, b):
    compact.append({key: value for key, value in result.items() if key != "coin_positions"})
delta_displacement = b["max_coin_displacement_m"] - a["max_coin_displacement_m"]
delta_lift = b["max_coin_lift_m"] - a["max_coin_lift_m"]
interaction_a = a["contact_pair_counts"].get("coin_fingertip", 0) > 0 or a["max_coin_displacement_m"] > 0.005
interaction_b = b["contact_pair_counts"].get("coin_fingertip", 0) > 0 or b["max_coin_displacement_m"] > 0.005
if interaction_a and interaction_b:
    relative_motion_delta = abs(delta_displacement) / max(a["max_coin_displacement_m"], b["max_coin_displacement_m"], 1e-9)
    h3 = "supported" if relative_motion_delta > 0.25 else "significantly_weakened"
else:
    h3 = "supported" if interaction_a != interaction_b else "inconclusive"
summary = {
    "replay_sha256": manifest["replay_sha256"],
    "stage_single_variable_pass": stage_diff["only_intended_variable"],
    "conditions": compact,
    "official_minus_triangle_mesh": {
        "max_coin_displacement_m": delta_displacement,
        "max_coin_lift_m": delta_lift,
    },
    "interaction_reached": {"triangle_mesh": interaction_a, "official": interaction_b},
    "h3_assessment": h3,
}
(HERE / "paired_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

with (HERE / "contact_comparison.csv").open("w", newline="", encoding="utf-8") as stream:
    writer = csv.DictWriter(stream, fieldnames=[
        "condition", "minimum_fingertip_surface_distance_m", "contact_event_count",
        "coin_fingertip_events", "coin_stand_events", "max_contact_impulse_ns",
        "max_coin_displacement_m", "max_coin_lift_m", "max_tracking_error_rad",
        "final_success", "final_score",
    ])
    writer.writeheader()
    for result in (a, b):
        writer.writerow({
            "condition": result["condition"],
            "minimum_fingertip_surface_distance_m": result["minimum_fingertip_surface_distance_m"],
            "contact_event_count": result["contact_event_count"],
            "coin_fingertip_events": result["contact_pair_counts"].get("coin_fingertip", 0),
            "coin_stand_events": result["contact_pair_counts"].get("coin_stand", 0),
            "max_contact_impulse_ns": result["max_contact_impulse_ns"],
            "max_coin_displacement_m": result["max_coin_displacement_m"],
            "max_coin_lift_m": result["max_coin_lift_m"],
            "max_tracking_error_rad": result["max_tracking_error_rad"],
            "final_success": result["final_success"],
            "final_score": result["final_score"],
        })

fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
for result, label in ((a, "triangle mesh"), (b, "official")):
    positions = result["coin_positions"]
    displacement = np.linalg.norm(positions - positions[0], axis=1) * 1000
    lift = (positions[:, 2] - positions[0, 2]) * 1000
    x = np.arange(len(positions)) / 10 + 1
    axes[0].plot(x, displacement, label=label)
    axes[1].plot(x, lift, label=label)
axes[0].set_ylabel("coin displacement (mm)")
axes[1].set_ylabel("coin z delta (mm)")
axes[1].set_xlabel("policy step")
for axis in axes:
    axis.grid(alpha=0.25)
    axis.legend()
fig.tight_layout()
fig.savefig(HERE / "trajectory_comparison.png", dpi=160)
print(json.dumps(summary, indent=2))
