# 战斗调试器 - 网页指南

> 最近校正：2026-03-23

## 启用条件

`battle_debugger` 不是默认常驻模块。只有同时满足以下条件时，路由才会挂到 `/debugger/`：

- `DJANGO_DEBUG=1`
- `DJANGO_ENABLE_DEBUGGER=1`

并且访问者必须：

- 已登录
- 是 staff 用户

## 启动方式

```bash
export DJANGO_DEBUG=1
export DJANGO_ENABLE_DEBUGGER=1
make dev
```

访问：

```text
http://127.0.0.1:8000/debugger/
```

## 当前页面

| 路径 | 说明 |
|------|------|
| `/debugger/` | 首页，列出预设与工具入口 |
| `/debugger/simulate/` | 基于预设运行战斗模拟 |
| `/debugger/custom/` | 手工配置攻守双方门客、兵种与参数 |
| `/debugger/tune/` | 对单个参数做多值对比 |
| `/debugger/presets/<preset_name>/` | 查看预设详情 |
| `/debugger/result/<result_id>/` | 查看模拟结果 |

辅助 JSON 接口：

- `/debugger/api/guests/`
- `/debugger/api/skills/`
- `/debugger/api/troops/`

## 功能边界

### 1. 战斗模拟

- 从预设加载战斗配置
- 支持覆盖 tunable 参数
- 支持固定随机种子复现
- 单次提交最大重复次数为 `100`

### 2. 自定义配置

- 前端表单动态装配攻守双方门客与兵种
- 依赖 `/debugger/api/*` 三个接口拉取候选数据

### 3. 参数调优

- 对单个参数输入多组候选值
- 结果页包含图表展示
- 图表依赖 `Chart.js` CDN

## 结果缓存

- 结果保存在 Django cache
- 默认缓存时长：`3600` 秒
- 缓存失效后，结果页会提示“结果不存在或已过期”

## 实现说明

- 后端入口：`battle_debugger/views.py`
- 路由定义：`battle_debugger/urls.py`
- 预设目录：`battle_debugger/presets/`
- 核心执行器：`battle_debugger/simulator.py`

当前页面样式基于项目现有 `base.html`、自定义 CSS 变量与部分 `tw-*` 样式类，不是 Bootstrap 页面。

## 使用建议

- 复现问题时优先固定随机种子
- 做参数趋势比较时再提高重复次数
- 如果图表页加载异常，先排查外网是否能访问 `Chart.js` CDN
