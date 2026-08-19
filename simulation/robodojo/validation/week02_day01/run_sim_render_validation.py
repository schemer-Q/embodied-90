#!/usr/bin/env python3
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback

ROBODOJO_ROOT = Path("/home/nvidia/RoboDojo")
sys.path.insert(0, str(ROBODOJO_ROOT))
sys.path.append(str(ROBODOJO_ROOT / "XPolicyLab"))

from isaaclab.app import AppLauncher


parser = argparse.ArgumentParser(description="Validate RoboDojo simulation and RGB rendering without a policy server.")
parser.add_argument("--output-dir", type=Path, required=True)
parser.add_argument("--steps", type=int, default=75)
parser.add_argument("--seed", type=int, default=0)
parser.add_argument("--layout", type=int, default=0)
parser.add_argument("--device-id", type=int, default=0)
AppLauncher.add_app_launcher_args(parser)
args = parser.parse_args()

app_launcher = AppLauncher(args)
simulation_app = app_launcher.app

import numpy as np
from omegaconf import OmegaConf
from PIL import Image

from env.global_configs import BENCHMARK, ENV_CONFIG_PATH, ROOT_DIR
import src.eval_client.eval_env as eval_env_module
from task.RoboDojo import task_registry
from utils.load_file import load_yaml
from utils.pipeline_utils import process_config, process_randomization


