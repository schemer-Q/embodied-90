#!/usr/bin/env python3
"""Deterministic compatibility probe for the official ACT temporal ensemble."""

import json
from pathlib import Path

import numpy as np
import torch


OUTPUT = Path(__file__).with_name("temporal_agg_smoke.json")


def main():
    max_steps = 8
    num_queries = 4
    action_dim = 14
    buffer = torch.zeros(max_steps, max_steps + num_queries, action_dim)
    records = []

    for step in range(max_steps):
        chunk = torch.arange(
            1 + step * num_queries * action_dim,
            1 + (step + 1) * num_queries * action_dim,
            dtype=torch.float32,
        ).reshape(1, num_queries, action_dim)
        buffer[[step], step : step + num_queries] = chunk
        candidates = buffer[:, step]
        populated = torch.all(candidates != 0, dim=1)
        candidates = candidates[populated]
        weights = np.exp(-0.01 * np.arange(len(candidates)))
        weights = weights / weights.sum()
        action = (candidates * torch.from_numpy(weights).float().unsqueeze(1)).sum(dim=0)
        expected_candidates = min(step + 1, num_queries)
        assert candidates.shape == (expected_candidates, action_dim)
        assert action.shape == (action_dim,)
        assert torch.isfinite(action).all()
        assert np.isclose(weights.sum(), 1.0)
        records.append(
            {
                "step": step,
                "candidate_count": len(candidates),
                "weights": weights.tolist(),
                "action_finite": True,
                "action_dim": len(action),
            }
        )

    OUTPUT.write_text(
        json.dumps(
            {
                "formula": "exp(-0.01 * arange(candidate_count)) normalized",
                "query_frequency": 1,
                "num_queries": num_queries,
                "action_dim": action_dim,
                "records": records,
                "passed": True,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print("temporal aggregation synthetic smoke: pass")


if __name__ == "__main__":
    main()
