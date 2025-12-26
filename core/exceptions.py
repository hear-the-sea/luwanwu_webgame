"""
游戏核心异常类

提供统一的异常处理机制，替代分散的 ValueError。
每个异常类包含错误代码和用户友好的消息。

使用示例:
    from core.exceptions import InsufficientResourceError, GuestNotIdleError

    if not has_enough_silver(manor, cost):
        raise InsufficientResourceError("silver", cost, manor.silver)

    if guest.status != GuestStatus.IDLE:
        raise GuestNotIdleError(guest)
"""

from __future__ import annotations

from typing import Any


class GameError(Exception):
    """
    游戏错误基类

    所有游戏业务逻辑相关的异常都应继承此类。
    提供统一的错误代码和消息格式化机制。
    """

    error_code: str = "GAME_ERROR"
    default_message: str = "游戏发生错误"

    def __init__(self, message: str | None = None, **context: Any):
        self.message = message or self.default_message
        self.context = context
        super().__init__(self.message)

    def __str__(self) -> str:
        return self.message


# ============ 资源相关异常 ============


class ResourceError(GameError):
    """资源相关错误基类"""

    error_code = "RESOURCE_ERROR"


class InsufficientResourceError(ResourceError):
    """资源不足"""

    error_code = "INSUFFICIENT_RESOURCE"

    def __init__(
        self,
        resource_type: str,
        required: int,
        available: int,
        message: str | None = None,
    ):
        self.resource_type = resource_type
        self.required = required
        self.available = available
        if message is None:
            labels = {
                "grain": "粮食",
                "silver": "银两",
            }
            label = labels.get(resource_type, resource_type)
            message = f"{label}不足，需要 {required}，当前 {available}"
        super().__init__(
            message,
            resource_type=resource_type,
            required=required,
            available=available,
        )


class InsufficientSilverError(InsufficientResourceError):
    """银两不足（常用快捷类）"""

    error_code = "INSUFFICIENT_SILVER"

    def __init__(self, required: int, available: int, message: str | None = None):
        super().__init__("silver", required, available, message)


# ============ 门客相关异常 ============


class GuestError(GameError):
    """门客相关错误基类"""

    error_code = "GUEST_ERROR"


class GuestNotIdleError(GuestError):
    """门客不是空闲状态"""

    error_code = "GUEST_NOT_IDLE"

    def __init__(self, guest: Any, message: str | None = None):
        guest_name = getattr(guest, "display_name", str(guest))
        guest_status = getattr(guest, "status", "unknown")
        if message is None:
            status_labels = {
                "idle": "空闲",
                "working": "打工中",
                "deployed": "出征中",
                "injured": "重伤",
            }
            status_label = status_labels.get(guest_status, guest_status)
            message = f"{guest_name} 当前状态为「{status_label}」，无法执行此操作"
        super().__init__(message, guest_name=guest_name, guest_status=guest_status)


class GuestInjuredError(GuestError):
    """门客重伤"""

    error_code = "GUEST_INJURED"

    def __init__(self, guest: Any, message: str | None = None):
        guest_name = getattr(guest, "display_name", str(guest))
        if message is None:
            message = f"{guest_name} 处于重伤状态，请先治疗"
        super().__init__(message, guest_name=guest_name)


class GuestMaxLevelError(GuestError):
    """门客已达等级上限"""

    error_code = "GUEST_MAX_LEVEL"

    def __init__(self, guest: Any, max_level: int = 100, message: str | None = None):
        guest_name = getattr(guest, "display_name", str(guest))
        if message is None:
            message = f"{guest_name} 已达等级上限 {max_level}"
        super().__init__(message, guest_name=guest_name, max_level=max_level)


class GuestTrainingInProgressError(GuestError):
    """门客正在训练中"""

    error_code = "GUEST_TRAINING_IN_PROGRESS"

    def __init__(self, guest: Any, message: str | None = None):
        guest_name = getattr(guest, "display_name", str(guest))
        if message is None:
            message = f"{guest_name} 已在等待升级完成"
        super().__init__(message, guest_name=guest_name)


class GuestNotRequirementError(GuestError):
    """门客属性不满足要求"""

    error_code = "GUEST_NOT_REQUIREMENT"

    def __init__(
        self,
        guest: Any,
        requirement_type: str,
        required: int,
        actual: int,
        message: str | None = None,
    ):
        guest_name = getattr(guest, "display_name", str(guest))
        if message is None:
            labels = {
                "level": "等级",
                "force": "武力",
                "intellect": "智力",
                "defense": "防御",
                "agility": "敏捷",
            }
            label = labels.get(requirement_type, requirement_type)
            message = f"{guest_name} {label}不足，需要 {required}，当前 {actual}"
        super().__init__(
            message,
            guest_name=guest_name,
            requirement_type=requirement_type,
            required=required,
            actual=actual,
        )


