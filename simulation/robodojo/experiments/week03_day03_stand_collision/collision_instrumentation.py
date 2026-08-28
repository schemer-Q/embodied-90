"""Capture actual USD collision state, contacts, and object motion during replay."""

import json
import os
from pathlib import Path

import numpy as np
import torch
import omni.usd
from omni.physx import get_physx_simulation_interface
from omegaconf import DictConfig, ListConfig, OmegaConf
from PIL import Image
from pxr import PhysicsSchemaTools, PhysxSchema, Usd, UsdGeom, UsdPhysics


def plain(value):
    if isinstance(value, (DictConfig, ListConfig)):
        return OmegaConf.to_container(value, resolve=True)
    if hasattr(value, "detach"):
        value = value.detach().cpu().numpy()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    return value


def append_jsonl(path, row):
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(plain(row), separators=(",", ":")) + "\n")


class CollisionTrace:
    def __init__(self, env):
        self.env = env
        self.output = Path(os.environ["ROBODOJO_FULL_EPISODE_TRACE_DIR"])
        self.output.mkdir(parents=True, exist_ok=True)
        self.contact_path = self.output / "contact_trace.jsonl"
        self.object_path = self.output / "object_trace.jsonl"
        self.contact_path.write_text("", encoding="utf-8")
        self.object_path.write_text("", encoding="utf-8")
        self.frames = self.output / "keyframes"
        self.frames.mkdir(exist_ok=True)
        self.events = []
        self.event_cursor = 0
        self.captured_first_contact = False
        self.original_reset = env.reset
        self.original_step = env.step

    def object(self, label):
        manager = self.env.scene_manager.layout_manager
        name = manager.get_instance_name(0, label)
        return name, manager.get_scene_object(0, name)

    def pose(self, label):
        name, _ = self.object(label)
        position, orientation = self.env.scene_manager.layout_manager.get_instance_pose(
            env_idx=0, inst_name=name, relative=True
        )
        return {"instance_name": name, "position_m": plain(position), "orientation_wxyz": plain(orientation)}

    @staticmethod
    def collider_snapshot(stage, root_path):
        rows = []
        root = stage.GetPrimAtPath(root_path)
        for prim in Usd.PrimRange(root):
            collision = UsdPhysics.CollisionAPI.Get(stage, prim.GetPath())
            if not collision:
                continue
            mesh_api = UsdPhysics.MeshCollisionAPI.Get(stage, prim.GetPath())
            approximation = None
            if mesh_api:
                approximation = mesh_api.GetApproximationAttr().Get()
            rows.append({
                "prim_path": prim.GetPath().pathString,
                "prim_type": prim.GetTypeName(),
                "collision_enabled": collision.GetCollisionEnabledAttr().Get(),
                "mesh_approximation": approximation,
            })
        return rows

    def stage_snapshot(self):
        stage = omni.usd.get_context().get_stage()
        assets = {}
        for label in ("coin0", "vertical_coin_stand", "piggy_bank"):
            name, obj = self.object(label)
            assets[label] = {
                "instance_name": name,
                "prim_path": obj.usd_prim_path,
                "pose": self.pose(label),
                "scale": plain(getattr(obj, "scale", None)),
                "physics_config": plain(dict(getattr(obj, "physics_config", {}))),
                "colliders": self.collider_snapshot(stage, obj.usd_prim_path),
            }
        tracer = self.env._week02_day05_full_episode_tracer
        actual_14d, actual_16d, ee_pose, _, _ = tracer._state()
        snapshot = {
            "condition": os.environ.get("STAND_COLLISION_CONDITION"),
            "mesh_categories": os.environ.get("ACT_GEOMETRY_MESH_CATEGORIES"),
            "assets": assets,
            "robot": {
                "actual_joint_positions_14d": actual_14d,
                "actual_joint_positions_physical_16d": actual_16d,
                "end_effector_pose": ee_pose,
            },
        }
        (self.output / "stage_snapshot.json").write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")

    def on_contact(self, headers, contact_data, _friction_anchors):
        coin_path = self.coin_path
        for header in headers:
            paths = {
                "actor0": str(PhysicsSchemaTools.intToSdfPath(header.actor0)),
                "actor1": str(PhysicsSchemaTools.intToSdfPath(header.actor1)),
                "collider0": str(PhysicsSchemaTools.intToSdfPath(header.collider0)),
                "collider1": str(PhysicsSchemaTools.intToSdfPath(header.collider1)),
            }
            if not any(coin_path in path for path in paths.values()):
                continue
            contacts = []
            start = header.contact_data_offset
            for index in range(start, start + header.num_contact_data):
                item = contact_data[index]
                contacts.append({
                    "position_m": list(item.position),
                    "normal": list(item.normal),
                    "impulse_ns": float(item.impulse),
                    "separation_m": float(item.separation),
                })
            joined = " ".join(paths.values())
            pair = "other"
            if "/robot0/link7" in joined or "/robot0/link8" in joined:
                pair = "coin_fingertip"
            elif self.stand_path in joined:
                pair = "coin_stand"
            self.events.append({"pair": pair, "paths": paths, "contacts": contacts})

    def capture(self, name):
        observation = self.env.get_obs()["vision"]
        for camera in ("cam_head", "cam_left_wrist", "cam_right_wrist"):
            path = self.frames / f"{name}_{camera}.jpg"
            Image.fromarray(np.asarray(observation[camera]["color"])).save(path, quality=95)

    def reset(self, seed=None, options=None):
        result = self.original_reset(seed=seed, options=options)
        _, coin = self.object("coin0")
        _, stand = self.object("vertical_coin_stand")
        manifest = json.loads(Path(os.environ["ACT_REPLAY_MANIFEST"]).read_text(encoding="utf-8"))
        frozen = manifest["initial_state"]["coin_pose"]
        coin.set_local_pose(
            translation=np.asarray(frozen["position"], dtype=np.float32),
            orientation=np.asarray(frozen["orientation_wxyz"], dtype=np.float32),
        )
        coin.set_linear_velocity(torch.zeros(3))
        coin.set_angular_velocity(torch.zeros(3))
        self.coin_path = coin.usd_prim_path
        self.stand_path = stand.usd_prim_path
        coin_prim = omni.usd.get_context().get_stage().GetPrimAtPath(self.coin_path)
        PhysxSchema.PhysxContactReportAPI.Apply(coin_prim).CreateThresholdAttr().Set(0.0)
        self.subscription = get_physx_simulation_interface().subscribe_full_contact_report_events(self.on_contact)
        self.events.clear()
        self.event_cursor = 0
        self.captured_first_contact = False
        self.stage_snapshot()
        self.capture("reset")
        return result

    def step(self, env_idx_list, decimation=1):
        result = self.original_step(env_idx_list=env_idx_list, decimation=decimation)
        tracer = self.env._week02_day05_full_episode_tracer
        current = tracer.current
        if current is None:
            return result
        new_events = self.events[self.event_cursor:]
        self.event_cursor = len(self.events)
        policy_step = current["policy_step"]
        internal_step = tracer.internal_step
        for event in new_events:
            append_jsonl(self.contact_path, {
                "policy_step": policy_step,
                "internal_step": internal_step,
                **event,
            })
        append_jsonl(self.object_path, {
            "policy_step": policy_step,
            "internal_step": internal_step,
            "coin_pose": self.pose("coin0"),
            "stand_pose": self.pose("vertical_coin_stand"),
            "new_contact_events": len(new_events),
            "cumulative_contact_events": len(self.events),
        })
        if new_events and not self.captured_first_contact:
            self.capture(f"first_contact_step_{policy_step:03d}_{internal_step:02d}")
            self.captured_first_contact = True
        if internal_step == 10 and policy_step in (17, 18, 35, 51, 300):
            self.capture(f"step_{policy_step:03d}")
        return result

    def install(self):
        self.env.reset = self.reset
        self.env.step = self.step


def install_collision_trace(env):
    trace = CollisionTrace(env)
    trace.install()
    env._week03_day03_collision_trace = trace
    print(f"[stand-collision-trace] output={trace.output}", flush=True)
