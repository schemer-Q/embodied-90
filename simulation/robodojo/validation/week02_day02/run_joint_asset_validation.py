#!/usr/bin/env python3
import argparse
import csv
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import traceback

ROBODOJO_ROOT = Path("/home/nvidia/RoboDojo")
sys.path.insert(0, str(ROBODOJO_ROOT))
sys.path.append(str(ROBODOJO_ROOT / "XPolicyLab"))

from isaaclab.app import AppLauncher


parser = argparse.ArgumentParser(description="Validate dual-X5 joints and deposit-coin assets without ACT.")
parser.add_argument("--day2-dir", type=Path, required=True)
parser.add_argument("--day3-dir", type=Path, required=True)
parser.add_argument("--seed", type=int, default=0)
parser.add_argument("--layout", type=int, default=0)
parser.add_argument("--device-id", type=int, default=0)
AppLauncher.add_app_launcher_args(parser)
args = parser.parse_args()

app_launcher = AppLauncher(args)
simulation_app = app_launcher.app

import numpy as np
from omegaconf import OmegaConf
from PIL import Image, ImageDraw
from pxr import Usd, UsdGeom, UsdPhysics

from env.global_configs import BENCHMARK, ENV_CONFIG_PATH, ROOT_DIR
import src.eval_client.eval_env as eval_env_module
from task.RoboDojo import task_registry
from utils.load_file import load_yaml
from utils.pipeline_utils import process_config, process_randomization


TASK_NAME = "deposit_coin"
ENV_CFG_NAME = "arx_x5"
OBJECT_LABELS = ("coin0", "piggy_bank", "vertical_coin_stand")


class NullModelClient:
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


def array(value):
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    return np.asarray(value, dtype=np.float64)


def values(value):
    return array(value).reshape(-1).tolist()


def jsonable(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "detach") or isinstance(value, np.ndarray):
        return array(value).tolist()
    if OmegaConf.is_config(value):
        return OmegaConf.to_container(value, resolve=True)
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return str(value)


def write_json(path, data):
    with path.open("w", encoding="utf-8") as handle:
        json.dump(jsonable(data), handle, ensure_ascii=False, indent=2)
        handle.write("\n")


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
        "evaluation_id": "week02_day02_day03",
        "trial_id": "week02_day02_day03",
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
    OmegaConf.update(config, "camera.default_frequency", eval_cfg["observation"].get("collect_freq", 0), force_add=True)
    config.sim.seed = [args.seed]
    return config


def target_robots(env):
    return [robot for robot in env.robot_manager.robot_list if robot.type == "target"]


def hold_action(env):
    action = {}
    for robot in target_robots(env):
        arm_key = env.robot_manager.process_name(robot.arm_name)
        gripper_key = env.robot_manager.process_name(robot.gripper_name)
        action[arm_key] = values(env.robot_manager.get_joint(robot, env_idx_list=[0])[0])
        physical = float(array(env.robot_manager.get_end_effector_real_val(robot, env_idx_list=[0])[0])[0])
        lower, upper = map(float, robot.gripper_scale)
        normalized = (physical - lower) / (upper - lower)
        if robot.gripper_move["sign"] != 1:
            normalized = 1.0 - normalized
        action[gripper_key] = [float(np.clip(normalized, 0.0, 1.0))]
    return action


def robot_runtime_state(env):
    result = {}
    for robot in target_robots(env):
        result[robot.arm_name] = {
            "arm_qpos": values(env.robot_manager.get_joint(robot, env_idx_list=[0])[0]),
            "gripper_qpos": values(env.robot_manager.get_end_effector_real_val(robot, env_idx_list=[0])[0]),
            "ee_pose_relative": values(env.robot_manager.get_real_endpose(robot, env_idx_list=[0], is_relative=True)[0]),
            "link7_pose_relative": values(env.robot_manager.get_link_pose(robot, "link7", [0], True)[0]),
            "link8_pose_relative": values(env.robot_manager.get_link_pose(robot, "link8", [0], True)[0]),
        }
    return result


def prim_joint_types(stage, root_path):
    result = {}
    root = stage.GetPrimAtPath(root_path)
    if not root.IsValid():
        return result
    for prim in Usd.PrimRange(root):
        if prim.IsA(UsdPhysics.RevoluteJoint):
            result[prim.GetName()] = "revolute"
        elif prim.IsA(UsdPhysics.PrismaticJoint):
            result[prim.GetName()] = "prismatic"
        elif prim.IsA(UsdPhysics.FixedJoint):
            result[prim.GetName()] = "fixed"
    return result


