# Changelog

## 0.22.12 — Detailed NIC inventory export

- Export one row per host port with physical location, port number, adapter identity, speed, link state and available neighbor information.
- Collect optional Redfish port metadata and preserve read-only information alongside editable address columns; retain legacy CSV import compatibility.
- Improve Excel readability with frozen identity columns and support for columns beyond Z.

## 0.22.10 — Manual acceptance skips

- Add a Manual pass action to each installation acceptance item; persist task-scoped operator decisions and display Skipped.
- Apply skips to base, GPU and reboot acceptance without claiming automatic verification or changing the frozen installation plan.
- Keep operator/time/evidence audit records and preserve skip decisions during concurrent worker updates.

## 0.22.9 — Per-check installation acceptance

- Retain individual acceptance results and continue read-only base checks after network mismatches; show failures without bypassing required checks or reboot gates.
- Remove pending-verification suffixes from the acceptance panel.
- Add optional GPU deployment-state acceptance, offline NICo bundle handling and OCI import tooling.
- Simplify managed-device filtering.

## 0.22.8 — Network acceptance diagnostics

- Report the missing planned IPv4 address when an interface has no IPv4 data, instead of an index error.
- Clarify installation acceptance labels, including system disk and EFI partition verification.

## 0.22.7 — Manual acceptance entry

- Add Start acceptance to the right of failure dialogs and remove the task/log shortcut.
- Resume the original installation checks without stale recovery progress hiding the action; settle waiting boot recovery when acceptance starts.

## 0.22.6

- Store local switch/power-shelf Expected-shaped records in SQLite; manage controller addresses without native lifecycle declaration writes.
- Unify managed-device address display, expand per-MAC planning edits and display actual subnet MTU.


**English** · [简体中文](CHANGELOG.zh-CN.md)

Capability milestones for the current source lineage. Historical version headings identify development baselines, not published PXEye releases. Site addresses, device identities and operational logs are excluded.

## 0.22.5 — PCIe interface inventory and planning updates

- Collect MAC-to-PCIe function addresses through shared Redfish/Scout parsing and show them in device details and interface exports.
- Export formatted Excel interface lists with a PCIe column, wider columns, grid borders and text-preserving cells; accept the completed file through the existing import flow and retain legacy CSV support.
- Allow independent host interfaces to share a subnet through import and installation rendering, and allow local planning updates while tasks keep their frozen revisions.
- Clarify existing MTU configuration and primary boot-interface selection.

## 0.22.1 — Online and offline Helm deployment

- Default to online Chart downloads from URLs, Helm repositories or OCI; accept browser uploads for offline Charts and complete recipes.
- Edit or import values YAML, preview Helm installation commands, and retain frozen inputs for bounded execution and recovery.
- Remove the mandatory deployment-package PVC from the bootstrap manifest; distinguish a completed Helm install from full NICo readiness.

## 0.22.0 — NICo cluster deployment

- Start PXEye independently before NICo and open the cluster deployment page.
- Run background Helm preflight/deployment from local versioned packages; display complete services, phases and command records.
- Add a single-replica database/PKI/Vault bootstrap Chart, material mount adaptation and verified site handoff.
- Document packages, permissions and page usage in both languages.

## 0.21.26 — Network action visibility

- Remove the OS DNS action from the network list and show internal address segments without a Delete button.

## 0.21.25 — Simplified batch credential dialog

- Show only the shared BMC / PMC username and password fields when retrieving discovery information in bulk. Use the management addresses from the selected endpoints without repeating the device list or address selection.

## 0.21.24 — Batch discovery information retrieval

- Select discovered endpoints and enter shared BMC / PMC credentials once for up to 50 devices, using four concurrent reads.
- Reuse single-device identity parsing, management-MAC verification and session-bound enrollment proofs; show per-device results and confirm enrollment without re-entering credentials.
- Keep retrieval separate from enrollment, clear selection on subnet changes and report failed reads independently.

## 0.21.23 — Device management layout consistency

- Place Device plans after Discovered devices and Managed devices, retaining Managed devices as the default tab.
- Reuse the device management search-field layout and table typography for arrival plans, including responsive sizing and secondary MAC text.
- Align the runtime health version with package metadata; retain the existing BIOS/PXE recovery fixes.

## 0.21.20 — Shared device identification

