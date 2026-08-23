#!/usr/bin/env python3
"""Validate the full trajectory, summarize events, videos, and keyframes."""

import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess

import cv2
import numpy as np


CAMERAS = ("cam_head", "cam_left_wrist", "cam_right_wrist")


def load_jsonl(path):
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ffprobe(path):
    command = [
        "ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate,nb_read_frames,duration",
        "-of", "json", str(path),
    ]
    return json.loads(subprocess.check_output(command, text=True))["streams"][0]


def write_keyframes(video_paths, keyframe_dir, selected_steps):
    keyframe_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for camera, path in video_paths.items():
        capture = cv2.VideoCapture(str(path))
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        for step in selected_steps:
            frame_index = min(step, frame_count - 1)
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ok, frame = capture.read()
            if not ok:
                raise RuntimeError(f"Failed to read {camera} frame {frame_index}")
            output = keyframe_dir / f"{camera}_step_{step:03d}.jpg"
            cv2.imwrite(str(output), frame)
            manifest.append({
                "camera": camera,
                "policy_step": step,
                "video_frame": frame_index,
                "path": str(output),
                "sha256": sha256(output),
                "shape": list(frame.shape),
                "mean_bgr": np.mean(frame, axis=(0, 1)).tolist(),
                "std_bgr": np.std(frame, axis=(0, 1)).tolist(),
            })
        capture.release()
    return manifest