TASK_NAME = "deposit_coin"
ENV_CFG_NAME = "arx_x5"
CAMERAS = ("cam_head", "cam_left_wrist", "cam_right_wrist")
CAPTURE_STEPS = {0: "reset", args.steps // 2: "mid", args.steps: "final"}


class NullModelClient:
    """Policy-client replacement used only to satisfy EvalEnv reset/close hooks."""

    def __init__(self, **_kwargs):
        pass

    def call(self, func_name=None, obs=None, **_kwargs):
        if func_name not in {"reset", "trial_end"}:
            raise RuntimeError(f"Unexpected policy call during no-policy validation: {func_name}")
        return None

    def close(self):
        pass


def run_text(command):
    return subprocess.run(command, cwd=ROBODOJO_ROOT, check=True, text=True, capture_output=True).stdout.rstrip()


def as_numpy(value):
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    return np.asarray(value, dtype=np.float64)


def finite_list(value):
    array = as_numpy(value)
    return array.tolist(), bool(np.isfinite(array).all())


def build_config():
    eval_cfg = load_yaml(os.path.join(ENV_CONFIG_PATH, f"{ENV_CFG_NAME}.yml"))
    eval_cfg.update(
        {
            "task_name": TASK_NAME,
            "num_envs": 1,
            "device_id": args.device_id,
            "eval_batch": False,
            "policy_name": "no_policy_validation",
            "additional_info": f"seed={args.seed},layout={args.layout}",
            "seed": args.seed,
            "physx_monitor_enabled": False,
            "eval_num": 1,
        }
    )
    deploy_cfg = {
        "policy_name": "no_policy_validation",
        "port": 1,
        "host": "127.0.0.1",
        "protocol": "ws",
        "policy_server_url": "ws://127.0.0.1:1",
        "evaluation_id": "week02_day01",
        "trial_id": "week02_day01",
        "action_case_id": "deposit_coin_validation",
        "repeat_index": None,
    }
    benchmark_path = os.path.join(ROOT_DIR, "task", BENCHMARK)
    config = OmegaConf.create(
        {
            "sim": load_yaml(os.path.join(ENV_CONFIG_PATH, "sim", f"{eval_cfg['config']['sim']}.yml")),
            "scene": load_yaml(os.path.join(ENV_CONFIG_PATH, "scene", f"{eval_cfg['config']['scene']}.yml")),
            "camera": load_yaml(os.path.join(ENV_CONFIG_PATH, "camera", f"{eval_cfg['config']['camera']}.yml")),
            "robot": load_yaml(os.path.join(ENV_CONFIG_PATH, "robot", f"{eval_cfg['config']['robot']}.yml")),
            "task_env": load_yaml(task_registry.task_config_path(os.path.join(benchmark_path, "config"), TASK_NAME)),
            "eval_cfg": eval_cfg,
            "deploy_cfg": deploy_cfg,
        }
    )
    OmegaConf.update(config, "sim.scene.num_envs", 1, force_add=True)
    OmegaConf.update(config, "eval_cfg.num_envs", 1, force_add=True)
    config = process_randomization(config)
    config, _ = process_config(config, task_name=TASK_NAME)
    OmegaConf.update(
        config,
        "camera.default_frequency",
        eval_cfg["observation"].get("collect_freq", 0),
        force_add=True,
    )
    config.sim.seed = [args.seed]
    return config


def object_state(env, label):
    layout_manager = env.scene_manager.layout_manager
    instance_name = layout_manager.get_instance_name(env_idx=0, label=label)
    if instance_name is None:
        raise RuntimeError(f"Required scene label is missing: {label}")
    scene_object = layout_manager.get_scene_object(env_idx=0, inst_name=instance_name)
    if scene_object is None:
        raise RuntimeError(f"Scene object is missing: {label} ({instance_name})")
    position, orientation = layout_manager.get_instance_pose(env_idx=0, inst_name=instance_name)
    position, position_finite = finite_list(position)
    orientation, orientation_finite = finite_list(orientation)
    return {
        "instance_name": instance_name,
        "position": position,
        "orientation": orientation,
        "finite": position_finite and orientation_finite,
    }


def robot_state(env):
    result = {}
    for robot in env.robot_manager.robot_list:
        if robot.type != "target":
            continue
        qpos, qpos_finite = finite_list(env.robot_manager.get_joint(robot, env_idx_list=[0])[0])
        gripper, gripper_finite = finite_list(
            env.robot_manager.get_end_effector_real_val(robot, env_idx_list=[0])[0]
        )
        ee_pose, ee_finite = finite_list(
            env.robot_manager.get_real_endpose(robot, env_idx_list=[0], is_relative=True)[0]
        )
        result[robot.arm_name] = {
            "qpos": qpos,
            "gripper_qpos": gripper,
            "ee_pose": ee_pose,
            "finite": qpos_finite and gripper_finite and ee_finite,
        }
    if len(result) != 2:
        raise RuntimeError(f"Expected two target arms, found {list(result)}")
    return result


def hold_position_action(env):
    action = {}
    for robot in env.robot_manager.robot_list:
        if robot.type != "target":
            continue
        arm_key = env.robot_manager.process_name(robot.arm_name)
        gripper_key = env.robot_manager.process_name(robot.gripper_name)
        action[arm_key] = env.robot_manager.get_joint(robot, env_idx_list=[0])[0].astype(float).tolist()
        physical = float(env.robot_manager.get_end_effector_real_val(robot, env_idx_list=[0])[0][0])
        lower, upper = map(float, robot.gripper_scale)
        fraction = (physical - lower) / (upper - lower)
        normalized = fraction if robot.gripper_move["sign"] == 1 else 1.0 - fraction
        action[gripper_key] = [float(np.clip(normalized, 0.0, 1.0))]
    return action


def simulation_state(env):
    backend = env.sim.unwrapped
    current_time = getattr(backend.sim, "current_time", None)
    return {
        "physics_step_counter": int(backend._sim_step_counter),
        "common_step_counter": int(backend.common_step_counter),
        "simulation_time_s": None if current_time is None else float(current_time),
    }


def frame_stats(array):
    array = np.asarray(array)
    return {
        "shape": list(array.shape),
        "dtype": str(array.dtype),
        "min": int(array.min()),
        "max": int(array.max()),
        "mean": float(array.mean()),
        "std": float(array.std()),
        "all_black": bool(array.max() == 0),
        "near_constant": bool(array.std() < 1.0 or int(array.max()) - int(array.min()) < 5),
        "finite": bool(np.isfinite(array).all()),
    }


def capture_observation(env, output_dir, label):
    observation = env.get_obs()
    actual_cameras = set(observation["vision"])
    missing = set(CAMERAS) - actual_cameras
    if missing:
        raise RuntimeError(f"Missing camera observations: {sorted(missing)}; got {sorted(actual_cameras)}")
    stats = {}
    frames = {}
    for camera in CAMERAS:
        frame = np.asarray(observation["vision"][camera]["color"]).copy()
        if frame.ndim != 3 or frame.shape[2] != 3:
            raise RuntimeError(f"Unexpected RGB shape for {camera}: {frame.shape}")
        if frame.dtype != np.uint8:
            raise RuntimeError(f"Unexpected RGB dtype for {camera}: {frame.dtype}")
        stats[camera] = frame_stats(frame)
        frames[camera] = frame
        Image.fromarray(frame).save(output_dir / f"{camera}_{label}.jpg", quality=95)
    return stats, frames


def summarize_drift(samples, key_path):
    arrays = []
    for sample in samples:
        value = sample
        for key in key_path:
            value = value[key]
        arrays.append(np.asarray(value, dtype=np.float64))
    initial = arrays[0]
    drift = [float(np.linalg.norm(value - initial)) for value in arrays]
    return {"initial": initial.tolist(), "final": arrays[-1].tolist(), "max_norm": max(drift), "final_norm": drift[-1]}


def main():
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    os.environ["ROBODOJO_SAVE_VIDEO"] = "0"
    os.environ["ROBODOJO_RUN_ID"] = "week02_day01"
    report = {
        "started_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "config": {
            "task": TASK_NAME,
            "env_cfg": ENV_CFG_NAME,
            "num_envs": 1,
            "seed": args.seed,
            "layout": args.layout,
            "policy_steps": args.steps,
            "action": "current joint position target refreshed each policy step",
            "policy_server": False,
            "task_reward_and_episode_end_hooks": "disabled after reset",
        },
        "robodojo": {
            "commit": run_text(["git", "rev-parse", "HEAD"]),
            "status_short": run_text(["git", "status", "--short"]).splitlines(),
        },
        "captures": {},
        "state_samples": [],
        "error": None,
    }
    env = None
    try:
        eval_env_module.WsModelClient = NullModelClient
        env = eval_env_module.create_eval_env(build_config(), simulation_app)
        if args.layout not in env.seed_manager.seed_list:
            raise RuntimeError(f"Layout {args.layout} is unavailable; valid IDs: {env.seed_manager.seed_list}")
        env.reset(seed=[args.layout])
        env.reward_manager.step = lambda env_idx_list=None: None
        env.is_episode_end = lambda: False

        reset_stats, reset_frames = capture_observation(env, output_dir, "reset")
        report["captures"]["reset"] = reset_stats
        report["state_samples"].append(
            {
                "policy_step": 0,
                "simulation": simulation_state(env),
                "objects": {label: object_state(env, label) for label in ("coin0", "piggy_bank", "vertical_coin_stand")},
                "robots": robot_state(env),
            }
        )

        capture_frames = {"reset": reset_frames}
        for policy_step in range(1, args.steps + 1):
            env.take_action(hold_position_action(env))
            sample = {
                "policy_step": policy_step,
                "simulation": simulation_state(env),
                "objects": {label: object_state(env, label) for label in ("coin0", "piggy_bank", "vertical_coin_stand")},
                "robots": robot_state(env),
            }
            report["state_samples"].append(sample)
            capture_label = CAPTURE_STEPS.get(policy_step)
            if capture_label:
                stats, frames = capture_observation(env, output_dir, capture_label)
                report["captures"][capture_label] = stats
                capture_frames[capture_label] = frames

        report["drift"] = {
            "coin_translation_m": summarize_drift(report["state_samples"], ("objects", "coin0", "position")),
            "coin_orientation_quaternion": summarize_drift(
                report["state_samples"], ("objects", "coin0", "orientation")
            ),
            "left_arm_qpos": summarize_drift(report["state_samples"], ("robots", "left_arm", "qpos")),
            "right_arm_qpos": summarize_drift(report["state_samples"], ("robots", "right_arm", "qpos")),
        }
        report["temporal_frame_difference"] = {}
        for camera in CAMERAS:
            reset_frame = capture_frames["reset"][camera].astype(np.float32)
            final_frame = capture_frames["final"][camera].astype(np.float32)
            report["temporal_frame_difference"][camera] = {
                "reset_to_final_mean_abs": float(np.abs(final_frame - reset_frame).mean()),
                "reset_to_final_max_abs": float(np.abs(final_frame - reset_frame).max()),
            }

        samples_finite = all(
            all(obj["finite"] for obj in sample["objects"].values())
            and all(robot["finite"] for robot in sample["robots"].values())
            for sample in report["state_samples"]
        )
        images_valid = all(
            stat["finite"] and not stat["all_black"] and not stat["near_constant"]
            for capture in report["captures"].values()
            for stat in capture.values()
        )
        initial_sim = report["state_samples"][0]["simulation"]
        final_sim = report["state_samples"][-1]["simulation"]
        expected_physics_steps = args.steps * int(env.obs_manager.collect_interval)
        physics_step_delta = final_sim["physics_step_counter"] - initial_sim["physics_step_counter"]
        common_step_delta = final_sim["common_step_counter"] - initial_sim["common_step_counter"]
        report["checks"] = {
            "environment_created": True,
            "scene_reset": True,
            "required_objects_present": True,
            "all_recorded_states_finite": samples_finite,
            "physics_step_delta_matches_expected": physics_step_delta == expected_physics_steps,
            "common_step_delta_matches_expected": common_step_delta == expected_physics_steps,
            "completed_policy_steps": int(env.take_action_cnt[0]) == args.steps,
            "all_rgb_frames_valid": images_valid,
            "coin_translation_below_5mm": report["drift"]["coin_translation_m"]["max_norm"] < 0.005,
            "left_arm_qpos_drift_below_1e-6": report["drift"]["left_arm_qpos"]["max_norm"] < 1e-6,
            "right_arm_qpos_drift_below_1e-6": report["drift"]["right_arm_qpos"]["max_norm"] < 1e-6,
        }
        report["completed_at"] = datetime.now(timezone.utc).astimezone().isoformat()
    except Exception as exc:
        report["error"] = {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}
        raise
    finally:
        with (output_dir / "observation_stats.json").open("w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        if env is not None:
            env.close()
        simulation_app.close()


if __name__ == "__main__":
    main()
