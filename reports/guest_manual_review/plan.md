# 门客全量人工审查计划

目标：对 `data/guests/*.yaml` 全量门客进行分批人工审查，覆盖文案质量、字段一致性、来源标注、性别准确性与可维护性。

## 审查标准

- 文案可读性：避免模板化、重复句、编辑痕迹、机器噪声（如“由于由于…”）。
- 信息完整度：简介保持足够信息量，重点门客文案不低于 100 字。
- 字段一致性：`default_gender`、`source` 语义与人物设定一致。
- 数据稳定性：YAML 结构可解析，无格式损坏。
- 回归校验：`scripts/audit_guest_metadata.py --min-flavor-len 100` 通过。

## 批次划分

- 批次 A（已完成）：`base.yaml`、`gulong.yaml`、`hermits.yaml`、`huangyi.yaml`、`jinyong.yaml`、`liangyshen.yaml`、`wenruian.yaml`、`special.yaml`、`original.yaml`、`suitang.yaml`
- 批次 B（已完成）：历史系 `history_xianqin_*`、`history_qinhan_*`、`history_suitang_*`
- 批次 C（已完成）：历史系 `history_songliaojinyuan_*`、`history_sljnbc_*`、`history_mingqing_*`

## 当前进度

- 批次 A：完成
- 批次 B：完成（全量异常扫描 + 复检）
- 批次 C：完成（重复句去同构 + 全量复检）

## 阶段性结论

- 当前全量审计结果：`issues = 0`
- 当前数据解析结果：64 个 guest YAML 全部可解析
- 非来源高频重复句（阈值 `>=3`）结果：`0`
