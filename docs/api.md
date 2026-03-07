# 春秋乱世庄园主 - API 接口文档

## 概述

本文档描述了"春秋乱世庄园主"游戏的所有 HTTP 接口。所有需要认证的接口都需要用户登录后访问。

### 通用说明

- **认证方式**: Session 认证（Django 默认）
- **内容类型**: 大部分接口使用表单提交 (`application/x-www-form-urlencoded`)
- **错误处理**: 错误信息通过 Django Messages 框架返回，重定向到相关页面
- **CSRF**: 所有 POST 请求需要携带 CSRF Token

### 速率限制

| 类型 | 限制 |
|------|------|
| 匿名用户 | 100 请求/小时 |
| 认证用户 | 1000 请求/小时 |
| 门客招募 | 20 次/小时 |
| 战斗/任务 | 100 次/小时 |
| 附件领取 | 50 次/小时 |

---

## 账户模块 (`/accounts/`)

### 登录

```
POST /accounts/login/
```

**表单参数:**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| username | string | 是 | 用户名 |
| password | string | 是 | 密码 |

**成功响应:** 重定向到首页，设置 Session

**特性:** 自动登出其他设备（单点登录）

---

### 注册

```
POST /accounts/register/
```

**表单参数:**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| username | string | 是 | 用户名 |
| password1 | string | 是 | 密码 |
| password2 | string | 是 | 确认密码 |

**成功响应:** 自动登录并重定向到首页

---

### 用户资料

```
GET /accounts/profile/
```

**需要认证:** 是

**响应:** 渲染用户资料页面

---

## 庄园模块 (`/manor/`)

### 仪表盘

```
GET /manor/
```

**需要认证:** 是

**响应内容:**
- 资源状态（木材、石料、铁矿、粮食、银两）
- 建筑列表及状态
- 最近资源事件
- 进行中的任务

---

### 建筑升级

```
POST /manor/building/{pk}/upgrade/
```

**需要认证:** 是

**路径参数:**
| 参数 | 类型 | 说明 |
|------|------|------|
| pk | int | 建筑实例 ID |

**响应:** 重定向到仪表盘，显示升级进度

**错误情况:**
- 资源不足
- 正在升级中
- 建筑不属于当前用户

---

### 任务面板

```
GET /manor/tasks/
```

**需要认证:** 是

**查询参数:**
| 参数 | 类型 | 说明 |
|------|------|------|
| mission | string | 选中的任务 key |

**响应内容:**
- 任务列表及每日剩余次数
- 可出征门客
- 兵种配置选项
- 进行中的任务

---

### 接受任务/出征

```
POST /manor/tasks/accept/
```

**需要认证:** 是

**表单参数:**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| mission_key | string | 是 | 任务标识 |
| guest_ids | int[] | 是 | 出征门客 ID 列表 |
| troop_{key} | int | 否 | 各兵种数量 |

**响应:** 重定向到任务面板

**验证规则:**
- 门客数量不超过出战上限（默认 5，可升级至 15）
- 总兵力不超过门客带兵上限（基础值 + 等级门槛加成 + 装备/套装加成）
- 门客状态必须为空闲
- 今日任务次数未用尽

---

### 撤退任务

```
POST /manor/missions/{pk}/retreat/
```

**需要认证:** 是

**路径参数:**
| 参数 | 类型 | 说明 |
|------|------|------|
| pk | int | MissionRun ID |

**响应:** 重定向到仪表盘

**说明:** 只能在战斗开始前撤退

---

### 仓库

```
GET /manor/warehouse/
```

**需要认证:** 是

**查询参数:**
| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| tab | string | warehouse | warehouse/treasury |
| category | string | all | 物品分类筛选 |

**响应内容:**
- 物品列表（按存储位置分离）
- 分类筛选选项
- 藏宝阁容量（treasury 标签）

---

### 使用物品

```
POST /manor/warehouse/use/{pk}/
```

**需要认证:** 是

**路径参数:**
| 参数 | 类型 | 说明 |
|------|------|------|
| pk | int | InventoryItem ID |

**响应:** 重定向到仓库页

**支持物品类型:**
- `resource_pack`: 资源补给包
- 其他类型需在特定场景使用

---

### 移动物品到藏宝阁

```
POST /manor/warehouse/move-to-treasury/{pk}/
```

**需要认证:** 是

**表单参数:**
| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| quantity | int | 1 | 移动数量 |

