---
page_id: installation-profiles
language: en
title: Installation profiles
description: Configure reusable OS, disk rules, partitioning and default login settings.
navigation_group: configuration
updated_at: "2026-11-08"
product_version: "0.21.26"
---

# Installation profiles

**English** · [简体中文](installation-profiles.zh-CN.md) · [Page guides](README.md)

## 1. Purpose and entry point

Open **Configuration → Installation profiles (配置 → 安装方案)** to share OS, disk selection, partition and login defaults across servers. Devices select a version under **System configuration → Current installation profile (系统配置 → 当前安装方案)**. Maintain per-device hostname, management interface and fixed address in device configuration.

## 2. Field values

### Basic settings, disks and login

| Field | Requirement |
| --- | --- |
| Profile name / description (方案名称 / 说明) | Required name, at most 100 characters; description at most 1000. |
| Default OS (默认 OS) | A registered, enabled Ubuntu Server OS matching the profile architecture. |
| Selection rule / candidate scope (选择规则 / 候选范围) | Unique match, smallest or largest capacity; all disks or NVMe only. An explicit device disk takes precedence. |
| Serial / model patterns (序列号 / 型号规则) | Optional; `*` matches any characters, `?` one character. Case-sensitive; all filters apply together. |
| Minimum / maximum capacity (最小 / 最大容量) | Optional GiB values. Capacity rules require complete Scout size data; minimum must not exceed maximum. |
| Root filesystem (根分区格式) | `ext4` or `XFS`. |
| EFI partition (EFI 分区) | Integer `512–4096` MiB; default `1024`. |
| Root partition (根分区) | Empty uses remaining space; fixed size is at least `20` GiB, leaving excess unallocated. |
| OS username (OS 用户名) | Ordinary user, at most 32 characters. Start with a lowercase letter or `_`; subsequent characters may include lowercase letters, digits, `_` and `-`. Cannot be `root`. |
| Login mode / default password (登录方式 / 默认密码) | SSH password or key login. Supply a password in the profile or per device; empty preserves an existing password. **Default password handling (默认密码处理)** can explicitly clear it. |
| SSH public keys (SSH 公钥) | One complete key per line. Key login requires valid keys in the final configuration. |

### Optional settings

Expand **Advanced settings (高级设置)**:

| Field | Requirement |
| --- | --- |
| Timezone (时区) | IANA timezone, such as `Asia/Shanghai`. |
| NTP servers (NTP 服务器) | One reachable address or hostname per line; required when publishing. |
| Extra packages (额外软件包) | One package name per line. Installation dependencies must exist on the ISO or configured repositories. |
| APT primary / security URL (APT 软件源 / 安全更新源 URL) | Reachable repositories for the target architecture. Empty values use ISO materials for offline installation. |
| DNS acceptance domains / HTTP acceptance URLs (DNS 验收域名 / HTTP 验收 URL) | One per line, checked during acceptance. DNS acceptance domains do not configure DNS servers. |

## 3. Actions

1. Click **New profile (新建方案)** or **Copy (复制)** an existing one, enter values and **Save draft (保存草稿)**.
2. Reopen the draft and **Check profile (检查方案)**. Resolve missing OS, username, NTP or incompatible materials.
3. Click **Publish version (发布版本)**. Select it in device **System configuration (系统配置)** and review the resolved login and disk settings.
4. Use **View (查看)** for published versions. To change one, click **New version (新版本)**, edit and publish, then select that version for devices.
5. **Disable (停用)** profiles for new installations and **Enable (启用)** them again as needed. Unreferenced drafts may be deleted.

## 4. Example

| Item | Example |
| --- | --- |
| Name / OS | `Ubuntu-ARM64-NVMe` / enabled Ubuntu Server ARM64 |
| Disk selection | Unique match, NVMe only, serial pattern `OS-*` |
| Partitions | EFI `1024` MiB, ext4 root using remaining space |
| Login | User `operator`, SSH key login, an actual complete public key |
| Timezone / NTP | `Asia/Shanghai` / `192.0.2.123` (replace with the actual service) |

Create this example from a base profile of the same architecture. If `OS-*` matches multiple disks, select a specific disk in device system configuration before creating a task.

## 5. Notes

- New profiles inherit base architecture and network mode; the page cannot change architecture. Configure a suitable base during deployment if missing.
- Supported layout is single-disk GPT / UEFI, EFI and root, without swap. The page does not create RAID, LVM, multi-disk layouts or custom scripts.
- No match, tied matches or incomplete size data will not select a disk arbitrarily. Narrow the rule or choose a disk per device.
- **Inherit selected profile (继承所选方案)** uses the specific selected version; device overrides take precedence.
- Publishing does not install servers; created tasks retain snapshots. Password login requires a password in the profile or device configuration.

Related: [Operating systems](operating-systems.md) · [Device management](device-management.md) · [Installation tasks](installation-tasks.md)
