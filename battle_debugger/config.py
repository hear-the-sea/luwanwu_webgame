"""
配置加载与管理模块

负责加载YAML配置、预设配置、命令行参数，并进行合并和校验。

安全说明：
- 预设名称必须经过白名单校验，防止路径穿越攻击
- 仅允许加载 preset_dir 目录内的 YAML 文件
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

# 安全常量：预设名称白名单正则（仅允许字母、数字、下划线、连字符）
PRESET_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9_-]+$')


# ============ 配置数据类 ============

@dataclass
class GuestConfig:
    """门客配置"""
    template: str
    level: int
    force: Optional[int] = None
    intellect: Optional[int] = None
    defense: Optional[int] = None
    agility: Optional[int] = None
    luck: Optional[int] = None
    skills: List[str] = field(default_factory=list)
    archetype: Optional[str] = None  # civil/military


@dataclass
class PartyConfig:
    """阵营配置"""
    guests: List[GuestConfig] = field(default_factory=list)
    troops: Dict[str, int] = field(default_factory=dict)
    technology_level: int = 0
    technology_levels: Dict[str, int] = field(default_factory=dict)


@dataclass
class BattleConfig:
    """战斗配置"""
    name: str
    description: str = ""
    attacker: PartyConfig = field(default_factory=PartyConfig)
    defender: PartyConfig = field(default_factory=PartyConfig)
    tunable_params: Dict[str, Any] = field(default_factory=dict)
    seed: Optional[int] = None
    repeat: int = 1


# ============ 配置加载器 ============

class ConfigLoader:
    """配置加载器"""

    def __init__(self, preset_dir: Optional[str] = None):
        """
        初始化配置加载器

        Args:
            preset_dir: 预设配置目录路径，默认为 battle_debugger/presets/
        """
        if preset_dir is None:
            # 默认使用 battle_debugger/presets/ 目录
            current_dir = Path(__file__).parent
            self.preset_dir = current_dir / "presets"
        else:
            self.preset_dir = Path(preset_dir)

    def load_preset(self, preset_name: str) -> BattleConfig:
        """
        加载预设配置

        Args:
            preset_name: 预设名称（不含.yaml后缀）

        Returns:
            BattleConfig对象

        Raises:
            FileNotFoundError: 预设文件不存在
            ValueError: 预设名称包含非法字符（安全校验）
        """
        # 安全校验：预设名称白名单
        if not preset_name or not PRESET_NAME_PATTERN.match(preset_name):
            raise ValueError(f"预设名称包含非法字符: {preset_name}")

        preset_file = self.preset_dir / f"{preset_name}.yaml"

        # 安全校验：确保解析后的路径仍在 preset_dir 内（防止符号链接攻击）
        try:
            resolved_preset = preset_file.resolve()
            resolved_dir = self.preset_dir.resolve()
            if not str(resolved_preset).startswith(str(resolved_dir) + os.sep):
                raise ValueError(f"预设路径越界: {preset_name}")
        except (OSError, ValueError):
            raise ValueError(f"预设路径无效: {preset_name}")

        if not preset_file.exists():
            raise FileNotFoundError(f"预设配置不存在: {preset_name}")

        return self.load_yaml(str(preset_file))

    def load_yaml(self, file_path: str) -> BattleConfig:
        """
        从YAML文件加载配置

        Args:
            file_path: YAML文件路径

        Returns:
            BattleConfig对象
        """
        with open(file_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        return self._parse_config(data)

    def _parse_config(self, data: dict) -> BattleConfig:
        """解析配置字典为BattleConfig对象"""
        name = data.get("name", "Unnamed")
        description = data.get("description", "")

        # 解析攻方
        attacker_data = data.get("attacker", {})
        attacker = self._parse_party(attacker_data)

        # 解析守方
        defender_data = data.get("defender", {})
        defender = self._parse_party(defender_data)

        # 解析可调参数
        tunable_params = data.get("tunable_params", {})

        return BattleConfig(
            name=name,
            description=description,
            attacker=attacker,
            defender=defender,
            tunable_params=tunable_params
        )

    def _parse_party(self, data: dict) -> PartyConfig:
        """解析阵营配置"""
        guests = []
        guests_data = data.get("guests", [])
        for guest_data in guests_data:
            guest = GuestConfig(
                template=guest_data["template"],
                level=guest_data.get("level", 1),
                force=guest_data.get("force"),
                intellect=guest_data.get("intellect"),
                defense=guest_data.get("defense"),
                agility=guest_data.get("agility"),
                luck=guest_data.get("luck"),
                skills=guest_data.get("skills", []),
                archetype=guest_data.get("archetype")
            )
            guests.append(guest)

        troops = data.get("troops", {})
        technology_level = data.get("technology_level", 0)
        technology_levels = data.get("technology_levels", {})

        return PartyConfig(
            guests=guests,
            troops=troops,
            technology_level=technology_level,
            technology_levels=technology_levels
        )

    def merge_config(self, base: BattleConfig, overrides: Dict[str, Any]) -> BattleConfig:
        """
        合并配置和覆盖参数

        Args:
            base: 基础配置
            overrides: 覆盖参数字典（支持点号路径，如 "attacker.guests.0.force"）

        Returns:
            合并后的配置
        """
        # 深拷贝基础配置
        import copy
        merged = copy.deepcopy(base)

        # 应用覆盖
        for key, value in overrides.items():
            self._apply_override(merged, key, value)

        return merged

    def _apply_override(self, config: BattleConfig, path: str, value: Any):
        """应用覆盖参数（支持点号路径）"""
        parts = path.split(".")
        obj = config

        # 遍历路径
        for i, part in enumerate(parts[:-1]):
            if part == "tunable_params":
                obj = obj.tunable_params
            elif part == "attacker":
                obj = obj.attacker
            elif part == "defender":
                obj = obj.defender
            elif part == "guests":
                obj = obj.guests
            elif part == "troops":
                obj = obj.troops
            elif part.isdigit():
                # 数组索引
                obj = obj[int(part)]
            else:
                obj = getattr(obj, part)

        # 设置最终值
        final_key = parts[-1]
        if isinstance(obj, dict):
            obj[final_key] = value
        elif isinstance(obj, list) and final_key.isdigit():
            obj[int(final_key)] = value
        else:
            setattr(obj, final_key, value)

    def _validate_party_guests(self, guests: List[GuestConfig], side_name: str) -> List[str]:
        errors: List[str] = []
        for i, guest in enumerate(guests):
            if not guest.template:
                errors.append(f"{side_name}门客{i}: 缺少template")
            if guest.level < 1 or guest.level > 100:
                errors.append(f"{side_name}门客{i}: 等级必须在1-100之间")
        return errors

    def _validate_party_troops(self, troops: Dict[str, int], side_name: str) -> List[str]:
        errors: List[str] = []
        for troop_key, count in troops.items():
            if count <= 0:
                errors.append(f"{side_name}小兵 {troop_key}: 数量必须大于0")
        return errors

    def validate(self, config: BattleConfig) -> List[str]:
        """
        校验配置

        Args:
            config: 配置对象

        Returns:
            错误列表，空列表表示无错误
        """
        errors: List[str] = []

        attacker_has_units = bool(config.attacker.guests or config.attacker.troops)
        defender_has_units = bool(config.defender.guests or config.defender.troops)

        if not attacker_has_units:
            errors.append("攻方必须至少有门客或小兵")
        if not defender_has_units:
            errors.append("守方必须至少有门客或小兵")

        errors.extend(self._validate_party_guests(config.attacker.guests, "攻方"))
        errors.extend(self._validate_party_guests(config.defender.guests, "守方"))
        errors.extend(self._validate_party_troops(config.attacker.troops, "攻方"))
        errors.extend(self._validate_party_troops(config.defender.troops, "守方"))

        return errors
    def list_presets(self) -> List[str]:
        """
        列出所有可用的预设配置

        Returns:
            预设名称列表
        """
        if not self.preset_dir.exists():
            return []

        presets = []
        for file in self.preset_dir.glob("*.yaml"):
            presets.append(file.stem)

        return sorted(presets)

    def get_preset_info(self, preset_name: str) -> Dict[str, str]:
        """
        获取预设配置的基本信息

        Args:
            preset_name: 预设名称

        Returns:
            包含name和description的字典
        """
        try:
            config = self.load_preset(preset_name)
            return {
                "name": config.name,
                "description": config.description
            }
        except FileNotFoundError:
            return {}


# ============ 默认参数 ============

DEFAULT_TUNABLE_PARAMS = {
    # 屠戮倍率
    "slaughter_multiplier": 30,

    # 攻击倍率
    "troop_attack_divisor_vs_guest": 4.0,
    "troop_attack_divisor_vs_troop": 1.0,

    # 防御倍率
    "troop_defense_divisor": 2.0,

    # 减伤公式
    "guest_vs_troop_reduction_coeff": 0.005,
    "guest_vs_troop_reduction_cap": 0.75,
    "other_reduction_base": 120,
    "other_reduction_coeff": 0.85,

    # 五行相克
    "counter_multiplier": 1.5,

    # 暴击
    "crit_chance": 0.05,
    "crit_multiplier": 1.5,

    # 先锋惩罚
    "preemptive_penalty": 0.8,

    # 目标选择
    "priority_target_weight": 0.6,

    # 回合上限
    "max_rounds": 16,
}
