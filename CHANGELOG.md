# Changelog

**English** · [简体中文](CHANGELOG.zh-CN.md)

Capability milestones for the current source lineage. Historical version headings identify development baselines, not published PXEye releases. Site addresses, device identities and operational logs are excluded.

## 0.21.5 — Installation recovery visibility

- Displayed restarted installation observation as “Waiting for installation result” with its deadline and an explicit refresh action.
- Kept the read-only recovery observer active across repeated service updates until the original observation deadline.
- Continued to withhold acceptance and retry actions until trustworthy completion or identity evidence exists.

## 0.21.4 — Clear equipment actions

- Sized per-device actions to their labels instead of stretching them across the table cell.
- Renamed the switch and power-shelf action to “Sync to NICo” and clarified that it creates or updates an Expected device declaration after the device has entered the PXEye inventory.

## 0.21.3 — Faster batch submission

- Removed the redundant device-count confirmation field and grouped review controls by intent.
- Created tasks from the accepted frozen preflight while retaining complete safety validation in the execution worker before destructive actions.
- Opened the returned batch immediately and refreshed supporting lists in the background.

## 0.21.2 — Installation concurrency

- Added a site-level default installation concurrency from 1 to 50, with a default of 5.
- Froze the current default into each new batch so later site changes do not alter existing work.
- Added bounded parallel execution within a batch while keeping batches ordered and resource operations excluded during installation.

## 0.21.1 — Installation preflight

- Reduced the installation review to device identity, installation configuration and operating-system materials, with batch progress and failure-only details.
- Reused the initial NICo allocation observation during reinstall review while retaining the complete safety preflight immediately before execution.
- Added source-revision metadata and a commit-before-build workflow for traceable images.
- Made the runtime UID setup compatible with Ubuntu base images that already provide UID 1000.
- Aligned the API, package metadata and browser asset revision on version 0.21.1.

## 0.21.0 — Source structure and packaging

- Split HTTP transport/routes, task coordination, clients, contracts and device projections.
- Centralized Store initialization and legacy import; made inventory export/seed an explicit refresh.
- Replaced shared CSV temporary files with a common atomic writer.
- Added safe error codes, request correlation and sanitized stack locations.
- Registered frontend pages/actions and polling; removed overrides and formatted assets.
- Added installable package/CLI entries, pinned developer tooling and Apache-2.0 licensing.
- Completed static and wheel checks; no regression, container build, deployment or hardware run.

## Unreleased — PXEye technical preview

- Introduced the PXEye name and brand assets.
- Reorganized public documentation into English/Chinese README, features, architecture, deployment, operator, security and contribution guides.
- Added reference-architecture UI screenshots and reproducible display-only data.
- Provided independent build inputs, styles and generic Kubernetes deployment scaffolding.
- Prepared from the 0.20.3 development baseline; private security reporting remains to be configured.

## 0.20 — Site and hardware operations

- Core connectivity, mTLS identity, storage and service views.
- Rack topology and persistent manual ordering.
- Unified servers, DPU endpoints, NVLink switches and power shelves.
- Redfish address updates, recorded progress and read-only recovery.

## 0.19 — Unified management addresses

- Interface-level planning across device types.
- Batch identity refresh, address-operation previews and result verification.
- Separate server installation plans and non-server address management.

## 0.15–0.18 — Installation reliability

- Disk rules, GPT/UEFI, ext4/XFS and target-disk acceptance.
- Installer events, boot-order recovery and normal-reboot verification.
- Instance-release state linked to installation eligibility.
- CSV/Excel inventory templates.

## 0.13–0.14 — Workflow and network boundaries

- Automatic hardware preparation, frozen plans and scoped recovery.
- Background OS preparation, registration, activation and concurrency protection.
- Live NICo networks separated from drafts; native edits not emulated by destructive recreation.

## 0.8–0.12 — Planning and first installation

- DHCP/BMC discovery, identity retrieval and device planning.
- Expected Machine, Machine, Scout and Instance integration.
- ISO upload/directory import, profiles, batches, SOL logs and SSH acceptance.
- SQLite revisions, request idempotency, locks and persistent recovery.
