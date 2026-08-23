"""Trace a fixed-seed ACT episode from policy output through task scoring."""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess

import numpy as np
import torch


ACTION_KEYS = (
    "left_arm_joint_state",
    "left_ee_joint_state",
    "right_arm_joint_state",
    "right_ee_joint_state",
)
RANDOM_ENV_KEYS = (
    "PYTHONHASHSEED",
    "CUDA_VISIBLE_DEVICES",
    "CUBLAS_WORKSPACE_CONFIG",
    "ACT_QUERY_FREQ",
    "ACT_TEMPORAL_AGG",
    "ACT_NO_INTERP",
    "GRIPPER_EPS",
    "ACT_GRIPPER_MIN_POSITION",
    "ACT_GT_REPLAY_LAYOUT_ID",
    "ROBODOJO_RUN_ID",
)


def _plain(value):
    if value is None:
        return None
    if hasattr(value, "detach"):
        value = value.detach().cpu().numpy()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _command(command, cwd):
    try:
        return subprocess.check_output(command, cwd=cwd, text=True, stderr=subprocess.STDOUT).strip()
    except Exception as exc:
        return f"unavailable: {type(exc).__name__}: {exc}"


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class FullEpisodeTracer:
    def __init__(self, env):
        self.env = env
        self.output_dir = Path(os.environ["ROBODOJO_FULL_EPISODE_TRACE_DIR"])
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.internal_path = self.output_dir / "full_episode_internal.jsonl"
        self.policy_path = self.output_dir / "full_episode_trace.jsonl"
        self.metadata_path = self.output_dir / "full_episode_metadata.json"
        self.internal_path.write_text("", encoding="utf-8")
        self.policy_path.write_text("", encoding="utf-8")
        self.current = None
        self.internal_step = 0
        self.robots = {}
        self.initial_coin_pose = None
        self.original_reset = env.reset
        self.original_take_action = env.take_action
        self.original_validate = env.validate_action_dict
        self.original_process = env.process_control_info
        self.original_step = env.step
        self.original_control_robot = env.robot_manager.control_robot

    def _target_robots(self):
        robots = {}
        for index, robot in enumerate(self.env.robot_manager.robot_list):
            if robot.type != "target":
                continue
            side = "left" if robot.arm_name.startswith("left_") else "right"
            robots[side] = (robot, self.env.robot_manager.robot_key[index])
        if set(robots) != {"left", "right"}:
            raise RuntimeError(f"Expected left/right target robots, got {sorted(robots)}")
        return robots

    def _coin_pose(self):
        manager = self.env.scene_manager.layout_manager
        instance = manager.get_instance_name(0, "coin0")
        position, orientation = manager.get_instance_pose(env_idx=0, inst_name=instance, relative=True)
        return {
            "instance_name": instance,
            "position": _plain(position),
            "orientation_wxyz": _plain(orientation),
            "frame": "env-relative",
        }

    def _state(self):
        actual_14d = []
        actual_16d = []
        end_effector_pose = {}
        for side in ("left", "right"):
            robot, articulation = self.robots[side]
            qpos = _plain(articulation.data.joint_pos[0])
            arm = [qpos[index] for index in robot.arm_joint_indices]
            gripper = [qpos[index] for index in robot.gripper_joint_indices]
            actual_14d.extend(arm + [gripper[0]])
            actual_16d.extend(arm + gripper)
            pose = self.env.robot_manager.get_real_endpose(robot, env_idx_list=[0], is_relative=True)[0]
            end_effector_pose[side] = _plain(pose)
        coin_pose = self._coin_pose()
        coin_z_delta = None
        if self.initial_coin_pose is not None:
            coin_z_delta = float(coin_pose["position"][2] - self.initial_coin_pose["position"][2])
        return actual_14d, actual_16d, end_effector_pose, coin_pose, coin_z_delta

    def _target_buffers(self):
        canonical = []
        physical = []
        for side in ("left", "right"):
            robot, articulation = self.robots[side]
            target = _plain(articulation.data.joint_pos_target[0])
            arm = [target[index] for index in robot.arm_joint_indices]
            gripper = [target[index] for index in robot.gripper_joint_indices]
            canonical.extend(arm + [gripper[0]])
            physical.extend(arm + gripper)
        return canonical, physical

    def _canonical_control(self, control):
        if not control:
            return None
        values = []
        manager = self.env.robot_manager
        for side in ("left", "right"):
            robot, _ = self.robots[side]
            arm_key = manager.process_name(robot.arm_name)
            gripper_key = manager.process_name(robot.gripper_name)
            values.extend(_plain(control[arm_key]["position"]))
            values.append(float(_plain(control[gripper_key]["position"])[0]))
        return values

    @staticmethod
    def _pack_action(action):
        return np.concatenate([np.asarray(action[key], dtype=float) for key in ACTION_KEYS]).tolist()

    def _robot_metadata(self, side):
        robot, articulation = self.robots[side]
        return {
            "side": side,
            "arm_name": robot.arm_name,
            "gripper_name": robot.gripper_name,
            "joint_names": list(articulation.joint_names),
            "arm_joint_indices": _plain(robot.arm_joint_indices),
            "gripper_joint_indices": _plain(robot.gripper_joint_indices),
            "configured_gripper_scale_m": _plain(robot.gripper_scale),
            "runtime_soft_joint_limits": _plain(articulation.data.soft_joint_pos_limits[0]),
        }

    def _write_metadata(self):
        checkpoint_dir = Path(os.environ["ROBODOJO_ACT_CHECKPOINT_DIR"])
        checkpoint_files = {}
        for name in ("policy_last.ckpt", "dataset_stats.pkl"):
            path = checkpoint_dir / name
            checkpoint_files[name] = {
                "path": str(path),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        initial_14d, initial_16d, initial_ee, _, _ = self._state()
        payload = {
            "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
            "run_id": os.environ.get("ROBODOJO_RUN_ID"),
            "launch_command": os.environ.get("ROBODOJO_FULL_LAUNCH_COMMAND"),
            "config": {
                "task": self.env.task_name,
                "env_cfg": self.env.config_name,
                "action_type": "joint",
                "policy": self.env.policy_name,
                "checkpoint": checkpoint_dir.name,
                "seed": int(self.env.eval_seed),
                "layout": int(self.env.env_seeds[0]),
                "num_envs": int(self.env.num_envs),
                "episode_limit": int(self.env.step_lim),
                "internal_controls_per_policy_step": int(self.env.obs_manager.collect_interval),
            },
            "versions": {
                "python": platform.python_version(),
                "pytorch": torch.__version__,
                "isaacsim": importlib.metadata.version("isaacsim"),
            },
            "randomness_environment": {key: os.environ.get(key) for key in RANDOM_ENV_KEYS},
            "robodojo": {
                "commit": _command(["git", "rev-parse", "HEAD"], "/home/nvidia/RoboDojo"),
                "status_short": _command(["git", "status", "--short"], "/home/nvidia/RoboDojo").splitlines(),
                "submodules_recursive": _command(
                    ["git", "submodule", "status", "--recursive"], "/home/nvidia/RoboDojo"
                ).splitlines(),
                "submodule_worktree_status": {
                    "XPolicyLab": _command(
                        ["git", "status", "--short"], "/home/nvidia/RoboDojo/XPolicyLab"
                    ).splitlines(),
                    "third_party/curobo": _command(
                        ["git", "status", "--short"], "/home/nvidia/RoboDojo/third_party/curobo"
                    ).splitlines(),
                },
            },
            "experiment_repository": {
                "commit": _command(["git", "rev-parse", "HEAD"], "/home/nvidia/embodied-90"),
                "status_short": _command(["git", "status", "--short"], "/home/nvidia/embodied-90").splitlines(),
            },
            "checkpoint_files": checkpoint_files,
            "action_order": list(ACTION_KEYS),
            "act": {"temporal_agg": False, "query_frequency": 50, "chunk_size": 50},
            "initial_state": {
                "coin_pose": self.initial_coin_pose,
                "actual_joint_positions_14d": initial_14d,
                "actual_joint_positions_physical_16d": initial_16d,
                "end_effector_pose": initial_ee,
            },
            "robots": [self._robot_metadata(side) for side in ("left", "right")],
        }
        self.metadata_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def reset(self, seed=None, options=None):
        result = self.original_reset(seed=seed, options=options)
        self.robots = self._target_robots()
        self.initial_coin_pose = self._coin_pose()
        self._write_metadata()
        return result

    def validate_action_dict(self, action):
        result = self.original_validate(action)
        if self.current is not None:
            self.current["validation_calls"] += 1
            self.current["validation_pass"] = True
        return result

    def process_control_info(self, control_info, env_idx):
        sequence = self.original_process(control_info, env_idx)
        if self.current is not None and env_idx == 0:
            self.current["converted_control_info"] = _plain(control_info)
            self.current["control_sequence"] = _plain(sequence)
        return sequence

    def control_robot(self, meta_control_list=None):
        if self.current is not None and meta_control_list and meta_control_list[0]:
            output = meta_control_list[0].get_action(self.env.robot_manager, env_idx=0)
            self.current["controller_output"] = _plain(output)
        result = self.original_control_robot(meta_control_list=meta_control_list)
        if self.current is not None:
            canonical, physical = self._target_buffers()
            self.current["written_target_14d"] = canonical
            self.current["written_target_physical_16d"] = physical
        return result

    def step(self, env_idx_list, decimation=1):
        self.internal_step += 1
        result = self.original_step(env_idx_list=env_idx_list, decimation=decimation)
        if self.current is None:
            return result
        actual_14d, actual_16d, ee_pose, coin_pose, coin_z_delta = self._state()
        written = self.current.get("written_target_14d")
        sequence = self.current.get("control_sequence") or []
        queue_target = sequence[self.internal_step - 1] if self.internal_step <= len(sequence) else None
        row = {
            "policy_step": self.current["policy_step"],
            "internal_step": self.internal_step,
            "act_chunk_number": (self.current["policy_step"] - 1) // 50,
            "act_chunk_index": (self.current["policy_step"] - 1) % 50,
            "act_chunk_refresh": (self.current["policy_step"] - 1) % 50 == 0,
            "act_action_14d": self.current["act_action_14d"],
            "validation_pass": self.current["validation_pass"],
            "interpolation_target_14d": self._canonical_control(queue_target),
            "controller_output_14d": self._canonical_control(self.current.get("controller_output")),
            "written_joint_targets_14d": written,
            "written_joint_targets_physical_16d": self.current.get("written_target_physical_16d"),
            "actual_joint_positions_14d": actual_14d,
            "actual_joint_positions_physical_16d": actual_16d,
            "tracking_error_14d": (np.asarray(actual_14d) - np.asarray(written)).tolist(),
            "end_effector_pose": ee_pose,
            "coin_pose": coin_pose,
            "coin_z_delta": coin_z_delta,
        }
        with self.internal_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, separators=(",", ":")) + "\n")
        return result

    def _policy_result(self):
        reward_manager = self.env.reward_manager
        reward = float(reward_manager.get_reward(final_check=False)[0])
        score = float(reward_manager.get_score()[0])
        actual_14d, actual_16d, ee_pose, coin_pose, coin_z_delta = self._state()
        return {
            "policy_step": self.current["policy_step"],
            "act_chunk_number": (self.current["policy_step"] - 1) // 50,
            "act_chunk_index": (self.current["policy_step"] - 1) % 50,
            "act_chunk_refresh": (self.current["policy_step"] - 1) % 50 == 0,
            "act_action_14d": self.current["act_action_14d"],
            "actual_joint_positions_14d": actual_14d,
            "actual_joint_positions_physical_16d": actual_16d,
            "left_arm_joints": actual_14d[0:6],
            "left_gripper": actual_14d[6],
            "right_arm_joints": actual_14d[7:13],
            "right_gripper": actual_14d[13],
            "end_effector_pose": ee_pose,
            "coin_pose": coin_pose,
            "coin_z_delta": coin_z_delta,
            "reward": reward,
            "score": score,
            "success": bool(self.env.end_flag[0] and self.env.success[0]),
            "episode_ended": bool(self.env.end_flag[0]),
            "score_completed_count": int(reward_manager.score_completed_count[0]),
            "max_internal_tracking_error": float(self.current["max_internal_tracking_error"]),
        }

    def take_action(self, action):
        policy_step = int(self.env.take_action_cnt[0]) + 1
        self.current = {
            "policy_step": policy_step,
            "act_action_14d": self._pack_action(action),
            "validation_pass": False,
            "validation_calls": 0,
            "max_internal_tracking_error": 0.0,
        }
        self.internal_step = 0
        try:
            result = self.original_take_action(action)
            policy_row = self._policy_result()
            with self.policy_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(policy_row, separators=(",", ":")) + "\n")
            return result
        finally:
            self.current = None

    def install(self):
        original_step = self.step

        def tracked_step(env_idx_list, decimation=1):
            result = original_step(env_idx_list=env_idx_list, decimation=decimation)
            if self.current is not None:
                actual_14d, _, _, _, _ = self._state()
                written = self.current.get("written_target_14d")
                if written is not None:
                    error = float(np.max(np.abs(np.asarray(actual_14d) - np.asarray(written))))
                    self.current["max_internal_tracking_error"] = max(
                        self.current["max_internal_tracking_error"], error
                    )
            return result

        self.env.reset = self.reset
        self.env.take_action = self.take_action
        self.env.validate_action_dict = self.validate_action_dict
        self.env.process_control_info = self.process_control_info
        self.env.step = tracked_step
        self.env.robot_manager.control_robot = self.control_robot
        print(f"[full-episode-trace] output={self.output_dir}", flush=True)


def install_full_episode_trace(env):
    tracer = FullEpisodeTracer(env)
    tracer.install()
    env._week02_day05_full_episode_tracer = tracer