def robot_snapshot(env):
    stage = env.scene_manager.layout_manager.scene_manager.stage
    robots = []
    mapping = []
    action_offset = 0
    for robot_index, robot in enumerate(target_robots(env)):
        articulation = env.robot_manager.robot_key[env.robot_manager.robot_list.index(robot)]
        runtime_paths = list(getattr(articulation.root_physx_view, "prim_paths", []))
        root_path = runtime_paths[0] if runtime_paths else str(articulation.cfg.prim_path)
        types = prim_joint_types(stage, root_path)
        limits = array(articulation.data.soft_joint_pos_limits[0])
        defaults = array(articulation.data.default_joint_pos[0])
        actual = array(articulation.data.joint_pos[0])
        joints = []
        for local_index, (joint_index, joint_name) in enumerate(zip(robot.arm_joint_indices, robot.arm_joints_name)):
            index = int(joint_index)
            joints.append(
                {
                    "name": joint_name,
                    "articulation_index": index,
                    "type": types.get(joint_name, "not resolved from USD traversal"),
                    "position_limit": limits[index].tolist(),
                    "default_position": float(defaults[index]),
                    "reset_position": float(actual[index]),
                    "finite": bool(np.isfinite(actual[index])),
                    "within_limit": bool(limits[index, 0] <= actual[index] <= limits[index, 1]),
                    "action_dimension": action_offset + local_index,
                }
            )
            mapping.append(
                {
                    "action_dimension": action_offset + local_index,
                    "side": "left" if robot_index == 0 else "right",
                    "semantic": f"{robot.arm_name} {joint_name}",
                    "command_key": env.robot_manager.process_name(robot.arm_name),
                    "command_element": local_index,
                    "articulation_joint": joint_name,
                    "articulation_index": index,
                    "mimic": "",
                }
            )
        gripper_dim = action_offset + len(robot.arm_joint_indices)
        base_name = robot.gripper_move["base"]
        mimic_name, mimic_scale, mimic_offset = robot.gripper_move["mimic"]
        for joint_index, joint_name in zip(robot.gripper_joint_indices, robot.gripper_joints_name):
            index = int(joint_index)
            joints.append(
                {
                    "name": joint_name,
                    "articulation_index": index,
                    "type": types.get(joint_name, "not resolved from USD traversal"),
                    "position_limit": limits[index].tolist(),
                    "default_position": float(defaults[index]),
                    "reset_position": float(actual[index]),
                    "finite": bool(np.isfinite(actual[index])),
                    "within_limit": bool(limits[index, 0] <= actual[index] <= limits[index, 1]),
                    "action_dimension": gripper_dim,
                }
            )
        mapping.append(
            {
                "action_dimension": gripper_dim,
                "side": "left" if robot_index == 0 else "right",
                "semantic": f"{robot.gripper_name} normalized opening",
                "command_key": env.robot_manager.process_name(robot.gripper_name),
                "command_element": 0,
                "articulation_joint": base_name,
                "articulation_index": int(robot.gripper_joint_indices[0]),
                "mimic": f"{mimic_name}={mimic_scale}*{base_name}+{mimic_offset}",
            }
        )
        robots.append(
            {
                "side": "left" if robot_index == 0 else "right",
                "arm_name": robot.arm_name,
                "articulation_cfg_prim_path": str(articulation.cfg.prim_path),
                "articulation_runtime_prim_paths": runtime_paths,
                "joint_names_runtime": list(articulation.joint_names),
                "arm_joint_indices": [int(item) for item in robot.arm_joint_indices],
                "gripper_joint_indices": [int(item) for item in robot.gripper_joint_indices],
                "gripper_scale_m": list(map(float, robot.gripper_scale)),
                "gripper_move": jsonable(robot.gripper_move),
                "joints": joints,
            }
        )
        action_offset += len(robot.arm_joint_indices) + 1
    return robots, mapping


