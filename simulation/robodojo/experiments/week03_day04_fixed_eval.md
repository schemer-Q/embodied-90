# Week 3 Day 4: Coin-X5 Fix and Rerun

## Implemented Fix

Two defaults were changed based on the Week 3 A/B evidence:

1. ACT image input now defaults to RGB instead of BGR.
2. Triangle-mesh collision now defaults to `piggy_bank` only, leaving `vertical_coin_stand` on the official collision configuration.

Temporal aggregation remains disabled. The exact two-line change is archived in [`day04_fix.patch`](week03_day04_fixed_eval/day04_fix.patch).

## Run Configuration

- Task: `deposit_coin`
- Environment/action: `arx_x5` / joint
- Checkpoint: `RoboDojo-deposit_coin-arx_x5-joint-0`
- Seed/layout: `0` / `0`
- Episode: 300 policy steps, 10 internal controls per policy step
- Input color: RGB
- Temporal aggregation: false
- Triangle-mesh categories: `piggy_bank`
- Run ID: `week03_day04_seed0_layout0_rgb_official_stand`

The checkpoint and dataset-stat hashes are unchanged. Full configuration and dirty-worktree state are recorded in [`experiment_config.json`](week03_day04_fixed_eval/experiment_config.json).

## Fix Verification

| Check | Result | Evidence |
|---|---|---|
| ACT default is RGB | Pass | Source default and runtime metadata both report `rgb` |
| Stand uses official collision | Pass | No stand triangle-mesh override appears in the runtime log |
| Piggy bank uses triangle mesh | Pass | Runtime log records only `piggy_bank_0_3` override |
| Temporal aggregation disabled | Pass | `ACT_TEMPORAL_AGG` unset; false path retained |
| Checkpoint unchanged | Pass | SHA256 `dfbc1ddc...a56012e0` |
| Dataset stats unchanged | Pass | SHA256 `4a777e14...d04ef5b` |

Compact evidence is in [`fix_verification.txt`](week03_day04_fixed_eval/fix_verification.txt).

## Run Integrity

| Check | Result |
|---|---:|
| Policy steps | 300/300 |
| Internal records | 3000/3000 |
| Missing steps | 0 |
| Invalid values | 0 |
| Three videos | Complete |
| Result consistency | Pass |
| Exit code | 0 |

## Behavior and Result

| Event/metric | Result |
|---|---:|
| Left gripper starts closing | policy step 19 |
| Left gripper noticeably closed | policy step 34 |
| Surface distance at closure | 0.195 mm |
| Alignment error at closure | 11.649 mm |
| Minimum fingertip/coin surface distance | 0.031 mm at step 37 |
| Maximum coin displacement | 50.915 mm at step 50 |
| Maximum coin lift | 3.611 mm at step 41 |
| Lift threshold | 80 mm |
| Success / score | false / 0.0 |

The policy reaches and physically disturbs the coin, but it does not retain the coin during lift. The earliest confirmed failure remains after gripper closure and before successful lift.

## Conclusion

**The implementation fix passed, but Coin-X5 still failed.** RGB input plus the official stand collision is not sufficient to produce a successful trajectory for this fixed run. The observed maximum lift is only `3.611 mm`, far below the `80 mm` task threshold.

This run is not a new collision A/B experiment. Historical fixed-seed Isaac Sim runs show meaningful physical nondeterminism, so differences from an older single trajectory are not attributed solely to the stand change. The defensible conclusion is limited to: the intended defaults were applied correctly, the complete evaluation remained healthy, and the task outcome stayed unsuccessful.

Per the Week 3 stopping rule, Day 5 should switch to a more stable official alternative task instead of continuing unbounded Coin-X5 tuning.

## Artifacts

- Summary: [`fixed_summary.json`](week03_day04_fixed_eval/fixed_summary.json)
- Trajectory plot: [`fixed_trajectory.png`](week03_day04_fixed_eval/fixed_trajectory.png)
- Complete trace and keyframes: [`fixed/`](week03_day04_fixed_eval/fixed/)
- Run script: [`run_fixed_eval.sh`](week03_day04_fixed_eval/run_fixed_eval.sh)
- Analysis script: [`analyze_fixed.py`](week03_day04_fixed_eval/analyze_fixed.py)
