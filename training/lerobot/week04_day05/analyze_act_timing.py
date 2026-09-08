#!/usr/bin/env python3
"""Verify ACT action windows, normalization, queue consumption, and padding loss."""

from __future__ import annotations

import argparse
import csv
import inspect
import json
from pathlib import Path

import matplotlib
import numpy as np
import torch
import torch.nn.functional as F
from safetensors.torch import load_file

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from lerobot.datasets.factory import resolve_delta_timestamps
from lerobot.datasets.lerobot_dataset import LeRobotDataset, LeRobotDatasetMetadata
from lerobot.policies.act.configuration_act import ACTConfig
from lerobot.policies.act.modeling_act import ACTPolicy, ACTTemporalEnsembler
from lerobot.policies.factory import make_pre_post_processors
from lerobot.processor.normalize_processor import NormalizerProcessorStep
from lerobot.utils.random_utils import set_seed


REPO_ID = "lerobot/pusht"
REVISION = "b1c3ecbae7f244acc039a3dbc255a00dad1372b9"
EPS = 1e-8


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--frames", type=int, nargs="+", default=[0, 80, 160])
    parser.add_argument("--queue-frame", type=int, default=80)
    parser.add_argument("--seed", type=int, default=20260908)
    return parser.parse_args()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n")


def values(value: torch.Tensor) -> object:
    return value.detach().cpu().tolist()


def max_abs(left: torch.Tensor, right: torch.Tensor) -> float:
    return float((left.detach().cpu() - right.detach().cpu()).abs().max())


def source_location(value: object) -> dict[str, object]:
    value = inspect.unwrap(value)
    path = inspect.getsourcefile(value)
    _, line = inspect.getsourcelines(value)
    return {"file": path, "line": line}


def relevant_sample(sample: dict[str, object]) -> dict[str, object]:
    keys = {"observation.image", "observation.state", "action", "action_is_pad"}
    return {
        key: value.unsqueeze(0) if isinstance(value, torch.Tensor) else value
        for key, value in sample.items()
        if key in keys
    }


def normalization_check(
    dataset: LeRobotDataset,
    frames: list[int],
    preprocessor: object,
    postprocessor: object,
    stats: dict[str, torch.Tensor],
) -> dict[str, object]:
    feature_checks = []
    max_normalize_error = 0.0
    max_unnormalize_error = 0.0
    for frame_index in frames:
        sample = dataset[frame_index]
        batch = preprocessor(relevant_sample(sample))
        for key in ("observation.image", "observation.state", "action"):
            raw = sample[key].unsqueeze(0).to(batch[key].device)
            mean = stats[f"{key}.mean"].to(device=raw.device, dtype=raw.dtype)
            std = stats[f"{key}.std"].to(device=raw.device, dtype=raw.dtype)
            manual = (raw - mean) / (std + EPS)
            error = max_abs(manual, batch[key])
            max_normalize_error = max(max_normalize_error, error)
            feature_checks.append(
                {
                    "frame_index": frame_index,
                    "key": key,
                    "raw_shape": list(raw.shape),
                    "processed_shape": list(batch[key].shape),
                    "mean": values(mean),
                    "std": values(std),
                    "max_abs_error": error,
                }
            )

        normalized_action = batch["action"]
        restored = postprocessor(normalized_action)
        action_mean = stats["action.mean"].to(normalized_action.device)
        action_std = stats["action.std"].to(normalized_action.device)
        manual_restored = normalized_action * action_std + action_mean
        unnormalize_error = max_abs(manual_restored, restored)
        roundtrip_error = max_abs(restored, sample["action"].unsqueeze(0))
        max_unnormalize_error = max(max_unnormalize_error, unnormalize_error, roundtrip_error)
        feature_checks.append(
            {
                "frame_index": frame_index,
                "key": "action_roundtrip",
                "manual_vs_postprocessor_max_abs_error": unnormalize_error,
                "raw_vs_roundtrip_max_abs_error": roundtrip_error,
            }
        )

    return {
        "formula": {
            "normalize": "(x - mean) / (std + 1e-8)",
            "unnormalize": "x_normalized * std + mean",
            "mode": "MEAN_STD",
        },
        "statistics_count": {
            key: values(stats[f"{key}.count"])
            for key in ("observation.image", "observation.state", "action")
        },
        "checks": feature_checks,
        "max_normalize_error": max_normalize_error,
        "max_unnormalize_or_roundtrip_error": max_unnormalize_error,
        "pass": max_normalize_error <= 1e-6 and max_unnormalize_error <= 1e-4,
    }