def write_mapping(path, rows):
    fields = ["action_dimension", "side", "semantic", "command_key", "command_element", "articulation_joint", "articulation_index", "mimic"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def capture_head(env, path):
    frame = np.asarray(env.get_obs()["vision"]["cam_head"]["color"]).copy()
    Image.fromarray(frame).save(path, quality=95)
    return frame


def object_info(env, label):
    manager = env.scene_manager.layout_manager
    instance_name = manager.get_instance_name(0, label)
    obj = manager.get_scene_object(0, instance_name)
    local_pos, local_quat = manager.get_instance_pose(0, inst_name=instance_name, relative=True)
    queried_world_pos, queried_world_quat = manager.get_instance_pose(0, inst_name=instance_name, relative=False)
    env_origin = array(manager.scene_manager.env_origins[0]).reshape(3)
    local_pos_np = array(local_pos).reshape(3)
    metadata = manager.get_instance_metadata(0, inst_name=instance_name)
    bbox_vertices = manager.get_instance_bbox_vertices(instance_name, 0)
    prim_path = getattr(obj, "usd_prim_path", getattr(obj, "_prim_path", None))
    material = getattr(obj, "physics_material", None)
    runtime_material = None
    if material is not None:
        runtime_material = {
            "prim_path": str(getattr(material, "prim_path", "not exposed")),
            "static_friction": float(material.get_static_friction()),
            "dynamic_friction": float(material.get_dynamic_friction()),
            "restitution": float(material.get_restitution()),
        }
    return {
        "label": label,
        "instance_name": instance_name,
        "instance_type": manager.instance_type_by_env[0].get(instance_name),
        "prim_path": prim_path,
        "usd_path": getattr(obj, "usd_path", None),
        "local_pose": {"position": values(local_pos), "quaternion_wxyz": values(local_quat)},
        "world_pose_queried": {"position": values(queried_world_pos), "quaternion_wxyz": values(queried_world_quat)},
        "world_pose_from_local_plus_env_origin": {
            "position": (local_pos_np + env_origin).tolist(),
            "quaternion_wxyz": values(local_quat),
        },
        "scale": values(getattr(obj, "scale", [1, 1, 1])),
        "bbox_local_vertices": None if bbox_vertices is None else array(bbox_vertices).reshape(-1, 3).tolist(),
        "bbox_local_min": None if bbox_vertices is None else array(bbox_vertices).reshape(-1, 3).min(axis=0).tolist(),
        "bbox_local_max": None if bbox_vertices is None else array(bbox_vertices).reshape(-1, 3).max(axis=0).tolist(),
        "metadata_physics": jsonable((metadata or {}).get("physics")),
        "runtime_object_physics_config": jsonable(getattr(obj, "physics_config", None)),
        "runtime_mass_attribute": getattr(obj, "mass", None),
        "runtime_physics_material": runtime_material,
        "track_contact_forces_config": jsonable(getattr(obj, "physics_config", {}).get("track_contact_forces", False)),
    }


def usd_physics_summary(stage, root_path):
    root = stage.GetPrimAtPath(root_path)
    summary = {"root_valid": bool(root.IsValid()), "rigid_body_prims": [], "collision_prims": [], "mass_prims": []}
    if not root.IsValid():
        return summary
    for prim in Usd.PrimRange(root):
        path = prim.GetPath().pathString
        if prim.HasAPI(UsdPhysics.RigidBodyAPI):
            api = UsdPhysics.RigidBodyAPI(prim)
            summary["rigid_body_prims"].append({"path": path, "enabled": api.GetRigidBodyEnabledAttr().Get()})
        if prim.HasAPI(UsdPhysics.CollisionAPI):
            api = UsdPhysics.CollisionAPI(prim)
            mesh_api = UsdPhysics.MeshCollisionAPI(prim)
            approximation = mesh_api.GetApproximationAttr().Get() if mesh_api else None
            summary["collision_prims"].append(
                {"path": path, "type": prim.GetTypeName(), "enabled": api.GetCollisionEnabledAttr().Get(), "approximation": approximation}
            )
        if prim.HasAPI(UsdPhysics.MassAPI):
            api = UsdPhysics.MassAPI(prim)
            summary["mass_prims"].append(
                {"path": path, "mass": api.GetMassAttr().Get(), "density": api.GetDensityAttr().Get()}
            )
    return summary


def pose(env, label):
    manager = env.scene_manager.layout_manager
    instance_name = manager.get_instance_name(0, label)
    position, quaternion = manager.get_instance_pose(0, inst_name=instance_name)
    return {"position": values(position), "quaternion_wxyz": values(quaternion)}


def passive_settle(env, day3_dir):
    samples = [{"internal_step": 0, "coin": pose(env, "coin0")}]
    for step in range(1, 101):
        env.sim_step(render=False)
        if step % 10 == 0:
            samples.append({"internal_step": step, "coin": pose(env, "coin0")})
    positions = np.asarray([sample["coin"]["position"] for sample in samples])
    finite = bool(np.isfinite(positions).all())
    displacement = np.linalg.norm(positions - positions[0], axis=1)
    result = {
        "samples": samples,
        "finite": finite,
        "max_translation_from_initial_m": float(displacement.max()),
        "final_translation_from_initial_m": float(displacement[-1]),
        "z_min_m": float(positions[:, 2].min()),
        "z_max_m": float(positions[:, 2].max()),
        "stable_below_5mm": finite and float(displacement.max()) < 0.005,
    }
    with (day3_dir / "passive_settle.log").open("w", encoding="utf-8") as handle:
        handle.write("Passive settle: 100 internal PhysX/control steps, no object command\n")
        for sample in samples:
            handle.write(f"step={sample['internal_step']:03d} coin_pos_m={sample['coin']['position']}\n")
        handle.write(json.dumps({key: value for key, value in result.items() if key != "samples"}, indent=2) + "\n")
    return result


def joint_vector(state):
    return np.concatenate(
        [
            np.asarray(state["left_arm"]["arm_qpos"]),
            np.asarray(state["left_arm"]["gripper_qpos"]),
            np.asarray(state["right_arm"]["arm_qpos"]),
            np.asarray(state["right_arm"]["gripper_qpos"]),
        ]
    )


def run_joint_probes(env, day2_dir):
    frames_dir = day2_dir / "joint_probe_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    baseline_action = hold_action(env)
    probes = [
        ("left_joint1", "left_arm_joint_state", 0, 0.05, 0, [0]),
        ("left_joint6", "left_arm_joint_state", 5, 0.05, 5, [5]),
        ("left_gripper", "left_ee_joint_state", 0, -0.10, 6, [6, 7]),
        ("right_joint1", "right_arm_joint_state", 0, 0.05, 8, [8]),
        ("right_joint6", "right_arm_joint_state", 5, 0.05, 13, [13]),
        ("right_gripper", "right_ee_joint_state", 0, -0.10, 14, [14, 15]),
    ]
    results = []
    for name, key, element, offset, flattened_index, allowed_indices in probes:
        before = robot_runtime_state(env)
        capture_head(env, frames_dir / f"{name}_before.jpg")
        action = {action_key: list(action_value) for action_key, action_value in baseline_action.items()}
        action[key][element] += offset
        action[key][element] = float(np.clip(action[key][element], 0.0, 1.0)) if "ee_" in key else action[key][element]
        env.take_action(action)
        after = robot_runtime_state(env)
        capture_head(env, frames_dir / f"{name}_after.jpg")
        delta = joint_vector(after) - joint_vector(before)
        expected_delta = float(delta[flattened_index])
        other_delta = np.delete(delta, allowed_indices)
        gripper = "gripper" in name
        passed = abs(expected_delta) > (0.001 if gripper else 0.01) and math.copysign(1, expected_delta) == math.copysign(1, offset)
        results.append(
            {
                "probe": name,
                "command_key": key,
                "command_element": element,
                "command_offset": offset,
                "before": before,
                "after": after,
                "actual_expected_joint_delta": expected_delta,
                "allowed_coupled_joint_deltas": delta[allowed_indices].tolist(),
                "max_abs_other_joint_delta": float(np.max(np.abs(other_delta))),
                "direction_response_and_isolation_pass": passed and float(np.max(np.abs(other_delta))) < 0.001,
            }
        )
        for _ in range(3):
            env.take_action(baseline_action)
    with (day2_dir / "joint_probe.log").open("w", encoding="utf-8") as handle:
        handle.write("Each probe starts from the restored reset target; one policy action equals 10 internal steps.\n")
        for result in results:
            handle.write(
                f"{result['probe']}: command_offset={result['command_offset']:+.4f}, "
                f"actual_delta={result['actual_expected_joint_delta']:+.6f}, "
                f"max_other_delta={result['max_abs_other_joint_delta']:.6f}, "
                f"pass={result['direction_response_and_isolation_pass']}\n"
            )
    return results


def controlled_approach(env, day3_dir):
    robots = target_robots(env)
    left, right = robots[0], robots[1]
    start_left = array(env.robot_manager.get_real_endpose(left, [0], True)[0])
    right_pose = values(env.robot_manager.get_real_endpose(right, [0], True)[0])
    coin_initial = np.asarray(pose(env, "coin0")["position"])
    target_position = coin_initial + np.array([0.0, -0.10, 0.10])
    samples = []
    capture_head(env, day3_dir / "collision_probe_start.jpg")
    for waypoint in range(1, 7):
        ratio = waypoint / 6.0
        target_pose = start_left.copy()
        target_pose[:3] = (1.0 - ratio) * start_left[:3] + ratio * target_position
        left_ik = env.robot_manager.solve_ik(target_pose.tolist(), 0, left, trans="world")
        sample = {"waypoint": waypoint, "ratio": ratio, "target_left_ee_pose": target_pose.tolist(), "ik_status": left_ik.get("status")}
        if left_ik.get("status") != "Success":
            sample["executed"] = False
            samples.append(sample)
            break
        action = hold_action(env)
        action[env.robot_manager.process_name(left.arm_name)] = values(left_ik["joint_value"])
        action[env.robot_manager.process_name(right.arm_name)] = action[env.robot_manager.process_name(right.arm_name)]
        env.take_action(action)
        state = robot_runtime_state(env)
        coin_now = np.asarray(pose(env, "coin0")["position"])
        finger_positions = [np.asarray(state["left_arm"][key][:3]) for key in ("link7_pose_relative", "link8_pose_relative")]
        sample.update(
            {
                "executed": True,
                "actual_left_ee_pose": state["left_arm"]["ee_pose_relative"],
                "coin_position": coin_now.tolist(),
                "coin_displacement_m": float(np.linalg.norm(coin_now - coin_initial)),
                "finger_origin_distance_to_coin_m": [float(np.linalg.norm(item - coin_now)) for item in finger_positions],
            }
        )
        samples.append(sample)
    capture_head(env, day3_dir / "collision_probe_final.jpg")
    result = {
        "method": "six IK-derived joint-target waypoints; left link6 moves toward a pre-contact pose 0.10 m behind and 0.10 m above coin",
        "contact_sensor_enabled": False,
        "contact_claim": "not directly verified; runtime collision APIs and visual proximity are reported separately",
        "samples": samples,
        "completed_waypoints": sum(bool(sample.get("executed")) for sample in samples),
        "coin_max_displacement_m": max((sample.get("coin_displacement_m", 0.0) for sample in samples), default=0.0),
        "visual_review_required": True,
    }
    with (day3_dir / "collision_probe.log").open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(result, indent=2) + "\n")
    return result


