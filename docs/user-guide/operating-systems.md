---
page_id: operating-systems
language: en
title: Operating systems
description: Import Ubuntu ISOs, prepare boot files and register installable NICo OS definitions.
navigation_group: resources
updated_at: "2026-11-08"
product_version: "0.21.26"
---

# Operating systems

**English** · [简体中文](operating-systems.zh-CN.md) · [Page guides](README.md)

## 1. Purpose and entry point

Open **Resources → Operating systems (资源 → 操作系统)** to upload or select an ISO, prepare boot files and register a NICo OS definition. Prepared systems are selected in [Installation profiles](installation-profiles.md) and device system configuration.

PXEye requires a writable, persistent material directory. NICo PXE HTTP must publish those same files, and target hosts must reach the public URLs. See [Deployment](../deployment.md#4-mount-and-publish-materials) for configuration.

## 2. Field values

| Field | Requirement |
| --- | --- |
| OS version name (OS 版本名称) | Required, at most 100 characters. Include distribution, version and architecture. |
| ISO file (ISO 文件) | Select a local `.iso` through **Upload ISO (上传 ISO)**. The default limit is 16 GiB; deployment settings may override it. |
| ISO in directory (目录中的 ISO) | Select a mounted source file through **Use server ISO (使用服务器 ISO)**. This is not a browser-local path or an arbitrary server path. |
| SHA256 checksum (SHA256 校验值) | Optional 64-character hexadecimal digest from the source. The service computes a digest even when omitted. |
| Architecture / installer | Detected from ISO metadata. Ubuntu Server supports `amd64 → x86_64` and `arm64 → aarch64`. |

## 3. Actions

### Browser upload

1. Click **Upload ISO (上传 ISO)**, enter a name, select the file and optional checksum, then click **Upload and prepare (上传并准备)**.
2. Wait for upload and extraction. If interrupted, use **Resume upload (继续上传)** and select the original file with the same name and size.
3. Registration follows extraction automatically. If it remains **Prepared, awaiting registration (已准备 · 待登记)**, click **Continue preparation and registration (继续准备并登记)**.
4. Once **Registered (已登记)**, click **Make available (设为可用)** and select it in a profile.

### Server-directory import

1. Put the ISO at the top level of a configured source directory mounted into PXEye. Click **Use server ISO (使用服务器 ISO)**.
2. Select **ISO in directory (目录中的 ISO)**, enter a name and optional checksum, then click **Import and prepare (导入并准备)**.
3. The service copies the ISO, extracts boot files and registers automatically. Click **Make available (设为可用)** after registration.

Click the OS name to inspect its source, NICo OS ID, and published ISO/kernel/initrd URLs, sizes and SHA256 values. On failure or uncertain results, use **Check / prepare again (核对 / 重新准备)** and resolve the error before proceeding.

## 4. Example

| Item | Example |
| --- | --- |
| OS version name | `Ubuntu Server 24.04 ARM64` |
| ISO | `ubuntu-24.04-live-server-arm64.iso` in a source directory |
| Checksum | The file provider's SHA256, or leave empty. |

The service creates a separate version directory:

```text
/materials/<OS-ID>/
  install.iso
  kernel
  initrd
  info.txt
```

This example uses `os_library.directory=/materials`. The first three files are published at the configured `public_base_url/<OS-ID>/`; `info.txt` identifies the release. URLs and kernel parameters are generated without modifying the ISO. Per-device autoinstall configuration is generated separately when an installation task is created.

## 5. Notes

- Ubuntu Server autoinstall is supported. Other installers or ISOs without standard `/.disk/info`, `/casper/vmlinuz` and `/casper/initrd` files need adaptation.
- Registering an ARM64 ISO confirms material preparation only. Hosts also need matching ARM64 EFI, Scout and installation profiles.
- An OS referenced by active tasks cannot be disabled, re-prepared or cancelled. Import a separate version for changed media.
- **Cancel this version (取消此版本)** deletes its prepared files; server-source ISOs remain. An existing NICo record does not imply complete PXEye materials.
- Publication checks originate from PXEye. Verify the target host's download path separately.

Related: [Installation profiles](installation-profiles.md) · [Installation tasks](installation-tasks.md) · [Pre-installation checklist](../pre-installation-checklist.md)
