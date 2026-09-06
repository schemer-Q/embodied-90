#!/usr/bin/env python3
"""Summarize the tiny ACT run and verify that its checkpoint can be loaded."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from pathlib import Path

import torch
from lerobot.policies.act.modeling_act import ACTPolicy


METRIC_RE = re.compile(
    r"step:(?P<step>\d+).*?loss:(?P<loss>[\d.eE+-]+).*?"
    r"grdn:(?P<grad>[\d.eE+-]+).*?lr:(?P<lr>[\d.eE+-]+).*?"
    r"updt_s:(?P<update>[\d.eE+-]+).*?data_s:(?P<data>[\d.eE+-]+)"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    return parser.parse_args()


def parse_gpu_trace(path: Path) -> dict[str, float | int]:
    memory: list[float] = []
    utilization: list[float] = []
    power: list[float] = []
    with path.open() as stream:
        for row in csv.reader(stream):
            if len(row) != 5:
                continue
            try:
                utilization.append(float(row[1]))
                memory.append(float(row[2]))
                power.append(float(row[4]))
            except ValueError:
                continue
    return {
        "samples": len(memory),
        "max_memory_mib": max(memory),
        "max_utilization_percent": max(utilization),
        "max_power_w": max(power),
    }


def main() -> None:
    args = parse_args()
    artifact_dir = args.artifact_dir.resolve()
    run_dir = artifact_dir / "run"
    log_text = (artifact_dir / "train.log").read_text(errors="replace")

    records = []
    for match in METRIC_RE.finditer(log_text.replace("\r", "\n")):
        records.append(
            {
                "step": int(match.group("step")),
                "loss": float(match.group("loss")),
                "grad_norm": float(match.group("grad")),
                "lr": float(match.group("lr")),
                "update_s": float(match.group("update")),
                "data_s": float(match.group("data")),
            }
        )
    if len(records) != 50:
        raise RuntimeError(f"Expected 50 metric records, got {len(records)}")

    checkpoint_link = run_dir / "checkpoints" / "last"
    checkpoint_dir = checkpoint_link.resolve()
    model_dir = checkpoint_dir / "pretrained_model"
    model_path = model_dir / "model.safetensors"
    if not model_path.is_file():
        raise FileNotFoundError(model_path)

    policy = ACTPolicy.from_pretrained(model_dir, device="cpu")
    parameters = list(policy.parameters())
    all_parameters_finite = all(bool(torch.isfinite(parameter).all()) for parameter in parameters)
    total_parameters = sum(parameter.numel() for parameter in parameters)

    checkpoint_files = []
    for path in sorted(checkpoint_dir.rglob("*")):
        if path.is_file():
            checkpoint_files.append(
                {
                    "path": str(path.relative_to(checkpoint_dir)),
                    "bytes": path.stat().st_size,
                    "sha256": sha256(path),
                }
            )

    losses = [record["loss"] for record in records]
    gradients = [record["grad_norm"] for record in records]
    metrics = {
        "completed_steps": len(records),
        "expected_steps": 50,
        "first_loss": losses[0],
        "last_loss": losses[-1],
        "min_loss": min(losses),
        "max_loss": max(losses),
        "mean_loss_first_10": sum(losses[:10]) / 10,
        "mean_loss_last_10": sum(losses[-10:]) / 10,
        "all_losses_finite": all(math.isfinite(value) for value in losses),
        "all_logged_grad_norms_finite": all(math.isfinite(value) for value in gradients),
        "nonzero_grad_steps": sum(value > 0 for value in gradients),
        "mean_update_s": sum(record["update_s"] for record in records) / len(records),
        "mean_dataloading_s": sum(record["data_s"] for record in records) / len(records),
        "gpu": parse_gpu_trace(artifact_dir / "gpu_trace.csv"),
        "checkpoint": {
            "path": str(checkpoint_dir),
            "model_sha256": sha256(model_path),
            "load_smoke_pass": True,
            "all_parameters_finite": all_parameters_finite,
            "total_parameters": total_parameters,
        },
        "records": records,
    }
    if not all_parameters_finite:
        raise RuntimeError("Loaded checkpoint contains NaN/Inf parameters")

    manifest = {
        "checkpoint_link": str(checkpoint_link),
        "resolved_checkpoint": str(checkpoint_dir),
        "files": checkpoint_files,
        "total_bytes": sum(item["bytes"] for item in checkpoint_files),
    }
    (artifact_dir / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    (artifact_dir / "checkpoint_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({key: value for key, value in metrics.items() if key != "records"}, indent=2))


if __name__ == "__main__":
    main()
