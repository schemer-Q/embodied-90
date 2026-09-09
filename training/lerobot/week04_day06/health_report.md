# LeRobot Dataset Health Report

## Summary

- Overall: **PASS**
- Pass: `35`
- Warning: `0`
- Fail: `0`
- Elapsed: `1.31 s`

## Dataset

- Root: `/home/nvidia/embodied-90/training/lerobot/week04_day02/dataset/lerobot_pusht`
- Repo ID: `lerobot/pusht`
- Revision: `b1c3ecbae7f244acc039a3dbc255a00dad1372b9`
- Frames: `25650`
- Episodes: `206`
- State/action dimensions: `2 / 2`

## Checks

| Category | Check | Status | Evidence |
| --- | --- | --- | --- |
| structure | required metadata files | PASS | missing=[] |
| structure | LeRobot v3 codebase version | PASS | codebase_version=v3.0 |
| statistics | metadata statistics are finite | PASS | features=11 |
| structure | data Parquet exists | PASS | files=1 |
| structure | episode metadata Parquet exists | PASS | files=1 |
| schema | required frame columns | PASS | missing=[] |
| counts | frame count matches info | PASS | parquet=25650, info=25650 |
| counts | episode count matches info | PASS | metadata=206, info=206 |
| counts | task count matches info | PASS | tasks=1, info=1 |
| schema | state dimension matches info | PASS | parquet=2, info=[2] |
| schema | action dimension matches info | PASS | parquet=2, info=[2] |
| schema | state dimension matches expectation | PASS | actual=2, expected=2 |
| schema | action dimension matches expectation | PASS | actual=2, expected=2 |
| values | state values finite | PASS | shape=(25650, 2) |
| values | action values finite | PASS | shape=(25650, 2) |
| statistics | observation.state min/max match metadata | PASS | observed_min=[13.45642375946045, 32.93829345703125], observed_max=[496.14617919921875, 510.9578857421875] |
| statistics | action min/max match metadata | PASS | observed_min=[12.0, 25.0], observed_max=[511.0, 511.0] |
| episodes | episode indices contiguous | PASS | range=0..205 |
| episodes | episode bounds contiguous | PASS | final_to=25650, total_frames=25650 |
| episodes | frame indices reset and remain contiguous | PASS | episodes=206 |
| time | timestamps match frame_index / fps | PASS | fps=10, atol=1e-5 |
| indices | global index contiguous | PASS | range=0..25649 |
| tasks | all task indices resolve | PASS | unknown=[], valid=[0] |
| video | expected camera keys declared | PASS | declared=['observation.image'], missing=[] |
| video | video metadata references resolve | PASS | declared_cameras=1, referenced_files=1 |
| video | referenced video files exist | PASS | referenced=1, missing=[] |
| video | observation.image dimensions | PASS | stream=96x96, schema=[96, 96, 3] |
| video | observation.image fps | PASS | stream=10.0, dataset=10 |
| video | observation.image decodes | PASS | frames=25650 |
| video | observation.image frame count | PASS | decoded=25650, episode_metadata=25650 |
| video | observation.image first frame nonconstant | PASS | stats={'shape': [96, 96, 3], 'min': 60, 'max': 255, 'mean': 248.80302372685185, 'std': 22.135374401280266} |
| api | LeRobotDataset length matches info | PASS | api=25650, info=25650 |
| api | sample tensors valid | PASS | indices=[0, 3206, 6412, 9618, 12824, 16030, 19236, 22442, 25649] |
| window | first action window valid | PASS | shape=[10, 2], mask=[False, False, False, False, False, False, False, False, False, False] |
| window | terminal action padding valid | PASS | shape=[10, 2], mask=[False, True, True, True, True, True, True, True, True, True] |

## Interpretation

`PASS` means the tested contract held for this local snapshot. `WARN` requires review but does not make the dataset unreadable. `FAIL` makes the run exit nonzero. The checker is read-only and does not establish task quality or demonstration quality.