def temporal_window_check(
    dataset: LeRobotDataset,
    config: ACTConfig,
    frames: list[int],
    delta_timestamps: dict[str, list[float]],
) -> dict[str, object]:
    frame_checks = []
    for frame_index in frames:
        sample = dataset[frame_index]
        mask = sample["action_is_pad"]
        clamped_indices = [min(frame_index + offset, len(dataset) - 1) for offset in config.action_delta_indices]
        frame_checks.append(
            {
                "frame_index": frame_index,
                "requested_episode_frame_indices": [
                    frame_index + offset for offset in config.action_delta_indices
                ],
                "resolved_episode_frame_indices": clamped_indices,
                "action_is_pad": values(mask),
                "valid_action_count": int((~mask).sum()),
                "padded_action_count": int(mask.sum()),
                "action_targets": values(sample["action"]),
            }
        )

    return {
        "fps": dataset.meta.fps,
        "chunk_size": config.chunk_size,
        "n_action_steps": config.n_action_steps,
        "observation_delta_indices": config.observation_delta_indices,
        "action_delta_indices": config.action_delta_indices,
        "delta_timestamps_seconds": delta_timestamps,
        "observation_history": "current observation only",
        "frames": frame_checks,
        "checks": {
            "action_offsets_are_0_through_9": config.action_delta_indices == list(range(10)),
            "no_observation_history_window": config.observation_delta_indices is None,
            "terminal_frame_has_one_valid_and_nine_padded": bool(
                (~dataset[len(dataset) - 1]["action_is_pad"]).sum() == 1
                and dataset[len(dataset) - 1]["action_is_pad"].sum() == 9
            ),
        },
    }


