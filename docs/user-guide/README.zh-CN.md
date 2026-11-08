# 页面使用指南

[English](README.md) · **简体中文** · [文档中心](../README.zh-CN.md)

每个大菜单页对应一份指南，先介绍用途，再说明如何填写和操作。

| 菜单 | 指南 | 用途 |
| --- | --- | --- |
| 总览 → 机柜拓扑 | [机柜拓扑](rack-topology.zh-CN.md) | 机柜分组、设备定位与排列 |
| 装机 → 安装任务 | [安装任务](installation-tasks.zh-CN.md) | 选择设备、执行安装与查看结果 |
| 资源 → 设备管理 | [设备管理](device-management.zh-CN.md) | 规划导入、发现纳管、地址与系统配置 |
| 资源 → 实例管理 | [实例管理](instance-management.zh-CN.md) | 实例查询与退租回收 |
| 资源 → 操作系统 | [操作系统](operating-systems.zh-CN.md) | 导入 ISO、准备与启用 OS |
| 资源 → 网络管理 | [网络管理](network-management.zh-CN.md) | 子网创建、地址保留与 DHCP 前提 |
| 配置 → 安装方案 | [安装方案](installation-profiles.zh-CN.md) | OS、选盘、分区与登录默认值 |
| 配置 → 站点设置 | [站点设置](site-settings.zh-CN.md) | 连接、存储与安装并发 |
| 配置 → NICo 集群 | [NICo 集群](nico-cluster.zh-CN.md) | Helm 部署、服务状态与站点连接 |

## 编写约定

- 文件统一放在 `docs/user-guide/`，使用稳定英文名称，例如 `network-management.md`。
- 每页配套 `.zh-CN.md` 中文版，内容对应并互相链接。
- 统一五部分：**用途与入口 → 字段填写 → 操作步骤 → 填写示例 → 注意事项**。参考链接放在文末。
- 字段用表格，步骤用编号；只保留完成操作需要的信息，详细原理链接到参考文档。
- 示例使用虚构数据；新增页面同步更新本索引和文档中心。
- 面向用户的指南只写功能、操作和必要限制；源码核对、提交编号及编写者验证记录保存在内部维护资料中。
- 前置条件写明需要具备的配置和连通性，使用通用表述，不按组织或团队分配职责。

## 网站索引

指南顶部使用通用 YAML 元数据，正文使用标准 Markdown 标题与相对链接：

```yaml
---
page_id: network-management
language: zh-CN
title: 网络管理
description: 子网用途、字段填写与创建和删除操作。
navigation_group: resources
updated_at: "2026-11-08"
product_version: "0.21.26"
---
```

两种语言共享 `page_id` 和菜单分组 `navigation_group`。网站可按元数据建立页面索引，按二、三级标题生成目录；当前不绑定网站框架。
