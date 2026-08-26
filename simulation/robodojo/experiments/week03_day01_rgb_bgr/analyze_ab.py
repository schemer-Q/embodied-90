#!/usr/bin/env python3
"""Compare complete BGR and RGB Coin-X5 trajectories."""

import csv
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


PROJECT_ROOT = Path("/home/nvidia/embodied-90")
EXPERIMENT_DIR = PROJECT_ROOT / "simulation/robodojo/experiments/week03_day01_rgb_bgr"
DAY5_DIR = PROJECT_ROOT / "simulation/robodojo/validation/week02_day05"
CONDITIONS = ("bgr", "rgb")
CHUNK_BOUNDARIES = (51, 101, 151, 201, 251)


def load_jsonl(path):
    with Path(path).open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def first_step(rows, predicate):
    return next((row["policy_step"] for row in rows if predicate(row)), None)


def summarize(condition, rows, metadata, integrity):
    initial_coin = np.asarray(metadata["initial_state"]["coin_pose"]["position"], dtype=float)
    coin_positions = np.asarray([row["coin_pose"]["position"] for row in rows], dtype=float)
    actions = np.asarray([row["act_action_14d"] for row in rows], dtype=float)
    left_gripper = np.asarray([row["left_gripper"] for row in rows], dtype=float)
    initial_gripper = float(metadata["initial_state"]["actual_joint_positions_14d"][6])
    surface_distance = np.asarray(
        [row["fingertip_surface"]["minimum_surface_distance_m"] for row in rows],
        dtype=float,
    )
    alignment_error = np.asarray(
        [row["fingertip_alignment"]["alignment_error_m"] for row in rows],
        dtype=float,
    )
    closing_start = first_step(rows, lambda row: row["left_gripper"] < initial_gripper - 0.002)
    noticeably_closed = first_step(rows, lambda row: row["left_gripper"] < 0.01)
    close_index = (noticeably_closed or int(np.argmin(left_gripper)) + 1) - 1
    displacement = np.linalg.norm(coin_positions - initial_coin, axis=1)
    tracking = np.asarray([row["max_internal_tracking_error"] for row in rows], dtype=float)
    result = {
        "condition": condition,
        "input_color_order": condition,
        "policy_steps": len(rows),
        "internal_records": integrity["internal_records"],
        "missing_policy_steps": integrity["missing_policy_steps"],
        "invalid_values": integrity["invalid_values"],
        "videos_complete": integrity["videos_complete"],
        "final_success": integrity["final_success"],
        "final_score": integrity["final_score"],
        "initial_coin_position_m": initial_coin.tolist(),
        "max_coin_displacement_m": float(np.max(displacement)),
        "max_coin_displacement_step": int(np.argmax(displacement)) + 1,
        "max_coin_lift_m": float(np.max(coin_positions[:, 2] - initial_coin[2])),
        "max_coin_lift_step": int(np.argmax(coin_positions[:, 2] - initial_coin[2])) + 1,
        "left_gripper_closing_start": closing_start,
        "left_gripper_noticeably_closed": noticeably_closed,
        "minimum_fingertip_surface_distance_m": float(np.min(surface_distance)),
        "minimum_fingertip_surface_distance_step": int(np.argmin(surface_distance)) + 1,
        "minimum_fingertip_midpoint_alignment_error_m": float(np.min(alignment_error)),
        "minimum_fingertip_midpoint_alignment_step": int(np.argmin(alignment_error)) + 1,
        "closure_geometry": {
            "policy_step": close_index + 1,
            "minimum_surface_distance_m": float(surface_distance[close_index]),
            "fingertip_midpoint_alignment_error_m": float(alignment_error[close_index]),
            "coin_minus_fingertip_midpoint_m": rows[close_index]["fingertip_alignment"][
                "coin_minus_fingertip_midpoint_m"
            ],
            "left_gripper_m": float(left_gripper[close_index]),
        },
        "max_tracking_error": float(np.max(tracking)),
        "max_tracking_error_step": int(np.argmax(tracking)) + 1,
        "chunk_boundary_tracking_error": {
            str(step): float(tracking[step - 1]) for step in CHUNK_BOUNDARIES
        },
        "all_actions_finite": bool(np.isfinite(actions).all()),
    }
    (EXPERIMENT_DIR / condition / "trajectory_summary.json").write_text(
        json.dumps(result, indent=2),
        encoding="utf-8",
    )
    return result