def first_step(rows, predicate):
    return next((row["policy_step"] for row in rows if predicate(row)), None)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", type=Path, required=True)
    parser.add_argument("--result-dir", type=Path, required=True)
    parser.add_argument("--exit-code", type=int, required=True)
    args = parser.parse_args()
    output_dir = args.dir
    internal = load_jsonl(output_dir / "full_episode_internal.jsonl")
    policy = load_jsonl(output_dir / "full_episode_trace.jsonl")
    metadata = json.loads((output_dir / "full_episode_metadata.json").read_text(encoding="utf-8"))
    result = json.loads((args.result_dir / "_result.json").read_text(encoding="utf-8"))
    (output_dir / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")

    video_paths = {}
    video_manifest = []
    for camera in CAMERAS:
        matches = list(args.result_dir.glob(f"episode_0000000_{camera}_*.mp4"))
        if len(matches) != 1:
            raise RuntimeError(f"Expected one {camera} video, got {matches}")
        path = matches[0]
        video_paths[camera] = path
        probe = ffprobe(path)
        video_manifest.append({
            "camera": camera,
            "path": str(path),
            "size_bytes": path.stat().st_size,
            "sha256": sha256(path),
            **probe,
        })
    (output_dir / "video_manifest.json").write_text(json.dumps(video_manifest, indent=2), encoding="utf-8")

    policy_steps = [row["policy_step"] for row in policy]
    internal_counts = {step: 0 for step in range(1, 301)}
    for row in internal:
        internal_counts[row["policy_step"]] = internal_counts.get(row["policy_step"], 0) + 1
    missing_steps = sorted(set(range(1, 301)) - set(policy_steps))
    invalid_values = 0
    numeric_fields = (
        "act_action_14d", "written_joint_targets_14d", "actual_joint_positions_14d",
        "tracking_error_14d", "coin_z_delta",
    )
    for row in internal:
        for field in numeric_fields:
            if not np.isfinite(np.asarray(row[field], dtype=float)).all():
                invalid_values += 1
        nested_values = (
            row["end_effector_pose"]["left"],
            row["end_effector_pose"]["right"],
            row["coin_pose"]["position"],
            row["coin_pose"]["orientation_wxyz"],
        )
        invalid_values += sum(not np.isfinite(np.asarray(value, dtype=float)).all() for value in nested_values)

    incorrect_internal_sequences = {}
    for step in range(1, 301):
        sequence = [row["internal_step"] for row in internal if row["policy_step"] == step]
        if sequence != list(range(1, 11)):
            incorrect_internal_sequences[str(step)] = sequence

    result_detail = result["details"]["0"] if "0" in result["details"] else result["details"][0]
    final_policy = policy[-1]
    result_consistent = (
        bool(final_policy["success"]) == bool(result_detail["success"])
        and abs(float(final_policy["score"]) / 100.0 - float(result_detail["score"])) < 1e-9
    )
    initial_z = float(metadata["initial_state"]["coin_pose"]["position"][2])
    coin_delta = np.asarray([row["coin_z_delta"] for row in policy], dtype=float)
    tracking = np.asarray([row["max_internal_tracking_error"] for row in policy], dtype=float)
    left_gripper = np.asarray([row["left_gripper"] for row in policy], dtype=float)
    left_ee_z = np.asarray([row["end_effector_pose"]["left"][2] for row in policy], dtype=float)
    right_ee_z = np.asarray([row["end_effector_pose"]["right"][2] for row in policy], dtype=float)

    initial_gripper = float(metadata["initial_state"]["actual_joint_positions_14d"][6])
    closing_start = first_step(policy, lambda row: row["left_gripper"] < initial_gripper - 0.002)
    noticeably_closed = first_step(policy, lambda row: row["left_gripper"] < 0.01)
    lift_start = None
    for index in range(3, len(left_ee_z)):
        prior_min = float(np.min(left_ee_z[:index]))
        if left_ee_z[index] - prior_min > 0.005:
            lift_start = index + 1
            break
    distances = []
    for row in policy:
        coin = np.asarray(row["coin_pose"]["position"], dtype=float)
        left = np.asarray(row["end_effector_pose"]["left"][:3], dtype=float)
        right = np.asarray(row["end_effector_pose"]["right"][:3], dtype=float)
        distances.append(min(float(np.linalg.norm(left - coin)), float(np.linalg.norm(right - coin))))
    closest_step = int(np.argmin(distances)) + 1

    selected_steps = sorted({0, closing_start or 1, noticeably_closed or 1, lift_start or 1, 50, 51, closest_step, 300})
    keyframe_manifest = write_keyframes(video_paths, output_dir / "keyframes", selected_steps)
    (output_dir / "keyframes" / "manifest.json").write_text(
        json.dumps(keyframe_manifest, indent=2), encoding="utf-8"
    )

    csv_fields = [
        "policy_step", "act_chunk_number", "act_chunk_index", "act_chunk_refresh",
        "act_action_14d", "left_arm_joints", "left_gripper", "right_arm_joints",
        "right_gripper", "left_end_effector_pose", "right_end_effector_pose",
        "coin_position", "coin_orientation_wxyz", "coin_z_delta", "reward", "score",
        "success", "episode_ended", "max_internal_tracking_error",
    ]
    with (output_dir / "full_episode_trace.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=csv_fields, lineterminator="\n")
        writer.writeheader()
        for row in policy:
            writer.writerow({
                "policy_step": row["policy_step"],
                "act_chunk_number": row["act_chunk_number"],
                "act_chunk_index": row["act_chunk_index"],
                "act_chunk_refresh": row["act_chunk_refresh"],
                "act_action_14d": json.dumps(row["act_action_14d"], separators=(",", ":")),
                "left_arm_joints": json.dumps(row["left_arm_joints"], separators=(",", ":")),
                "left_gripper": row["left_gripper"],
                "right_arm_joints": json.dumps(row["right_arm_joints"], separators=(",", ":")),
                "right_gripper": row["right_gripper"],
                "left_end_effector_pose": json.dumps(row["end_effector_pose"]["left"], separators=(",", ":")),
                "right_end_effector_pose": json.dumps(row["end_effector_pose"]["right"], separators=(",", ":")),
                "coin_position": json.dumps(row["coin_pose"]["position"], separators=(",", ":")),
                "coin_orientation_wxyz": json.dumps(row["coin_pose"]["orientation_wxyz"], separators=(",", ":")),
                "coin_z_delta": row["coin_z_delta"],
                "reward": row["reward"],
                "score": row["score"],
                "success": row["success"],
                "episode_ended": row["episode_ended"],
                "max_internal_tracking_error": row["max_internal_tracking_error"],
            })

    summary = {
        "policy_steps": len(policy),
        "internal_records": len(internal),
        "missing_policy_steps": missing_steps,
        "incorrect_internal_step_counts": {
            str(step): count for step, count in internal_counts.items() if count != 10
        },
        "incorrect_internal_step_sequences": incorrect_internal_sequences,
        "invalid_values": invalid_values,
        "validation_failures": sum(not row["validation_pass"] for row in internal),
        "final_success": bool(result_detail["success"]),
        "final_score": float(result_detail["score"]),
        "exit_code": args.exit_code,
        "result_consistent": result_consistent,
        "video_count": len(video_manifest),
        "video_frame_counts": {item["camera"]: int(item["nb_read_frames"]) for item in video_manifest},
        "videos_complete": (
            len({int(item["nb_read_frames"]) for item in video_manifest}) == 1
            and all(int(item["nb_read_frames"]) >= 300 for item in video_manifest)
        ),
        "initial_coin_z": initial_z,
        "max_coin_lift": float(np.max(coin_delta)),
        "max_tracking_error": float(np.max(tracking)),
        "max_tracking_error_policy_step": int(np.argmax(tracking)) + 1,
        "events": {
            "left_gripper_closing_start": closing_start,
            "left_gripper_noticeably_closed": noticeably_closed,
            "left_end_effector_lift_start": lift_start,
            "closest_end_effector_origin_to_coin": closest_step,
            "closest_end_effector_origin_distance_m": float(np.min(distances)),
            "act_chunk_refresh_steps": [1, 51, 101, 151, 201, 251],
            "episode_end": 300,
        },
        "earliest_failure_stage": "coin did not exceed the 0.08 m lift threshold",
        "result_directory": str(args.result_dir),
    }
    (output_dir / "full_episode_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    import matplotlib.pyplot as plt

    steps = np.arange(1, len(policy) + 1)
    fig, axes = plt.subplots(5, 1, figsize=(14, 15), sharex=True)
    axes[0].plot(steps, left_gripper, label="left")
    axes[0].plot(steps, [row["right_gripper"] for row in policy], label="right")
    axes[0].set_ylabel("gripper (m)")
    axes[0].legend()
    axes[1].plot(steps, left_ee_z, label="left EE z")
    axes[1].plot(steps, right_ee_z, label="right EE z")
    axes[1].set_ylabel("EE z (m)")
    axes[1].legend()
    axes[2].plot(steps, coin_delta, label="coin z delta")
    axes[2].axhline(0.08, color="red", linestyle="--", label="lift threshold")
    axes[2].set_ylabel("coin dz (m)")
    axes[2].legend()
    axes[3].plot(steps, tracking, label="max tracking error")
    axes[3].set_ylabel("max |q-target|")
    axes[3].legend()
    axes[4].step(steps, [row["score"] for row in policy], where="post", label="process score")
    axes[4].set_ylabel("score")
    axes[4].set_xlabel("policy step")
    for axis in axes:
        for boundary in (1, 51, 101, 151, 201, 251):
            axis.axvline(boundary, color="gray", linestyle=":", linewidth=0.8)
        axis.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(output_dir / "trajectory_plot.png", dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    main()