- Use shared Redfish and NICo-report parsing to identify physical servers, supported NVLink switches, power shelves and BlueField DPUs.
- Retain the detected type during supported-device enrollment and reuse identity parsing for discovery, management-address refresh and server BMC checks.
- Verify the observed management MAC and hardware serial; reject ambiguous identities and conflicting declared types. Server Scout details now include the device type.

## 0.21.19 — Independent device planning

- Add a Device plans tab with a flat CSV template, validation preview, editable planning rows and comparison with managed server configuration.
- Match selected enrolled servers by unique SN, locate the management interface by observed MAC and resolve an exact CIDR to an existing subnet; preserve credentials and running tasks.
- Keep imports separate from discovery and enrollment. Matching saves configuration for the existing address and installation actions.
- Display management subnet ranges without names, and add a bilingual device management guide.

## 0.21.17 — Resolved system-disk review

- Read current NICo/Scout hardware during installation preflight and return the uniquely resolved disk model, full serial, capacity, source and observation time to the review page.
- Allow device system planning to select a different concrete disk for the next reinstall; freeze both the previous and target disks instead of silently restoring the old target.
- Render only the preflight-resolved disk as the final installation target, and show a pending Scout state when a profile rule has not been resolved yet.

## 0.21.14 — Running state after boot recovery

- Return a recovered task to the running installation state after receiving its authenticated installer-start event.
- Keep the bounded observer active for installed-system identity and acceptance instead of leaving the task marked as needing attention.

## 0.21.13 — Immediate installer progress

- Persist the authenticated installer `started` event while observing an automatic boot recovery.
- Mark boot recovery complete as soon as the retained request enters the installer instead of waiting for the installed-system SSH identity.

## 0.21.12 — Standard one-time PXE recovery

- Detect when a verified OEM network-first recovery still returns to the existing operating system.
- Use the BMC's advertised standard Redfish `Pxe` plus `Once` override for one final, ledgered restart.
- Preserve the original custom-PXE request, Machine, Instance and disks; stop instead of replaying an uncertain write or restart.

## 0.21.11 — Bounded network-boot fallback recovery

- Detect a completed NICo restart that returned to disk before the retained custom-PXE request reached the installer.
- Restore network-first boot and issue one ledgered recovery restart without recreating the installation request, Instance or disk operation.
- Stop with an unknown result after a service interruption during either write operation instead of replaying it.

## 0.21.10 — Single-owner recovery restart

- Let NICo's recovered state machine perform the retained custom-PXE restart after PXEye verifies the repaired boot order.
- Remove the extra administrative restart that could precede NICo's own restart.
- Display NICo takeover and network restart as separate persisted incident steps.

## 0.21.9 — Public-evidence recovery gate

- Gate BIOS recovery on the accepted task, `Assigned/BiosSetupFailed`, unchanged Instance configuration and absence of installer or disk-write evidence.
- Stop relying on NICo's internal one-time iPXE flag, which is intentionally omitted from the public Instance representation while the state machine retains the reboot request separately.
- Upgrade a v1 diagnosis-only stop without replaying any configuration write, restart or installation request.

## 0.21.8 — Automatic NICo boot recovery

- Detect a bounded pre-installer `BiosSetupFailed` state and verify that the accepted Machine, Instance, boot interface and untouched-disk evidence still match the task.
- Restore the vendor-confirmed network-first boot order, verify the read-back and request one restart through NICo without replaying custom PXE.
- Resume observation of the original installation attempt and stop safely when a configuration or restart result is unknown.
- Present the repair as a consistent five-step incident workflow with its scope and current evidence.

## 0.21.7 — OS-independent network boot recovery

- Removed old-system SSH and root-disk inspection from reinstall preflight.
- Leave custom-PXE retries, boot-order convergence and pre-install restarts exclusively to NICo.
- Observe and report NICo boot failures without issuing a competing Redfish or SSH restart.
- Keep strict task-bound SSH verification for the newly installed operating system.

## 0.21.6 — Lenovo disk handoff

- Handle the nested hard-disk order exposed by older Lenovo firmware during post-install recovery.
- Prefer a physical-disk fallback only when the BMC exposes exactly one unambiguous physical target.
- Preserve the standard Redfish one-time boot path and existing behavior on other platforms.

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