def main():
    rows = {}
    metadata = {}
    integrity = {}
    summaries = {}
    for condition in CONDITIONS:
        directory = EXPERIMENT_DIR / condition
        rows[condition] = load_jsonl(directory / "full_episode_trace.jsonl")
        metadata[condition] = json.loads(
            (directory / "full_episode_metadata.json").read_text(encoding="utf-8")
        )
        integrity[condition] = json.loads(
            (directory / "full_episode_summary.json").read_text(encoding="utf-8")
        )
        summaries[condition] = summarize(
            condition,
            rows[condition],
            metadata[condition],
            integrity[condition],
        )

    if len(rows["bgr"]) != 300 or len(rows["rgb"]) != 300:
        raise RuntimeError("Both conditions must contain exactly 300 policy steps")

    actions = {
        condition: np.asarray([row["act_action_14d"] for row in rows[condition]], dtype=float)
        for condition in CONDITIONS
    }
    action_l2 = np.linalg.norm(actions["rgb"] - actions["bgr"], axis=1)
    coin = {
        condition: np.asarray([row["coin_pose"]["position"] for row in rows[condition]], dtype=float)
        for condition in CONDITIONS
    }
    surface = {
        condition: np.asarray(
            [row["fingertip_surface"]["minimum_surface_distance_m"] for row in rows[condition]],
            dtype=float,
        )
        for condition in CONDITIONS
    }
    alignment = {
        condition: np.asarray(
            [row["fingertip_alignment"]["alignment_error_m"] for row in rows[condition]],
            dtype=float,
        )
        for condition in CONDITIONS
    }
    tracking = {
        condition: np.asarray([row["max_internal_tracking_error"] for row in rows[condition]], dtype=float)
        for condition in CONDITIONS
    }
    left_ee = {
        condition: np.asarray([row["end_effector_pose"]["left"][:3] for row in rows[condition]], dtype=float)
        for condition in CONDITIONS
    }
    initial_state_delta = {
        "coin_position_max_abs_m": float(
            np.max(
                np.abs(
                    np.asarray(metadata["rgb"]["initial_state"]["coin_pose"]["position"], dtype=float)
                    - np.asarray(metadata["bgr"]["initial_state"]["coin_pose"]["position"], dtype=float)
                )
            )
        ),
        "robot_qpos_max_abs": float(
            np.max(
                np.abs(
                    np.asarray(
                        metadata["rgb"]["initial_state"]["actual_joint_positions_14d"], dtype=float
                    )
                    - np.asarray(
                        metadata["bgr"]["initial_state"]["actual_joint_positions_14d"], dtype=float
                    )
                )
            )
        ),
    }

    with (EXPERIMENT_DIR / "paired_comparison.csv").open(
        "w", newline="", encoding="utf-8"
    ) as stream:
        fields = [
            "policy_step",
            "action_l2_rgb_minus_bgr",
            "bgr_left_gripper_m",
            "rgb_left_gripper_m",
            "bgr_surface_distance_m",
            "rgb_surface_distance_m",
            "bgr_alignment_error_m",
            "rgb_alignment_error_m",
            "bgr_coin_z_delta_m",
            "rgb_coin_z_delta_m",
            "bgr_tracking_error",
            "rgb_tracking_error",
        ]
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for index in range(300):
            writer.writerow(
                {
                    "policy_step": index + 1,
                    "action_l2_rgb_minus_bgr": action_l2[index],
                    "bgr_left_gripper_m": rows["bgr"][index]["left_gripper"],
                    "rgb_left_gripper_m": rows["rgb"][index]["left_gripper"],
                    "bgr_surface_distance_m": surface["bgr"][index],
                    "rgb_surface_distance_m": surface["rgb"][index],
                    "bgr_alignment_error_m": alignment["bgr"][index],
                    "rgb_alignment_error_m": alignment["rgb"][index],
                    "bgr_coin_z_delta_m": rows["bgr"][index]["coin_z_delta"],
                    "rgb_coin_z_delta_m": rows["rgb"][index]["coin_z_delta"],
                    "bgr_tracking_error": tracking["bgr"][index],
                    "rgb_tracking_error": tracking["rgb"][index],
                }
            )

    day5_rows = load_jsonl(DAY5_DIR / "full_episode_trace.jsonl")
    day5_metadata = json.loads((DAY5_DIR / "full_episode_metadata.json").read_text(encoding="utf-8"))
    day5_actions = np.asarray([row["act_action_14d"] for row in day5_rows], dtype=float)
    day5_action_l2 = np.linalg.norm(actions["bgr"] - day5_actions, axis=1)
    day5_coin = np.asarray([row["coin_pose"]["position"] for row in day5_rows], dtype=float)
    day5_initial = np.asarray(day5_metadata["initial_state"]["coin_pose"]["position"], dtype=float)
    day5_max_lift = float(np.max(day5_coin[:, 2] - day5_initial[2]))
    baseline_reproduction = {
        "day5_final_success": False,
        "day5_final_score": 0.0,
        "day5_max_coin_lift_m": day5_max_lift,
        "initial_coin_position_max_abs_m": float(
            np.max(
                np.abs(
                    np.asarray(metadata["bgr"]["initial_state"]["coin_pose"]["position"], dtype=float)
                    - day5_initial
                )
            )
        ),
        "action_l2_mean": float(np.mean(day5_action_l2)),
        "action_l2_max": float(np.max(day5_action_l2)),
        "action_l2_first_60_mean": float(np.mean(day5_action_l2[:60])),
        "same_final_result": (
            summaries["bgr"]["final_success"] is False
            and summaries["bgr"]["final_score"] == 0.0
        ),
        "coin_lift_difference_m": float(
            summaries["bgr"]["max_coin_lift_m"] - day5_max_lift
        ),
    }
    baseline_reproduction["behavioral_baseline_reproduced"] = bool(
        baseline_reproduction["same_final_result"]
        and baseline_reproduction["initial_coin_position_max_abs_m"] <= 1e-5
        and summaries["bgr"]["max_coin_lift_m"] < 1e-5
    )

    paired_summary = {
        "conditions_complete": all(
            summaries[condition]["policy_steps"] == 300
            and summaries[condition]["internal_records"] == 3000
            and summaries[condition]["missing_policy_steps"] == []
            and summaries[condition]["invalid_values"] == 0
            and summaries[condition]["videos_complete"]
            for condition in CONDITIONS
        ),
        "single_variable": "ACT_INPUT_COLOR_ORDER",
        "initial_state_delta": initial_state_delta,
        "initial_state_match": (
            initial_state_delta["coin_position_max_abs_m"] <= 1e-5
            and initial_state_delta["robot_qpos_max_abs"] <= 1e-5
        ),
        "action_difference": {
            "mean_l2": float(np.mean(action_l2)),
            "median_l2": float(np.median(action_l2)),
            "max_l2": float(np.max(action_l2)),
            "max_l2_step": int(np.argmax(action_l2)) + 1,
            "first_60_mean_l2": float(np.mean(action_l2[:60])),
            "steps_above_1e-6": int(np.count_nonzero(action_l2 > 1e-6)),
        },
        "bgr": summaries["bgr"],
        "rgb": summaries["rgb"],
        "rgb_minus_bgr": {
            "minimum_surface_distance_m": (
                summaries["rgb"]["minimum_fingertip_surface_distance_m"]
                - summaries["bgr"]["minimum_fingertip_surface_distance_m"]
            ),
            "minimum_alignment_error_m": (
                summaries["rgb"]["minimum_fingertip_midpoint_alignment_error_m"]
                - summaries["bgr"]["minimum_fingertip_midpoint_alignment_error_m"]
            ),
            "closure_alignment_error_m": (
                summaries["rgb"]["closure_geometry"]["fingertip_midpoint_alignment_error_m"]
                - summaries["bgr"]["closure_geometry"]["fingertip_midpoint_alignment_error_m"]
            ),
            "max_coin_displacement_m": (
                summaries["rgb"]["max_coin_displacement_m"]
                - summaries["bgr"]["max_coin_displacement_m"]
            ),
            "max_coin_lift_m": (
                summaries["rgb"]["max_coin_lift_m"]
                - summaries["bgr"]["max_coin_lift_m"]
            ),
            "max_tracking_error": (
                summaries["rgb"]["max_tracking_error"]
                - summaries["bgr"]["max_tracking_error"]
            ),
        },
        "day5_bgr_reproduction": baseline_reproduction,
        "interpretation_rule": (
            "Action change alone proves color sensitivity, not H1. H1 requires improved grasp "
            "geometry or repeatable coin motion; one pair cannot establish repeatability."
        ),
    }
    (EXPERIMENT_DIR / "paired_summary.json").write_text(
        json.dumps(paired_summary, indent=2),
        encoding="utf-8",
    )

    steps = np.arange(1, 301)
    fig, axes = plt.subplots(5, 1, figsize=(14, 16), sharex=True)
    axes[0].plot(steps, action_l2, color="black")
    axes[0].set_ylabel("action L2")
    for condition in CONDITIONS:
        axes[1].plot(steps, surface[condition], label=condition.upper())
        axes[2].plot(steps, alignment[condition], label=condition.upper())
        axes[3].plot(
            steps,
            coin[condition][:, 2] - coin[condition][0, 2],
            label=condition.upper(),
        )
        axes[4].plot(
            steps,
            np.linalg.norm(left_ee[condition] - left_ee[condition][0], axis=1),
            label=condition.upper(),
        )
    axes[1].set_ylabel("surface distance (m)")
    axes[2].set_ylabel("midpoint error (m)")
    axes[3].set_ylabel("coin dz (m)")
    axes[4].set_ylabel("left EE displacement (m)")
    axes[4].set_xlabel("policy step")
    for axis in axes:
        for boundary in CHUNK_BOUNDARIES:
            axis.axvline(boundary, color="gray", linestyle=":", linewidth=0.8)
        axis.grid(alpha=0.25)
        if axis is not axes[0]:
            axis.legend()
    fig.tight_layout()
    fig.savefig(EXPERIMENT_DIR / "comparison_plot.png", dpi=160)
    plt.close(fig)
    print("A/B comparison complete")


if __name__ == "__main__":
    main()
