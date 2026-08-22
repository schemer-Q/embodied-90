import json
from pathlib import Path
import re

import numpy as np
import omni.usd
from omni.physx import get_physx_simulation_interface
from PIL import Image
from pxr import Gf, PhysicsSchemaTools, PhysxSchema, Usd, UsdGeom, UsdPhysics
import trimesh
from trimesh.proximity import closest_point_naive


def _array(value):
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    return np.asarray(value, dtype=np.float64)


def _values(value):
    return _array(value).reshape(-1).tolist()


def _robots(env):
    return [robot for robot in env.robot_manager.robot_list if robot.type == "target"]


def _pose(env, label):
    manager = env.scene_manager.layout_manager
    instance_name = manager.get_instance_name(0, label)
    position, quaternion = manager.get_instance_pose(0, inst_name=instance_name)
    return {"position": _values(position), "quaternion_wxyz": _values(quaternion)}


def _hold_action(env):
    action = {}
    for robot in _robots(env):
        arm_key = env.robot_manager.process_name(robot.arm_name)
        gripper_key = env.robot_manager.process_name(robot.gripper_name)
        action[arm_key] = _values(env.robot_manager.get_joint(robot, [0])[0])
        physical = float(_array(env.robot_manager.get_end_effector_real_val(robot, [0])[0])[0])
        lower, upper = map(float, robot.gripper_scale)
        normalized = (physical - lower) / (upper - lower)
        if robot.gripper_move["sign"] != 1:
            normalized = 1.0 - normalized
        action[gripper_key] = [float(np.clip(normalized, 0.0, 1.0))]
    return action


def _quaternion_matrix(quaternion_wxyz):
    w, x, y, z = np.asarray(quaternion_wxyz, dtype=np.float64)
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def _triangulate(counts, indices):
    triangles = []
    offset = 0
    for count in counts:
        face = indices[offset : offset + count]
        offset += count
        for index in range(1, count - 1):
            triangles.append([face[0], face[index], face[index + 1]])
    return np.asarray(triangles, dtype=np.int64)


def _collision_mesh(stage, root_path):
    meshes = []
    paths = []
    root = stage.GetPrimAtPath(root_path)
    for prim in Usd.PrimRange(root):
        path = prim.GetPath().pathString
        if not prim.IsA(UsdGeom.Mesh):
            continue
        if not prim.HasAPI(UsdPhysics.CollisionAPI) and "collision" not in path.lower():
            continue
        usd_mesh = UsdGeom.Mesh(prim)
        points = np.asarray(usd_mesh.GetPointsAttr().Get(), dtype=np.float64)
        faces = _triangulate(
            list(usd_mesh.GetFaceVertexCountsAttr().Get() or []),
            list(usd_mesh.GetFaceVertexIndicesAttr().Get() or []),
        )
        if points.size == 0 or faces.size == 0:
            continue
        transform = omni.usd.get_world_transform_matrix(prim)
        world_points = np.asarray(
            [list(transform.Transform(Gf.Vec3d(float(p[0]), float(p[1]), float(p[2])))) for p in points],
            dtype=np.float64,
        )
        meshes.append(trimesh.Trimesh(vertices=world_points, faces=faces, process=False))
        paths.append(path)
    if not meshes:
        available = [prim.GetPath().pathString for prim in Usd.PrimRange(root) if prim.IsA(UsdGeom.Mesh)]
        raise RuntimeError(f"No collision mesh below {root_path}; mesh prims={available}")
    return trimesh.util.concatenate(meshes), paths


def _fingertip_alignment(env, coin_path):
    stage = env.scene_manager.layout_manager.scene_manager.stage
    left = _robots(env)[0]
    ee_pose = _array(env.robot_manager.get_real_endpose(left, [0], True)[0])
    forward = _quaternion_matrix(ee_pose[3:]) @ np.array([1.0, 0.0, 0.0])
    tip_centers = {}
    for finger in ("link7", "link8"):
        finger_mesh, _ = _collision_mesh(stage, f"/World/envs/env_0/robot0/{finger}")
        projection = finger_mesh.vertices @ forward
        tip_vertices = finger_mesh.vertices[projection >= projection.max() - 0.008]
        tip_centers[finger] = tip_vertices.mean(axis=0)
    midpoint = 0.5 * (tip_centers["link7"] + tip_centers["link8"])
    coin_position = np.asarray(_pose(env, "coin0")["position"])
    error = coin_position - midpoint
    return {
        "link7_tip_center_m": tip_centers["link7"].tolist(),
        "link8_tip_center_m": tip_centers["link8"].tolist(),
        "fingertip_midpoint_m": midpoint.tolist(),
        "coin_center_m": coin_position.tolist(),
        "coin_minus_fingertip_midpoint_m": error.tolist(),
        "alignment_error_m": float(np.linalg.norm(error)),
    }


