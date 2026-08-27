"""Install Week 3 Day 2 tracing in the RoboDojo eval client."""

from importlib.abc import Loader, MetaPathFinder
from importlib.machinery import PathFinder
import os
import sys


TARGET_MODULE = "src.eval_client.eval_env"


class _TracingLoader(Loader):
    def __init__(self, wrapped):
        self.wrapped = wrapped

    def create_module(self, spec):
        create = getattr(self.wrapped, "create_module", None)
        return create(spec) if create is not None else None

    def exec_module(self, module):
        self.wrapped.exec_module(module)
        original = module.create_eval_env

        def create_traced_eval_env(*args, **kwargs):
            env = original(*args, **kwargs)
            import full_episode_instrumentation as tracing
            from geometry_sampler import GeometrySampler

            if "ACT_INPUT_COLOR_ORDER" not in tracing.RANDOM_ENV_KEYS:
                tracing.RANDOM_ENV_KEYS += (
                    "ACT_INPUT_COLOR_ORDER",
                    "ACT_GEOMETRY_MESH_CATEGORIES",
                    "ACT_MAX_TIMESTEPS",
                )

            original_policy_result = tracing.FullEpisodeTracer._policy_result

            def policy_result_with_geometry(tracer):
                row = original_policy_result(tracer)
                if not hasattr(tracer, "_week03_day02_geometry_sampler"):
                    tracer._week03_day02_geometry_sampler = GeometrySampler(tracer.env)
                row.update(tracer._week03_day02_geometry_sampler.sample())
                return row

            tracing.FullEpisodeTracer._policy_result = policy_result_with_geometry
            tracing.install_full_episode_trace(env)
            return env

        module.create_eval_env = create_traced_eval_env


class _TracingFinder(MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname != TARGET_MODULE:
            return None
        spec = PathFinder.find_spec(fullname, path)
        if spec is not None and spec.loader is not None:
            spec.loader = _TracingLoader(spec.loader)
        return spec


if os.environ.get("ROBODOJO_FULL_EPISODE_TRACE") == "1":
    sys.meta_path.insert(0, _TracingFinder())
