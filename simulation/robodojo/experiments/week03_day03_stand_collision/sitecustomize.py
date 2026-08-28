"""Install fixed-action replay and Day 3 collision instrumentation."""

from importlib.abc import Loader, MetaPathFinder
from importlib.machinery import PathFinder
import json
import os
import sys


class _Loader(Loader):
    def __init__(self, wrapped, fullname):
        self.wrapped = wrapped
        self.fullname = fullname

    def create_module(self, spec):
        create = getattr(self.wrapped, "create_module", None)
        return create(spec) if create is not None else None

    def exec_module(self, module):
        self.wrapped.exec_module(module)
        if self.fullname == "src.eval_client.eval_env":
            self._patch_eval_env(module)
        elif self.fullname.endswith("ACT.model"):
            self._patch_act_model(module)

    @staticmethod
    def _patch_act_model(module):
        original = module.Model._get_gt_action

        def get_replay_action(model):
            replay_path = os.environ.get("ACT_REPLAY_JSONL")
            if not replay_path:
                return original(model)
            if not hasattr(model, "_gt_actions"):
                with open(replay_path, encoding="utf-8") as stream:
                    rows = [json.loads(line) for line in stream if line.strip()]
                model._gt_actions = [row["action_14d"] for row in rows]
                if len(model._gt_actions) != 300 or any(len(action) != 14 for action in model._gt_actions):
                    raise ValueError("ACT_REPLAY_JSONL must contain 300 finite 14-D actions")
                model._gt_step = 0
                print(f"[FIXED_REPLAY] loaded {len(rows)} actions from {replay_path}", flush=True)
            action_vec = model._gt_actions[min(model._gt_step, len(model._gt_actions) - 1)]
            action_dict = module.unpack_robot_state(
                action_vec, model.action_type, model.robot_action_dim_info, source_type="obs"
            )
            with open("/tmp/gt_replay_actions.log", "a", encoding="utf-8") as stream:
                stream.write(f"step={model._gt_step} action={json.dumps(action_vec, separators=(',', ':'))}\n")
            model._gt_step += 1
            return [action_dict]

        module.Model._get_gt_action = get_replay_action

    @staticmethod
    def _patch_eval_env(module):
        original = module.create_eval_env

        def create_instrumented_env(*args, **kwargs):
            env = original(*args, **kwargs)
            import full_episode_instrumentation as tracing
            from collision_instrumentation import install_collision_trace
            from geometry_sampler import GeometrySampler

            tracing.RANDOM_ENV_KEYS += tuple(
                key for key in (
                    "ACT_REPLAY_JSONL",
                    "ACT_GEOMETRY_MESH_CATEGORIES",
                    "ACT_STAND_DISABLE_SOLID",
                ) if key not in tracing.RANDOM_ENV_KEYS
            )
            original_policy_result = tracing.FullEpisodeTracer._policy_result

            def policy_result_with_geometry(tracer):
                row = original_policy_result(tracer)
                if not hasattr(tracer, "_day03_geometry_sampler"):
                    tracer._day03_geometry_sampler = GeometrySampler(tracer.env)
                row.update(tracer._day03_geometry_sampler.sample())
                return row

            tracing.FullEpisodeTracer._policy_result = policy_result_with_geometry
            tracing.install_full_episode_trace(env)
            install_collision_trace(env)
            return env

        module.create_eval_env = create_instrumented_env


class _Finder(MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname != "src.eval_client.eval_env" and not fullname.endswith("ACT.model"):
            return None
        spec = PathFinder.find_spec(fullname, path)
        if spec is not None and spec.loader is not None:
            spec.loader = _Loader(spec.loader, fullname)
        return spec


if os.environ.get("ROBODOJO_STAND_COLLISION_REPLAY") == "1":
    sys.meta_path.insert(0, _Finder())
