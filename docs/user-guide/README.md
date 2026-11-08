# Page guides

**English** · [简体中文](README.zh-CN.md) · [Documentation](../README.md)

Each main menu page has one guide explaining its purpose, field values and actions.

| Menu | Guide | Purpose |
| --- | --- | --- |
| Overview → Rack topology (总览 → 机柜拓扑) | [Rack topology](rack-topology.md) | Rack groups, device lookup and ordering |
| Installation → Tasks (装机 → 安装任务) | [Tasks](installation-tasks.md) | Select devices, install and inspect results |
| Resources → Devices (资源 → 设备管理) | [Devices](device-management.md) | Plan import, enrollment, addresses and system configuration |
| Resources → Instances (资源 → 实例管理) | [Instances](instance-management.md) | Inspect instances and reclaim devices |
| Resources → Operating systems (资源 → 操作系统) | [Operating systems](operating-systems.md) | Import ISOs, prepare and enable OS versions |
| Resources → Networks (资源 → 网络管理) | [Networks](network-management.md) | Subnet creation, reservations and DHCP prerequisites |
| Configuration → Installation profiles (配置 → 安装方案) | [Installation profiles](installation-profiles.md) | OS, disk, partition and login defaults |
| Configuration → Site settings (配置 → 站点设置) | [Site settings](site-settings.md) | Connections, storage and installation concurrency |
| Configuration → NICo cluster | [NICo cluster](nico-cluster.md) | Online/offline Helm deployment, service status and site connection |

## Writing conventions

- Store guides in `docs/user-guide/` with stable English names, such as `network-management.md`.
- Provide a matching `.zh-CN.md` translation with reciprocal language links.
- Use five sections: **Purpose and entry point → Field values → Actions → Example → Notes**. Put reference links at the end.
- Use tables for fields and numbered steps for actions. Keep only information needed to complete the task; link detailed explanations.
- Use fictional examples and update this index and the documentation index when adding pages.
- User guides cover functions, actions and necessary limits. Keep source reviews, commit identifiers and author validation records in internal maintenance materials.
- State prerequisites as concrete configuration and connectivity requirements, without assigning responsibilities to organizations or teams.

## Website indexing

Use generic YAML metadata at the top, standard Markdown headings and relative links:

```yaml
---
page_id: network-management
language: en
title: Network management
description: Subnet purpose, field values, creation and deletion.
navigation_group: resources
updated_at: "2026-11-08"
product_version: "0.21.26"
---
```

Both languages share `page_id` and the menu group `navigation_group`. A website can index metadata and generate a table of contents from second- and third-level headings. No website framework is selected here.
