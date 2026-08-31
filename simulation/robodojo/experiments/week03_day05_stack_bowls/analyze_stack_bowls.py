#!/usr/bin/env python3
"""Validate a stack_bowls run and extract compact evidence."""

import argparse
import ast
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import cv2
import matplotlib.pyplot as plt
import numpy as np


HERE = Path(__file__).resolve().parent
CHECKPOINT = Path("/home/nvidia/RoboDojo/XPolicyLab/policy/ACT/checkpoints/RoboDojo-stack_bowls-arx_x5-joint-0")
CAMERAS = ("cam_head", "cam_left_wrist", "cam_right_wrist")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_actions(path: Path):
    actions = []
    steps = []
    pattern = re.compile(r"pred step=(\d+) action=(\[.*\]) left_gripper=")
    for line in path.read_text(encoding="utf-8").splitlines():
        match = pattern.search(line)
        if match:
            steps.append(int(match.group(1)))
            actions.append(ast.literal_eval(match.group(2)))
    values = np.asarray(actions, dtype=float)
    if values.ndim == 3 and values.shape[1] == 1:
        values = values[:, 0, :]
    return steps, values


def video_info(path: Path):
    capture = cv2.VideoCapture(str(path))
    frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    capture.release()
    return {"path": str(path), "frames": frames, "shape": [height, width, 3], "fps": fps, "sha256": sha256(path)}


def extract_keyframes(videos, output: Path):
    target = output / "keyframes"
    target.mkdir(exist_ok=True)
    manifest = []
    for camera, info in videos.items():
        capture = cv2.VideoCapture(info["path"])
        frame_count = info["frames"]
        for requested in (0, 50, 100, 200, 400, 600, 799):
            index = min(requested, frame_count - 1)
            capture.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, frame = capture.read()
            if not ok:
                continue
            path = target / f"{camera}_step{requested:03d}.jpg"
            cv2.imwrite(str(path), frame)
            manifest.append({"camera": camera, "requested_step": requested, "frame": index, "path": str(path.relative_to(HERE)), "sha256": sha256(path)})
        capture.release()
    (output / "keyframe_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("smoke", "full"), required=True)
    parser.add_argument("--result-dir", type=Path, required=True)
    parser.add_argument("--expected-steps", type=int, default=0)
    args = parser.parse_args()
    output = HERE / args.mode
    steps, actions = parse_actions(output / "act_pred_log.txt")
    exec_steps = sum(line.startswith("step=") for line in (output / "act_exec_log.txt").read_text(encoding="utf-8").splitlines())
    expected = args.expected_steps or 800
    result_source = next(args.result_dir.glob("*_result.json"))
    result = json.loads(result_source.read_text(encoding="utf-8"))
    shutil.copy2(result_source, output / "result.json")

    video_paths = list(args.result_dir.glob("*.mp4"))
    videos = {}
    for camera in CAMERAS:
        matches = [path for path in video_paths if camera in path.name]
        if matches:
            videos[camera] = video_info(matches[0])

    summary = {
        "task": "stack_bowls",
        "checkpoint": CHECKPOINT.name,
        "checkpoint_sha256": sha256(CHECKPOINT / "policy_last.ckpt"),
        "dataset_stats_sha256": sha256(CHECKPOINT / "dataset_stats.pkl"),
        "seed": 0,
        "layout": 0,
        "input_color_order": "rgb",
        "temporal_aggregation": False,
        "expected_policy_steps": expected,
        "action_records": len(actions),
        "execution_records": exec_steps,
        "action_dimension": None if actions.size == 0 else int(actions.shape[1]),
        "actions_finite": bool(actions.size and np.isfinite(actions).all()),
        "nonzero_actions": bool(actions.size and np.any(np.abs(actions) > 1e-8)),
        "continuous_steps": steps == list(range(expected)),
        "final_success": bool(result.get("details", {}).get("0", {}).get("success", False)),
        "final_score": float(result.get("score", 0.0)),
        "exit_code": int((output / "exit_code.txt").read_text().strip()),
        "videos": videos,
        "videos_complete": len(videos) == 3 and all(info["frames"] >= 800 for info in videos.values()),
    }
    if actions.size:
        jumps = np.linalg.norm(np.diff(actions, axis=0), axis=1)
        summary.update({
            "action_l2_mean": float(np.linalg.norm(actions, axis=1).mean()),
            "max_adjacent_action_jump": float(jumps.max()) if len(jumps) else 0.0,
        })
    (output / "run_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    assert summary["exit_code"] == 0
    assert summary["action_records"] == expected
    assert summary["execution_records"] == expected
    assert summary["action_dimension"] == 14 and summary["actions_finite"]
    assert summary["continuous_steps"]
    if args.mode == "full":
        assert summary["videos_complete"]
        extract_keyframes(videos, output)
        x = np.arange(1, len(actions) + 1)
        fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
        axes[0].plot(x, actions[:, 6], label="left gripper")
        axes[0].plot(x, actions[:, 13], label="right gripper")
        axes[0].set_ylabel("normalized target")
        axes[0].legend()
        axes[1].plot(x, np.linalg.norm(actions, axis=1))
        axes[1].set_ylabel("action L2")
        axes[1].set_xlabel("policy step")
        for axis in axes:
            axis.grid(alpha=0.25)
        fig.tight_layout()
        fig.savefig(HERE / "action_summary.png", dpi=160)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
