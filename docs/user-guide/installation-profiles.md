---
page_id: installation-profiles
language: en
title: Installation profiles
description: Configure reusable OS, disk rules, partitioning and default login settings.
navigation_group: configuration
updated_at: "2026-11-10"
product_version: "0.22.13"
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

### Custom files

Below **Default login configuration**, select **Add file** and enter an absolute target-system path and its text content. Expand a file card to edit it. **File attributes** contains the owner, four-digit octal permissions and overwrite/append mode; defaults are `root:root`, `0644` and overwrite. Empty content creates an empty file. Append does not merge YAML/JSON or insert a separator newline.

For example, set the path to `/etc/nico/site.yaml` and the content to:

```yaml
nico_endpoint: "http://192.0.2.100:8080"
site: "site-a"
```

Replace the address, save the draft, check and publish a new version, then select that version for the device. Target-system cloud-init writes the files on first boot after package and user initialization, creating parent directories if needed. Ordinary reboots do not rewrite them, and profile edits do not update installed hosts. After installation, inspect the file with `sudo cat /etc/nico/site.yaml`.

- Up to 32 files, 64 KiB of content per file and 256 KiB in total. UTF-8 content preserves indentation and newlines.
- Duplicate or overlapping file/directory paths are rejected. Managed network, login, cloud-init, runtime and installation-receipt paths are protected; existing template files cannot be shadowed.
- Variables such as `${NICO_VIP}` are literal text. This feature does not download remote content or execute scripts. A URL is only stored as content.
- Custom owners must already exist or be created during installation. The image must support cloud-init deferred file writes. Write failures are visible through existing host-configuration acceptance checks; manually skipping that check does not verify the files.
- Content is stored with the profile and delivered in installation data. Use it for ordinary text configuration, not passwords, private keys or tokens.

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


### Optional GPU environment check

Enable GPU environment check under Installation acceptance in an installation profile, then save and publish a new version. The flag is frozen with the task; historical profiles default to disabled and show Skipped. The check runs only after base installation acceptance and before normal reboot acceptance. It reads deployment results; it never launches GPU tests or provisioning scripts.

The producer must atomically publish `/var/lib/metal-deployer/state.json` using a temporary file and rename. Maximum size is 256 KiB. Use integer schema=1, a nonempty iso_version and the first-boot `/proc/sys/kernel/random/boot_id`. An optional task_id from `/etc/nico-installation.json` must match when present. started_at and updated_at must be timezone-qualified ISO 8601 timestamps belonging to this installation; synchronize node clocks.

Use pending/running/success/failed for overall and stage status. Supply a nonempty stages list with unique names; a nonempty current_stage must name a listed stage. Terminal stages require integer rc, and success requires rc=0. Optional start/end/log fields are supported; log paths are display-only. Acceptance requires overall=success and every stage success/rc=0. Failure, invalid protocol or identity mismatch requires attention. Missing files and transient SSH outages are polled approximately every 10 seconds, with a 20-second SSH limit and a 60-minute wait budget per acceptance attempt. updated_at alone is not a hang detector.

Success evidence is saved before normal reboot. Reboot acceptance uses that evidence rather than requiring the historical state file to match the new boot ID. Continue acceptance only observes again; it does not reinstall or rerun scripts. Final acceptance cannot pass without the required pre-reboot success evidence.

Acceptance labels follow: Installer success → Host configuration → System disk and EFI partition verification → Network configuration → SSH connectivity → DNS / HTTP / NTP connectivity → GPU environment check (optional) → Reboot acceptance. System disk and EFI partition verification checks root/ESP placement rather than reconfiguring firmware. Existing required/advisory service policies are unchanged. This state file is a custom deployment protocol, not the standard cloud-init status.
