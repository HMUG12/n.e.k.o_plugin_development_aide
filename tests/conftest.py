"""Load the plugin package for standalone test runs.

The repository root *is* the plugin package (``plugin.plugins.development_aide``
once mounted into N.E.K.O), but its directory name here is not a valid Python
identifier, so tests import it by file location instead.
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

if "development_aide" not in sys.modules:
    spec = importlib.util.spec_from_file_location(
        "development_aide",
        ROOT / "__init__.py",
        submodule_search_locations=[str(ROOT)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["development_aide"] = module
    spec.loader.exec_module(module)
