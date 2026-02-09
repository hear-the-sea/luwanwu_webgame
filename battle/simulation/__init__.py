"""
战斗模拟模块

提供战斗模拟的核心功能，包括：
- simulate_battle: 执行完整战斗模拟
- build_rng: 构建可复现的随机数生成器

使用示例:
    from battle.simulation import simulate_battle, build_rng

    seed, rng = build_rng()
    result = simulate_battle(attackers, defenders, rng, seed, travel_seconds, config)
"""

from .battle_flow import resolve_priority_phases, simulate_battle
from .utils import build_rng

__all__ = [
    "simulate_battle",
    "build_rng",
    "resolve_priority_phases",
]
