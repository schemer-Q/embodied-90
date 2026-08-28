# Week 3 Day 3: Stand Collision Replay

## Configuration

- Task/environment/action: `deposit_coin` / `arx_x5` / joint.
- Seed/layout: `0` / `0`.
- Replay source: Week 3 Day 2 RGB + `temporal_agg=false` trajectory.
- Replay SHA256: `b8f9fcf8653279b36dad0b5c04fcc83c9af790809caf9106d35268bca1192b13`.
- Replay length: 300 policy actions, each finite and 14-D; both runs returned the replay actions with maximum absolute difference `0.0`.
- ACT network: not loaded or queried. The replay-only dummy model returned one recorded action per policy step.
- A (`triangle_mesh`): `ACT_GEOMETRY_MESH_CATEGORIES=vertical_coin_stand,piggy_bank`.
- B (`official`): `ACT_GEOMETRY_MESH_CATEGORIES=piggy_bank`.

The source trajectory's step-0 coin pose was restored after reset and linear/angular velocity was zeroed in both conditions. This was necessary because collision representation already changed the coin during reset settling in the first, archived attempt.

## Single-Variable Audit

| Check | Result | Evidence |
|---|---|---|
| Frozen replay | Pass | 300 actions; identical replay SHA and executed values |
| Initial coin pose | Pass | Exact match in both stage snapshots |
| Initial robot joints | Pass | Exact 14-D match |
| Piggy-bank collision | Pass | Structured snapshots are identical |
| Coin configuration | Pass | Structured snapshots are identical |
| Stand collision | Changed | A adds root `mesh_approximation=none`; B retains official child defaults |
| Internal trajectory | Pass | 3000/3000 records per condition |
| Invalid action/state | Pass | No invalid replay actions; pose traces remain finite |

[`stage_diff.json`](week03_day03_stand_collision/stage_diff.json) contains the machine-checked assertion. Earlier non-comparable runs are retained under `attempts/` and excluded from the result.

## Results

| Metric | Triangle mesh | Official |
|---|---:|---:|
| Minimum fingertip/coin surface distance | 0.034 mm | 0.012 mm |
| First coin displacement >1 mm | policy 35, internal 7 | policy 35, internal 9 |
| Maximum coin displacement | 83.904 mm | 149.868 mm |
| Maximum coin lift | 13.336 mm | 13.280 mm |
| Maximum tracking error | 0.591604 rad | 0.591604 rad |
| Contact-report events | 0 | 0 |
| Success / score | false / 0.0 | false / 0.0 |

Both conditions reached the interaction stage: collision-mesh surface separation fell below `0.04 mm`, followed by more than `80 mm` of coin motion. The runtime `PhysxContactReportAPI` emitted no event in either run, consistent with the earlier contact-probe limitation. Therefore this report does not claim sensor-confirmed contact; near-zero collision-surface separation plus rigid-body motion is the interaction evidence.

The official condition changed the direction and magnitude of coin motion. Its maximum displacement was `65.964 mm` larger, while maximum lift differed by only `-0.056 mm`. Neither condition reached the `0.08 m` lift threshold.

## H3 Assessment

**Supported as a material interaction factor, but not established as the sole lift-failure root cause.** With identical actions and initial state, switching only the stand collision changed the coin trajectory substantially. This rules out the claim that the stand representation has no effect. However, both conditions still failed and produced nearly identical maximum lift, so the single pair does not show that the local triangle-mesh override causes the original failure by itself.

A B-to-A repeat is the next check if stronger repeatability evidence is required. The current pair supports H3 as a high-priority physics factor, not a declared final fix.

## Artifacts

- Frozen replay and provenance: [`replay_actions.jsonl`](week03_day03_stand_collision/replay_actions.jsonl), [`replay_manifest.json`](week03_day03_stand_collision/replay_manifest.json)
- Actual collision audit: [`stage_diff.json`](week03_day03_stand_collision/stage_diff.json)
- Paired metrics: [`paired_summary.json`](week03_day03_stand_collision/paired_summary.json), [`contact_comparison.csv`](week03_day03_stand_collision/contact_comparison.csv)
- Per-condition evidence: `triangle_mesh/` and `official/` contain object/control traces, empty contact traces, logs, results, stage snapshots, and three-camera keyframes.
- Plot: [`trajectory_comparison.png`](week03_day03_stand_collision/trajectory_comparison.png)