---

### 移动物品到仓库

```
POST /manor/warehouse/move-to-warehouse/{pk}/
```

**需要认证:** 是

**表单参数:**
| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| quantity | int | 1 | 移动数量 |

---

### 消息中心

```
GET /manor/messages/
```

**需要认证:** 是

**响应内容:**
- 消息列表
- 未读消息数量

---

### 查看消息

```
GET /manor/messages/view/{pk}/
```

**需要认证:** 是

**响应:**
- 战报类型：重定向到战报详情
- 其他类型：渲染消息详情页
- AJAX 请求：返回 JSON 格式

**JSON 响应示例:**
```json
{
  "success": true,
  "message_id": 123,
  "was_unread": true,
  "unread_count": 5,
  "redirect_url": "/battle/report/456/"  // 仅战报消息
}
```

---

### 领取附件

```
POST /manor/messages/{pk}/claim/
```

**需要认证:** 是

**响应:** 重定向到消息页或消息详情页

---

### 删除消息

```
POST /manor/messages/delete/
```

**表单参数:**
| 参数 | 类型 | 说明 |
|------|------|------|
| message_ids | int[] | 消息 ID 列表 |

---

### 删除所有消息

```
POST /manor/messages/delete-all/
```

---

### 标记消息已读

```
POST /manor/messages/mark/
```

**表单参数:**
| 参数 | 类型 | 说明 |
|------|------|------|
| message_ids | int[] | 消息 ID 列表 |

---

### 标记所有消息已读

```
POST /manor/messages/mark-all/
```

---

### 招募大厅

```
GET /manor/recruitment/
```

**需要认证:** 是

**响应内容:**
- 卡池列表
- 候选门客
- 招募记录
- 门客列表及容量
- 可用装备

---

### 科技研究

```
GET /manor/technology/
```

**需要认证:** 是

**查询参数:**
| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| tab | string | basic | basic/martial/production |

**响应内容:**
- 科技列表及当前等级
- 升级所需资源
- 科技效果说明

---

### 升级科技

```
POST /manor/technology/upgrade/{tech_key}/
```

**需要认证:** 是

**表单参数:**
| 参数 | 类型 | 说明 |
|------|------|------|
| tab | string | 当前标签页 |

---

### 打工系统

```
GET /manor/work/
```

**需要认证:** 是

**查询参数:**
| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| tier | string | junior | junior/intermediate/senior |

**响应内容:**
- 工作区列表
- 空闲门客
- 进行中/可领取的打工记录

---

### 派遣打工

```
POST /manor/work/assign/
```

**表单参数:**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| guest_id | int | 是 | 门客 ID |
| work_key | string | 是 | 工作标识 |

---

### 召回门客

```
POST /manor/work/recall/{pk}/
```

**说明:** 无报酬召回

---

### 领取打工报酬

```
POST /manor/work/claim/{pk}/
```

---

## 门客模块 (`/guests/`)

### 门客列表

```
GET /guests/
```

**需要认证:** 是

**响应内容:**
- 门客列表（含工资信息）
- 经验道具
- 药品道具
- 今日未发工资统计

---

### 门客详情

```
GET /guests/{pk}/
```

**需要认证:** 是

**响应内容:**
- 门客属性及状态
- 装备槽位及选项
- 技能槽位
- 技能书列表
- 套装信息

---

### 辞退门客

```
POST /guests/{pk}/dismiss/
```

**说明:** 装备自动返还仓库

---

### 招募门客

```
POST /guests/recruit/
```

**表单参数:**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| pool | int | 是 | 卡池 ID |

**响应:** 生成候选门客，重定向到招募大厅

---

### 培养门客

```
POST /guests/train/
```

**表单参数:**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| guest | int | 是 | 门客 ID |
| levels | int | 是 | 升级等级数 |
| next | string | 否 | 返回 URL |

---

### 装备/卸装

```
POST /guests/equip/
```

**表单参数:**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| gear | int | 是 | 装备实例 ID |
| guest | int | 是 | 门客 ID |

```
POST /guests/unequip/
```

**表单参数:**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| guest | int | 是 | 门客 ID |
| gear | int[] | 是 | 装备实例 ID 列表 |

---

### 技能点分配

```
POST /guests/{pk}/allocate-points/
```

