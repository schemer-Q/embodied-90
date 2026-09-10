# LeRobot Pipeline Command Index

## Status Legend

| Status | Meaning |
| --- | --- |
| Verified | Executed locally during Week 4 with saved evidence |
| CLI confirmed | Entry point and arguments confirmed from LeRobot 0.4.4; not executed end to end |
| Blocked | Current training venv lacks a runtime dependency or hardware |
| Planned | Template for Week 5; ports, IDs, camera indices and Hub revisions must be frozen first |

## Environment and Data

| Step | Command | Input | Output | Gate | Status |
| --- | --- | --- | --- | --- | --- |
| Build isolated environment | `bash training/lerobot/week04_day03/setup_training_environment.sh` | RoboDojo Python 3.11/Torch 2.7 base | `/tmp/embodied90-week04-day02-lerobot` | ACT CLI imports | Verified |
| Acquire pinned sample data | `bash training/lerobot/week04_day02/run_validation.sh` | `lerobot/pusht` revision `b1c3ecb...` | Local LeRobot v3 snapshot and manifest | Dataset schema and hashes recorded | Verified |
| Check dataset | `python training/lerobot/week04_day06/check_dataset.py --root "$DATASET_ROOT" --repo-id "$DATASET_REPO" --revision "$DATASET_REV" --expected-state-dim "$STATE_DIM" --expected-action-dim "$ACTION_DIM" --action-window "$CHUNK_SIZE" --output "$REPORT_DIR"` | Local v3 dataset | JSON, CSV and Markdown reports | No FAIL; optionally `--strict-warnings` | Verified |
| Visual review | `bash training/lerobot/week04_day02/run_validation.sh` | Selected episode | Contact sheet and state/action plots | Cameras and trajectories plausible | Verified for PushT |

## SO-101 Collection Templates

Use environment variables or a local untracked configuration for ports and IDs. Never commit credentials or host-specific device paths as universal defaults.

```bash
lerobot-find-port
lerobot-find-cameras opencv --output-dir outputs/cameras --record-time-s 6

lerobot-calibrate \
  --robot.type=so101_follower \
  --robot.port="$FOLLOWER_PORT" \
  --robot.id="$FOLLOWER_ID"

lerobot-calibrate \
  --teleop.type=so101_leader \
  --teleop.port="$LEADER_PORT" \
  --teleop.id="$LEADER_ID"

lerobot-teleoperate \
  --robot.type=so101_follower \
  --robot.port="$FOLLOWER_PORT" \
  --robot.id="$FOLLOWER_ID" \
  --teleop.type=so101_leader \
  --teleop.port="$LEADER_PORT" \
  --teleop.id="$LEADER_ID"

lerobot-record \
  --robot.type=so101_follower \
  --robot.port="$FOLLOWER_PORT" \
  --robot.id="$FOLLOWER_ID" \
  --robot.cameras="{front: {type: opencv, index_or_path: $CAMERA_INDEX, width: 640, height: 480, fps: 30}}" \
  --teleop.type=so101_leader \
  --teleop.port="$LEADER_PORT" \
  --teleop.id="$LEADER_ID" \
  --dataset.repo_id="$DATASET_REPO" \
  --dataset.root="$DATASET_ROOT" \
  --dataset.num_episodes=10 \
  --dataset.single_task="$TASK_TEXT" \
  --dataset.push_to_hub=false \
  --display_data=true
```

`lerobot-find-port` is interactive and asks the operator to disconnect a USB cable. In the current training venv, `lerobot-record` and `lerobot-teleoperate` fail during import because optional package `rerun` is absent. These commands are therefore **Blocked/Planned**, not validated workflows. Hardware motion also requires an operator-controlled stop and low-speed limits.

## Hub Transfer

Authenticate outside scripts with `hf auth login` or an injected `HF_TOKEN`. Do not place token values in shell history, reports, patches or Git.

```bash
hf upload "$DATASET_REPO" "$DATASET_ROOT" . \
  --repo-type dataset \
  --private \
  --commit-message "Upload validated dataset"

hf download "$DATASET_REPO" \
  --repo-type dataset \
  --revision "$DATASET_REV" \
  --local-dir "$TRAIN_DATASET_ROOT"

hf upload "$MODEL_REPO" "$CHECKPOINT_DIR" . \
  --repo-type model \
  --private \
  --commit-message "Upload validated checkpoint"

hf download "$MODEL_REPO" \
  --repo-type model \
  --revision "$MODEL_REV" \
  --local-dir "$DEPLOY_MODEL_DIR"
```

The `hf upload` and `hf download` CLI options were confirmed locally. No Week 4 dataset or checkpoint was uploaded. A Hub commit hash, not `main`, must be recorded after upload and used as the download revision.

## Training, Release, and Deployment

| Step | Command | Required artifacts | Gate | Status |
| --- | --- | --- | --- | --- |
| Tiny ACT training | `bash training/lerobot/week04_day03/train_tiny.sh` | Pinned dataset, config, seed | Finite loss/gradient; checkpoint loads | Verified |
| Parameter update | `/tmp/embodied90-week04-day02-lerobot/bin/python training/lerobot/week04_day03/verify_parameter_update.py` | Checkpoint and dataset metadata | Trained state differs from initialization | Verified |
| Offline inference | `bash training/lerobot/week04_day04/run_offline_inference.sh` | Model, config, preprocessor, postprocessor | Finite action; deterministic repeat; queue check | Verified |
| Chunk contract | `bash training/lerobot/week04_day05/run_analysis.sh` | Checkpoint and action window | Normalization, padding and queue checks pass | Verified |
| Policy deployment/recording | `lerobot-record ... --policy.path="$DEPLOY_MODEL_DIR"` | Robot/camera config, calibration, matching schema and processors | Low-speed dry run and stop control pass | Planned |

Before deployment, compare the downloaded model and processor hashes with the release manifest. Call `policy.reset()` at each episode boundary. Validate observation keys, image layout, state/action dimensions, FPS and normalization statistics before enabling motion.

