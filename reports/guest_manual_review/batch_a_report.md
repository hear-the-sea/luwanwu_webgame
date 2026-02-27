# 批次 A 审查记录

## 覆盖范围

- 文件数：10
- 门客总数：673
- 文件：
  - `data/guests/base.yaml`
  - `data/guests/gulong.yaml`
  - `data/guests/hermits.yaml`
  - `data/guests/huangyi.yaml`
  - `data/guests/jinyong.yaml`
  - `data/guests/liangyshen.yaml`
  - `data/guests/wenruian.yaml`
  - `data/guests/special.yaml`
  - `data/guests/original.yaml`
  - `data/guests/suitang.yaml`

## 发现并修复的问题

1. `jinyong.yaml` 存在明显文案污染
- 现象：出现“由于由于…”重复词串与“此处修正为”编辑痕迹。
- 处理：对相关条目进行人工重写与语义修复，删除编辑痕迹，统一可读性。

2. `jinyong.yaml` 性别字段遗留 `unknown`
- 现象：多名人物性别可明确判定，但字段仍为 `unknown`。
- 处理：人工核对后修正 36 条；保留 `hero_dongfang_bubai` 为 `unknown`（设定存在跨性别语义，暂不强行归类）。

3. `base.yaml` 文案过短
- 现象：8 条基础模板简介均低于 100 字。
- 处理：全部扩写并提升描述质量，修复格式小瑕疵。

## 回归结果

- `scripts/audit_guest_metadata.py --batch-size 200 --min-flavor-len 100`
  - 结果：`issues = 0`
- 异常模式扫描（重复词串/编辑痕迹）
  - 批次 A：未发现残留

## 备注

- 本批次以“先去噪、再人工重写、最后回归校验”为主。
- 下一批将按历史分段进入 `history_xianqin_* / history_qinhan_* / history_suitang_*` 的逐文件审查。
