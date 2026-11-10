---
page_id: installation-tasks
language: en
title: Installation tasks
description: Select devices, review configuration, install and inspect logs and acceptance results.
navigation_group: installation
updated_at: "2026-11-09"
product_version: "0.22.8"
---

# Installation tasks

**English** · [简体中文](installation-tasks.zh-CN.md) · [Page guides](README.md)

## 1. Purpose and entry point

Open **Installation → Tasks (装机 → 安装任务)** to install or reinstall servers and track progress, logs and results. Prepare an available OS, a published profile, device configuration and the connectivity required by the [pre-installation checklist](../pre-installation-checklist.md).

## 2. Field values

The wizard uses saved device configuration and has two steps: **Select devices (选择设备)** and **Review configuration (核对配置)**.

| Item | Input / review requirement |
| --- | --- |
| Device selection | Filter by SN, architecture, management subnet or current system; at most 50 devices per batch. Devices with active tasks or incomplete releases cannot be selected. |
| Query current system (查询当前系统) | Queries selected devices, or filtered devices when none are selected; 1–50 devices. Use results to review the current OS. |
| Target OS / profile | Read from device system configuration; OS architecture must match the target host and profile. |
| Hostname / management address | Read from device configuration; interface, address and subnet must correspond. |
| System disk | Shows the explicit disk or profile selection. When selection awaits Scout, check the later result and cleanup scope. |
| Concurrency | Read from [Site settings](site-settings.md) and frozen when the batch is created. |
| Execution confirmation | Confirm devices, addresses and disks, and allow installation and reboot. Initial onboarding cleanup also requires confirmation for all disks. |

## 3. Actions

### Create and track

1. Click **New installation task (新建安装任务)**, select devices, optionally **Query current system (查询当前系统)**, then click **Next (下一步)**.
2. Review each device and the preflight results. Use **Edit device plan (编辑设备规划)** to correct configuration and review again after saving. Resolve failed checks before proceeding.
3. Read the impact, complete confirmations and click **Confirm and install (确认并安装)**. The service chooses first installation or reinstallation per device and saves a configuration snapshot.
4. Click **View devices (逐台查看)** in the batch. Open a device record for **Live installation logs (实时安装日志)**, **Execution and recovery records (执行与恢复记录)** and **Installation acceptance (安装验收)**.
5. Review system disk, fixed networking, SSH and normal reboot checks. Save **Download acceptance report (下载验收报告)** when available.

### Handle failures

Click **Handle problem (处理问题)** and use the action offered for the current stage:

| Action | Situation / impact |
| --- | --- |
| View automatic repair / recovery progress | Inspect recovery steps or installation-result observation before taking further action. |
| Start acceptance (开始验收) | Click at the lower right of the failure dialog, confirm the SN and permit boot/reboot verification to start acceptance for the original task. Recovery progress does not hide this entry. The current attempt must still have a trusted identity; all acceptance checks remain enforced and the disk is not rewritten. |
| Continue preparing device (继续准备设备) | Uses current device plans to resume onboarding preparation. Confirm the dialog's cleanup scope. |
| Retry installation / Recheck and continue (重试安装 / 重新检查并继续) | Reuses the original Instance and task plan. Review the new preflight and confirmation; continuing installation may overwrite the system disk again. |
| End task (结束任务) | Releases the PXEye task reservation and keeps history. It does not stop the physical installer or release the NICo Instance. |

## 4. Example

Save hostname `gpu-01`, management address `192.0.2.10`, a published Ubuntu profile and disk `DISK-001` for `SERIAL-1`. Select that device in a new task, verify these values and cleanup scope, then submit.

## 5. Notes

- Initial onboarding can clean all disks, including data disks. The selected installation disk alone does not define cleanup scope.
- A failed device pauses while the others continue. Do not create duplicate tasks to bypass a pending issue.
- Created tasks use snapshots; later device or profile edits do not automatically change the current installation. Removing an interface address does not remove its requirement from this attempt; acceptance reports the missing address.
- System disk and EFI partition verification reads the root disk, EFI partition and partition layout over SSH. It does not change firmware boot order.
- Start acceptance records base checks separately. An interface mismatch does not stop the remaining read-only checks. After each collection round, the acceptance panel shows passing checks and failure details. Required failures block GPU checking and reboot acceptance unless explicitly skipped.
- Queued/running tasks or an allocated Instance do not indicate a completed OS installation; review installation and boot acceptance results.

Related: [Device management](device-management.md) · [Operating systems](operating-systems.md) · [Installation profiles](installation-profiles.md) · [Install your first server](../getting-started.md)


### Manually skip an acceptance check

During installation acceptance, each item has a **Manual pass (手动通过)** button. Clicking it marks the item **Skipped (已跳过)** for this task and persists across refreshes. It does not record an automatic verification success. Finished tasks cannot be changed.

Running acceptance applies skips on its next check; paused tasks still require **Start acceptance**. Other items follow the frozen plan. Skipping reboot acceptance prevents a reboot that has not been dispatched; it cannot cancel an already dispatched reboot.

The acceptance report records each skipped item, operator, time and preceding check result. Skipping does not change the installation plan or disable task binding or trusted SSH transport; target reads still require a valid connection.

### Optional GPU environment check

Enable GPU environment check under Installation acceptance in an installation profile, then save and publish a new version. The flag is frozen with the task; historical profiles default to disabled and show Skipped. The check runs only after base installation acceptance and before normal reboot acceptance. It reads deployment results; it never launches GPU tests or provisioning scripts.

The producer must atomically publish `/var/lib/metal-deployer/state.json` using a temporary file and rename. Maximum size is 256 KiB. Use integer schema=1, a nonempty iso_version and the first-boot `/proc/sys/kernel/random/boot_id`. An optional task_id from `/etc/nico-installation.json` must match when present. started_at and updated_at must be timezone-qualified ISO 8601 timestamps belonging to this installation; synchronize node clocks.

Use pending/running/success/failed for overall and stage status. Supply a nonempty stages list with unique names; a nonempty current_stage must name a listed stage. Terminal stages require integer rc, and success requires rc=0. Optional start/end/log fields are supported; log paths are display-only. Acceptance requires overall=success and every stage success/rc=0. Failure, invalid protocol or identity mismatch requires attention. Missing files and transient SSH outages are polled approximately every 10 seconds, with a 20-second SSH limit and a 60-minute wait budget per acceptance attempt. updated_at alone is not a hang detector.

Success evidence is saved before normal reboot. Reboot acceptance uses that evidence rather than requiring the historical state file to match the new boot ID. Continue acceptance only observes again; it does not reinstall or rerun scripts. Final acceptance cannot pass without the required pre-reboot success evidence.

Acceptance labels follow: Installer success → Host configuration → System disk and EFI partition verification → Network configuration → SSH connectivity → DNS / HTTP / NTP connectivity → GPU environment check (optional) → Reboot acceptance. System disk and EFI partition verification checks root/ESP placement rather than reconfiguring firmware. Existing required/advisory service policies are unchanged. This state file is a custom deployment protocol, not the standard cloud-init status.
