# Week 2 Day 4: ACT Action and Controller Validation

## Configuration

| Item | Value |
|---|---|
| RoboDojo commit | `9226f48ea694b3f53db12d4922e8b1199f8d0891` plus recorded dirty worktree |
| Task / environment / action | `deposit_coin` / `arx_x5` / `joint` |
| Policy / checkpoint | ACT / `RoboDojo-deposit_coin-arx_x5-joint-0` |
| Seed / layout / environments | `0` / `0` / `1` |
| Trace window | policy steps 20-60 inclusive |
| Internal controls | 10 per policy step, 410 records total |
| Run ID | `week02_day04_action_trace_20260822` |

The episode was intentionally stopped after policy step 60 by `ACT_DEBUG_STOP_STEP=60`. The resulting `0 success / 1 failure` is therefore not a full 300-step task score and is not used as task-outcome evidence.

## Result

**Control-chain result: Pass, with a policy chunk-boundary timing risk.** The same action is traceable from the ACT server's denormalized 14-D output through unpacking, validation, gripper conversion, interpolation, queue consumption, controller output, IsaacLab target buffer, and post-PhysX joint position. No dimension loss, left/right swap, or silent queue drop was found.

| Check | Result | Runtime evidence |
|---|---|---|
| 14-D dimension order | Pass | Server vector and client repack match exactly for all 41 actions; max absolute error `0.0` |
| Left/right mapping | Pass | `[0:6],6,[7:13],13` remain left arm, left gripper, right arm, right gripper |
| ACT denormalization | Pass | Traced server output is after `post_process`; server/client comparison error `0.0` |
| Action validation | Pass | Every traced action passed both validation calls |
| Gripper scale conversion | Pass | Observed conversion max absolute error `0.0`; values above 1 were clipped to `0.044 m` |
| 10-step interpolation | Pass | 8 interpolated plus 2 held; arm formula error `2.38e-7`, gripper error `6.94e-18`, hold error `0.0` |
| Queue consumption | Pass | Every policy step produced and consumed exactly 10 records; 410/410 present |
| Joint target write | Pass | Controller output versus IsaacLab target-buffer max absolute error `1.86e-9` |
| Actual joint response | Pass with transient | Response direction agreed with target direction for 96.0% of nontrivial samples; chunk refresh caused a temporary left-arm error |
| Close/lift ordering | Pass for command ordering; task interaction still fails | Left gripper closed before the left end effector rose, while coin z stayed constant |

Primary machine-readable evidence is in [action_trace.jsonl](week02_day04/action_trace.jsonl), [action_trace.csv](week02_day04/action_trace.csv), [action_trace_summary.json](week02_day04/action_trace_summary.json), and [action_tracking_plot.png](week02_day04/action_tracking_plot.png). The formal process log is [formal_eval.log](week02_day04/formal_eval.log).

## Action Mapping

The 14-D action order is:

| Dimensions | Unpacked key | Controller target |
|---|---|---|
| `0..5` | `left_arm_joint_state` | left `joint1..joint6` |
| `6` | `left_ee_joint_state` | left `joint7`, with `joint8 = joint7` |
| `7..12` | `right_arm_joint_state` | right `joint1..joint6` |
| `13` | `right_ee_joint_state` | right `joint7`, with `joint8 = joint7` |

`unpack_robot_state` defines dual-arm order as `[arm_0, ee_0, arm_1, ee_1]` (`XPolicyLab/utils/process_data.py:176-233`). Runtime comparison against [act_pred_log.txt](week02_day04/act_pred_log.txt) confirms that repacking the four client keys reproduces every server action exactly. Arm values enter `control_info` unchanged (`src/eval_client/eval_env.py:411-439`).

All action and joint values were finite. Arm targets remained inside the recorded runtime joint limits. The right gripper ACT output reached `1.03556`; clipping to `[0,1]` correctly produced `0.044 m`.

## Gripper Limits

Both grippers have configured physical scale `[-0.01, 0.044] m`, while the runtime finger limits are `[0.0, 0.044] m`.

