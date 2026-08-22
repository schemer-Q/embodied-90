#!/usr/bin/env python3
"""Validate and summarize the Week 2 Day 4 runtime action trace."""

import argparse
import csv
import json
from pathlib import Path

import numpy as np


def load_jsonl(path):
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def maximum_abs(values):
    array = np.asarray(values, dtype=float)
    return float(np.max(np.abs(array))) if array.size else 0.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", type=Path, required=True)
    args = parser.parse_args()
    output_dir = args.dir
    rows = load_jsonl(output_dir / "action_trace.jsonl")
    metadata = json.loads((output_dir / "action_trace_metadata.json").read_text(encoding="utf-8"))
    if not rows:
        raise RuntimeError("action_trace.jsonl contains no records")

    csv_fields = [
        "policy_step", "internal_step", "act_chunk_number", "act_chunk_index", "act_chunk_refresh",
        *[f"raw_action_{index}" for index in range(14)],
        *[f"left_arm_target_{index}" for index in range(6)],
        "left_gripper_normalized", "left_gripper_physical_target",
        *[f"right_arm_target_{index}" for index in range(6)],
        "right_gripper_normalized", "right_gripper_physical_target",
        "written_joint_targets", "actual_joint_positions", "tracking_error",
        "left_ee_z", "right_ee_z", "coin_z",
    ]
    with (output_dir / "action_trace.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=csv_fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            action = row["denormalized_action_14d"]
            converted = row["converted_control_info"]
            csv_row = {
                "policy_step": row["policy_step"],
                "internal_step": row["internal_step"],
                "act_chunk_number": row["act_chunk_number"],
                "act_chunk_index": row["act_chunk_index"],
                "act_chunk_refresh": row["act_chunk_refresh"],
                "left_gripper_normalized": row["left_gripper_normalized"],
                "left_gripper_physical_target": converted["left_ee_joint_state"]["position"][0],
                "right_gripper_normalized": row["right_gripper_normalized"],
                "right_gripper_physical_target": converted["right_ee_joint_state"]["position"][0],
                "written_joint_targets": json.dumps(row["written_joint_targets"], separators=(",", ":")),
                "actual_joint_positions": json.dumps(row["actual_joint_positions"], separators=(",", ":")),
                "tracking_error": json.dumps(row["tracking_error"], separators=(",", ":")),
                "left_ee_z": row["end_effector_z"]["left"],
                "right_ee_z": row["end_effector_z"]["right"],
                "coin_z": row["coin_z"],
            }
            csv_row.update({f"raw_action_{i}": action[i] for i in range(14)})
            csv_row.update({f"left_arm_target_{i}": action[i] for i in range(6)})
            csv_row.update({f"right_arm_target_{i}": action[i + 7] for i in range(6)})
            writer.writerow(csv_row)

    policy_steps = sorted({row["policy_step"] for row in rows})
    counts = {step: sum(row["policy_step"] == step for row in rows) for step in policy_steps}
    final_rows = [row for row in rows if row["internal_step"] == 10]
    all_finite = all(
        np.isfinite(row["denormalized_action_14d"]).all()
        and np.isfinite(row["written_joint_targets"]).all()
        and np.isfinite(row["actual_joint_positions"]).all()
        for row in rows
    )
    validation_pass = all(row["validation_pass"] for row in rows)
    ten_steps_each = all(count == 10 for count in counts.values())
    buffer_write_error = maximum_abs([
        np.asarray(row["written_joint_targets"]) - np.asarray(row["controller_output_14d"])
        for row in rows
    ])
    tracking_error = np.asarray([row["tracking_error"] for row in rows], dtype=float)
    max_tracking_by_dim = np.max(np.abs(tracking_error), axis=0).tolist()

    gripper = {}
    for side, action_index, physical_index in (("left", 6, 6), ("right", 13, 13)):
        normalized = np.asarray([row["denormalized_action_14d"][action_index] for row in final_rows])
        converted = np.asarray([
            row["converted_control_info"][f"{side}_ee_joint_state"]["position"][0]
            for row in final_rows
        ])
        written = np.asarray([row["written_joint_targets"][physical_index] for row in rows])
        actual = np.asarray([row["actual_joint_positions"][physical_index] for row in rows])
        expected = np.clip(normalized, 0.0, 1.0) * 0.054 - 0.01
        gripper[side] = {
            "normalized_min_max": [float(normalized.min()), float(normalized.max())],
            "converted_min_max_m": [float(converted.min()), float(converted.max())],
            "conversion_max_abs_error_m": maximum_abs(converted - expected),
            "written_min_max_m": [float(written.min()), float(written.max())],
            "actual_min_max_m": [float(actual.min()), float(actual.max())],
            "negative_targets_written": int(np.sum(written < 0.0)),
            "actual_below_soft_limit": int(np.sum(actual < -1e-6)),
        }

    action_by_step = {row["policy_step"]: row["denormalized_action_14d"] for row in final_rows}
    chunk_jump = None
    if 50 in action_by_step and 51 in action_by_step:
        delta = np.asarray(action_by_step[51]) - np.asarray(action_by_step[50])
        chunk_jump = {
            "l2": float(np.linalg.norm(delta)),
            "max_abs": float(np.max(np.abs(delta))),
            "delta_14d": delta.tolist(),
        }

    summary = {
        "row_count": len(rows),
        "policy_steps": policy_steps,
        "continuous_policy_steps": policy_steps == list(range(min(policy_steps), max(policy_steps) + 1)),
        "internal_step_counts": counts,
        "ten_internal_steps_each": ten_steps_each,
        "validation_pass": validation_pass,
        "all_values_finite": all_finite,
        "joint_target_buffer_vs_controller_max_abs_error": buffer_write_error,
        "max_tracking_error_by_action_dimension": max_tracking_by_dim,
        "gripper": gripper,
        "chunk_boundary_50_to_51": chunk_jump,
        "metadata": metadata,
    }
    (output_dir / "action_trace_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    try:
        import matplotlib.pyplot as plt

        x = np.asarray([(row["policy_step"] - policy_steps[0]) * 10 + row["internal_step"] for row in rows])
        fig, axes = plt.subplots(4, 1, figsize=(13, 12), sharex=True)
        for side, index, color in (("left", 6, "tab:blue"), ("right", 13, "tab:orange")):
            axes[0].plot(x, [row["written_joint_targets"][index] for row in rows], color=color, label=f"{side} target")
            axes[0].plot(x, [row["actual_joint_positions"][index] for row in rows], color=color, linestyle="--", label=f"{side} actual")
        axes[0].axhline(0.0, color="black", linewidth=0.8, label="runtime soft lower limit")
        axes[0].set_ylabel("gripper (m)")
        axes[0].legend(ncol=3)
        axes[0].grid(alpha=0.25)

        axes[1].plot(x, np.max(np.abs(tracking_error[:, :6]), axis=1), label="left arm")
        axes[1].plot(x, np.max(np.abs(tracking_error[:, 7:13]), axis=1), label="right arm")
        axes[1].set_ylabel("max |q-target| (rad)")
        axes[1].legend()
        axes[1].grid(alpha=0.25)

        axes[2].plot(x, [row["end_effector_z"]["left"] for row in rows], label="left EE z")
        axes[2].plot(x, [row["end_effector_z"]["right"] for row in rows], label="right EE z")
        axes[2].plot(x, [row["coin_z"] for row in rows], label="coin z")
        axes[2].set_ylabel("relative/world z (m)")
        axes[2].legend()
        axes[2].grid(alpha=0.25)

        step_x = [row["policy_step"] for row in final_rows]
        axes[3].plot(step_x, [row["left_gripper_normalized"] for row in final_rows], label="left normalized")
        axes[3].plot(step_x, [row["right_gripper_normalized"] for row in final_rows], label="right normalized")
        axes[3].axvline(51, color="red", linestyle=":", label="ACT chunk refresh")
        axes[3].set_ylabel("ACT gripper")
        axes[3].set_xlabel("policy step (bottom) / internal control index (upper panels)")
        axes[3].legend()
        axes[3].grid(alpha=0.25)
        fig.tight_layout()
        fig.savefig(output_dir / "action_tracking_plot.png", dpi=160)
        plt.close(fig)
    except Exception as exc:
        (output_dir / "plot_error.log").write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")

    log_lines = [
        "Week 2 Day 4 action trace analysis",
        f"rows={len(rows)} policy_steps={policy_steps[0]}..{policy_steps[-1]}",
        f"ten_internal_steps_each={ten_steps_each}",
        f"validation_pass={validation_pass}",
        f"all_values_finite={all_finite}",
        f"joint_target_buffer_vs_controller_max_abs_error={buffer_write_error:.9g}",
        f"left_gripper={json.dumps(gripper['left'], sort_keys=True)}",
        f"right_gripper={json.dumps(gripper['right'], sort_keys=True)}",
        f"chunk_boundary_50_to_51={json.dumps(chunk_jump, sort_keys=True)}",
    ]
    (output_dir / "action_trace.log").write_text("\n".join(log_lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
