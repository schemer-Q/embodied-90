#!/usr/bin/env python3
"""Read-only health checks for a local LeRobot v3 dataset."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import av
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import torch

from lerobot.datasets.lerobot_dataset import LeRobotDataset


@dataclass
class Check:
    category: str
    name: str
    status: str
    evidence: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--revision")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-state-dim", type=int)
    parser.add_argument("--expected-action-dim", type=int)
    parser.add_argument("--expected-camera", action="append", default=[])
    parser.add_argument("--action-window", type=int, default=0)
    parser.add_argument("--sample-count", type=int, default=9)
    parser.add_argument("--strict-warnings", action="store_true")
    return parser.parse_args()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def missing_paths(root: Path, relative_paths: list[str]) -> list[str]:
    return [relative for relative in relative_paths if not (root / relative).is_file()]


def array_is_finite(value: np.ndarray) -> bool:
    return bool(np.isfinite(value).all())


def timestamps_match(value: np.ndarray, fps: float, atol: float = 1e-5) -> bool:
    if value.ndim != 1 or len(value) == 0 or not array_is_finite(value):
        return False
    expected = np.arange(len(value), dtype=np.float64) / fps
    return bool(np.allclose(value, expected, rtol=0, atol=atol))


def json_is_finite(value: object) -> bool:
    if isinstance(value, dict):
        return all(json_is_finite(item) for item in value.values())
    if isinstance(value, list):
        return all(json_is_finite(item) for item in value)
    if isinstance(value, float):
        return math.isfinite(value)
    return True


def add_check(checks: list[Check], category: str, name: str, condition: bool, evidence: str) -> None:
    checks.append(Check(category, name, "PASS" if condition else "FAIL", evidence))


def add_warning(checks: list[Check], category: str, name: str, warning: bool, evidence: str) -> None:
    checks.append(Check(category, name, "WARN" if warning else "PASS", evidence))


def fixed_list_dim(field: pa.Field) -> int | None:
    return field.type.list_size if pa.types.is_fixed_size_list(field.type) else None


def feature_shape(info: dict[str, Any], key: str) -> list[int] | None:
    feature = info.get("features", {}).get(key)
    return feature.get("shape") if feature else None


def collect_tables(paths: list[Path]) -> pa.Table:
    if not paths:
        raise FileNotFoundError("No Parquet files found")
    return pa.concat_tables([pq.read_table(path) for path in paths], promote_options="default")


def numeric_matrix(table: pa.Table, key: str) -> np.ndarray:
    return np.asarray(table[key].to_pylist())


def check_structure(root: Path, checks: list[Check]) -> tuple[dict[str, Any], dict[str, Any]]:
    required = ["meta/info.json", "meta/stats.json", "meta/tasks.parquet"]
    missing = missing_paths(root, required)
    add_check(checks, "structure", "required metadata files", not missing, f"missing={missing}")
    if missing:
        raise FileNotFoundError(f"Missing required files: {missing}")

    info = json.loads((root / "meta/info.json").read_text())
    stats = json.loads((root / "meta/stats.json").read_text())
    add_check(
        checks,
        "structure",
        "LeRobot v3 codebase version",
        str(info.get("codebase_version", "")).startswith("v3"),
        f"codebase_version={info.get('codebase_version')}",
    )
    add_check(
        checks,
        "statistics",
        "metadata statistics are finite",
        json_is_finite(stats),
        f"features={len(stats)}",
    )
    return info, stats


def check_parquet(
    root: Path,
    info: dict[str, Any],
    stats: dict[str, Any],
    checks: list[Check],
    expected_state_dim: int | None,
    expected_action_dim: int | None,
) -> tuple[pa.Table, pa.Table, pa.Table, dict[str, Any]]:
    data_paths = sorted(root.glob("data/chunk-*/*.parquet"))
    episode_paths = sorted(root.glob("meta/episodes/chunk-*/*.parquet"))
    add_check(checks, "structure", "data Parquet exists", bool(data_paths), f"files={len(data_paths)}")
    add_check(
        checks, "structure", "episode metadata Parquet exists", bool(episode_paths), f"files={len(episode_paths)}"
    )
    data = collect_tables(data_paths)
    episodes = collect_tables(episode_paths)
    tasks = pq.read_table(root / "meta/tasks.parquet")

    required_columns = {
        "observation.state",
        "action",
        "episode_index",
        "frame_index",
        "timestamp",
        "index",
        "task_index",
    }
    missing_columns = sorted(required_columns - set(data.column_names))
    add_check(checks, "schema", "required frame columns", not missing_columns, f"missing={missing_columns}")
    if missing_columns:
        raise ValueError(f"Missing frame columns: {missing_columns}")

    total_frames = int(info["total_frames"])
    total_episodes = int(info["total_episodes"])
    total_tasks = int(info["total_tasks"])
    add_check(checks, "counts", "frame count matches info", len(data) == total_frames, f"parquet={len(data)}, info={total_frames}")
    add_check(
        checks,
        "counts",
        "episode count matches info",
        len(episodes) == total_episodes,
        f"metadata={len(episodes)}, info={total_episodes}",
    )
    add_check(checks, "counts", "task count matches info", len(tasks) == total_tasks, f"tasks={len(tasks)}, info={total_tasks}")

    state_field = data.schema.field("observation.state")
    action_field = data.schema.field("action")
    state_dim = fixed_list_dim(state_field)
    action_dim = fixed_list_dim(action_field)
    declared_state_shape = feature_shape(info, "observation.state")
    declared_action_shape = feature_shape(info, "action")
    add_check(checks, "schema", "state dimension matches info", declared_state_shape == [state_dim], f"parquet={state_dim}, info={declared_state_shape}")
    add_check(checks, "schema", "action dimension matches info", declared_action_shape == [action_dim], f"parquet={action_dim}, info={declared_action_shape}")
    if expected_state_dim is not None:
        add_check(checks, "schema", "state dimension matches expectation", state_dim == expected_state_dim, f"actual={state_dim}, expected={expected_state_dim}")
    if expected_action_dim is not None:
        add_check(checks, "schema", "action dimension matches expectation", action_dim == expected_action_dim, f"actual={action_dim}, expected={expected_action_dim}")

    state = numeric_matrix(data, "observation.state")
    action = numeric_matrix(data, "action")
    add_check(checks, "values", "state values finite", array_is_finite(state), f"shape={state.shape}")
    add_check(checks, "values", "action values finite", array_is_finite(action), f"shape={action.shape}")

    for key, observed in (("observation.state", state), ("action", action)):
        recorded = stats.get(key, {})
        recorded_min = np.asarray(recorded.get("min", []), dtype=np.float64)
        recorded_max = np.asarray(recorded.get("max", []), dtype=np.float64)
        observed_min = np.min(observed, axis=0)
        observed_max = np.max(observed, axis=0)
        bounds_match = (
            recorded_min.shape == observed_min.shape
            and recorded_max.shape == observed_max.shape
            and np.allclose(recorded_min, observed_min, rtol=0, atol=1e-5)
            and np.allclose(recorded_max, observed_max, rtol=0, atol=1e-5)
        )
        add_check(
            checks,
            "statistics",
            f"{key} min/max match metadata",
            bool(bounds_match),
            f"observed_min={observed_min.tolist()}, observed_max={observed_max.tolist()}",
        )

    episode_indices = data["episode_index"].to_numpy()
    frame_indices = data["frame_index"].to_numpy()
    timestamps = data["timestamp"].to_numpy()
    global_indices = data["index"].to_numpy()
    task_indices = data["task_index"].to_numpy()
    ep_rows = sorted(episodes.to_pylist(), key=lambda row: row["episode_index"])
    expected_episode_indices = list(range(total_episodes))
    add_check(
        checks,
        "episodes",
        "episode indices contiguous",
        [row["episode_index"] for row in ep_rows] == expected_episode_indices,
        f"range=0..{total_episodes - 1}",
    )
    bounds_ok = bool(ep_rows) and ep_rows[0]["dataset_from_index"] == 0
    previous_to = 0
    episode_content_ok = True
    timestamp_ok = True
    lengths = []
    for row in ep_rows:
        start = int(row["dataset_from_index"])
        stop = int(row["dataset_to_index"])
        length = int(row["length"])
        lengths.append(length)
        bounds_ok &= start == previous_to and stop - start == length and length > 0
        previous_to = stop
        section = slice(start, stop)
        episode_id = int(row["episode_index"])
        episode_content_ok &= bool(np.all(episode_indices[section] == episode_id))
        episode_content_ok &= bool(np.array_equal(frame_indices[section], np.arange(length)))
        timestamp_ok &= timestamps_match(timestamps[section], float(info["fps"]))
    bounds_ok &= previous_to == total_frames
    add_check(checks, "episodes", "episode bounds contiguous", bounds_ok, f"final_to={previous_to}, total_frames={total_frames}")
    add_check(checks, "episodes", "frame indices reset and remain contiguous", episode_content_ok, f"episodes={len(ep_rows)}")
    add_check(checks, "time", "timestamps match frame_index / fps", timestamp_ok, f"fps={info['fps']}, atol=1e-5")
    add_check(checks, "indices", "global index contiguous", bool(np.array_equal(global_indices, np.arange(total_frames))), f"range=0..{total_frames - 1}")

    valid_task_ids = set(tasks["task_index"].to_pylist())
    unknown_task_ids = sorted(set(task_indices.tolist()) - valid_task_ids)
    add_check(checks, "tasks", "all task indices resolve", not unknown_task_ids, f"unknown={unknown_task_ids}, valid={sorted(valid_task_ids)}")

    summary = {
        "data_files": [{"path": str(path.relative_to(root)), "sha256": sha256(path)} for path in data_paths],
        "episode_metadata_files": [
            {"path": str(path.relative_to(root)), "sha256": sha256(path)} for path in episode_paths
        ],
        "frames": total_frames,
        "episodes": total_episodes,
        "tasks": total_tasks,
        "state_dim": state_dim,
        "action_dim": action_dim,
        "episode_length": {
            "min": min(lengths),
            "max": max(lengths),
            "mean": float(np.mean(lengths)),
        },
        "state_min": np.min(state, axis=0).tolist(),
        "state_max": np.max(state, axis=0).tolist(),
        "action_min": np.min(action, axis=0).tolist(),
        "action_max": np.max(action, axis=0).tolist(),
    }
    return data, episodes, tasks, summary


def expected_video_files(root: Path, info: dict[str, Any], episodes: pa.Table) -> dict[Path, dict[str, Any]]:
    result: dict[Path, dict[str, Any]] = {}
    template = info["video_path"]
    for key, feature in info["features"].items():
        if feature.get("dtype") != "video":
            continue
        chunk_column = f"videos/{key}/chunk_index"
        file_column = f"videos/{key}/file_index"
        if chunk_column not in episodes.column_names or file_column not in episodes.column_names:
            continue
        for row in episodes.select([chunk_column, file_column, "length"]).to_pylist():
            relative = template.format(
                video_key=key,
                chunk_index=int(row[chunk_column]),
                file_index=int(row[file_column]),
            )
            path = root / relative
            file_summary = result.setdefault(
                path, {"key": key, "episodes": 0, "expected_frames": 0}
            )
            file_summary["episodes"] += 1
            file_summary["expected_frames"] += int(row["length"])
    return result


def check_videos(
    root: Path,
    info: dict[str, Any],
    episodes: pa.Table,
    checks: list[Check],
    expected_cameras: list[str],
) -> dict[str, Any]:
    declared_cameras = sorted(
        key for key, feature in info["features"].items() if feature.get("dtype") == "video"
    )
    missing_expected = sorted(set(expected_cameras) - set(declared_cameras))
    add_check(checks, "video", "expected camera keys declared", not missing_expected, f"declared={declared_cameras}, missing={missing_expected}")

    expected_files = expected_video_files(root, info, episodes)
    add_check(
        checks,
        "video",
        "video metadata references resolve",
        bool(expected_files) == bool(declared_cameras),
        f"declared_cameras={len(declared_cameras)}, referenced_files={len(expected_files)}",
    )
    missing_files = [str(path.relative_to(root)) for path in expected_files if not path.is_file()]
    add_check(checks, "video", "referenced video files exist", not missing_files, f"referenced={len(expected_files)}, missing={missing_files}")

    files = []
    for path, reference in expected_files.items():
        if not path.is_file():
            continue
        key = reference["key"]
        feature = info["features"][key]
        expected_height, expected_width, expected_channels = feature["shape"]
        with av.open(str(path)) as container:
            stream = container.streams.video[0]
            decoded = 0
            first_stats = None
            for frame in container.decode(video=0):
                if decoded == 0:
                    rgb = frame.to_ndarray(format="rgb24")
                    first_stats = {
                        "shape": list(rgb.shape),
                        "min": int(rgb.min()),
                        "max": int(rgb.max()),
                        "mean": float(rgb.mean()),
                        "std": float(rgb.std()),
                    }
                decoded += 1
            fps = float(stream.average_rate)
            shape_ok = (
                stream.height == expected_height
                and stream.width == expected_width
                and expected_channels == 3
            )
            fps_ok = math.isclose(fps, float(info["fps"]), rel_tol=0, abs_tol=1e-6)
            nonconstant = first_stats is not None and first_stats["std"] > 1e-6
            add_check(checks, "video", f"{key} dimensions", shape_ok, f"stream={stream.width}x{stream.height}, schema={feature['shape']}")
            add_check(checks, "video", f"{key} fps", fps_ok, f"stream={fps}, dataset={info['fps']}")
            add_check(checks, "video", f"{key} decodes", decoded > 0, f"frames={decoded}")
            add_check(
                checks,
                "video",
                f"{key} frame count",
                decoded == reference["expected_frames"],
                "decoded={}, episode_metadata={}".format(decoded, reference["expected_frames"]),
            )
            add_check(checks, "video", f"{key} first frame nonconstant", bool(nonconstant), f"stats={first_stats}")
            files.append(
                {
                    "path": str(path.relative_to(root)),
                    "key": key,
                    "sha256": sha256(path),
                    "frames_decoded": decoded,
                    "stream_frames_reported": stream.frames,
                    "fps": fps,
                    "codec": stream.codec_context.name,
                    "pixel_format": stream.codec_context.pix_fmt,
                    "first_frame": first_stats,
                }
            )
    return {"declared_cameras": declared_cameras, "files": files}


def check_api_samples(
    root: Path,
    repo_id: str,
    revision: str | None,
    info: dict[str, Any],
    checks: list[Check],
    sample_count: int,
) -> tuple[LeRobotDataset, list[dict[str, Any]]]:
    dataset = LeRobotDataset(repo_id, root=root, revision=revision, video_backend="pyav")
    add_check(checks, "api", "LeRobotDataset length matches info", len(dataset) == info["total_frames"], f"api={len(dataset)}, info={info['total_frames']}")
    count = min(max(sample_count, 1), len(dataset))
    indices = sorted(set(np.linspace(0, len(dataset) - 1, count, dtype=int).tolist()))
    sample_results = []
    all_valid = True
    for index in indices:
        sample = dataset[index]
        entry = {"index": index, "features": {}}
        for key, feature in info["features"].items():
            if key not in sample:
                entry["features"][key] = {"missing": True}
                all_valid = False
                continue
            if not isinstance(sample[key], torch.Tensor):
                entry["features"][key] = {"not_tensor": True}
                all_valid = False
                continue
            value = sample[key]
            finite = bool(torch.isfinite(value).all()) if value.dtype.is_floating_point else True
            expected_dtype = {
                "video": torch.float32,
                "float32": torch.float32,
                "float64": torch.float64,
                "int64": torch.int64,
                "bool": torch.bool,
            }.get(feature["dtype"])
            dtype_ok = expected_dtype is None or value.dtype == expected_dtype
            expected_shape = list(feature["shape"])
            if feature["dtype"] == "video":
                expected_shape = [expected_shape[2], expected_shape[0], expected_shape[1]]
            shape_ok = list(value.shape) == expected_shape or (expected_shape == [1] and value.ndim == 0)
            stats = {
                "shape": list(value.shape),
                "dtype": str(value.dtype),
                "dtype_matches_schema": dtype_ok,
                "finite": finite,
            }
            if value.dtype.is_floating_point:
                stats.update(min=float(value.min()), max=float(value.max()), std=float(value.float().std(unbiased=False)))
            if feature["dtype"] == "video":
                nonconstant = float(value.float().std(unbiased=False)) > 1e-6
                in_range = float(value.min()) >= 0.0 and float(value.max()) <= 1.0
                stats.update(nonconstant=nonconstant, in_unit_range=in_range)
                all_valid &= nonconstant and in_range
            all_valid &= finite and shape_ok and dtype_ok
            stats["shape_matches_schema"] = shape_ok
            entry["features"][key] = stats
        sample_results.append(entry)
    add_check(checks, "api", "sample tensors valid", all_valid, f"indices={indices}")
    return dataset, sample_results


def check_action_window(
    root: Path,
    repo_id: str,
    revision: str | None,
    info: dict[str, Any],
    checks: list[Check],
    window: int,
) -> dict[str, Any] | None:
    if window <= 0:
        return None
    offsets = [index / float(info["fps"]) for index in range(window)]
    dataset = LeRobotDataset(
        repo_id,
        root=root,
        revision=revision,
        delta_timestamps={"action": offsets},
        video_backend="pyav",
    )
    first = dataset[0]
    terminal = dataset[len(dataset) - 1]
    action_dim = int(feature_shape(info, "action")[0])
    first_ok = list(first["action"].shape) == [window, action_dim] and not bool(first["action_is_pad"].any())
    terminal_mask = terminal["action_is_pad"]
    terminal_ok = (
        list(terminal["action"].shape) == [window, action_dim]
        and not bool(terminal_mask[0])
        and bool(terminal_mask[1:].all())
    )
    add_check(checks, "window", "first action window valid", first_ok, f"shape={list(first['action'].shape)}, mask={first['action_is_pad'].tolist()}")
    add_check(checks, "window", "terminal action padding valid", terminal_ok, f"shape={list(terminal['action'].shape)}, mask={terminal_mask.tolist()}")
    return {
        "window": window,
        "offsets_seconds": offsets,
        "first_mask": first["action_is_pad"].tolist(),
        "terminal_mask": terminal_mask.tolist(),
    }


def write_csv(path: Path, checks: list[Check]) -> None:
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["category", "name", "status", "evidence"])
        writer.writeheader()
        writer.writerows(asdict(check) for check in checks)


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    summary = report["summary"]
    parquet = report["parquet"]
    lines = [
        "# LeRobot Dataset Health Report",
        "",
        "## Summary",
        "",
        f"- Overall: **{summary['overall']}**",
        f"- Pass: `{summary['pass']}`",
        f"- Warning: `{summary['warn']}`",
        f"- Fail: `{summary['fail']}`",
        f"- Elapsed: `{report['elapsed_seconds']:.2f} s`",
        "",
        "## Dataset",
        "",
        f"- Root: `{report['dataset']['root']}`",
        f"- Repo ID: `{report['dataset']['repo_id']}`",
        f"- Revision: `{report['dataset']['revision']}`",
        f"- Frames: `{parquet.get('frames', 'unavailable')}`",
        f"- Episodes: `{parquet.get('episodes', 'unavailable')}`",
        f"- State/action dimensions: `{parquet.get('state_dim', 'unavailable')} / {parquet.get('action_dim', 'unavailable')}`",
        "",
        "## Checks",
        "",
        "| Category | Check | Status | Evidence |",
        "| --- | --- | --- | --- |",
    ]
    for check in report["checks"]:
        evidence = str(check["evidence"]).replace("|", "\\|")
        lines.append(f"| {check['category']} | {check['name']} | {check['status']} | {evidence} |")
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "`PASS` means the tested contract held for this local snapshot. `WARN` requires review but does not make the dataset unreadable. `FAIL` makes the run exit nonzero. The checker is read-only and does not establish task quality or demonstration quality.",
        ]
    )
    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    args = parse_args()
    start_time = time.perf_counter()
    root = args.root.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    checks: list[Check] = []

    try:
        info, stats = check_structure(root, checks)
        data, episodes, _tasks, parquet_summary = check_parquet(
            root,
            info,
            stats,
            checks,
            args.expected_state_dim,
            args.expected_action_dim,
        )
        video_summary = check_videos(root, info, episodes, checks, args.expected_camera)
        _dataset, api_samples = check_api_samples(
            root,
            args.repo_id,
            args.revision,
            info,
            checks,
            args.sample_count,
        )
        window_summary = check_action_window(
            root,
            args.repo_id,
            args.revision,
            info,
            checks,
            args.action_window,
        )
    except Exception as error:
        checks.append(Check("runtime", "checker completed", "FAIL", f"{type(error).__name__}: {error}"))
        parquet_summary = locals().get("parquet_summary", {})
        video_summary = locals().get("video_summary", {})
        api_samples = locals().get("api_samples", [])
        window_summary = locals().get("window_summary")

    counts = {status: sum(check.status == status for check in checks) for status in ("PASS", "WARN", "FAIL")}
    overall = "FAIL" if counts["FAIL"] else "WARN" if counts["WARN"] else "PASS"
    report = {
        "dataset": {
            "root": str(root),
            "repo_id": args.repo_id,
            "revision": args.revision,
            "read_only": True,
        },
        "summary": {
            "overall": overall,
            "pass": counts["PASS"],
            "warn": counts["WARN"],
            "fail": counts["FAIL"],
        },
        "checks": [asdict(check) for check in checks],
        "parquet": parquet_summary,
        "video": video_summary,
        "api_samples": api_samples,
        "action_window": window_summary,
        "elapsed_seconds": time.perf_counter() - start_time,
    }
    write_json(output / "health_report.json", report)
    write_csv(output / "checks.csv", checks)
    write_markdown(output / "health_report.md", report)
    print(json.dumps(report["summary"], indent=2))

    failed = counts["FAIL"] > 0 or (args.strict_warnings and counts["WARN"] > 0)
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()

