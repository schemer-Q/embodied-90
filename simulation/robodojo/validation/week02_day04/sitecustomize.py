"""Install the Day 4 EvalEnv instrumentation without editing RoboDojo."""

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
            from action_trace_instrumentation import install_action_trace

            install_action_trace(env)
            return env

        module.create_eval_env = create_traced_eval_env


class _TracingFinder(MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname != TARGET_MODULE:
            return None
        spec = PathFinder.find_spec(fullname, path)
        if spec is None or spec.loader is None:
            return spec
        spec.loader = _TracingLoader(spec.loader)
        return spec


if os.environ.get("ROBODOJO_ACTION_TRACE") == "1":
    sys.meta_path.insert(0, _TracingFinder())
    print("[action-trace] EvalEnv import hook installed", file=sys.stderr, flush=True)
