"""Cached fingertip/coin collision geometry sampling for policy trajectories."""

import numpy as np
import omni.usd
from pxr import Gf, Usd, UsdGeom, UsdPhysics
import trimesh
from trimesh.proximity import closest_point_naive

from contact_probe import _array, _pose, _quaternion_matrix, _robots, _triangulate


class GeometrySampler:
    def __init__(self, env):
        self.env = env
        self.stage = env.scene_manager.layout_manager.scene_manager.stage
        manager = env.scene_manager.layout_manager
        coin_name = manager.get_instance_name(0, "coin0")
        self.coin_path = manager.get_scene_object(0, coin_name).usd_prim_path
        self.records = {
            "coin": self._mesh_records(self.coin_path),
            "link7": self._mesh_records("/World/envs/env_0/robot0/link7"),
            "link8": self._mesh_records("/World/envs/env_0/robot0/link8"),
        }

    def _mesh_records(self, root_path):
        records = []
        root = self.stage.GetPrimAtPath(root_path)
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
            if points.size and faces.size:
                records.append({"prim": prim, "points": points, "faces": faces, "path": path})
        if not records:
            raise RuntimeError(f"No collision mesh below {root_path}")
        return records

    @staticmethod
    def _world_vertices(record):
        transform = omni.usd.get_world_transform_matrix(record["prim"])
        return np.asarray(
            [
                list(transform.Transform(Gf.Vec3d(float(point[0]), float(point[1]), float(point[2]))))
                for point in record["points"]
            ],
            dtype=np.float64,
        )

    def _coin_mesh(self):
        meshes = []
        for record in self.records["coin"]:
            meshes.append(
                trimesh.Trimesh(
                    vertices=self._world_vertices(record),
                    faces=record["faces"],
                    process=False,
                )
            )
        return trimesh.util.concatenate(meshes)

    def sample(self):
        coin_mesh = self._coin_mesh()
        left = _robots(self.env)[0]
        ee_pose = _array(self.env.robot_manager.get_real_endpose(left, [0], True)[0])
        forward = _quaternion_matrix(ee_pose[3:]) @ np.array([1.0, 0.0, 0.0])
        tip_centers = {}
        finger_results = {}
        distances = []
        for finger in ("link7", "link8"):
            vertices = np.concatenate(
                [self._world_vertices(record) for record in self.records[finger]],
                axis=0,
            )
            projection = vertices @ forward
            tip_vertices = vertices[projection >= projection.max() - 0.008]
            _, distance, _ = closest_point_naive(coin_mesh, tip_vertices)
            minimum = float(np.min(distance))
            center = np.mean(tip_vertices, axis=0)
            tip_centers[finger] = center
            distances.append(minimum)
            finger_results[finger] = {
                "collision_mesh_paths": [record["path"] for record in self.records[finger]],
                "tip_vertex_count": int(len(tip_vertices)),
                "surface_distance_m": minimum,
                "tip_center_m": center.tolist(),
            }

        midpoint = 0.5 * (tip_centers["link7"] + tip_centers["link8"])
        coin_position = np.asarray(_pose(self.env, "coin0")["position"], dtype=float)
        error = coin_position - midpoint
        return {
            "fingertip_surface": {
                "method": "cached collision meshes; front 8 mm fingertip vertices to coin triangles",
                "coin_collision_mesh_paths": [record["path"] for record in self.records["coin"]],
                "fingers": finger_results,
                "minimum_surface_distance_m": min(distances),
            },
            "fingertip_alignment": {
                "link7_tip_center_m": tip_centers["link7"].tolist(),
                "link8_tip_center_m": tip_centers["link8"].tolist(),
                "fingertip_midpoint_m": midpoint.tolist(),
                "coin_center_m": coin_position.tolist(),
                "coin_minus_fingertip_midpoint_m": error.tolist(),
                "alignment_error_m": float(np.linalg.norm(error)),
            },
        }
