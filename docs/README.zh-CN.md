# 文档中心

[English](README.md) · **简体中文**

PXEye 公开项目文档均提供内容对应的中英文版本。首次使用按“装机前检查 → 部署 PXEye → 首台装机”阅读；判断某项操作的原生映射和限制时阅读功能与架构。

| 文档 | English | 简体中文 | 用途 |
| --- | --- | --- | --- |
| 离线交付构建 | [Read](../offline-build/BUILD.md) | [阅读](../offline-build/BUILD.zh-CN.md) | 可复制的构建步骤、交付物、范围和交接边界。 |
| 离线包现场部署 | [Read](../offline-build/onsite/README.md) | [阅读](../offline-build/onsite/README.zh-CN.md) | 导入已校验交付包、冻结站点参数并支持断点安装。 |
| 装机前检查 | [Read](pre-installation-checklist.md) | [阅读](pre-installation-checklist.zh-CN.md) | 一句话一项，分发现、主机 OS 写入及受管 DPU 阶段检查。 |
| 现场 DHCP 快速检查 | [Read](dhcp-check.md) | [阅读](dhcp-check.zh-CN.md) | Make 单入口、无外部依赖的 Discover/Offer 检测及结果定位。 |
| 部署指南 | [Read](deployment.md) | [阅读](deployment.zh-CN.md) | 二进制、站点配置、凭据、挂载和持久化。 |
| NICo 集群部署 | [Read](nico-deployment.md) | [阅读](nico-deployment.zh-CN.md) | 独立启动 PXEye、在线/离线 Helm 部署、权限与站点连接。 |
| 首台装机 | [Read](getting-started.md) | [阅读](getting-started.zh-CN.md) | 从纳管到验收的首次单机流程。 |
| 功能与边界 | [Read](features.md) | [阅读](features.zh-CN.md) | 原生映射、设备能力和安装范围。 |
| 系统架构 | [Read](architecture.md) | [阅读](architecture.zh-CN.md) | 运行环境、模块职责和数据归属。 |
| 代码结构评审 | [Read](code-structure-review.md) | [阅读](code-structure-review.zh-CN.md) | 静态问题、优先级与建议的调整顺序。 |
| 参考集群 | [Read](reference-cluster.md) | [阅读](reference-cluster.zh-CN.md) | GB200 架构示例与截图生成。 |
| 文档设计参考 | [Read](documentation-references.md) | [阅读](documentation-references.zh-CN.md) | NetBox、Tinkerbell、Metal3、Argo CD 调研。 |
| 公开发布准备 | [Read](publishing.md) | [阅读](publishing.zh-CN.md) | 仓库边界与发布职责。 |

## 页面使用指南

按菜单查阅页面作用、字段填写、操作步骤和结果确认；每个大页面单独维护，统一结构见[页面使用指南索引](user-guide/README.zh-CN.md)。

| 菜单位置 | English | 简体中文 |
| --- | --- | --- |
| 总览 → 机柜拓扑 | [Read](user-guide/rack-topology.md) | [阅读](user-guide/rack-topology.zh-CN.md) |
| 装机 → 安装任务 | [Read](user-guide/installation-tasks.md) | [阅读](user-guide/installation-tasks.zh-CN.md) |
| 资源 → 设备管理 / 网卡信息 | [Read](user-guide/device-management.md) | [阅读](user-guide/device-management.zh-CN.md) |
| 资源 → 实例管理 | [Read](user-guide/instance-management.md) | [阅读](user-guide/instance-management.zh-CN.md) |
| 资源 → 操作系统 | [Read](user-guide/operating-systems.md) | [阅读](user-guide/operating-systems.zh-CN.md) |
| 资源 → 网络管理 | [Read](user-guide/network-management.md) | [阅读](user-guide/network-management.zh-CN.md) |
| 配置 → 安装方案 | [Read](user-guide/installation-profiles.md) | [阅读](user-guide/installation-profiles.zh-CN.md) |
| 配置 → 站点设置 | [Read](user-guide/site-settings.md) | [阅读](user-guide/site-settings.zh-CN.md) |
| 配置 → NICo 集群 | [Read](user-guide/nico-cluster.md) | [阅读](user-guide/nico-cluster.zh-CN.md) |

## 项目维护

| 文档 | English | 简体中文 |
| --- | --- | --- |
| 项目介绍 | [Read](../README.md) | [阅读](../README.zh-CN.md) |
| 贡献指南 | [Read](../CONTRIBUTING.md) | [阅读](../CONTRIBUTING.zh-CN.md) |
| 安全说明 | [Read](../SECURITY.md) | [阅读](../SECURITY.zh-CN.md) |
| 变更记录 | [Read](../CHANGELOG.md) | [阅读](../CHANGELOG.zh-CN.md) |
| 运行工具 | [Read](../bin/README.md) | [阅读](../bin/README.zh-CN.md) |

命令、字段和路径在两种语言中保留原始技术拼写。当前产品界面为简体中文，双语文档不表示已有界面国际化能力。历史现场记录与上游文档保留在开发工作区，不属于公开 PXEye 文档。
