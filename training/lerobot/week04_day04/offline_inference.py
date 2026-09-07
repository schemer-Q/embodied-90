#!/usr/bin/env python3
"""Run deterministic offline ACT inference on pinned PushT observations."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import time
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageDraw

from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot.policies.act.modeling_act import ACTPolicy
from lerobot.policies.factory import make_pre_post_processors
from lerobot.utils.random_utils import set_seed


REPO_ID = "lerobot/pusht"
REVISION = "b1c3ecbae7f244acc039a3dbc255a00dad1372b9"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--frames", type=int, nargs="+", default=[0, 80, 160])
    parser.add_argument("--seed", type=int, default=20260907)
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tensor_sha256(value: torch.Tensor) -> str:
    array = value.detach().cpu().contiguous().numpy()
    return hashlib.sha256(array.tobytes()).hexdigest()


def tensor_stats(value: torch.Tensor) -> dict[str, object]:
    numeric = value.detach().cpu().to(torch.float64)
    return {
        "shape": list(value.shape),
        "dtype": str(value.dtype),
        "device": str(value.device),
        "finite": bool(torch.isfinite(numeric).all()),
        "min": float(numeric.min()),
        "max": float(numeric.max()),
        "mean": float(numeric.mean()),
        "std": float(numeric.std(unbiased=False)),
        "sha256": tensor_sha256(value),
    }


def to_json_values(value: torch.Tensor) -> list[object]:
    return value.detach().cpu().tolist()


def save_input_snapshot(output: Path, samples: list[tuple[int, dict[str, object]]]) -> None:
    images = []
    for frame_index, sample in samples:
        image = sample["observation.image"].detach().cpu().numpy()
        rgb = np.clip(np.moveaxis(image, 0, -1) * 255.0, 0, 255).round().astype(np.uint8)
        images.append((frame_index, Image.fromarray(rgb)))

    label_height = 24
    width = sum(image.width for _, image in images)
    height = max(image.height for _, image in images) + label_height
    sheet = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(sheet)
    x = 0
    for frame_index, image in images:
        draw.text((x + 4, 5), f"frame {frame_index}", fill="black")
        sheet.paste(image, (x, label_height))
        x += image.width
    sheet.save(output / "input_snapshot.png")


def synchronize() -> None:
    if torch.cuda.is_available():
        torch.cuda.synchronize()


def main() -> None:
    args = parse_args()
    dataset_root = args.dataset_root.resolve()
    checkpoint = args.checkpoint.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for this validation")
    model_path = checkpoint / "model.safetensors"
    if not model_path.is_file():
        raise FileNotFoundError(model_path)
    processor_files = [
        "policy_preprocessor.json",
        "policy_preprocessor_step_3_normalizer_processor.safetensors",
        "policy_postprocessor.json",
        "policy_postprocessor_step_0_unnormalizer_processor.safetensors",
    ]
    missing_processor_files = [name for name in processor_files if not (checkpoint / name).is_file()]
    if missing_processor_files:
        raise FileNotFoundError(f"Missing processor files: {missing_processor_files}")

    set_seed(args.seed)
    dataset = LeRobotDataset(
        REPO_ID,
        root=dataset_root,
        revision=REVISION,
        episodes=[0],
        video_backend="pyav",
    )
    if any(index < 0 or index >= len(dataset) for index in args.frames):
        raise ValueError(f"Frame indices must be within [0, {len(dataset) - 1}]")

    samples = [(index, dataset[index]) for index in args.frames]
    save_input_snapshot(output, samples)

    policy = ACTPolicy.from_pretrained(checkpoint, device="cuda")
    policy.eval()
    preprocessor, postprocessor = make_pre_post_processors(
        policy.config,
        pretrained_path=str(checkpoint),
    )

    parameters_finite = all(torch.isfinite(parameter).all() for parameter in policy.parameters())
    rows: list[dict[str, object]] = []
    frame_results: list[dict[str, object]] = []
    deterministic_checks: list[bool] = []
    queue_chunk_checks: list[bool] = []
    all_actions_finite = True

    for frame_index, sample in samples:
        observation = {
            key: value
            for key, value in sample.items()
            if key in {"observation.image", "observation.state"}
        }
        processed = preprocessor(observation)
        processed_with_action = preprocessor({**observation, "action": sample["action"]})

        set_seed(args.seed)
        policy.reset()
        synchronize()
        start = time.perf_counter()
        with torch.inference_mode():
            normalized_chunk = policy.predict_action_chunk(processed)
        synchronize()
        chunk_latency_ms = (time.perf_counter() - start) * 1000.0
        action_chunk = postprocessor(normalized_chunk)

        set_seed(args.seed)
        policy.reset()
        queue_normalized = []
        queue_latencies_ms = []
        for _ in range(policy.config.n_action_steps):
            synchronize()
            start = time.perf_counter()
            with torch.inference_mode():
                action = policy.select_action(processed)
            synchronize()
            queue_latencies_ms.append((time.perf_counter() - start) * 1000.0)
            queue_normalized.append(action)
        queue_normalized_tensor = torch.stack(queue_normalized, dim=1)
        queue_actions = postprocessor(queue_normalized_tensor)

        set_seed(args.seed)
        policy.reset()
        with torch.inference_mode():
            repeat_chunk = policy.predict_action_chunk(processed)

        deterministic = bool(torch.equal(normalized_chunk, repeat_chunk))
        queue_matches_chunk = bool(
            torch.equal(
                normalized_chunk[:, : policy.config.n_action_steps],
                queue_normalized_tensor,
            )
        )
        deterministic_checks.append(deterministic)
        queue_chunk_checks.append(queue_matches_chunk)
        all_actions_finite &= bool(torch.isfinite(action_chunk).all())

        normalized_gt = processed_with_action["action"]
        ground_truth = sample["action"].unsqueeze(0)
        first_action_l2_to_gt = float(torch.linalg.vector_norm(action_chunk[:, 0].cpu() - ground_truth))
        frame_result = {
            "frame_index": frame_index,
            "timestamp": float(sample["timestamp"]),
            "raw_observation": {
                "image": tensor_stats(observation["observation.image"]),
                "state": tensor_stats(observation["observation.state"]),
            },
            "processed_observation": {
                "image": tensor_stats(processed["observation.image"]),
                "state": tensor_stats(processed["observation.state"]),
            },
            "ground_truth_action": to_json_values(ground_truth),
            "normalized_ground_truth_action": to_json_values(normalized_gt),
            "normalized_action_chunk": to_json_values(normalized_chunk),
            "action_chunk": to_json_values(action_chunk),
            "chunk_shape": list(action_chunk.shape),
            "chunk_latency_ms": chunk_latency_ms,
            "queue_call_latencies_ms": queue_latencies_ms,
            "queue_matches_direct_chunk": queue_matches_chunk,
            "same_seed_repeat_bitwise_equal": deterministic,
            "first_action_l2_to_ground_truth": first_action_l2_to_gt,
        }
        frame_results.append(frame_result)

        for queue_index in range(policy.config.n_action_steps):
            rows.append(
                {
                    "frame_index": frame_index,
                    "queue_index": queue_index,
                    "normalized_action_0": float(queue_normalized_tensor[0, queue_index, 0]),
                    "normalized_action_1": float(queue_normalized_tensor[0, queue_index, 1]),
                    "action_0": float(queue_actions[0, queue_index, 0]),
                    "action_1": float(queue_actions[0, queue_index, 1]),
                    "ground_truth_action_0": float(ground_truth[0, 0]),
                    "ground_truth_action_1": float(ground_truth[0, 1]),
                    "select_action_latency_ms": queue_latencies_ms[queue_index],
                }
            )

    max_memory_mib = torch.cuda.max_memory_allocated() / (1024**2)
    checks = {
        "checkpoint_loaded": True,
        "parameters_finite": bool(parameters_finite),
        "three_or_more_frames": len(frame_results) >= 3,
        "all_actions_finite": all_actions_finite,
        "all_chunk_shapes_match": all(
            result["chunk_shape"] == [1, policy.config.chunk_size, 2] for result in frame_results
        ),
        "same_seed_repeats_bitwise_equal": all(deterministic_checks),
        "select_action_queue_matches_direct_chunk": all(queue_chunk_checks),
    }
    checks["all_checks_pass"] = all(checks.values())

    result = {
        "run": {
            "repo_id": REPO_ID,
            "revision": REVISION,
            "dataset_root": str(dataset_root),
            "episode": 0,
            "dataset_frames": len(dataset),
            "selected_frames": args.frames,
            "seed": args.seed,
            "checkpoint": str(checkpoint),
            "checkpoint_sha256": sha256_file(model_path),
            "processor_sha256": {
                name: sha256_file(checkpoint / name) for name in processor_files
            },
            "device": "cuda",
        },
        "environment": {
            "python": platform.python_version(),
            "torch": torch.__version__,
            "cuda_runtime": torch.version.cuda,
            "gpu": torch.cuda.get_device_name(0),
            "max_memory_allocated_mib": max_memory_mib,
        },
        "policy": {
            "type": policy.config.type,
            "chunk_size": policy.config.chunk_size,
            "n_action_steps": policy.config.n_action_steps,
            "input_features": {
                key: {"type": str(value.type), "shape": list(value.shape)}
                for key, value in policy.config.input_features.items()
            },
            "output_features": {
                key: {"type": str(value.type), "shape": list(value.shape)}
                for key, value in policy.config.output_features.items()
            },
        },
        "checks": checks,
        "frames": frame_results,
    }
    (output / "inference_results.json").write_text(json.dumps(result, indent=2) + "\n")

    with (output / "inference_trace.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    summary = {
        "checks": checks,
        "checkpoint_sha256": result["run"]["checkpoint_sha256"],
        "frames": [
            {
                "frame_index": item["frame_index"],
                "chunk_latency_ms": item["chunk_latency_ms"],
                "first_action": item["action_chunk"][0][0],
                "ground_truth_action": item["ground_truth_action"][0],
                "first_action_l2_to_ground_truth": item["first_action_l2_to_ground_truth"],
            }
            for item in frame_results
        ],
        "max_memory_allocated_mib": max_memory_mib,
    }
    (output / "inference_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))

    if not checks["all_checks_pass"]:
        raise RuntimeError("One or more offline inference checks failed")


if __name__ == "__main__":
    main()

