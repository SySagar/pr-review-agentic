import importlib

import evals
import harness
import harness.agents
import harness.checks
import mcp_servers


def test_package_imports() -> None:
    expected = [
        "harness",
        "harness.agents",
        "harness.checks",
        "mcp_servers",
        "evals",
    ]

    for module_name in expected:
        module = importlib.import_module(module_name)
        assert module is not None
        assert module.__spec__ is not None
        assert module.__spec__.name == module_name


def test_every_package_is_usable_smoke() -> None:
    package_modules = [
        harness,
        harness.agents,
        harness.checks,
        mcp_servers,
        evals,
    ]

    for module in package_modules:
        assert hasattr(module, "__file__")
        assert module.__file__
        assert hasattr(module, "__package__")
