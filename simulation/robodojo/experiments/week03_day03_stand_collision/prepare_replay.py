#!/usr/bin/env python3
"""Freeze the Week 3 Day 2 temporal=false actions for collision replay."""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
SOURCE = ROOT / "simulation/robodojo/experiments/week03_day02_temporal_agg/false/full_episode_trace.jsonl"
REPLAY = HERE / "replay_actions.jsonl"


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


rows = [json.loads(line) for line in SOURCE.read_text(encoding="utf-8").splitlines() if line]
source_metadata = json.loads((SOURCE.parent / "full_episode_metadata.json").read_text(encoding="utf-8"))
assert [row["policy_step"] for row in rows] == list(range(1, 301))
with REPLAY.open("w", encoding="utf-8") as stream:
    for row in rows:
        action = row["act_action_14d"]
        assert len(action) == 14 and all(isinstance(value, (int, float)) for value in action)
        stream.write(json.dumps({"policy_step": row["policy_step"], "action_14d": action}, separators=(",", ":")) + "\n")

manifest = {
    "source": str(SOURCE.relative_to(ROOT)),
    "source_sha256": sha256(SOURCE),
    "replay": str(REPLAY.relative_to(ROOT)),
    "replay_sha256": sha256(REPLAY),
    "policy_steps": len(rows),
    "action_dimensions": 14,
    "action_order": [
        "left_arm_joint1..joint6",
        "left_gripper_normalized",
        "right_arm_joint1..joint6",
        "right_gripper_normalized",
    ],
    "source_condition": "RGB, temporal_agg=false, seed=0, layout=0",
    "initial_state": source_metadata["initial_state"],
}
(HERE / "replay_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
print(manifest["replay_sha256"])
