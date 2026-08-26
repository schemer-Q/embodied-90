#!/usr/bin/env python3
"""Validate that the ACT color switch changes only the red/blue channels."""

import hashlib
import inspect
import json
import os
from pathlib import Path
import sys

import cv2
import numpy as np
from PIL import Image
import yaml


PROJECT_ROOT = Path("/home/nvidia/embodied-90")
ROBODOJO_ROOT = Path("/home/nvidia/RoboDojo")
EXPERIMENT_DIR = PROJECT_ROOT / "simulation/robodojo/experiments/week03_day01_rgb_bgr"
SOURCE_DIR = PROJECT_ROOT / "simulation/robodojo/validation/week02_day01"
MODEL_PATH = ROBODOJO_ROOT / "XPolicyLab/policy/ACT/model.py"
DEPLOY_PATH = ROBODOJO_ROOT / "XPolicyLab/policy/ACT/deploy.yml"
CAMERAS = ("cam_head", "cam_right_wrist", "cam_left_wrist")


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stats(array):
    return {
        "shape": list(array.shape),
        "dtype": str(array.dtype),
        "min": float(np.min(array)),
        "max": float(np.max(array)),
        "mean_per_channel": np.mean(array, axis=(0, 1)).tolist(),
        "std_per_channel": np.std(array, axis=(0, 1)).tolist(),
    }


def main():
    sys.path.insert(0, str(ROBODOJO_ROOT))
    from XPolicyLab.policy.ACT.model import prepare_act_input_color

    output_dir = EXPERIMENT_DIR / "input_validation"
    output_dir.mkdir(parents=True, exist_ok=True)
    camera_results = {}
    for camera in CAMERAS:
        source_path = SOURCE_DIR / f"{camera}_reset.jpg"
        source_rgb = np.asarray(Image.open(source_path).convert("RGB"))
        resized_rgb = cv2.resize(source_rgb, (640, 480), interpolation=cv2.INTER_LINEAR)
        bgr = prepare_act_input_color(resized_rgb, "bgr")
        rgb = prepare_act_input_color(resized_rgb, "rgb")
        bgr_tensor = np.moveaxis(bgr, -1, 0) / 255.0
        rgb_tensor = np.moveaxis(rgb, -1, 0) / 255.0

        source_output = output_dir / f"{camera}_source_rgb.png"
        bgr_output = output_dir / f"{camera}_act_bgr_as_rgb.png"
        rgb_output = output_dir / f"{camera}_act_rgb.png"
        Image.fromarray(resized_rgb).save(source_output)
        Image.fromarray(bgr).save(bgr_output)
        Image.fromarray(rgb).save(rgb_output)

        camera_results[camera] = {
            "source": str(source_path),
            "source_sha256": sha256(source_path),
            "source_rgb": stats(resized_rgb),
            "act_bgr": stats(bgr),
            "act_rgb": stats(rgb),
            "bgr_tensor": stats(np.moveaxis(bgr_tensor, 0, -1)),
            "rgb_tensor": stats(np.moveaxis(rgb_tensor, 0, -1)),
            "shape_equal": bgr.shape == rgb.shape,
            "dtype_equal": bgr.dtype == rgb.dtype,
            "range_equal": int(bgr.min()) == int(rgb.min()) and int(bgr.max()) == int(rgb.max()),
            "green_channel_equal": bool(np.array_equal(bgr[..., 1], rgb[..., 1])),
            "red_blue_exact_swap": bool(np.array_equal(bgr, rgb[..., ::-1])),
            "rgb_is_identity": bool(np.array_equal(rgb, resized_rgb)),
            "saved_images": [str(source_output), str(bgr_output), str(rgb_output)],
        }

    previous = os.environ.pop("ACT_INPUT_COLOR_ORDER", None)
    try:
        sample = np.asarray(Image.open(SOURCE_DIR / "cam_head_reset.jpg").convert("RGB"))
        default_is_bgr = np.array_equal(
            prepare_act_input_color(sample),
            prepare_act_input_color(sample, "bgr"),
        )
        invalid_value_rejected = False
        try:
            prepare_act_input_color(sample, "invalid")
        except ValueError:
            invalid_value_rejected = True
    finally:
        if previous is not None:
            os.environ["ACT_INPUT_COLOR_ORDER"] = previous

    deploy = yaml.safe_load(DEPLOY_PATH.read_text(encoding="utf-8"))
    source_lines, first_line = inspect.getsourcelines(prepare_act_input_color)
    result = {
        "source_frame_policy": "Week 2 Day 1 reset frames decoded explicitly as RGB with Pillow",
        "model_path": str(MODEL_PATH),
        "model_function": "prepare_act_input_color",
        "model_function_line": first_line,
        "model_function_source": "".join(source_lines),
        "camera_order_expected": list(CAMERAS),
        "camera_order_deploy": deploy["camera_names"],
        "camera_order_matches": deploy["camera_names"] == list(CAMERAS),
        "resize": {"width": 640, "height": 480, "interpolation": "cv2.INTER_LINEAR"},
        "post_color_processing": "np.moveaxis(HWC, -1, 0) / 255.0",
        "default_is_bgr": bool(default_is_bgr),
        "invalid_value_rejected": invalid_value_rejected,
        "cameras": camera_results,
    }
    result["all_checks_pass"] = bool(
        result["camera_order_matches"]
        and result["default_is_bgr"]
        and result["invalid_value_rejected"]
        and all(
            item["shape_equal"]
            and item["dtype_equal"]
            and item["range_equal"]
            and item["green_channel_equal"]
            and item["red_blue_exact_swap"]
            and item["rgb_is_identity"]
            for item in camera_results.values()
        )
    )
    output_path = EXPERIMENT_DIR / "input_color_validation.json"
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    if not result["all_checks_pass"]:
        raise SystemExit(f"Color validation failed; see {output_path}")
    print(f"Color validation passed: {output_path}")


if __name__ == "__main__":
    main()