def queue_check(
    policy: ACTPolicy,
    processed_observation: dict[str, torch.Tensor],
    postprocessor: object,
    calls: int,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    forward_count = 0

    def count_forward(_module: object, _inputs: object, _output: object) -> None:
        nonlocal forward_count
        forward_count += 1

    handle = policy.model.register_forward_hook(count_forward)
    policy.reset()
    rows = []
    try:
        for call_index in range(calls):
            queue_before = len(policy._action_queue)
            forward_before = forward_count
            with torch.inference_mode():
                normalized_action = policy.select_action(processed_observation)
            action = postprocessor(normalized_action)
            rows.append(
                {
                    "call": call_index + 1,
                    "chunk_number": call_index // policy.config.n_action_steps + 1,
                    "chunk_action_index": call_index % policy.config.n_action_steps,
                    "queue_length_before": queue_before,
                    "queue_length_after": len(policy._action_queue),
                    "forward_called": forward_count > forward_before,
                    "cumulative_forward_calls": forward_count,
                    "normalized_action_0": float(normalized_action[0, 0]),
                    "normalized_action_1": float(normalized_action[0, 1]),
                    "action_0": float(action[0, 0]),
                    "action_1": float(action[0, 1]),
                }
            )
    finally:
        handle.remove()

    refresh_calls = [row["call"] for row in rows if row["forward_called"]]
    expected_refresh_calls = list(range(1, calls + 1, policy.config.n_action_steps))
    summary = {
        "calls": calls,
        "forward_calls": forward_count,
        "refresh_calls": refresh_calls,
        "expected_refresh_calls": expected_refresh_calls,
        "queue_capacity": policy.config.n_action_steps,
        "pass": refresh_calls == expected_refresh_calls,
    }
    return rows, summary


def padding_loss_check(
    policy: ACTPolicy,
    processed_terminal_batch: dict[str, torch.Tensor],
    seed: int,
) -> dict[str, object]:
    baseline = {key: value.clone() if isinstance(value, torch.Tensor) else value for key, value in processed_terminal_batch.items()}
    padded_perturbation = {
        key: value.clone() if isinstance(value, torch.Tensor) else value for key, value in baseline.items()
    }
    valid_perturbation = {
        key: value.clone() if isinstance(value, torch.Tensor) else value for key, value in baseline.items()
    }
    mask = baseline["action_is_pad"]
    padded_perturbation["action"][mask] += 123.0
    valid_perturbation["action"][:, 0] += 1.0

    policy.train()
    losses = []
    l1_losses = []
    for batch in (baseline, padded_perturbation, valid_perturbation):
        set_seed(seed)
        with torch.inference_mode():
            loss, loss_dict = policy(batch)
        losses.append(float(loss))
        l1_losses.append(float(loss_dict["l1_loss"]))
    policy.eval()

    synthetic_target = torch.tensor([[[1.0], [20.0], [30.0]]])
    synthetic_prediction = torch.zeros_like(synthetic_target)
    synthetic_mask = torch.tensor([[False, True, True]])
    masked_terms = (
        F.l1_loss(synthetic_target, synthetic_prediction, reduction="none")
        * ~synthetic_mask.unsqueeze(-1)
    )
    synthetic_loss = float(masked_terms.mean())

    padded_difference = abs(losses[0] - losses[1])
    valid_difference = abs(losses[0] - losses[2])
    return {
        "terminal_action_is_pad": values(mask),
        "baseline_total_loss": losses[0],
        "padded_targets_plus_123_total_loss": losses[1],
        "first_valid_target_plus_1_total_loss": losses[2],
        "baseline_l1_loss": l1_losses[0],
        "padded_targets_plus_123_l1_loss": l1_losses[1],
        "first_valid_target_plus_1_l1_loss": l1_losses[2],
        "padded_perturbation_loss_difference": padded_difference,
        "valid_perturbation_loss_difference": valid_difference,
        "synthetic_example": {
            "target": values(synthetic_target),
            "is_pad": values(synthetic_mask),
            "masked_l1_terms": values(masked_terms),
            "mean_loss": synthetic_loss,
            "interpretation": "padded terms contribute zero numerator but remain in mean denominator",
        },
        "checks": {
            "padded_target_values_do_not_change_loss": padded_difference <= 1e-7,
            "valid_target_value_changes_loss": valid_difference > 1e-7,
            "synthetic_mask_matches_expected_mean": abs(synthetic_loss - 1.0 / 3.0) <= 1e-7,
        },
    }


def save_plot(output: Path, rows: list[dict[str, object]], terminal_mask: torch.Tensor) -> None:
    calls = [int(row["call"]) for row in rows]
    forward_calls = [int(row["cumulative_forward_calls"]) for row in rows]
    queue_lengths = [int(row["queue_length_after"]) for row in rows]

    fig, axes = plt.subplots(2, 1, figsize=(9, 6), constrained_layout=True)
    axes[0].step(calls, queue_lengths, where="mid", label="queue length after select_action")
    axes[0].step(calls, forward_calls, where="mid", label="cumulative model forwards")
    axes[0].set_xticks(calls)
    axes[0].set_xlabel("select_action call")
    axes[0].set_ylabel("count")
    axes[0].grid(alpha=0.25)
    axes[0].legend()

    offsets = np.arange(len(terminal_mask))
    colors = ["#2f855a" if not item else "#c53030" for item in terminal_mask.tolist()]
    axes[1].bar(offsets, np.ones_like(offsets), color=colors)
    axes[1].set_xticks(offsets)
    axes[1].set_yticks([])
    axes[1].set_xlabel("action offset from terminal frame")
    axes[1].set_title("green = valid target, red = padding masked from L1")
    fig.savefig(output / "chunk_window_plot.png", dpi=160)
    plt.close(fig)


def main() -> None:
    args = parse_args()
    dataset_root = args.dataset_root.resolve()
    checkpoint = args.checkpoint.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for this validation")

    policy = ACTPolicy.from_pretrained(checkpoint, device="cuda")
    policy.eval()
    preprocessor, postprocessor = make_pre_post_processors(
        policy.config,
        pretrained_path=str(checkpoint),
    )
    metadata = LeRobotDatasetMetadata(
        REPO_ID,
        root=dataset_root,
        revision=REVISION,
    )
    delta_timestamps = resolve_delta_timestamps(policy.config, metadata)
    if delta_timestamps is None:
        raise RuntimeError("ACT training window unexpectedly resolved to None")
    dataset = LeRobotDataset(
        REPO_ID,
        root=dataset_root,
        revision=REVISION,
        episodes=[0],
        delta_timestamps=delta_timestamps,
        video_backend="pyav",
    )

    stats_path = checkpoint / "policy_preprocessor_step_3_normalizer_processor.safetensors"
    stats = load_file(stats_path)
    normalization = normalization_check(dataset, args.frames, preprocessor, postprocessor, stats)
    temporal_window = temporal_window_check(dataset, policy.config, args.frames, delta_timestamps)

    queue_sample = dataset[args.queue_frame]
    queue_observation = preprocessor(
        {
            "observation.image": queue_sample["observation.image"],
            "observation.state": queue_sample["observation.state"],
        }
    )
    queue_rows, queue_summary = queue_check(policy, queue_observation, postprocessor, calls=21)

    terminal_sample = dataset[len(dataset) - 1]
    terminal_batch = preprocessor(relevant_sample(terminal_sample))
    padding_loss = padding_loss_check(policy, terminal_batch, args.seed)
    save_plot(output, queue_rows, terminal_sample["action_is_pad"])

    with (output / "chunk_trace.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(queue_rows[0]))
        writer.writeheader()
        writer.writerows(queue_rows)

    source_index = {
        "resolve_delta_timestamps": source_location(resolve_delta_timestamps),
        "ACTConfig.action_delta_indices": source_location(ACTConfig.action_delta_indices.fget),
        "ACTPolicy.select_action": source_location(ACTPolicy.select_action),
        "ACTPolicy.forward": source_location(ACTPolicy.forward),
        "NormalizerProcessorStep._apply_transform": source_location(NormalizerProcessorStep._apply_transform),
        "ACTTemporalEnsembler.update": source_location(ACTTemporalEnsembler.update),
    }

    temporal_window["checks"]["all_checks_pass"] = all(temporal_window["checks"].values())
    padding_loss["checks"]["all_checks_pass"] = all(padding_loss["checks"].values())
    checks = {
        "normalization_matches_manual_formula": normalization["pass"],
        "temporal_window_matches_config": temporal_window["checks"]["all_checks_pass"],
        "queue_refreshes_only_when_empty": queue_summary["pass"],
        "padding_is_excluded_from_loss": padding_loss["checks"]["all_checks_pass"],
    }
    checks["all_checks_pass"] = all(checks.values())

    write_json(output / "normalization_check.json", normalization)
    write_json(output / "temporal_window.json", temporal_window)
    write_json(output / "padding_loss_check.json", padding_loss)
    write_json(output / "source_index.json", source_index)
    summary = {
        "run": {
            "repo_id": REPO_ID,
            "revision": REVISION,
            "episode": 0,
            "frames": args.frames,
            "queue_frame": args.queue_frame,
            "seed": args.seed,
            "checkpoint": str(checkpoint),
        },
        "config": {
            "fps": metadata.fps,
            "chunk_size": policy.config.chunk_size,
            "n_action_steps": policy.config.n_action_steps,
            "temporal_ensemble_coeff": policy.config.temporal_ensemble_coeff,
            "observation_delta_indices": policy.config.observation_delta_indices,
            "action_delta_indices": policy.config.action_delta_indices,
        },
        "normalization": {
            "max_normalize_error": normalization["max_normalize_error"],
            "max_unnormalize_or_roundtrip_error": normalization[
                "max_unnormalize_or_roundtrip_error"
            ],
        },
        "queue": queue_summary,
        "padding_loss": padding_loss,
        "checks": checks,
    }
    write_json(output / "analysis_summary.json", summary)
    print(json.dumps(summary, indent=2))

    if not checks["all_checks_pass"]:
        raise RuntimeError("One or more ACT timing checks failed")


if __name__ == "__main__":
    main()

