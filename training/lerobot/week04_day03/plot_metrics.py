#!/usr/bin/env python3
"""Plot loss, gradient norm, and update time from metrics.json."""

import json
from pathlib import Path

import matplotlib.pyplot as plt


ARTIFACT_DIR = Path(__file__).resolve().parent
records = json.loads((ARTIFACT_DIR / "metrics.json").read_text())["records"]
steps = [record["step"] for record in records]

fig, axes = plt.subplots(3, 1, figsize=(9, 8), sharex=True, constrained_layout=True)
axes[0].plot(steps, [record["loss"] for record in records])
axes[0].set_ylabel("loss")
axes[1].plot(steps, [record["grad_norm"] for record in records])
axes[1].set_ylabel("grad norm")
axes[2].plot(steps, [record["update_s"] for record in records])
axes[2].set_ylabel("update (s)")
axes[2].set_xlabel("optimizer step")
for axis in axes:
    axis.grid(alpha=0.25)
fig.savefig(ARTIFACT_DIR / "loss_curve.png", dpi=160)
