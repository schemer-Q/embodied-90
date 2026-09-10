# Week 4 Report

## Goal

Establish a local, inspectable LeRobot data → training → inference workflow and document how it extends to collection, Hub transfer and deployment.

## Completion

- [x] Audited LeRobot v3 fields, episode boundaries and dual-X5 action schema.
- [x] Downloaded and visualized a pinned `lerobot/pusht` snapshot.
- [x] Completed 50 Tiny ACT optimizer steps on RTX 5070.
- [x] Reloaded the checkpoint and completed deterministic offline inference.
- [x] Verified normalization, action windows, queue consumption and padding loss.
- [x] Implemented and negatively tested a reusable dataset health checker.
- [x] Documented collection, upload, training, download and deployment flow.

## Results

| Area | Result |
| --- | --- |
| Dataset | `lerobot/pusht@b1c3ecb...`, 206 episodes and 25,650 frames |
| Training | 50/50 steps, finite loss/gradient, 11.7M-parameter checkpoint saved |
| Parameter update | 8,419,857 state values changed from same-seed initialization |
| Offline inference | Three fixed frames, finite `[1,10,2]` chunks, deterministic repeats |
| ACT timing | 21 `select_action` calls caused forwards at calls 1, 11 and 21 |
| Normalization | Manual and processor normalization error `0`; round-trip error `1.53e-5` |
| Dataset health | 35 PASS, 0 WARN, 0 FAIL; 25,650/25,650 video frames decoded |

## Deliverables

- [Dataset schema audit](../../training/lerobot/week04_day01_dataset_schema.md)
- [Dataset visualization](../../training/lerobot/week04_day02_dataset_visualization.md)
- [Tiny ACT training](../../training/lerobot/week04_day03_tiny_act_training.md)
- [Offline inference](../../training/lerobot/week04_day04_offline_inference.md)
- [ACT chunking and timing](../../training/lerobot/week04_day05_act_chunking.md)
- [Dataset health checker](../../training/lerobot/week04_day06_data_health.md)
- [End-to-end pipeline](../../training/lerobot/week04_day07_pipeline.md)
- [Command index](../../training/lerobot/week04_day07/command_index.md)

## Boundaries and Risks

- Tiny ACT is a software-path smoke test, not a task-capable policy evaluation.
- PushT is a 2-D, single-camera dataset and does not validate SO-101 or dual-X5 semantics.
- Current training venv lacks `rerun`, blocking record/teleoperate entry-point imports.
- Hub upload/download and authentication remain untested external steps.
- Robot ports, camera indices, calibration and motion safety limits require hardware validation.
- The local checkpoint is intentionally Git-ignored; its manifest and SHA256 are committed.

## Week 5 Priorities

1. Freeze the hardware LeRobot environment and install collection dependencies.
2. Prepare and verify port discovery, calibration, teleoperation and camera commands.
3. Rehearse a local-only 10-episode collection with health and visual gates.
4. Prepare ACT and SmolVLA training configurations without claiming hardware success early.

## Status

**Green.** All Week 4 deliverables are complete. The tested boundary is explicit: local data, training and offline inference pass; Hub transfer and SO-101 motion remain pending.