**表单参数:**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| guest | int | 是 | 门客 ID |
| attribute | string | 是 | force/intellect/defense_stat/agility/luck |
| points | int | 是 | 分配点数 |

---

### 学习/遗忘技能

```
POST /guests/{pk}/learn-skill/
```

**表单参数:**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| item_id | int | 是 | 技能书物品 ID |

```
POST /guests/{pk}/forget-skill/
```

**表单参数:**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| guest_skill_id | int | 是 | GuestSkill ID |

---

### 使用经验道具

```
POST /guests/{pk}/use-exp-item/
```

**表单参数:**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| item_id | int | 是 | 经验道具 ID |

**说明:** 缩短培养时间

---

### 使用药品

```
POST /guests/{pk}/use-medicine/
```

**表单参数:**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| item_id | int | 是 | 药品 ID |

**说明:** 恢复生命值，可解除重伤状态

---

### 候选门客操作

```
POST /guests/candidates/accept/
```

**表单参数:**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| candidate_ids | int[] | 是 | 候选 ID 列表 |
| action | string | 否 | accept(默认)/discard/retain |

**action 说明:**
- `accept`: 正式招募为门客
- `discard`: 放弃候选
- `retain`: 收为家丁（消耗家丁容量）

---

### 使用放大镜

```
POST /guests/candidates/reveal/
```

**表单参数:**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| item_id | int | 是 | 放大镜道具 ID |

**说明:** 显现所有候选门客的稀有度

---

### 支付工资

```
POST /guests/{pk}/pay-salary/
```

**说明:** 支付单个门客当日工资

```
POST /guests/pay-all-salaries/
```

**说明:** 一键支付所有门客工资

---

## 战斗模块 (`/battle/`)

### 战报详情

```
GET /battle/report/{pk}/
```

**需要认证:** 是

**响应内容:**
- 攻守双方门客及兵种
- 回合详细记录
- 战斗结果及掉落

---

## 交易模块 (`/trade/`)

### 交易主页

```
GET /trade/
```

**需要认证:** 是

**查询参数:**
| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| tab | string | shop | bank/shop/market |

#### Shop 标签
| 参数 | 类型 | 说明 |
|------|------|------|
| category | string | 物品分类 |

#### Market 标签
| 参数 | 类型 | 说明 |
|------|------|------|
| view | string | buy/sell/my_listings |
| category | string | 分类筛选 |
| rarity | string | 稀有度筛选 |
| order_by | string | 排序方式 |
| page | int | 分页 |

---

### 商店购买

```
POST /trade/shop/buy/
```

**表单参数:**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| item_key | string | 是 | 物品标识 |
| quantity | int | 否 | 数量（默认 1） |

---

### 商店出售

```
POST /trade/shop/sell/
```

**表单参数:**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| item_key | string | 是 | 物品标识 |
| quantity | int | 否 | 数量（默认 1） |

---

### 兑换金条

```
POST /trade/bank/exchange-gold-bar/
```

**表单参数:**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| quantity | int | 否 | 数量（默认 1） |

**说明:** 每日限额，收取手续费

---

### 交易行上架

```
POST /trade/market/create/
```

**表单参数:**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| item_key | string | 是 | 物品标识 |
| quantity | int | 是 | 数量 |
| unit_price | int | 是 | 单价 |
| duration | int | 否 | 上架时长（秒，默认 7200） |

---

### 交易行购买

```
POST /trade/market/purchase/{listing_id}/
```

**说明:** 物品通过邮件发送

---

### 取消上架

```
POST /trade/market/cancel/{listing_id}/
```

**说明:** 物品退回仓库

---

## 帮会模块 (`/guilds/`)

### 帮会大厅

```
GET /guilds/
```

**需要认证:** 是

**响应:**
- 已加入帮会：重定向到帮会详情
- 未加入：显示帮会列表

---

### 帮会列表

```
GET /guilds/list/
```

**查询参数:**
| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| ordering | string | -level | 排序方式 |
| search | string | | 搜索关键词 |
| page | int | 1 | 分页 |

---

### 搜索帮会

```
GET /guilds/search/
```

**查询参数:**
| 参数 | 类型 | 说明 |
|------|------|------|
| q | string | 搜索关键词 |

---

### 创建帮会

```
GET/POST /guilds/create/
```

**表单参数:**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| name | string | 是 | 帮会名称 |
| description | string | 否 | 帮会描述 |
| emblem | string | 否 | 帮徽（默认 default） |