def annotate_scene(source_path, output_path, asset_snapshot, coordinate_snapshot):
    image = Image.open(source_path).convert("RGB")
    draw = ImageDraw.Draw(image)
    coin = asset_snapshot["objects"]["coin0"]["local_pose"]["position"]
    bank = asset_snapshot["objects"]["piggy_bank"]["local_pose"]["position"]
    lines = [
        "Coin-X5 fixed layout 0 (head camera)",
        f"coin0 local XYZ m: {coin[0]:+.3f}, {coin[1]:+.3f}, {coin[2]:+.3f}",
        f"piggy_bank local XYZ m: {bank[0]:+.3f}, {bank[1]:+.3f}, {bank[2]:+.3f}",
        f"stage up axis: {coordinate_snapshot['stage']['up_axis']}; meters/unit: {coordinate_snapshot['stage']['meters_per_unit']}",
        "Text coordinates are measured values; no projected 3-D axis is implied.",
    ]
    panel_height = 18 * len(lines) + 16
    draw.rectangle((8, 8, min(image.width - 8, 760), panel_height), fill=(0, 0, 0))
    for index, line in enumerate(lines):
        draw.text((16, 14 + index * 18), line, fill=(255, 255, 255))
    image.save(output_path)


def main():
    day2_dir = args.day2_dir.resolve()
    day3_dir = args.day3_dir.resolve()
    day2_dir.mkdir(parents=True, exist_ok=True)
    day3_dir.mkdir(parents=True, exist_ok=True)
    for stale_error in (day2_dir / "probe_error.json", day3_dir / "probe_error.json"):
        stale_error.unlink(missing_ok=True)
    os.environ["ROBODOJO_SAVE_VIDEO"] = "0"
    os.environ["ROBODOJO_RUN_ID"] = "week02_day02_day03"
    env = None
    error = None
    try:
        eval_env_module.WsModelClient = NullModelClient
        env = eval_env_module.create_eval_env(build_config(), simulation_app)
        env.reset(seed=[args.layout])
        env.reward_manager.step = lambda env_idx_list=None: None
        env.is_episode_end = lambda: False

        robots, mapping = robot_snapshot(env)
        initial_state = {
            "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
            "config": {"task": TASK_NAME, "env_cfg": ENV_CFG_NAME, "seed": args.seed, "layout": args.layout, "policy_server": False},
            "robodojo_commit": run_text(["git", "rev-parse", "HEAD"]),
            "robodojo_status_short": run_text(["git", "status", "--short"]).splitlines(),
            "action_order_source": "XPolicyLab/utils/process_data.py::pack_robot_state/unpack_robot_state",
            "robots": robots,
            "runtime_state": robot_runtime_state(env),
        }
        write_json(day2_dir / "robot_initial_state.json", initial_state)
        write_mapping(day2_dir / "joint_mapping.csv", mapping)

        manager = env.scene_manager.layout_manager
        stage = manager.scene_manager.stage
        objects = {label: object_info(env, label) for label in OBJECT_LABELS}
        for info in objects.values():
            info["usd_physics"] = usd_physics_summary(stage, info["prim_path"])
        asset_snapshot = {
            "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
            "config": {"task": TASK_NAME, "env_cfg": ENV_CFG_NAME, "seed": args.seed, "layout": args.layout},
            "objects": objects,
        }
        write_json(day3_dir / "asset_snapshot.json", asset_snapshot)

        env_origin = values(manager.scene_manager.env_origins[0])
        coin_name = manager.get_instance_name(0, "coin0")
        bank_name = manager.get_instance_name(0, "piggy_bank")
        bank_metadata = manager.get_instance_metadata(0, inst_name=bank_name)
        bottom = manager.get_functional_points("bottom", "passive", bank_metadata, obj_name=bank_name, env_idx=0)
        center = manager.get_functional_points("center", "passive", bank_metadata, obj_name=bank_name, env_idx=0)
        initial_coin_z = objects["coin0"]["local_pose"]["position"][2]
        reward_pre_pose = values(env.reward_manager.func_parser.pre_state[0][coin_name]["pose"])
        coordinate_snapshot = {
            "stage": {"up_axis": UsdGeom.GetStageUpAxis(stage), "meters_per_unit": UsdGeom.GetStageMetersPerUnit(stage)},
            "environment_origin_world_m": env_origin,
            "pose_interface": "LayoutManager.get_instance_pose defaults to environment-relative coordinates",
            "coin": {
                "instance_name": coin_name,
                "initial_local_z_m": initial_coin_z,
                "reward_pre_state_pose": reward_pre_pose,
                "same_instance_and_coordinate_as_is_lift": bool(np.allclose(reward_pre_pose[:3], objects["coin0"]["local_pose"]["position"])),
                "is_lift_expression": "current_relative_coin_z - initial_relative_coin_z > 0.08",
                "threshold_m": 0.08,
            },
            "piggy_bank": {
                "instance_name": bank_name,
                "bbox_local_min": objects["piggy_bank"]["bbox_local_min"],
                "bbox_local_max": objects["piggy_bank"]["bbox_local_max"],
                "bottom_functional_points_relative": bottom,
                "center_functional_points_relative": center,
            },
            "initial_robot_coin_relative_positions": {
                side: {
                    "ee_minus_coin_m": (
                        np.asarray(initial_state["runtime_state"][side]["ee_pose_relative"][:3])
                        - np.asarray(objects["coin0"]["local_pose"]["position"])
                    ).tolist()
                }
                for side in ("left_arm", "right_arm")
            },
            "code_sources": {
                "pose": "env/scene_manager/layout_manager.py::get_instance_pose",
                "lift": "env/reward_manager/func_parser.py::is_lift",
                "score": "task/RoboDojo/tasks/deposit_coin.py::get_score",
                "bbox": "env/scene_manager/layout_manager.py::get_instance_bbox_vertices",
            },
        }
        write_json(day3_dir / "coordinate_snapshot.json", coordinate_snapshot)

        passive = passive_settle(env, day3_dir)
        probes = run_joint_probes(env, day2_dir)
        approach = controlled_approach(env, day3_dir)
        write_json(day2_dir / "joint_probe_results.json", {"probes": probes})
        write_json(day3_dir / "passive_settle.json", passive)
        write_json(day3_dir / "collision_probe.json", approach)
        annotate_scene(day3_dir / "collision_probe_final.jpg", day3_dir / "annotated_scene.png", asset_snapshot, coordinate_snapshot)
    except Exception as exc:
        error = {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}
        write_json(day2_dir / "probe_error.json", error)
        write_json(day3_dir / "probe_error.json", error)
        raise
    finally:
        if env is not None:
            env.close()
        simulation_app.close()


if __name__ == "__main__":
    main()
