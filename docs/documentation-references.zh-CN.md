# 文档设计参考

[English](documentation-references.md) · **简体中文** · [文档中心](README.zh-CN.md)

查阅日期：**2026-11-07**。以下是上游公开文档参考，不代表 PXEye 实现了这些项目的能力。分支页面会变化，本次结论以查阅时内容为准。未复制其他项目的介绍正文、截图或徽章。

## 采用的组织方式

| 参考项目 | 公开文档的特点 | PXEye 的应用 |
| --- | --- | --- |
| [NetBox README](https://github.com/netbox-community/netbox/blob/main/README.md) | 先明确产品定位和事实来源边界，再串联功能、入门和机柜/网络截图。 | 前置 NICo 与 PXEye 的数据归属，先展示真实产品页面，再介绍实现。 |
| [Tinkerbell README](https://github.com/tinkerbell/tinkerbell/blob/main/README.md) | 先说明装机用途和网络/ISO/BMC 能力，治理、贡献、安全分别设入口。 | 介绍保持聚焦，部署前提和治理独立成文。 |
| [Metal3 Bare Metal Operator](https://github.com/metal3-io/baremetal-operator/blob/main/README.md) | 把清单资源与检查、装机、清理对应起来，并链接 API 与部署指南。 | 模块对应原生资源，明确发现、站点清理与 OS 安装的区别。 |
| [Argo CD README](https://github.com/argoproj/argo-cd/blob/master/README.md) | 先说明是什么、为什么，再提供完整文档和社区入口。 | README 围绕定位、价值、流程和操作指南入口组织。 |

NetBox 的职责划分帮助我们区分规划与设备实际状态。PXEye 还会执行硬件操作，因此需要说明从保存规划到确认写入、再到读回验证的转换。

Tinkerbell 和 Metal3 将启动、硬件检查和清理写成具体能力，而不是笼统描述自动化。PXEye 同样将 Scout 准备与无人值守 OS 安装分开。Argo CD 的介绍结构帮助把部署命令和实现细节移出开篇的价值说明。

## 最终文档层次

- README：定位、产品截图、核心能力、操作流程、入门入口和支持范围。
- 快速开始：完整首次单机路径，使用可对应页面的操作名称。
- 功能说明：实际作用、资源边界、硬件与网络前提。
- 架构：数据归属、模块、执行逻辑和版本兼容。
- 部署：配置、准确凭据文件名、挂载、发布路径和持久化。
- 参考集群：截图数据来源和可重复生成的方法。
- 贡献、安全、发布准备：项目维护责任。

每份公开文档提供内容意图一致的中英文版本，命令、字段和文件名保留技术原文。截图使用同一份数据，并注明为界面示例。不编造正式发布版本、许可证、CI 徽章、用户案例或生产能力。

## 技术参考

NICo [模板化 iPXE](https://docs.nvidia.com/infra-controller/documentation/configuration-day-1/templated-i-pxe-operating-systems)、[网络配置](https://docs.nvidia.com/infra-controller/documentation/provisioning-day-0/ip-and-network-configuration)和 [Rack 状态机](https://docs.nvidia.com/infra-controller/documentation/architecture/state-machines/rack-machine-switch-power-shelf)用于核对原生术语。[参考集群](reference-cluster.zh-CN.md)列明硬件架构来源。在线资料仍需与集成 Core 版本核对。