# ============ 容量相关异常 ============


class CapacityError(GameError):
    """容量相关错误基类"""

    error_code = "CAPACITY_ERROR"


class GuestCapacityFullError(CapacityError):
    """门客容量已满"""

    error_code = "GUEST_CAPACITY_FULL"
    default_message = "聚贤庄容量已满，升级后再招募新的门客"


class RetainerCapacityFullError(CapacityError):
    """家丁容量已满"""

    error_code = "RETAINER_CAPACITY_FULL"
    default_message = "家丁房容量已满，无法继续安置家丁"


class SkillSlotFullError(CapacityError):
    """技能位已满"""

    error_code = "SKILL_SLOT_FULL"
    default_message = "技能位已满"


class EquipmentSlotFullError(CapacityError):
    """装备槽位已满"""

    error_code = "EQUIPMENT_SLOT_FULL"

    def __init__(self, slot: str, message: str | None = None):
        if message is None:
            message = "该槽位已满"
        super().__init__(message, slot=slot)


class TreasuryCapacityFullError(CapacityError):
    """藏宝阁空间不足"""

    error_code = "TREASURY_CAPACITY_FULL"

    def __init__(
        self,
        required_space: int,
        remaining_space: int,
        message: str | None = None,
    ):
        if message is None:
            message = f"藏宝阁空间不足，剩余空间：{remaining_space}，需要空间：{required_space}"
        super().__init__(
            message,
            required_space=required_space,
            remaining_space=remaining_space,
        )


# ============ 物品相关异常 ============


class ItemError(GameError):
    """物品相关错误基类"""

    error_code = "ITEM_ERROR"


class ItemNotFoundError(ItemError):
    """物品不存在"""

    error_code = "ITEM_NOT_FOUND"
    default_message = "物品不存在"


class ItemInsufficientError(ItemError):
    """物品数量不足"""

    error_code = "ITEM_INSUFFICIENT"

    def __init__(
        self,
        item_name: str,
        required: int,
        available: int,
        message: str | None = None,
    ):
        if message is None:
            message = f"{item_name} 数量不足，需要 {required}，当前 {available}"
        super().__init__(
            message,
            item_name=item_name,
            required=required,
            available=available,
        )


# ============ 装备相关异常 ============


class EquipmentError(GameError):
    """装备相关错误基类"""

    error_code = "EQUIPMENT_ERROR"


class EquipmentAlreadyEquippedError(EquipmentError):
    """装备已被其他门客使用"""

    error_code = "EQUIPMENT_ALREADY_EQUIPPED"
    default_message = "该装备已被其他门客使用"


class EquipmentNotEquippedError(EquipmentError):
    """装备未被此门客使用"""

    error_code = "EQUIPMENT_NOT_EQUIPPED"
    default_message = "该装备未被此门客使用"


class DuplicateEquipmentError(EquipmentError):
    """同名装备已装备"""

    error_code = "DUPLICATE_EQUIPMENT"
    default_message = "同名装备已装备，无法重复装备"


# ============ 任务相关异常 ============


class MissionError(GameError):
    """任务相关错误基类"""

    error_code = "MISSION_ERROR"


class MissionDailyLimitError(MissionError):
    """任务次数已耗尽"""

    error_code = "MISSION_DAILY_LIMIT"
    default_message = "今日该任务次数已耗尽"


class MissionCannotRetreatError(MissionError):
    """无法撤退"""

    error_code = "MISSION_CANNOT_RETREAT"

    def __init__(self, reason: str = "ended", message: str | None = None):
        if message is None:
            if reason == "ended":
                message = "任务已结束，无法撤退"
            elif reason == "returning":
                message = "已进入返程，无法撤退"
            else:
                message = "无法撤退"
        super().__init__(message, reason=reason)


# ============ 建筑相关异常 ============


class BuildingError(GameError):
    """建筑相关错误基类"""

    error_code = "BUILDING_ERROR"


class BuildingUpgradingError(BuildingError):
    """建筑正在升级中"""

    error_code = "BUILDING_UPGRADING"
    default_message = "建筑正在升级中"


class BuildingNotBuiltError(BuildingError):
    """建筑尚未建造"""

    error_code = "BUILDING_NOT_BUILT"

    def __init__(self, building_name: str, message: str | None = None):
        if message is None:
            message = f"{building_name}尚未建造"
        super().__init__(message, building_name=building_name)


