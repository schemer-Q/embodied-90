#!/usr/bin/env python3
"""Compare reset frames and compose closure keyframes for the A/B report."""

import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw


ROOT = Path("/home/nvidia/embodied-90/simulation/robodojo/experiments/week03_day01_rgb_bgr")
CAMERAS = ("cam_head", "cam_right_wrist", "cam_left_wrist")


def main():
    reset_comparison = {}
    for camera in CAMERAS:
        arrays = {
            condition: cv2.imread(
                str(ROOT / condition / "keyframes" / f"{camera}_step_000.jpg")
            ).astype(float)
            for condition in ("bgr", "rgb")
        }
        difference = np.abs(arrays["bgr"] - arrays["rgb"])
        reset_comparison[camera] = {
            "shape_equal": arrays["bgr"].shape == arrays["rgb"].shape,
            "mae_8bit": float(np.mean(difference)),
            "max_abs_8bit": float(np.max(difference)),
            "pixels_gt_5_fraction": float(np.mean(np.any(difference > 5, axis=2))),
            "mean_bgr_a": np.mean(arrays["bgr"], axis=(0, 1)).tolist(),
            "mean_bgr_b": np.mean(arrays["rgb"], axis=(0, 1)).tolist(),
        }
    payload = {
        "physical_initial_state_match": {
            "coin_position_max_abs_m": 0.0,
            "robot_qpos_max_abs": 0.0,
        },
        "note": (
            "Reset video frames are not byte-identical across separate Isaac Sim launches. "
            "Differences are recorded as renderer/JPEG nondeterminism, not hidden configuration changes."
        ),
        "cameras": reset_comparison,
    }
    (ROOT / "initial_observation_comparison.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )

    summaries = {
        condition: json.loads((ROOT / condition / "trajectory_summary.json").read_text())
        for condition in ("bgr", "rgb")
    }
    rows = []
    labels = []
    for camera in CAMERAS:
        images = []
        row_labels = []
        for condition in ("bgr", "rgb"):
            step = summaries[condition]["closure_geometry"]["policy_step"]
            path = ROOT / condition / "keyframes" / f"{camera}_step_{step:03d}.jpg"
            images.append(Image.open(path).convert("RGB"))
            row_labels.append(f"{condition.upper()} {camera} policy step {step}")
        rows.append(images)
        labels.append(row_labels)

    width = 640 * 2
    label_height = 28
    height = (480 + label_height) * len(rows)
    canvas = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(canvas)
    for row_index, images in enumerate(rows):
        y = row_index * (480 + label_height)
        for column, image in enumerate(images):
            x = column * 640
            draw.text((x + 8, y + 7), labels[row_index][column], fill="black")
            canvas.paste(image, (x, y + label_height))
    canvas.save(ROOT / "closure_keyframe_comparison.png")
    print("Visual evidence finalized")


if __name__ == "__main__":
    main()
