from __future__ import annotations

from core.utils.infrastructure import (
    CACHE_INFRASTRUCTURE_EXCEPTIONS,
    InfrastructureExceptions,
    is_expected_cache_infrastructure_error,
)

CacheInfrastructureExceptions = InfrastructureExceptions

__all__ = [
    "CACHE_INFRASTRUCTURE_EXCEPTIONS",
    "CacheInfrastructureExceptions",
    "is_expected_cache_infrastructure_error",
]