# ============ 技术相关异常 ============


class TechnologyError(GameError):
    """技术相关错误基类"""

    error_code = "TECHNOLOGY_ERROR"


class TechnologyNotFoundError(TechnologyError):
    """未知技术"""

    error_code = "TECHNOLOGY_NOT_FOUND"

    def __init__(self, tech_key: str, message: str | None = None):
        if message is None:
            message = f"未知技术: {tech_key}"
        super().__init__(message, tech_key=tech_key)


# ============ 消息相关异常 ============


class MessageError(GameError):
    """消息相关错误基类"""

    error_code = "MESSAGE_ERROR"


class MessageNotFoundError(MessageError):
    """消息不存在"""

    error_code = "MESSAGE_NOT_FOUND"
    default_message = "该消息不存在"


class AttachmentNotFoundError(MessageError):
    """附件不存在"""

    error_code = "ATTACHMENT_NOT_FOUND"
    default_message = "该消息没有附件"


class AttachmentAlreadyClaimedError(MessageError):
    """附件已领取"""

    error_code = "ATTACHMENT_ALREADY_CLAIMED"
    default_message = "附件已经领取过了"


# ============ 打工相关异常 ============


class WorkError(GameError):
    """打工相关错误基类"""

    error_code = "WORK_ERROR"


class WorkNotInProgressError(WorkError):
    """不在打工中"""

    error_code = "WORK_NOT_IN_PROGRESS"
    default_message = "该任务不是打工中状态，无法召回"


class WorkNotCompletedError(WorkError):
    """任务未完成"""

    error_code = "WORK_NOT_COMPLETED"
    default_message = "该任务未完成，无法领取报酬"


class WorkRewardClaimedError(WorkError):
    """报酬已领取"""

    error_code = "WORK_REWARD_CLAIMED"
    default_message = "报酬已经领取过了"


class WorkLimitExceededError(WorkError):
    """打工人数超限"""

    error_code = "WORK_LIMIT_EXCEEDED"
    default_message = "打工人数已达上限"

    def __init__(self, limit: int):
        super().__init__(f"最多允许 {limit} 名门客同时打工")
        self.limit = limit


# ============ 工资相关异常 ============


class SalaryError(GameError):
    """工资相关错误基类"""

    error_code = "SALARY_ERROR"


class SalaryAlreadyPaidError(SalaryError):
    """工资已支付"""

    error_code = "SALARY_ALREADY_PAID"

    def __init__(self, guest: Any = None, message: str | None = None):
        if guest:
            guest_name = getattr(guest, "display_name", str(guest))
            if message is None:
                message = f"{guest_name} 今日工资已支付"
            super().__init__(message, guest_name=guest_name)
        else:
            if message is None:
                message = "所有门客今日工资已支付"
            super().__init__(message)


class NoGuestToPayError(SalaryError):
    """没有门客需要支付"""

    error_code = "NO_GUEST_TO_PAY"
    default_message = "所有门客今日工资已支付"


# ============ 招募相关异常 ============


class RecruitmentError(GameError):
    """招募相关错误基类"""

    error_code = "RECRUITMENT_ERROR"


class PoolNotConfiguredError(RecruitmentError):
    """卡池未配置"""

    error_code = "POOL_NOT_CONFIGURED"
    default_message = "卡池尚未配置门客"


class NoTemplateAvailableError(RecruitmentError):
    """没有可用模板"""

    error_code = "NO_TEMPLATE_AVAILABLE"
    default_message = "缺少可用的门客模板，请更新 guest_templates.yaml 并重新加载"


# ============ 属性点相关异常 ============


class AttributePointError(GameError):
    """属性点相关错误基类"""

    error_code = "ATTRIBUTE_POINT_ERROR"


class InvalidAllocationError(AttributePointError):
    """无效的加点请求"""

    error_code = "INVALID_ALLOCATION"

    def __init__(self, reason: str, message: str | None = None):
        if message is None:
            if reason == "zero_points":
                message = "加点数量必须大于 0"
            elif reason == "insufficient":
                message = "属性点不足"
            elif reason == "unknown_attribute":
                message = "未知的加点属性"
            else:
                message = "无效的加点请求"
        super().__init__(message, reason=reason)


# ============ 其他异常 ============


class GuestOwnershipError(GuestError):
    """门客不属于当前庄园"""

    error_code = "GUEST_OWNERSHIP_ERROR"

    def __init__(self, guest: Any = None, message: str | None = None):
        if message is None:
            message = "该门客不属于您的庄园"
        super().__init__(message)


