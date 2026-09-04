#!/usr/bin/env python3
"""Inspect one pinned LeRobot v3 episode and produce reproducible artifacts."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
from pathlib import Path

import av
import matplotlib
import numpy as np
import pyarrow.compute as pc
import pyarrow.parquet as pq
import torch
from PIL import Image, ImageDraw

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from lerobot.datasets.lerobot_dataset import LeRobotDataset


DEFAULT_REPO_ID = "lerobot/pusht"
DEFAULT_REVISION = "b1c3ecbae7f244acc039a3dbc255a00dad1372b9"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repo-id", default=DEFAULT_REPO_ID)
    parser.add_argument("--revision", default=DEFAULT_REVISION)
    parser.add_argument("--episode", type=int, default=0)
    return parser.parse_args()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def tensor_stats(value: torch.Tensor) -> dict[str, object]:
    result: dict[str, object] = {
        "shape": list(value.shape),
        "dtype": str(value.dtype),
    }
    if value.numel() == 0:
        return result
    if value.dtype == torch.bool:
        result["values"] = sorted(set(value.cpu().numpy().reshape(-1).tolist()))
        return result
    numeric = value.detach().cpu().to(torch.float64)
    result.update(
        finite=bool(torch.isfinite(numeric).all()),
        min=float(numeric.min()),
        max=float(numeric.max()),
        mean=float(numeric.mean()),
        std=float(numeric.std(unbiased=False)),
    )
    return result


def table_schema(path: Path) -> dict[str, object]:
    schema = pq.read_schema(path)
    return {
        "path": str(path),
        "fields": [{"name": field.name, "type": str(field.type)} for field in schema],
    }


def api_image_to_rgb(image: torch.Tensor) -> np.ndarray:
    array = image.detach().cpu().numpy()
    if array.ndim != 3 or array.shape[0] not in (1, 3, 4):
        raise ValueError(f"Expected CHW image from LeRobotDataset, got {array.shape}")
    return np.clip(np.moveaxis(array, 0, -1) * 255.0, 0, 255).round().astype(np.uint8)


def first_video_frame_rgb(path: Path) -> tuple[np.ndarray, dict[str, object]]:
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        frame = next(container.decode(video=0))
        info = {
            "codec": stream.codec_context.name,
            "pixel_format": stream.codec_context.pix_fmt,
            "width": stream.width,
            "height": stream.height,
            "average_rate": float(stream.average_rate),
            "frames_reported": stream.frames,
        }
        return frame.to_ndarray(format="rgb24"), info


def save_visualizations(
    output: Path,
    samples: list[tuple[int, dict[str, object]]],
    state: np.ndarray,
    action: np.ndarray,
    timestamps: np.ndarray,
) -> None:
    visual_dir = output / "visualizations"
    visual_dir.mkdir(parents=True, exist_ok=True)

    images: list[Image.Image] = []
    for local_index, frame in samples:
        rgb = api_image_to_rgb(frame["observation.image"])
        image = Image.fromarray(rgb)
        image.save(visual_dir / f"episode0_frame_{local_index:03d}.png")
        images.append(image)

    label_height = 22
    sheet = Image.new("RGB", (sum(image.width for image in images), images[0].height + label_height), "white")
    draw = ImageDraw.Draw(sheet)
    x = 0
    for (local_index, _), image in zip(samples, images, strict=True):
        sheet.paste(image, (x, label_height))
        draw.text((x + 4, 4), f"frame {local_index}", fill="black")
        x += image.width
    sheet.save(visual_dir / "episode0_contact_sheet.png")

    fig, axes = plt.subplots(2, 1, figsize=(9, 6), sharex=True, constrained_layout=True)
    axes[0].plot(timestamps, state[:, 0], label="state[0]")
    axes[0].plot(timestamps, state[:, 1], label="state[1]")
    axes[0].set_ylabel("state")
    axes[0].legend()
    axes[0].grid(alpha=0.25)
    axes[1].plot(timestamps, action[:, 0], label="action[0]")
    axes[1].plot(timestamps, action[:, 1], label="action[1]")
    axes[1].set_xlabel("timestamp (s)")
    axes[1].set_ylabel("action")
    axes[1].legend()
    axes[1].grid(alpha=0.25)
    fig.savefig(visual_dir / "episode0_state_action.png", dpi=160)
    plt.close(fig)


def main() -> None:
    args = parse_args()
    root = args.root.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    dataset = LeRobotDataset(
        args.repo_id,
        root=root,
        revision=args.revision,
        episodes=[args.episode],
        video_backend="pyav",
    )
    if not dataset.meta.video_keys:
        raise RuntimeError("The selected dataset has no video feature")

    data_path = next(root.glob("data/chunk-*/*.parquet"))
    episodes_path = next(root.glob("meta/episodes/chunk-*/*.parquet"))
    tasks_path = root / "meta/tasks.parquet"
    video_path = next(root.glob("videos/*/chunk-*/*.mp4"))
    info = json.loads((root / "meta/info.json").read_text())

    data_table = pq.read_table(data_path)
    episode_table = data_table.filter(pc.equal(data_table["episode_index"], args.episode))
    episode_meta_table = pq.read_table(episodes_path)
    episode_meta = episode_meta_table.filter(
        pc.equal(episode_meta_table["episode_index"], args.episode)
    )
    tasks_table = pq.read_table(tasks_path)

    frames = episode_table["frame_index"].to_numpy()
    timestamps = episode_table["timestamp"].to_numpy()
    global_indices = episode_table["index"].to_numpy()
    task_indices = episode_table["task_index"].to_numpy()
    state = np.asarray(episode_table["observation.state"].to_pylist(), dtype=np.float32)
    action = np.asarray(episode_table["action"].to_pylist(), dtype=np.float32)
    expected_dt = 1.0 / dataset.meta.fps

    checks = {
        "episode_rows_match_api_length": len(episode_table) == len(dataset),
        "frame_index_contiguous_from_zero": np.array_equal(frames, np.arange(len(frames))),
        "global_index_contiguous": bool(np.all(np.diff(global_indices) == 1)),
        "timestamp_monotonic": bool(np.all(np.diff(timestamps) > 0)),
        "timestamp_matches_fps": bool(
            np.allclose(np.diff(timestamps), expected_dt, rtol=0, atol=1e-5)
        ),
        "single_episode_index": set(episode_table["episode_index"].to_pylist()) == {args.episode},
        "single_task_index": len(set(task_indices.tolist())) == 1,
        "state_finite": bool(np.isfinite(state).all()),
        "action_finite": bool(np.isfinite(action).all()),
    }

    sample_indices = [0, len(dataset) // 2, len(dataset) - 1]
    samples = [(index, dataset[index]) for index in sample_indices]
    sample_summary = {}
    for index, frame in samples:
        sample_summary[str(index)] = {
            key: tensor_stats(value) if isinstance(value, torch.Tensor) else value
            for key, value in frame.items()
        }

    raw_rgb, video_info = first_video_frame_rgb(video_path)
    api_rgb = api_image_to_rgb(samples[0][1]["observation.image"])
    if raw_rgb.shape != api_rgb.shape:
        raise ValueError(f"Raw/API image shape mismatch: {raw_rgb.shape} vs {api_rgb.shape}")
    rgb_mae = float(np.abs(raw_rgb.astype(np.int16) - api_rgb.astype(np.int16)).mean())
    bgr_mae = float(np.abs(raw_rgb[..., ::-1].astype(np.int16) - api_rgb.astype(np.int16)).mean())
    color_order = "RGB" if rgb_mae < bgr_mae else "BGR"
    checks["api_image_matches_raw_rgb_better_than_bgr"] = rgb_mae < bgr_mae
    checks["all_checks_pass"] = all(checks.values())

    core_files = sorted(
        path for path in root.rglob("*") if path.is_file() and ".cache" not in path.parts
    )
    manifest = {
        "repo_id": args.repo_id,
        "revision": args.revision,
        "episode": args.episode,
        "root": str(root),
        "files": [
            {
                "path": str(path.relative_to(root)),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in core_files
        ],
    }
    manifest["total_bytes"] = sum(item["bytes"] for item in manifest["files"])

    environment = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "packages": {
            name: package_version(name)
            for name in (
                "lerobot",
                "datasets",
                "huggingface-hub",
                "pyarrow",
                "av",
                "torch",
                "torchvision",
                "numpy",
            )
        },
        "cuda_available": torch.cuda.is_available(),
        "video_backend": "pyav",
    }
    schema = {
        "info": info,
        "parquet": {
            "data": table_schema(data_path),
            "episodes": table_schema(episodes_path),
            "tasks": table_schema(tasks_path),
        },
        "tasks": tasks_table.to_pylist(),
        "episode_metadata": {
            key: episode_meta[key][0].as_py()
            for key in (
                "episode_index",
                "dataset_from_index",
                "dataset_to_index",
                "videos/observation.image/from_timestamp",
                "videos/observation.image/to_timestamp",
                "tasks",
                "length",
            )
        },
    }
    stats = {
        "episode": args.episode,
        "length": len(dataset),
        "fps": dataset.meta.fps,
        "camera_keys": dataset.meta.camera_keys,
        "sample_indices": sample_indices,
        "samples": sample_summary,
        "sequence": {
            "frame_index_first": int(frames[0]),
            "frame_index_last": int(frames[-1]),
            "timestamp_first": float(timestamps[0]),
            "timestamp_last": float(timestamps[-1]),
            "timestamp_step_mean": float(np.diff(timestamps).mean()),
            "timestamp_step_max_error": float(np.abs(np.diff(timestamps) - expected_dt).max()),
            "state_min": state.min(axis=0).tolist(),
            "state_max": state.max(axis=0).tolist(),
            "action_min": action.min(axis=0).tolist(),
            "action_max": action.max(axis=0).tolist(),
        },
        "image_contract": {
            "metadata_layout": info["features"]["observation.image"]["names"],
            "metadata_shape": info["features"]["observation.image"]["shape"],
            "api_layout": "CHW",
            "api_shape": list(samples[0][1]["observation.image"].shape),
            "api_dtype": str(samples[0][1]["observation.image"].dtype),
            "api_range": [
                float(samples[0][1]["observation.image"].min()),
                float(samples[0][1]["observation.image"].max()),
            ],
            "raw_decoder_layout": "HWC",
            "raw_decoder_dtype": str(raw_rgb.dtype),
            "raw_rgb_vs_api_mae": rgb_mae,
            "raw_bgr_vs_api_mae": bgr_mae,
            "inferred_api_color_order": color_order,
            "video": video_info,
        },
        "checks": checks,
    }

    save_visualizations(output, samples, state, action, timestamps)
    write_json(output / "environment.json", environment)
    write_json(output / "dataset_manifest.json", manifest)
    write_json(output / "schema.json", schema)
    write_json(output / "sample_stats.json", stats)
    print(json.dumps({"checks": checks, "image_contract": stats["image_contract"]}, indent=2))
    if not checks["all_checks_pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