def _surface_metrics(env, coin_path):
    stage = env.scene_manager.layout_manager.scene_manager.stage
    coin_mesh, coin_paths = _collision_mesh(stage, coin_path)
    result = {"coin_collision_mesh_paths": coin_paths, "fingers": {}}
    distances = []
    for finger in ("link7", "link8"):
        finger_mesh, finger_paths = _collision_mesh(stage, f"/World/envs/env_0/robot0/{finger}")
        _, finger_to_coin, _ = closest_point_naive(coin_mesh, finger_mesh.vertices)
        _, coin_to_finger, _ = closest_point_naive(finger_mesh, coin_mesh.vertices)
        distance = float(min(finger_to_coin.min(), coin_to_finger.min()))
        distances.append(distance)
        result["fingers"][finger] = {
            "collision_mesh_paths": finger_paths,
            "surface_distance_m": distance,
        }
    result["minimum_surface_distance_m"] = min(distances)
    return result


def _capture(env, frames_dir, repeat, stage_name):
    observation = env.get_obs()["vision"]
    saved = {}
    for camera in ("cam_head", "cam_left_wrist"):
        path = frames_dir / f"repeat_{repeat:02d}_{stage_name}_{camera}.jpg"
        Image.fromarray(np.asarray(observation[camera]["color"])).save(path, quality=95)
        saved[camera] = path.name
    return saved


class _ContactRecorder:
    def __init__(self, coin_path):
        self.coin_path = coin_path
        self.events = []
        coin_prim = omni.usd.get_context().get_stage().GetPrimAtPath(coin_path)
        report_api = PhysxSchema.PhysxContactReportAPI.Apply(coin_prim)
        report_api.CreateThresholdAttr().Set(0.0)
        self.subscription = get_physx_simulation_interface().subscribe_full_contact_report_events(self._on_event)

    def _on_event(self, headers, contact_data, _friction_anchors):
        for header in headers:
            actor0 = str(PhysicsSchemaTools.intToSdfPath(header.actor0))
            actor1 = str(PhysicsSchemaTools.intToSdfPath(header.actor1))
            collider0 = str(PhysicsSchemaTools.intToSdfPath(header.collider0))
            collider1 = str(PhysicsSchemaTools.intToSdfPath(header.collider1))
            paths = (actor0, actor1, collider0, collider1)
            if not any(self.coin_path in path for path in paths):
                continue
            if not any("/robot0/link7" in path or "/robot0/link8" in path for path in paths):
                continue
            points = []
            start = header.contact_data_offset
            for index in range(start, start + header.num_contact_data):
                item = contact_data[index]
                points.append(
                    {
                        "position": list(item.position),
                        "normal": list(item.normal),
                        "impulse": float(item.impulse),
                        "separation_m": float(item.separation),
                    }
                )
            self.events.append(
                {
                    "type": str(header.type),
                    "actor0": actor0,
                    "actor1": actor1,
                    "collider0": collider0,
                    "collider1": collider1,
                    "contacts": points,
                }
            )

    def close(self):
        self.subscription = None


def _sample(env, coin_initial, command, recorder, phase, step, coin_path):
    coin_position = np.asarray(_pose(env, "coin0")["position"])
    left = _robots(env)[0]
    return {
        "phase": phase,
        "step": step,
        "command_normalized": command,
        "actual_gripper_qpos_m": _values(env.robot_manager.get_end_effector_real_val(left, [0])[0]),
        "actual_arm_qpos_rad": _values(env.robot_manager.get_joint(left, [0])[0]),
        "coin_position_m": coin_position.tolist(),
        "coin_displacement_m": float(np.linalg.norm(coin_position - coin_initial)),
        "surface": _surface_metrics(env, coin_path),
        "coin_finger_contact_event_count": len(recorder.events),
    }


def _write_json(path, data):
    with Path(path).open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _recorded_approach_waypoints():
    log_path = Path(__file__).parents[2] / "logs" / "coin_x5_day04_act_exec.log"
    text = log_path.read_text(encoding="utf-8")
    matches = re.findall(r"step=(\d+) env=0 left_arm=\[(.*?)\] left_ee", text, flags=re.DOTALL)
    waypoints = []
    for step_text, values_text in matches:
        step = int(step_text)
        if step > 65:
            break
        qpos = np.fromstring(values_text.replace("\n", " "), sep=" ")
        if qpos.shape != (6,):
            raise ValueError(f"Invalid left-arm qpos at policy step {step}: {qpos}")
        waypoints.append((step, qpos.tolist()))
    if len(waypoints) != 65:
        raise RuntimeError(f"Expected 65 recorded approach waypoints, got {len(waypoints)} from {log_path}")
    return log_path, waypoints


