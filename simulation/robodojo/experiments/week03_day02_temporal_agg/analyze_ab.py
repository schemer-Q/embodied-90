#!/usr/bin/env python3
"""Compare RGB ACT trajectories with temporal aggregation disabled/enabled."""

import csv
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parent
CONDITIONS = ("false", "true")
BOUNDARIES = (51, 101, 151, 201, 251)
NUM_QUERIES = 50


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_jsonl(path):
    with Path(path).open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def vector_metrics(values):
    velocity = np.diff(values, axis=0)
    acceleration = np.diff(velocity, axis=0)
    jerk = np.diff(acceleration, axis=0)
    return {
        "mean_adjacent_l2": float(np.mean(np.linalg.norm(velocity, axis=1))),
        "max_adjacent_l2": float(np.max(np.linalg.norm(velocity, axis=1))),
        "max_single_dimension_jump": float(np.max(np.abs(velocity))),
        "mean_acceleration_l2": float(np.mean(np.linalg.norm(acceleration, axis=1))),
        "max_acceleration_l2": float(np.max(np.linalg.norm(acceleration, axis=1))),
        "mean_jerk_l2": float(np.mean(np.linalg.norm(jerk, axis=1))),
        "max_jerk_l2": float(np.max(np.linalg.norm(jerk, axis=1))),
    }


