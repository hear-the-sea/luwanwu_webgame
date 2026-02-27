# 批次 B/C 审查记录

## 覆盖范围

- 批次 B：
  - `history_xianqin_*.yaml`
  - `history_qinhan_*.yaml`
  - `history_suitang_*.yaml`
- 批次 C：
  - `history_songliaojinyuan_*.yaml`
  - `history_sljnbc_*.yaml`
  - `history_mingqing_*.yaml`

## 审查与优化动作

1. 全量异常文本扫描
- 检查项：重复词串、编辑痕迹、异常模板句式、重复收束句。
- 结果：B/C 未发现结构性噪声；发现并处理宋辽金元分卷中 6 条重复收束句。

2. 文案去同构
- 对 `history_songliaojinyuan_05.yaml`、`history_songliaojinyuan_06.yaml`、`history_songliaojinyuan_10.yaml` 的 6 条绿卡文案进行定向重写。
- 目标：降低批量生成痕迹，提升人物结尾句差异度。

3. 全量回归
- `scripts/audit_guest_metadata.py --batch-size 200 --min-flavor-len 100`
  - 结果：`issues = 0`
- 全体 guest YAML 可解析性校验
  - 结果：全部通过
- 非来源高频重复句（阈值 >=3）
  - 结果：`0`

## 结论

- B/C 当前无阻断性数据问题。
- 当前门客库在字段一致性、长度约束与模板化控制方面已达到可持续维护状态。
