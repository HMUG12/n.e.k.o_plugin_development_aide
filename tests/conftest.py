"""Test bootstrap: load the plugin package in standalone mode.

The repository root *is* the plugin package (``plugin.plugins.development_aide``
once mounted into N.E.K.O), but its directory name here is not a valid Python
identifier, so the module is loaded by file location.

The suite must also pass inside the N.E.K.O tree, where the market release
check runs pytest against the real SDK: ``NekoPluginBase`` there resolves the
plugin directory and metadata from a live ``PluginContext`` that unit tests do
not have. Blocking ``plugin`` keeps these tests on the package's in-memory
standalone fallback so they behave identically in both environments; SDK
integration itself is covered by the host's validator.
"""
import importlib.util
import sys
import types
from pathlib import Path

# Replacing the SDK module makes ``from plugin.sdk.plugin import ...`` raise
# ImportError, which the package catches to select its standalone fallback.
# Only this leaf module is replaced: pytest imports the plugin itself as the
# package ``plugin.plugins.development_aide`` inside the N.E.K.O tree, so the
# real ``plugin`` and ``plugin.plugins`` packages must stay intact.
sys.modules.setdefault("plugin.sdk.plugin", types.ModuleType("plugin.sdk.plugin"))

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
