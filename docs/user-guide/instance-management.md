---
page_id: instance-management
language: en
title: Instance management
description: Inspect NICo allocations, release instances and track device reclamation.
navigation_group: resources
updated_at: "2026-11-08"
product_version: "0.21.26"
---

# Instance management

**English** · [简体中文](instance-management.zh-CN.md) · [Page guides](README.md)

## 1. Purpose and entry point

Open **Resources → Instances (资源 → 实例管理)** to inspect device, address, OS and tenant configuration, or release a server allocation. An Instance is NICo's server allocation resource. This page reads existing instances; [Installation tasks](installation-tasks.md) handle allocation for installation.

## 2. Field values

| Item | Meaning / input requirement |
| --- | --- |
| Search instances (搜索实例) | Enter a name, ID, SN, hostname or IP. |
| Instance name / ID | NICo instance identity; verify the target before release. |
| Device SN / hostname | Associated device and hostname, with its source displayed. |
| NICo instance addresses / OS | Values from NICo instance configuration; they do not confirm OS login verification. |
| Machine state / release progress | Current Machine state and the separate release record. |
| Release confirmation | Enter the full device SN shown and confirm cleanup of all disks. |

## 3. Actions

### Inspect

1. Click **Refresh data (刷新数据)** and search for the instance.
2. Click **Details (详情)** for Machine, tenant, configuration versions and the latest Scout disk inventory.

### Release

1. Confirm the device no longer holds systems or data to preserve. Resolve active installation tasks first.
2. Click **Delete and reclaim (删除（退租回收）)**, verify instance, SN and all-disk scope, enter the SN and confirm cleanup.
3. Click **Confirm deletion and reclamation (确认删除并回收)**. Follow **Release records (回收记录)** using **View record (查看记录)** and **Refresh record (刷新记录)** as needed.
4. Wait for **Reclamation complete (回收完成)** and review Machine state before installing again.

## 4. Example

Search `SERIAL-1` and verify the instance to release. Enter `SERIAL-1` in the confirmation, allow all-disk cleanup and submit. Follow its release record until completion.

## 5. Notes

- Release reclaims the instance and associated resources and may reboot the device and clean all disks. Device plans and installation history remain.
- The device may still be preparing after the instance disappears; disappearance alone is insufficient to use it again.
- If the request result is unknown or reclamation fails, refresh and resolve NICo / Scout errors before resubmitting.
- When deletion is disabled, inspect the reason and resolve active tasks, identity association or pending release operations.

Related: [Installation tasks](installation-tasks.md) · [Device management](device-management.md)