def run_repeated_contact_probe(env, output_dir, layout):
    output_dir = Path(output_dir)
    frames_dir = output_dir / "contact_probe_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    repeats = []
    trajectory_path, approach_waypoints = _recorded_approach_waypoints()

    for repeat in range(1, 4):
        env.reset(seed=[layout])
        env.reward_manager.step = lambda env_idx_list=None: None
        env.is_episode_end = lambda: False
        manager = env.scene_manager.layout_manager
        coin_name = manager.get_instance_name(0, "coin0")
        coin_obj = manager.get_scene_object(0, coin_name)
        coin_path = coin_obj.usd_prim_path
        recorder = _ContactRecorder(coin_path)
        left = _robots(env)[0]
        coin_initial = np.asarray(_pose(env, "coin0")["position"])
        samples = []
        before_frames = None
        first_frames = None

        for policy_step, target_qpos in approach_waypoints:
            action = _hold_action(env)
            action[env.robot_manager.process_name(left.arm_name)] = target_qpos
            action[env.robot_manager.process_name(left.gripper_name)] = [1.0]
            prior_events = len(recorder.events)
            if policy_step == 60 and before_frames is None:
                before_frames = _capture(env, frames_dir, repeat, "before_contact")
            env.take_action(action)
            if policy_step == 65:
                samples.append(_sample(env, coin_initial, 1.0, recorder, "approach", policy_step, coin_path))
            if len(recorder.events) > prior_events and first_frames is None:
                first_frames = _capture(env, frames_dir, repeat, "first_contact")

        alignment_ok = True
        for alignment_step in range(1, 17):
            alignment = _fingertip_alignment(env, coin_path)
            error = np.asarray(alignment["coin_minus_fingertip_midpoint_m"])
            if alignment["alignment_error_m"] <= 0.004:
                break
            delta = error * min(1.0, 0.015 / alignment["alignment_error_m"])
            current_pose = _array(env.robot_manager.get_real_endpose(left, [0], True)[0])
            ik = {"status": "Fail"}
            for scale in (1.0, 0.5, 0.25, 0.125):
                target_pose = current_pose.copy()
                target_pose[:3] += scale * delta
                ik = env.robot_manager.solve_ik(target_pose.tolist(), 0, left, trans="world")
                if ik.get("status") == "Success":
                    break
            if ik.get("status") != "Success":
                alignment_ok = False
                samples.append({"phase": "alignment", "step": alignment_step, "ik_status": "Fail", "alignment": alignment})
                break
            before_frames = _capture(env, frames_dir, repeat, "before_contact")
            action = _hold_action(env)
            action[env.robot_manager.process_name(left.arm_name)] = _values(ik["joint_value"])
            action[env.robot_manager.process_name(left.gripper_name)] = [1.0]
            prior_events = len(recorder.events)
            env.take_action(action)
            samples.append({
                "phase": "alignment",
                "step": alignment_step,
                "ik_status": ik.get("status"),
                "alignment_before_action": alignment,
                "coin_finger_contact_event_count": len(recorder.events),
            })
            if len(recorder.events) > prior_events and first_frames is None:
                first_frames = _capture(env, frames_dir, repeat, "first_contact")
                break

        samples.append(_sample(env, coin_initial, 1.0, recorder, "alignment_final", alignment_step, coin_path))
        if before_frames is None:
            before_frames = _capture(env, frames_dir, repeat, "before_contact")

        contact_close_step = None
        collision_limited_step = None
        for close_step in range(1, 41):
            command = max(0.0, 1.0 - close_step * 0.025)
            action = _hold_action(env)
            action[env.robot_manager.process_name(left.gripper_name)] = [command]
            prior_events = len(recorder.events)
            env.take_action(action)
            if close_step in (1, 28, 32, 36, 40) or len(recorder.events) > prior_events:
                sample = _sample(env, coin_initial, command, recorder, "close", close_step, coin_path)
                samples.append(sample)
                if sample["surface"]["minimum_surface_distance_m"] < 0.001 and close_step >= 32 and collision_limited_step is None:
                    collision_limited_step = close_step
                    if first_frames is None:
                        first_frames = _capture(env, frames_dir, repeat, "first_collision_limit")
            if len(recorder.events) > prior_events and contact_close_step is None:
                contact_close_step = close_step
                if first_frames is None:
                    first_frames = _capture(env, frames_dir, repeat, "first_contact")
            if contact_close_step is not None and close_step >= contact_close_step + 5:
                break

        after_frames = _capture(env, frames_dir, repeat, "after_close")
        if first_frames is None:
            first_frames = _capture(env, frames_dir, repeat, "first_contact_not_detected")

        measured = [sample for sample in samples if "surface" in sample]
        close_samples = {sample["step"]: sample for sample in measured if sample["phase"] == "close"}
        limit_sample = close_samples.get(32)
        final_sample = close_samples.get(40)
        collision_limited = bool(
            collision_limited_step is not None
            and limit_sample is not None
            and final_sample is not None
            and final_sample["command_normalized"] == 0.0
            and 0.0 < final_sample["surface"]["minimum_surface_distance_m"] < 0.001
            and abs(
                final_sample["surface"]["minimum_surface_distance_m"]
                - limit_sample["surface"]["minimum_surface_distance_m"]
            ) < 0.0001
            and np.max(
                np.abs(
                    np.asarray(final_sample["actual_gripper_qpos_m"])
                    - np.asarray(limit_sample["actual_gripper_qpos_m"])
                )
            ) < 0.0002
        )
        max_displacement = max(sample["coin_displacement_m"] for sample in measured)
        min_surface_distance = min(sample["surface"]["minimum_surface_distance_m"] for sample in measured)
        max_impulse = max(
            (abs(point["impulse"]) for event in recorder.events for point in event["contacts"]),
            default=0.0,
        )
        repeats.append(
            {
                "repeat": repeat,
                "approach_ok": True,
                "alignment_ok": alignment_ok,
                "final_fingertip_alignment": _fingertip_alignment(env, coin_path),
                "approach_final_target_qpos_rad": approach_waypoints[-1][1],
                "contact_detected": bool(recorder.events),
                "contact_close_step": contact_close_step,
                "collision_limited": collision_limited,
                "collision_limited_step": collision_limited_step,
                "interaction_evidence": "contact_report" if recorder.events else ("collision_limit" if collision_limited else None),
                "contact_event_count": len(recorder.events),
                "max_contact_impulse_ns": max_impulse,
                "minimum_surface_distance_m": min_surface_distance,
                "coin_max_displacement_m": max_displacement,
                "frames": {
                    "before_contact": before_frames,
                    "first_contact": first_frames,
                    "after_close": after_frames,
                },
                "events": recorder.events,
                "samples": samples,
            }
        )
        recorder.close()

    result = {
        "method": "Replay policy steps 1-65 recorded left-arm qpos with gripper held fully open, then align the runtime fingertip-surface midpoint to coin center with <=0.015 m Cartesian increments and decrement normalized gripper command by 0.025; 10 internal steps per command",
        "approach_source": str(trajectory_path.relative_to(Path(__file__).parents[4])),
        "approach_policy_steps": [approach_waypoints[0][0], approach_waypoints[-1][0]],
        "surface_distance_method": "bidirectional vertex-to-triangle distance on runtime USD collision meshes",
        "contact_sensor": "PhysxContactReportAPI on coin, threshold 0; events filtered to robot0 link7/link8",
        "collision_limit_criterion": "close step 32 and final step 40 remain at a positive <1 mm surface gap; final command is 0; gap changes <0.1 mm and each actual finger qpos changes <0.2 mm",
        "repeat_count": 3,
        "successful_contact_repeats": sum(item["contact_detected"] for item in repeats),
        "all_repeats_contact": all(item["contact_detected"] for item in repeats),
        "successful_collision_limit_repeats": sum(item["collision_limited"] for item in repeats),
        "all_repeats_collision_limited": all(item["collision_limited"] for item in repeats),
        "successful_interaction_repeats": sum(item["interaction_evidence"] is not None for item in repeats),
        "all_repeats_have_interaction_evidence": all(item["interaction_evidence"] is not None for item in repeats),
        "repeats": repeats,
    }
    _write_json(output_dir / "contact_probe_repeated.json", result)
    with (output_dir / "contact_probe_repeated.log").open("w", encoding="utf-8") as handle:
        handle.write(f"successful_contact_repeats={result['successful_contact_repeats']}/3\n")
        handle.write(f"successful_collision_limit_repeats={result['successful_collision_limit_repeats']}/3\n")
        handle.write(f"successful_interaction_repeats={result['successful_interaction_repeats']}/3\n")
        for item in repeats:
            handle.write(
                f"repeat={item['repeat']} contact={item['contact_detected']} collision_limited={item['collision_limited']} "
                f"events={item['contact_event_count']} max_impulse_ns={item['max_contact_impulse_ns']:.8f} "
                f"min_surface_distance_m={item['minimum_surface_distance_m']:.8f} "
                f"coin_max_displacement_m={item['coin_max_displacement_m']:.8f}\n"
            )
    return result
