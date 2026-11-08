---
page_id: rack-topology
language: en
title: Rack topology
description: View devices, management addresses and power state by rack, and arrange cards.
navigation_group: overview
updated_at: "2026-11-08"
product_version: "0.21.26"
---

# Rack topology

**English** · [简体中文](rack-topology.zh-CN.md) · [Page guides](README.md)

## 1. Purpose and entry point

Open **Overview → Rack topology (总览 → 机柜拓扑)** to locate servers, switches, power shelves and DPU endpoints by rack, inspect management addresses, and arrange device cards.

## 2. Field values

The page reads existing device information. Editing consists of dragging cards.

| Display | Meaning / maintenance location |
| --- | --- |
| Rack | Groups devices by their NICo Rack assignment; devices without one appear in the unassigned group. Maintain assignments in device configuration. |
| Device SN, BMC address, management address | Read from inventory; addresses prefer observations, falling back to planned values. Maintain them in [Device management](device-management.md). |
| DPU count | Based on identified DPU interfaces; the “DPU nodes” summary counts devices with DPU interfaces. |
| Power dot | Last observed power state: green for on, gray for off, hollow for unknown. Hover for state and time. |
| Layout | Card order within network, compute, other-device and power zones. |

## 3. Actions

1. Click **Refresh topology (刷新拓扑)** to read inventory. Click a device card for details.
2. Click **Edit layout (编辑布局)** and drag cards within the same rack and zone.
3. Click **Save layout (保存布局)** to keep the order, or **Cancel (取消)** to discard unsaved changes.
4. To restore automatic sorting, enter layout editing and click **Restore automatic order (恢复自动排列)**. This immediately clears saved manual ordering for all racks.

## 4. Example

The compute zone of `RACK-01` contains `SERIAL-1` and `SERIAL-2`. Move `SERIAL-2` first and save. The next visit uses the saved order.

## 5. Notes

- Dragging changes display order only; it does not change rack assignments, addresses or cabling.
- The view shows logical groups, without physical rack units, heights or switch link mapping.
- The rack field in the planning CSV is for comparison; one-click matching does not change NICo Rack assignments.

Related: [Device management](device-management.md)
