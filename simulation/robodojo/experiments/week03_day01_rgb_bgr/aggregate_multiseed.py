#!/usr/bin/env python3
"""Aggregate the fixed-seed RGB/BGR paired summaries."""

import csv
import json
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parent
SEEDS = (0, 1, 2)
BOUNDARIES = (51, 101, 151, 201, 251)


def load_rows(directory):
    with (directory / "full_episode_trace.jsonl").open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def summarize(seed, condition):
    directory = ROOT / condition if seed == 0 else ROOT / f"seed{seed}" / condition
    rows = load_rows(directory)
    metadata = json.loads((directory / "full_episode_metadata.json").read_text(encoding="utf-8"))
    integrity = json.loads((directory / "full_episode_summary.json").read_text(encoding="utf-8"))
    initial_coin = np.asarray(metadata["initial_state"]["coin_pose"]["position"], dtype=float)
    coin = np.asarray([row["coin_pose"]["position"] for row in rows], dtype=float)
    surface = np.asarray([row["fingertip_surface"]["minimum_surface_distance_m"] for row in rows])
    alignment = np.asarray([row["fingertip_alignment"]["alignment_error_m"] for row in rows])
    tracking = np.asarray([row["max_internal_tracking_error"] for row in rows])
    gripper = np.asarray([row["left_gripper"] for row in rows])
    initial_gripper = float(metadata["initial_state"]["actual_joint_positions_14d"][6])
    close = next((i for i, value in enumerate(gripper) if value < 0.01), int(np.argmin(gripper)))
    return {
        "seed": seed,
        "condition": condition,
        "policy_steps": len(rows),
        "internal_records": integrity["internal_records"],
        "invalid_values": integrity["invalid_values"],
        "videos_complete": integrity["videos_complete"],
        "final_success": integrity["final_success"],
        "final_score": integrity["final_score"],
        "initial_coin_position_m": initial_coin.tolist(),
        "initial_gripper_m": initial_gripper,
        "closing_start": next((i + 1 for i, value in enumerate(gripper) if value < initial_gripper - 0.002), None),
        "noticeably_closed": close + 1,
        "closure_surface_distance_m": float(surface[close]),
        "closure_alignment_error_m": float(alignment[close]),
        "minimum_surface_distance_m": float(np.min(surface)),
        "minimum_alignment_error_m": float(np.min(alignment)),
        "max_coin_displacement_m": float(np.max(np.linalg.norm(coin - initial_coin, axis=1))),
        "max_coin_lift_m": float(np.max(coin[:, 2] - initial_coin[2])),
        "max_tracking_error": float(np.max(tracking)),
        "chunk_boundary_tracking_error": {str(step): float(tracking[step - 1]) for step in BOUNDARIES},
    }


def main():
    summaries = [summarize(seed, condition) for seed in SEEDS for condition in ("bgr", "rgb")]
    by_key = {(row["seed"], row["condition"]): row for row in summaries}
    pairs = []
    for seed in SEEDS:
        bgr = by_key[(seed, "bgr")]
        rgb = by_key[(seed, "rgb")]
        bgr_meta = json.loads(((ROOT / ("bgr" if seed == 0 else f"seed{seed}/bgr")) / "full_episode_metadata.json").read_text(encoding="utf-8"))
        rgb_meta = json.loads(((ROOT / ("rgb" if seed == 0 else f"seed{seed}/rgb")) / "full_episode_metadata.json").read_text(encoding="utf-8"))
        bgr_rows = load_rows(ROOT / ("bgr" if seed == 0 else f"seed{seed}/bgr"))
        rgb_rows = load_rows(ROOT / ("rgb" if seed == 0 else f"seed{seed}/rgb"))
        bgr_actions = np.asarray([row["act_action_14d"] for row in bgr_rows])
        rgb_actions = np.asarray([row["act_action_14d"] for row in rgb_rows])
        pairs.append({
            "seed": seed,
            "initial_coin_delta_m": float(np.max(np.abs(np.asarray(rgb_meta["initial_state"]["coin_pose"]["position"]) - np.asarray(bgr_meta["initial_state"]["coin_pose"]["position"])))),
            "action_mean_l2": float(np.mean(np.linalg.norm(rgb_actions - bgr_actions, axis=1))),
            "bgr_closure_surface_distance_m": bgr["closure_surface_distance_m"],
            "rgb_closure_surface_distance_m": rgb["closure_surface_distance_m"],
            "rgb_minus_bgr_closure_surface_distance_m": rgb["closure_surface_distance_m"] - bgr["closure_surface_distance_m"],
            "bgr_closure_alignment_error_m": bgr["closure_alignment_error_m"],
            "rgb_closure_alignment_error_m": rgb["closure_alignment_error_m"],
            "rgb_minus_bgr_closure_alignment_error_m": rgb["closure_alignment_error_m"] - bgr["closure_alignment_error_m"],
            "bgr_max_coin_displacement_m": bgr["max_coin_displacement_m"],
            "rgb_max_coin_displacement_m": rgb["max_coin_displacement_m"],
            "rgb_minus_bgr_max_coin_displacement_m": rgb["max_coin_displacement_m"] - bgr["max_coin_displacement_m"],
            "bgr_max_coin_lift_m": bgr["max_coin_lift_m"],
            "rgb_max_coin_lift_m": rgb["max_coin_lift_m"],
            "rgb_minus_bgr_max_coin_lift_m": rgb["max_coin_lift_m"] - bgr["max_coin_lift_m"],
            "bgr_max_tracking_error": bgr["max_tracking_error"],
            "rgb_max_tracking_error": rgb["max_tracking_error"],
            "bgr_success": bgr["final_success"],
            "rgb_success": rgb["final_success"],
            "bgr_score": bgr["final_score"],
            "rgb_score": rgb["final_score"],
        })
    output = {"seeds": list(SEEDS), "summaries": summaries, "paired": pairs}
    (ROOT / "multiseed_summary.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
    with (ROOT / "multiseed_comparison.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(pairs[0]))
        writer.writeheader()
        writer.writerows(pairs)
    print(json.dumps(pairs, indent=2))


if __name__ == "__main__":
    main()
