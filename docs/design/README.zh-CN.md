# 设计文档

[English](README.md) · **简体中文** · [文档中心](../README.zh-CN.md)

这里放解释“为什么这样做、做到哪里为止”的文档：产品范围、系统设计、交互规则，以及页面和 NICo 之间的数据契约。怎么操作页面见[页面使用指南](../user-guide/README.zh-CN.md)，怎么部署和构建见[文档中心](../README.zh-CN.md)。

## 文档

| 文档 | English | 简体中文 | 回答的问题 |
| --- | --- | --- | --- |
| 功能与边界 | [Read](features.md) | [阅读](features.zh-CN.md) | 每个功能对应 NICo 的什么，支持到哪里 |
| 系统架构 | [Read](architecture.md) | [阅读](architecture.zh-CN.md) | 运行环境、模块职责、数据归谁 |
| 交互规则 | [Read](interaction-rules.md) | [阅读](interaction-rules.zh-CN.md) | 页面、文案、状态和危险操作怎么设计 |
| 机柜运维：能力需求 | [Read](rack-operations-requirements.md) | [阅读](rack-operations-requirements.zh-CN.md) | 机柜级管理的目标能力全貌，以及每个功能域的实现状态。长期维护，设计变更同步到这里 |
| 机柜运维：范围与现状 | [Read](rack-operations.md) | [阅读](rack-operations.zh-CN.md) | 机柜方向做什么、不做什么、做到哪一步 |
| 机柜运维：操作类功能规则 | [Read](rack-operations-actions.md) | [阅读](rack-operations-actions.zh-CN.md) | PXEye 提供哪些 NICo 操作、哪些需要 RMS、NICo 不提供什么，以及预览、确认、执行和审计的规则 |
| 机柜运维：NICo 数据契约 | [Read](rack-operations-data-contract.md) | [阅读](rack-operations-data-contract.zh-CN.md) | 每个页面用 Core 的哪个接口和字段，哪些已在真实站点验证 |
| 代码结构评审 | [Read](code-structure-review.md) | [阅读](code-structure-review.zh-CN.md) | 历史静态问题和已完成的调整 |
| 文档设计参考 | [Read](documentation-references.md) | [阅读](documentation-references.zh-CN.md) | 文档结构参考了哪些项目 |

## 各类内容放在哪

| 内容 | 位置 | 说明 |
| --- | --- | --- |
| 设计文档 | `docs/design/` | 本目录。一个主题一份文档，写现行结论，不按日期追加过程 |
| 交互规则 | `docs/design/interaction-rules*.md` | 界面和文案的统一规则，只有这一份 |
| 页面使用指南 | `docs/user-guide/` | 一个菜单页面一份，文件名与菜单对应 |
| 现场采集 | `docs/field-survey/` | 每个机柜运维页面一份：现场用哪些命令行和接口、怎么核对、需要用户补充什么 |
| 部署、构建、现场操作 | `docs/` 根目录 | 面向操作的步骤说明 |
| AI 协作规则 | 各目录的 `AGENTS.md` | 根目录管仓库流程；`src/pxeye/AGENTS.md` 管代码；`docs/AGENTS.md` 管文档 |
| 人的贡献流程 | `CONTRIBUTING*.md` | 提交、检查、报告的要求 |
| 现场记录、过程评审、带站点信息的材料 | 仓库之外 | 不进入本仓库 |

## 命名

- 文件名用英文小写加连字符，以主题开头，如 `rack-operations-data-contract.md`。不加产品名前缀，不加日期和版本号。
- 每份文档两个文件：`<名称>.md`（英文）和 `<名称>.zh-CN.md`（简体中文），内容对应，互相链接。
- 同一主题的多份文档共用前缀，如 `rack-operations` 和 `rack-operations-data-contract`。
- 代码里同一个功能只用一个名字，后端模块、接口路径、前端脚本、状态和测试保持一致，如 `device_status.py`、`/api/device-status`、`device_status.js`。
- 文档不出现站点地址、序列号、凭据和个人名称；需要举例时用占位值。
