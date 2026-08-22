"""Runtime trace from ACT's returned action to post-PhysX joint state."""

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess

import numpy as np


ACTION_KEYS = (
    "left_arm_joint_state",
    "left_ee_joint_state",
    "right_arm_joint_state",
    "right_ee_joint_state",
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


def _git(command):
    try:
        return subprocess.check_output(
            command,
            cwd="/home/nvidia/RoboDojo",
            text=True,
            stderr=subprocess.STDOUT,
        ).strip()
    except Exception as exc:
        return f"unavailable: {exc}"


class ActionTracer:
    def __init__(self, env):
        self.env = env
        self.output_dir = Path(os.environ["ROBODOJO_ACTION_TRACE_DIR"])
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.jsonl_path = self.output_dir / "action_trace.jsonl"
        self.metadata_path = self.output_dir / "action_trace_metadata.json"
        self.start_step = int(os.environ.get("ROBODOJO_ACTION_TRACE_START", "20"))
        self.end_step = int(os.environ.get("ROBODOJO_ACTION_TRACE_END", "60"))
        self.current = None
        self.internal_step = 0
        self.original_take_action = env.take_action
        self.original_reset = env.reset
        self.original_validate = env.validate_action_dict
        self.original_process = env.process_control_info
        self.original_step = env.step
        self.original_control_robot = env.robot_manager.control_robot
        self.jsonl_path.write_text("", encoding="utf-8")
        self.robots = {}

    def _target_robots(self):
        result = {}
        for index, robot in enumerate(self.env.robot_manager.robot_list):
            if robot.type != "target":
                continue
            if robot.arm_name.startswith("left_"):
                side = "left"
            elif robot.arm_name.startswith("right_"):
                side = "right"
            else:
                continue
            result[side] = (robot, self.env.robot_manager.robot_key[index])
        if set(result) != {"left", "right"}:
            raise RuntimeError(f"Expected left/right target robots, got {sorted(result)}")
        return result

    def _robot_metadata(self, side):
        robot, articulation = self.robots[side]
        soft_limits = articulation.data.soft_joint_pos_limits[0]
        return {
            "side": side,
            "arm_name": robot.arm_name,
            "gripper_name": robot.gripper_name,
            "joint_names": list(articulation.joint_names),
            "arm_joint_indices": _plain(robot.arm_joint_indices),
            "gripper_joint_indices": _plain(robot.gripper_joint_indices),
            "configured_gripper_scale_m": _plain(robot.gripper_scale),
            "gripper_sign": float(robot.gripper_move["sign"]),
            "gripper_mimic": _plain(robot.gripper_move["mimic"]),
            "runtime_soft_joint_limits": _plain(soft_limits),
        }

    def _write_metadata(self):
        payload = {
            "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
            "robodojo_commit": _git(["git", "rev-parse", "HEAD"]),
            "robodojo_status_short": _git(["git", "status", "--short"]).splitlines(),
            "task": self.env.task_name,
            "config_name": self.env.config_name,
            "policy": self.env.policy_name,
            "seed": int(self.env.eval_seed),
            "trace_policy_steps_inclusive": [self.start_step, self.end_step],
            "collect_interval": int(self.env.obs_manager.collect_interval),
            "action_order": list(ACTION_KEYS),
            "raw_action_definition": (
                "The 14-D vector returned by the ACT server after post_process "
                "denormalization, losslessly repacked from the four action keys."
            ),
            "act_temporal_agg": False,
            "act_query_frequency": 50,
            "act_chunk_consumption": "one indexed action per observation; chunk refresh at policy steps 1 and 51",
            "gripper_eps": float(os.environ.get("GRIPPER_EPS", "0.2")),
            "robots": [self._robot_metadata(side) for side in ("left", "right")],
            "source_functions": {
                "policy_denormalization": "XPolicyLab/policy/ACT/detr/act_policy.py::ACT.get_action",
                "action_unpack": "XPolicyLab/utils/process_data.py::unpack_robot_state",
                "validation": "src/eval_client/eval_env.py::EvalEnv.validate_action_dict",
                "gripper_conversion": "src/eval_client/eval_env.py::EvalEnv.take_action_batch",
                "interpolation": "src/eval_client/eval_env.py::EvalEnv.process_control_info",
                "queue_and_slew_limit": "env/robot_manager/control_manager.py::ControlManager/MetaControl.get_action",
                "joint_target_write": "env/robot_manager/robot_manager.py::RobotManager.control_robot",
                "physx_step": "src/eval_client/eval_env.py::EvalEnv.step",
            },
        }
        self.metadata_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @staticmethod
    def _pack_action(action):
        return np.concatenate([np.asarray(action[key], dtype=float) for key in ACTION_KEYS]).tolist()

    def _canonical_from_control(self, control):
        if not control:
            return None
        values = []
        manager = self.env.robot_manager
        for side in ("left", "right"):
            robot, _ = self.robots[side]
            arm_key = manager.process_name(robot.arm_name)
            gripper_key = manager.process_name(robot.gripper_name)
            if arm_key not in control or gripper_key not in control:
                return None
            values.extend(_plain(control[arm_key]["position"]))
            values.append(float(_plain(control[gripper_key]["position"])[0]))
        return values

    def _physical_from_control(self, control):
        if not control:
            return None
        values = []
        manager = self.env.robot_manager
        for side in ("left", "right"):
            robot, _ = self.robots[side]
            arm_key = manager.process_name(robot.arm_name)
            gripper_key = manager.process_name(robot.gripper_name)
            values.extend(_plain(control[arm_key]["position"]))
            values.extend(_plain(control[gripper_key]["position"]))
        return values

    def _joint_state(self):
        canonical = []
        physical = []
        end_effector_z = {}
        manager = self.env.robot_manager
        for side in ("left", "right"):
            robot, articulation = self.robots[side]
            qpos = _plain(articulation.data.joint_pos[0])
            arm = [qpos[index] for index in robot.arm_joint_indices]
            gripper = [qpos[index] for index in robot.gripper_joint_indices]
            canonical.extend(arm + [gripper[0]])
            physical.extend(arm + gripper)
            pose = manager.get_real_endpose(robot, env_idx_list=[0], is_relative=True)[0]
            end_effector_z[side] = float(pose[2])
        return canonical, physical, end_effector_z

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

    def _coin_z(self):
        try:
            manager = self.env.scene_manager.layout_manager
            instance = manager.get_instance_name(0, "coin0")
            position, _ = manager.get_instance_pose(env_idx=0, inst_name=instance)
            return float(position[2])
        except Exception:
            return None

    def validate_action_dict(self, action):
        try:
            result = self.original_validate(action)
        except Exception as exc:
            if self.current is not None:
                self.current["validation_error"] = f"{type(exc).__name__}: {exc}"
            raise
        if self.current is not None:
            self.current["validation_calls"] += 1
            self.current["validation_pass"] = True
        return result

    def reset(self, seed=None, options=None):
        result = self.original_reset(seed=seed, options=options)
        self.robots = self._target_robots()
        self._write_metadata()
        return result

    def process_control_info(self, control_info, env_idx):
        sequence = self.original_process(control_info, env_idx)
        if self.current is not None and env_idx == 0:
            self.current["converted_control_info"] = _plain(control_info)
            self.current["control_sequence"] = _plain(sequence)
        return sequence

    def control_robot(self, meta_control_list=None):
        if self.current is not None and meta_control_list and meta_control_list[0]:
            controller_output = meta_control_list[0].get_action(self.env.robot_manager, env_idx=0)
            self.current["controller_output"] = _plain(controller_output)
        result = self.original_control_robot(meta_control_list=meta_control_list)
        if self.current is not None:
            canonical, physical = self._target_buffers()
            self.current["joint_target_buffer_14d"] = canonical
            self.current["joint_target_buffer_physical_16d"] = physical
        return result

    def step(self, env_idx_list, decimation=1):
        self.internal_step += 1
        result = self.original_step(env_idx_list=env_idx_list, decimation=decimation)
        if self.current is None:
            return result
        policy_step = self.current["policy_step"]
        if not self.start_step <= policy_step <= self.end_step:
            return result

        actual_14d, actual_16d, end_effector_z = self._joint_state()
        written_14d = self.current.get("joint_target_buffer_14d")
        tracking_error = None
        if written_14d is not None:
            tracking_error = (np.asarray(actual_14d) - np.asarray(written_14d)).tolist()
        sequence = self.current.get("control_sequence") or []
        queue_target = sequence[self.internal_step - 1] if self.internal_step <= len(sequence) else None
        row = {
            "policy_step": policy_step,
            "internal_step": self.internal_step,
            "act_chunk_number": (policy_step - 1) // 50,
            "act_chunk_index": (policy_step - 1) % 50,
            "act_chunk_refresh": (policy_step - 1) % 50 == 0,
            "denormalized_action_14d": self.current["denormalized_action_14d"],
            "unpacked_action": self.current["unpacked_action"],
            "validation_pass": self.current["validation_pass"],
            "validation_calls": self.current["validation_calls"],
            "left_gripper_normalized": self.current["unpacked_action"]["left_ee_joint_state"][0],
            "right_gripper_normalized": self.current["unpacked_action"]["right_ee_joint_state"][0],
            "converted_control_info": self.current.get("converted_control_info"),
            "interpolation_target": queue_target,
            "interpolation_target_14d": self._canonical_from_control(queue_target),
            "controller_output": self.current.get("controller_output"),
            "controller_output_14d": self._canonical_from_control(self.current.get("controller_output")),
            "written_joint_targets": written_14d,
            "written_joint_targets_physical_16d": self.current.get("joint_target_buffer_physical_16d"),
            "actual_joint_positions": actual_14d,
            "actual_joint_positions_physical_16d": actual_16d,
            "tracking_error": tracking_error,
            "end_effector_z": end_effector_z,
            "coin_z": self._coin_z(),
        }
        with self.jsonl_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, separators=(",", ":")) + "\n")
        return result

    def take_action(self, action):
        policy_step = int(self.env.take_action_cnt[0]) + 1
        plain_action = {key: _plain(value) for key, value in action.items()}
        self.current = {
            "policy_step": policy_step,
            "unpacked_action": plain_action,
            "denormalized_action_14d": self._pack_action(action),
            "validation_pass": False,
            "validation_calls": 0,
        }
        self.internal_step = 0
        try:
            return self.original_take_action(action)
        finally:
            self.current = None

    def install(self):
        self.env.reset = self.reset
        self.env.take_action = self.take_action
        self.env.validate_action_dict = self.validate_action_dict
        self.env.process_control_info = self.process_control_info
        self.env.step = self.step
        self.env.robot_manager.control_robot = self.control_robot
        print(
            f"[action-trace] recording policy steps {self.start_step}-{self.end_step} "
            f"to {self.jsonl_path}",
            flush=True,
        )


def install_action_trace(env):
    tracer = ActionTracer(env)
    tracer.install()
    env._week02_day04_action_tracer = tracer