class GuestFullHpError(GuestError):
    """门客已满血"""

    error_code = "GUEST_FULL_HP"

    def __init__(self, guest: Any = None, message: str | None = None):
        guest_name = getattr(guest, "display_name", "门客") if guest else "门客"
        if message is None:
            message = f"{guest_name}已满血"
        super().__init__(message, guest_name=guest_name)


class InvalidHealAmountError(GuestError):
    """治疗量无效"""

    error_code = "INVALID_HEAL_AMOUNT"
    default_message = "药品未配置有效生命值"


class NoGuestsError(GuestError):
    """没有门客"""

    error_code = "NO_GUESTS"
    default_message = "您还没有门客"


class InsufficientStockError(ItemError):
    """物品库存不足"""

    error_code = "INSUFFICIENT_STOCK"

    def __init__(
        self,
        item_name: str,
        required: int,
        available: int,
        message: str | None = None,
    ):
        if message is None:
            message = f"{item_name}数量不足，需要 {required}，当前 {available}"
        super().__init__(
            message,
            item_name=item_name,
            required=required,
            available=available,
        )


class ItemNotConfiguredError(ItemError):
    """物品未配置奖励"""

    error_code = "ITEM_NOT_CONFIGURED"
    default_message = "物品未配置奖励"


class ItemNotUsableError(ItemError):
    """物品不可使用"""

    error_code = "ITEM_NOT_USABLE"

    def __init__(self, item_name: str | None = None, reason: str | None = None, message: str | None = None):
        if message is None:
            reason_messages = {
                "not_warehouse_usable": "此物品不可在仓库使用",
                "equip_in_guest_detail": "装备道具请在门客详情页为指定门客使用",
                "skill_book": "技能书请在门客详情页为指定门客使用",
                "experience_item": "经验道具请在门客详情页为指定门客使用",
                "medicine": "药品道具请在门客详情页为指定门客使用",
                "magnifying_glass": "放大镜请在候选区使用",
                "unknown_effect": "未知的道具效果",
            }
            message = reason_messages.get(reason, "此物品不可使用")
        super().__init__(message, item_name=item_name, reason=reason)


class BuildingNotFoundError(BuildingError):
    """建筑不存在"""

    error_code = "BUILDING_NOT_FOUND"

    def __init__(self, building_key: str, message: str | None = None):
        building_names = {
            "treasury": "藏宝阁",
            "juxianzhuang": "聚贤庄",
            "jiadingfang": "家丁房",
        }
        building_name = building_names.get(building_key, building_key)
        if message is None:
            message = f"{building_name}尚未建造"
        super().__init__(message, building_key=building_key)


class InsufficientSpaceError(CapacityError):
    """空间不足"""

    error_code = "INSUFFICIENT_SPACE"

    def __init__(
        self,
        location: str,
        available: int,
        required: int,
        message: str | None = None,
    ):
        location_names = {
            "treasury": "藏宝阁",
            "warehouse": "仓库",
        }
        location_name = location_names.get(location, location)
        if message is None:
            message = f"{location_name}空间不足，剩余空间：{available}，需要空间：{required}"
        super().__init__(
            message,
            location=location,
            available=available,
            required=required,
        )


class TechnologyUpgradeInProgressError(TechnologyError):
    """技术正在升级中"""

    error_code = "TECHNOLOGY_UPGRADE_IN_PROGRESS"

    def __init__(self, tech_key: str, tech_name: str, message: str | None = None):
        if message is None:
            message = f"{tech_name} 正在升级中"
        super().__init__(message, tech_key=tech_key, tech_name=tech_name)


class TechnologyConcurrentUpgradeLimitError(TechnologyError):
    """同时升级的技术数量超限"""

    error_code = "TECHNOLOGY_CONCURRENT_UPGRADE_LIMIT"

    def __init__(self, limit: int, message: str | None = None):
        if message is None:
            message = f"同时最多只能研究 {limit} 项科技"
        super().__init__(message, limit=limit)


class TechnologyMaxLevelError(TechnologyError):
    """技术已达最高等级"""

    error_code = "TECHNOLOGY_MAX_LEVEL"

    def __init__(self, tech_key: str, tech_name: str, max_level: int, message: str | None = None):
        if message is None:
            message = f"{tech_name} 已达到最高等级"
        super().__init__(message, tech_key=tech_key, tech_name=tech_name, max_level=max_level)


class NoAttachmentError(MessageError):
    """消息没有附件"""

    error_code = "NO_ATTACHMENT"
    default_message = "该消息没有附件"
