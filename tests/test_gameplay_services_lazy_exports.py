import importlib
import sys
from contextlib import contextmanager

TARGET_MODULES = (
    "gameplay.services",
    "gameplay.services.jail",
    "gameplay.services.manor",
    "gameplay.services.technology",
    "gameplay.services.technology_helpers",
)


@contextmanager
def isolated_service_imports():
    originals = {name: sys.modules.get(name) for name in TARGET_MODULES}

    for name in TARGET_MODULES:
        sys.modules.pop(name, None)

    try:
        yield
    finally:
        for name in TARGET_MODULES:
            sys.modules.pop(name, None)

        for name, module in originals.items():
            if module is not None:
                sys.modules[name] = module


def test_gameplay_services_import_is_lazy():
    with isolated_service_imports():
        services = importlib.import_module("gameplay.services")

        assert "gameplay.services.jail" not in sys.modules
        assert "gameplay.services.manor" not in sys.modules
        assert "gameplay.services.technology" not in sys.modules
        assert "gameplay.services.technology_helpers" not in sys.modules
        assert "ensure_manor" in dir(services)
        assert "jail" in dir(services)


def test_gameplay_services_attribute_export_loads_only_requested_module():
    with isolated_service_imports():
        services = importlib.import_module("gameplay.services")

        ensure_manor = services.ensure_manor

        assert callable(ensure_manor)
        assert "gameplay.services.manor" in sys.modules
        assert "gameplay.services.technology" not in sys.modules
        assert services.ensure_manor is ensure_manor


def test_gameplay_services_module_exports_remain_compatible():
    with isolated_service_imports():
        from gameplay.services import jail as jail_service
        from gameplay.services import technology as technology_service
        from gameplay.services import technology_helpers

        services = sys.modules["gameplay.services"]

        assert jail_service is services.jail
        assert technology_service is services.technology
        assert technology_helpers is services.technology_helpers
        assert "gameplay.services.jail" in sys.modules
        assert "gameplay.services.technology" in sys.modules
        assert "gameplay.services.technology_helpers" in sys.modules
