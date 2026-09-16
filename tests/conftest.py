"""Shared test helpers.

``import falcon_screener.<module>`` would execute the package __init__, which
pulls in falcon_core / pandas / pytz.  These are unit tests for self-contained
modules, so we load those modules straight from their file instead, keeping the
suite runnable without the full runtime dependency tree and without network.
"""

import importlib.util
import sys
from pathlib import Path

SCREENER_SRC = Path(__file__).resolve().parents[1] / "src" / "falcon_screener"


def load_screener_module(name: str):
    """Load src/falcon_screener/<name>.py as a standalone module."""
    module_name = "falcon_screener_{}".format(name)
    if module_name in sys.modules:
        return sys.modules[module_name]

    path = SCREENER_SRC / "{}.py".format(name)
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError("Cannot load {}".format(path))

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module
