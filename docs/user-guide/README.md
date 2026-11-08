# Page guides

**English** · [简体中文](README.zh-CN.md) · [Documentation](../README.md)

Each main menu page has one guide explaining its purpose, field values and actions.

| Menu | Guide |
| --- | --- |
| Resources → Networks (资源 → 网络管理) | [Network management](network-management.md) |
| Resources → Devices (资源 → 设备管理) | [Device management](device-management.md) |

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
product_version: "0.21.7"
---
```

Both languages share `page_id` and the menu group `navigation_group`. A website can index metadata and generate a table of contents from second- and third-level headings. No website framework is selected here.
