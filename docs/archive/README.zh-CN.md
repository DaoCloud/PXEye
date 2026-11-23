# 归档文档

[English](README.md) · **简体中文** · [文档中心](../README.zh-CN.md)

这里放被取代、不再维护的文档。归档的文档保留归档时的原样，只做两处改动：顶部加一行归档说明，相对链接改到新位置。它们不是现行设计，不要据此开发新功能。

## 规则

- 一批归档一个目录，目录内保留原来的相对结构。
- 归档的文档不再更新。要引用其中仍然有效的内容，把它写进现行文档，不要回头修改归档。
- 不删除归档。历史版本同时保留在 Git 里。

## rack-operations-v1（2026-11-23 归档）

机柜运维方向的第一版设计：在“设备管理”下增加服务器、交换机、供电框、告警、布线、发现诊断、机柜、操作记录八个页面。它被面向 GB200 / GB300 整机柜的新设计取代，现行设计见[设计文档](../design/README.zh-CN.md)。

归档原因：新设计改变了菜单、页面划分和操作方式，这些文档描述的页面归属和规则不再适用。

仍然有参考价值的内容：

- 本分支的应用代码目前仍是第一版的页面。在新设计实现之前，这些文档仍然是现有代码行为的说明。
- 数据契约里“已验证”的 Core 接口和字段是在真实站点上读到的事实，与页面设计无关，实现新页面时仍可参考。
- 现场采集用到的工具（`tools/site-survey.sh`、`tools/core-survey.py`、`tools/core-capture.py`、`tools/core-replay.py`）仍在仓库里，采集与回放的方法没有变。

| 文档 | English | 简体中文 | 内容 |
| --- | --- | --- | --- |
| 机柜运维：能力需求 | [Read](rack-operations-v1/design/rack-operations-requirements.md) | [阅读](rack-operations-v1/design/rack-operations-requirements.zh-CN.md) | 目标能力与各功能域的实现状态 |
| 机柜运维：范围与现状 | [Read](rack-operations-v1/design/rack-operations.md) | [阅读](rack-operations-v1/design/rack-operations.zh-CN.md) | 八个只读页面的范围、规则和分期 |
| 机柜运维：操作类功能规则 | [Read](rack-operations-v1/design/rack-operations-actions.md) | [阅读](rack-operations-v1/design/rack-operations-actions.zh-CN.md) | 操作目录、需要 RMS 的操作、预览与审计规则 |
| 机柜运维：NICo 数据契约 | [Read](rack-operations-v1/design/rack-operations-data-contract.md) | [阅读](rack-operations-v1/design/rack-operations-data-contract.zh-CN.md) | 各页面使用的 Core 接口和字段及验证标记 |
| 交互规则 | [Read](rack-operations-v1/design/interaction-rules.md) | [阅读](rack-operations-v1/design/interaction-rules.zh-CN.md) | 页面归属、文案、状态、危险操作的规则 |
| 代码结构评审 | [Read](rack-operations-v1/design/code-structure-review.md) | [阅读](rack-operations-v1/design/code-structure-review.zh-CN.md) | 历史静态问题和已完成的调整 |
| 文档设计参考 | [Read](rack-operations-v1/design/documentation-references.md) | [阅读](rack-operations-v1/design/documentation-references.zh-CN.md) | 文档结构参考过的项目 |
| 现场采集指南（含七个页面） | [Read](rack-operations-v1/field-survey/README.md) | [阅读](rack-operations-v1/field-survey/README.zh-CN.md) | 到站点后每个页面用哪些命令和接口采集、怎么核对 |