**创建费用:** 消耗金条

---

### 帮会详情

```
GET /guilds/{guild_id}/
```

**响应内容:**
- 帮会基本信息
- 帮主及管理员
- 成员列表
- 公告
- 科技信息（仅成员可见）

---

### 帮会设置

```
GET/POST /guilds/{guild_id}/info/
```

**需要权限:** 帮主

**表单参数:**
| 参数 | 类型 | 说明 |
|------|------|------|
| description | string | 帮会描述 |
| auto_accept | bool | 自动接受申请 |

---

### 申请加入

```
GET/POST /guilds/{guild_id}/apply/
```

**表单参数:**
| 参数 | 类型 | 说明 |
|------|------|------|
| message | string | 申请留言 |

---

### 申请列表

```
GET /guilds/applications/
```

**需要权限:** 管理员或帮主

---

### 审批申请

```
POST /guilds/application/{app_id}/approve/
POST /guilds/application/{app_id}/reject/
```

**reject 表单参数:**
| 参数 | 类型 | 说明 |
|------|------|------|
| note | string | 拒绝理由 |

---

### 成员管理

```
GET /guilds/members/
```

**成员操作:**
```
POST /guilds/member/{member_id}/kick/      # 辞退成员
POST /guilds/member/{member_id}/appoint/   # 任命管理员
POST /guilds/member/{member_id}/demote/    # 罢免管理员
POST /guilds/member/{member_id}/transfer/  # 转让帮主
POST /guilds/leave/                        # 退出帮会
```

---

### 帮会升级/解散

```
POST /guilds/upgrade/
```

```
POST /guilds/disband/
```

**表单参数:**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| confirm_name | string | 是 | 输入帮会名称确认 |

---

### 捐赠系统

```
GET/POST /guilds/donate/
```

**表单参数:**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| resource_type | string | 是 | 资源类型 |
| amount | int | 是 | 捐赠数量 |

```
GET /guilds/contribution/ranking/
```

**查询参数:**
| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| type | string | total | total/weekly |
| page | int | 1 | 分页 |

---

### 帮会科技

```
GET /guilds/technology/
POST /guilds/technology/{tech_key}/upgrade/
```

---

### 帮会仓库

```
GET /guilds/warehouse/
POST /guilds/warehouse/{item_key}/exchange/
```

**表单参数:**
| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| quantity | int | 1 | 兑换数量 |

```
GET /guilds/warehouse/logs/
```

---

### 帮会公告

```
GET /guilds/announcements/
POST /guilds/announcement/create/
```

**需要权限:** 帮主

**表单参数:**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| content | string | 是 | 公告内容 |

---

### 帮会日志

```
GET /guilds/resources/          # 资源状态
GET /guilds/logs/donation/      # 捐赠日志
GET /guilds/logs/resource/      # 资源流水
```

---

## 战斗调试器 (`/debugger/`)

此模块仅用于开发测试，请参考 `battle_debugger` 应用代码。

---

## 错误码说明

| 状态码 | 说明 |
|--------|------|
| 302 | 重定向（成功或失败后跳转） |
| 403 | 权限不足 |
| 404 | 资源不存在 |
| 429 | 请求频率超限 |

错误信息通过 Django Messages 框架传递，在页面上以 Toast/Alert 形式展示。

---

## WebSocket 接口

游戏使用 Django Channels 提供实时通信功能。

### 连接地址

```
ws://{host}/ws/notifications/
```

### 消息类型

| 类型 | 说明 |
|------|------|
| resource_update | 资源变更通知 |
| battle_complete | 战斗完成通知 |
| message_new | 新消息通知 |

---

## 附录：稀有度定义

| 等级 | 标识 | 颜色 |
|------|------|------|
| 1 | black | 黑 |
| 2 | gray | 灰 |
| 3 | green | 绿 |
| 4 | blue | 蓝 |
| 5 | red | 红 |
| 6 | purple | 紫 |
| 7 | orange | 橙 |

---

## 附录：门客状态

| 状态 | 说明 |
|------|------|
| idle | 空闲，可出征/打工 |
| working | 打工中 |
| deployed | 出征中 |
| injured | 重伤，需药品治疗 |

---

## 附录：资源类型

| 标识 | 名称 |
|------|------|
| wood | 木材 |
| stone | 石料 |
| iron | 铁矿 |
| grain | 粮食 |
| silver | 银两 |
