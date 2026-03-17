"""
Shared random module reference for inventory services.

Concrete inventory submodules import this module directly so tests can patch the
same `inventory_random` object without depending on the package root facade.
"""

from __future__ import annotations

import random as inventory_random

__all__ = ["inventory_random"]