def summarize(condition, rows, metadata, integrity):
    actions = np.asarray([row["act_action_14d"] for row in rows], dtype=float)
    tracking = np.asarray([row["max_internal_tracking_error"] for row in rows], dtype=float)
    left_ee = np.asarray([row["end_effector_pose"]["left"][:3] for row in rows], dtype=float)
    gripper = np.asarray([row["left_gripper"] for row in rows], dtype=float)
    surface = np.asarray([row["fingertip_surface"]["minimum_surface_distance_m"] for row in rows])
    alignment = np.asarray([row["fingertip_alignment"]["alignment_error_m"] for row in rows])
    initial_coin = np.asarray(metadata["initial_state"]["coin_pose"]["position"], dtype=float)
    coin = np.asarray([row["coin_pose"]["position"] for row in rows], dtype=float)
    initial_gripper = float(metadata["initial_state"]["actual_joint_positions_14d"][6])
    closing_start = next((index for index, value in enumerate(gripper) if value < initial_gripper - 0.002), None)
    closed = next((index for index, value in enumerate(gripper) if value < 0.01), int(np.argmin(gripper)))
    action_smoothness = vector_metrics(actions)
    ee_smoothness = vector_metrics(left_ee)
    boundary = {}
    for step in BOUNDARIES:
        index = step - 1
        delta = actions[index] - actions[index - 1]
        boundary[str(step)] = {
            "action_jump_l2": float(np.linalg.norm(delta)),
            "max_single_dimension_jump": float(np.max(np.abs(delta))),
            "tracking_error": float(tracking[index]),
        }
    result = {
        "condition": condition,
        "input_color_order": "rgb",
        "temporal_agg": condition == "true",
        "policy_server_requests": len(rows),
        "network_action_queries": len(rows) if condition == "true" else 6,
        "policy_steps": len(rows),
        "internal_records": integrity["internal_records"],
        "missing_policy_steps": integrity["missing_policy_steps"],
        "invalid_values": integrity["invalid_values"],
        "videos_complete": integrity["videos_complete"],
        "final_success": integrity["final_success"],
        "final_score": integrity["final_score"],
        "initial_coin_position_m": initial_coin.tolist(),
        "action_smoothness": action_smoothness,
        "left_ee_smoothness": ee_smoothness,
        "chunk_boundaries": boundary,
        "max_tracking_error": float(np.max(tracking)),
        "max_tracking_error_step": int(np.argmax(tracking)) + 1,
        "left_gripper_closing_start": None if closing_start is None else closing_start + 1,
        "left_gripper_noticeably_closed": closed + 1,
        "closure_surface_distance_m": float(surface[closed]),
        "closure_alignment_error_m": float(alignment[closed]),
        "minimum_surface_distance_m": float(np.min(surface)),
        "minimum_alignment_error_m": float(np.min(alignment)),
        "max_coin_displacement_m": float(np.max(np.linalg.norm(coin - initial_coin, axis=1))),
        "max_coin_lift_m": float(np.max(coin[:, 2] - initial_coin[2])),
        "all_actions_finite": bool(np.isfinite(actions).all()),
    }
    (ROOT / condition / "trajectory_summary.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    return result, actions, tracking, left_ee, coin, surface, alignment


def main():
    data = {}
    metadata = {}
    integrity = {}
    for condition in CONDITIONS:
        directory = ROOT / condition
        data[condition] = load_jsonl(directory / "full_episode_trace.jsonl")
        metadata[condition] = load_json(directory / "full_episode_metadata.json")
        integrity[condition] = load_json(directory / "full_episode_summary.json")
        if len(data[condition]) != 300:
            raise RuntimeError(f"{condition} has {len(data[condition])} policy steps")

    results = {
        condition: summarize(condition, data[condition], metadata[condition], integrity[condition])
        for condition in CONDITIONS
    }
    summaries = {condition: results[condition][0] for condition in CONDITIONS}
    actions = {condition: results[condition][1] for condition in CONDITIONS}
    tracking = {condition: results[condition][2] for condition in CONDITIONS}
    left_ee = {condition: results[condition][3] for condition in CONDITIONS}
    coin = {condition: results[condition][4] for condition in CONDITIONS}
    surface = {condition: results[condition][5] for condition in CONDITIONS}
    alignment = {condition: results[condition][6] for condition in CONDITIONS}

    initial_delta = {
        "coin_position_max_abs_m": float(np.max(np.abs(
            np.asarray(metadata["true"]["initial_state"]["coin_pose"]["position"])
            - np.asarray(metadata["false"]["initial_state"]["coin_pose"]["position"])
        ))),
        "robot_qpos_max_abs": float(np.max(np.abs(
            np.asarray(metadata["true"]["initial_state"]["actual_joint_positions_14d"])
            - np.asarray(metadata["false"]["initial_state"]["actual_joint_positions_14d"])
        ))),
    }

    fields = [
        "policy_step", "action_l2_true_minus_false", "false_adjacent_action_l2",
        "true_adjacent_action_l2", "false_tracking_error", "true_tracking_error",
        "false_surface_distance_m", "true_surface_distance_m",
        "false_alignment_error_m", "true_alignment_error_m",
        "false_coin_z_delta_m", "true_coin_z_delta_m",
    ]
    with (ROOT / "paired_comparison.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for index in range(300):
            writer.writerow({
                "policy_step": index + 1,
                "action_l2_true_minus_false": np.linalg.norm(actions["true"][index] - actions["false"][index]),
                "false_adjacent_action_l2": "" if index == 0 else np.linalg.norm(actions["false"][index] - actions["false"][index - 1]),
                "true_adjacent_action_l2": "" if index == 0 else np.linalg.norm(actions["true"][index] - actions["true"][index - 1]),
                "false_tracking_error": tracking["false"][index],
                "true_tracking_error": tracking["true"][index],
                "false_surface_distance_m": surface["false"][index],
                "true_surface_distance_m": surface["true"][index],
                "false_alignment_error_m": alignment["false"][index],
                "true_alignment_error_m": alignment["true"][index],
                "false_coin_z_delta_m": data["false"][index]["coin_z_delta"],
                "true_coin_z_delta_m": data["true"][index]["coin_z_delta"],
            })

    with (ROOT / "aggregation_schedule.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["policy_step", "candidate_count", "oldest_weight", "newest_weight"], lineterminator="\n")
        writer.writeheader()
        for step in range(1, 301):
            count = min(step, NUM_QUERIES)
            weights = np.exp(-0.01 * np.arange(count))
            weights /= weights.sum()
            writer.writerow({"policy_step": step, "candidate_count": count, "oldest_weight": weights[0], "newest_weight": weights[-1]})

    paired = {
        "single_variable": "temporal_agg",
        "fixed_input_color_order": "rgb",
        "initial_state_delta": initial_delta,
        "initial_state_match": initial_delta["coin_position_max_abs_m"] <= 1e-5 and initial_delta["robot_qpos_max_abs"] <= 1e-5,
        "conditions_complete": all(
            summaries[c]["policy_steps"] == 300
            and summaries[c]["internal_records"] == 3000
            and summaries[c]["invalid_values"] == 0
            and summaries[c]["videos_complete"]
            for c in CONDITIONS
        ),
        "false": summaries["false"],
        "true": summaries["true"],
        "true_minus_false": {
            "mean_adjacent_action_l2": summaries["true"]["action_smoothness"]["mean_adjacent_l2"] - summaries["false"]["action_smoothness"]["mean_adjacent_l2"],
            "max_adjacent_action_l2": summaries["true"]["action_smoothness"]["max_adjacent_l2"] - summaries["false"]["action_smoothness"]["max_adjacent_l2"],
            "max_tracking_error": summaries["true"]["max_tracking_error"] - summaries["false"]["max_tracking_error"],
            "closure_surface_distance_m": summaries["true"]["closure_surface_distance_m"] - summaries["false"]["closure_surface_distance_m"],
            "closure_alignment_error_m": summaries["true"]["closure_alignment_error_m"] - summaries["false"]["closure_alignment_error_m"],
            "max_coin_displacement_m": summaries["true"]["max_coin_displacement_m"] - summaries["false"]["max_coin_displacement_m"],
            "max_coin_lift_m": summaries["true"]["max_coin_lift_m"] - summaries["false"]["max_coin_lift_m"],
        },
    }
    (ROOT / "paired_summary.json").write_text(json.dumps(paired, indent=2), encoding="utf-8")

    steps = np.arange(1, 301)
    fig, axes = plt.subplots(4, 1, figsize=(14, 13), sharex=True)
    for condition in CONDITIONS:
        adjacent = np.r_[np.nan, np.linalg.norm(np.diff(actions[condition], axis=0), axis=1)]
        axes[0].plot(steps, adjacent, label=condition)
        axes[1].plot(steps, tracking[condition], label=condition)
        axes[2].plot(steps, np.r_[np.nan, np.linalg.norm(np.diff(left_ee[condition], axis=0), axis=1)], label=condition)
        axes[3].plot(steps, np.linalg.norm(coin[condition] - coin[condition][0], axis=1), label=condition)
    for axis in axes:
        for boundary in BOUNDARIES:
            axis.axvline(boundary, color="gray", linestyle=":", linewidth=0.8)
        axis.grid(alpha=0.25)
        axis.legend()
    axes[0].set_ylabel("action jump L2")
    axes[1].set_ylabel("tracking error")
    axes[2].set_ylabel("left EE step (m)")
    axes[3].set_ylabel("coin displacement (m)")
    axes[3].set_xlabel("policy step")
    fig.tight_layout()
    fig.savefig(ROOT / "action_smoothness_plot.png", dpi=160)
    fig.savefig(ROOT / "trajectory_comparison.png", dpi=160)
    plt.close(fig)
    print("temporal aggregation A/B analysis complete")


if __name__ == "__main__":
    main()
