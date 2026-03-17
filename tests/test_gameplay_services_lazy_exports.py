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
        assert not hasattr(services, "__getattr__")
        assert "ensure_manor" not in dir(services)


def test_gameplay_services_direct_submodule_import_loads_only_requested_module():
    with isolated_service_imports():
        importlib.import_module("gameplay.services")

        manor_module = importlib.import_module("gameplay.services.manor")
        manor_core_module = importlib.import_module("gameplay.services.manor.core")

        assert manor_module is sys.modules["gameplay.services.manor"]
        assert hasattr(manor_core_module, "ensure_manor")
        assert "gameplay.services.manor" in sys.modules
        assert "gameplay.services.technology" not in sys.modules


def test_gameplay_services_submodule_imports_remain_compatible():
    with isolated_service_imports():
        from gameplay.services import jail as jail_service
        from gameplay.services import technology as technology_service
        from gameplay.services import technology_helpers

        assert jail_service is sys.modules["gameplay.services.jail"]
        assert technology_service is sys.modules["gameplay.services.technology"]
        assert technology_helpers is sys.modules["gameplay.services.technology_helpers"]
        assert "gameplay.services.jail" in sys.modules
        assert "gameplay.services.technology" in sys.modules
        assert "gameplay.services.technology_helpers" in sys.modules