The formal ACT window did not reach normalized 0. The observed ranges were:

| Side | ACT normalized | Converted target | Written target | Actual qpos |
|---|---:|---:|---:|---:|
| Left | `0.23167..0.81507` | `0.00251..0.03401 m` | `0.00251..0.04044 m` | `0.00382..0.04116 m` |
| Right | `0.95097..1.03556` | `0.04135..0.04400 m` | `0.04135..0.04400 m` | `0.04198..0.04400 m` |

Therefore no negative target was written in this ACT trace, and no actual qpos crossed the `0 m` lower limit. The exact normalized-zero path is nevertheless clear in code: `0` is converted to `-0.01 m` (`eval_env.py:420-439`), interpolation clamps against the configured `[-0.01, 0.044]` scale (`eval_env.py:618-635`), and `set_joint_position_target` writes the value directly without soft-limit clipping (`third_party/IsaacLab/.../articulation.py:1079-1101`). The runtime joint/PhysX limit constrains motion, but this run does **not** prove that a `-0.01 m` request is rewritten to `0 m` in the target buffer. A dedicated normalized-zero probe remains the correct test for that edge case.

The controller also applies a per-internal-step gripper slew limit of 20% of configured range (`control_manager.py:22-49`). This was visible at policy step 51: the left converted target was `0.024976 m`, while the final written target for that policy step was `0.022925 m`.

## Interpolation And Queue Timing

`process_control_info` uses `collect_interval=10`. Internal steps 1-8 use alpha `1/9..8/9`; steps 9-10 hold the exact policy target (`eval_env.py:575-637`). Every sequence was pushed and popped without loss (`control_manager.py:59-130`), then `RobotManager.control_robot` wrote both arm and finger targets (`robot_manager.py:356-405`) before one PhysX step (`eval_env.py:752-756`).

With `temporal_agg=false`, ACT refreshes a 50-query chunk at policy steps 1 and 51, and consumes one indexed query per observation (`act_policy.py:200-227`). It does not send all 50 queries to the environment at once.

At the chunk boundary from policy step 50 to 51:

- 14-D action jump L2 norm: `1.13475`;
- maximum per-dimension jump: `0.68593 rad`;
- maximum left-arm post-step tracking error: approximately `0.481 rad` at policy step 51;
- tracking recovered to approximately `0.0148 rad` by policy step 54.

This is not a mapping or queue-loss error. It is a discontinuity in the selected ACT action at chunk refresh, followed by expected controller/physics lag. It remains a policy timing risk worth testing separately.

## Closure And Lift Timing

The left gripper was already closing before policy step 34:

| Policy step | Left actual gripper | Left end-effector z | Coin z |
|---:|---:|---:|---:|
| 20 | `0.03833 m` | `0.96825 m` | `0.780547 m` |
| 33 | `0.01013 m` | `0.96206 m` | `0.780547 m` |
| 34 | `0.00936 m` | `0.96950 m` | `0.780547 m` |
| 40 | `0.00484 m` | `0.97723 m` | `0.780547 m` |

Thus closure precedes the clear upward motion beginning around policy step 34. The coin z remained `0.780547 m` throughout all 410 internal records. The controller did execute close-then-rise ordering, but the coin did not follow the gripper.

## Conclusion

The earliest abnormal layer is **not action transport, unpacking, left/right mapping, interpolation, queue consumption, or joint-target writing**. The formal chain delivers the intended values to the expected joints.

The remaining evidence points to two downstream candidates:

1. policy-produced grasp geometry/timing, including the substantial step 50-to-51 chunk discontinuity;
2. contact dynamics during closure, because the gripper and arm respond while coin z does not change.

The configured `-0.01 m` versus runtime `0 m` gripper lower-limit mismatch remains a documented edge case, but it was dormant in this trace and cannot explain these policy steps by itself.

## Reproduction

Run [run_action_trace.sh](week02_day04/run_action_trace.sh). The script uses the trained checkpoint, fixed seed/layout, stops at policy step 60, regenerates CSV/JSON/plot outputs, and asserts 410 complete internal records.
