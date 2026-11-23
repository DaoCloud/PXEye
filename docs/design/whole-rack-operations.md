# Rack-level infrastructure management and provisioning platform: design specification

**English** · [简体中文](whole-rack-operations.zh-CN.md) · [Design documents](README.md)

The design of whole-rack operations for GB200 / GB300, built on NVIDIA Infra Controller (NICo).

- Status: design draft, for design review. This document describes the target design, not implemented functionality; the application code on this branch still has the first-version pages.
- The page-level design is in the [frontend design](frontend/README.md): every page can be clicked through and carries its feature points.
- The interface is in Simplified Chinese. Menu and page names are quoted in Chinese, with an English gloss in parentheses where they first appear. The figures are labelled in Chinese.

## 1. Purpose

This document gives the overall design of the rack-level infrastructure management and provisioning platform (PXEye): the platform architecture, the end-to-end operations workflow, what each module is for and which resources it owns, how modules interact and depend on each other, the design of operations, and the non-functional design. It is the common basis for interface design, work breakdown and acceptance testing.

Its chapters correspond one to one with the [requirements specification](../archive/rack-operations-v1/design/rack-operations-requirements.md): the requirements say which capabilities are wanted, and this document says how the platform organises them. The target hardware is the NVIDIA GB200 / GB300 NVL72 whole rack, and the foundation is NVIDIA Infra Controller (NICo).

## 2. Design goals

- NICo is the only source of truth and the execution engine. The platform adds the interface, the inventory, reconciliation and gating of operations, and does not rebuild what NICo already provides.
- The rack and the NVLink domain are the units of operation: turn one arrival inventory into deliverable racks, and keep the racks deliverable while they run.
- The whole flow has a single manual input, the arrival inventory. Everything else is discovered or derived by NICo, or comes from a profile.
- An operation takes at most three inputs: object, action, reason. Order, timeouts and retries are decided by site-level rules and are not filled in per operation.
- Every write operation can be previewed, tracked and audited; an unknown result is never resent automatically.
- Critical safety interlocks stay with the facility. The platform does not replace them and only refuses an operation when it detects a risk.

## 3. Scope and boundaries

### 3.1 In scope

- Inventory, reconciliation and state management of racks, NVLink domains, compute trays, switch trays (NVLink switches), power shelves and DPUs.
- Rack bring-up (NICo's bringup), power on and off of racks and trays, firmware updates, maintenance, quarantine, replacement and decommissioning.
- Operating system installation and instance delivery, and handing ready machines to an upper-layer platform.
- A health summary of racks, domains and trays, with entry points for handling alerts.
- Profiles such as firmware baselines and installation profiles, and the audit of every write operation.

### 3.2 Out of scope

- Closed-loop control on the facility side, such as circuit breakers and coolant valves; the building management system (BMS) owns it.
- Configuration of devices NICo does not manage, such as access switches and rack PDUs.
- Storing and displaying time series such as metric curves, power and temperature; the monitoring system owns them, and the platform only links to it.
- Cluster assembly and workload scheduling, such as Kubernetes and SLURM; the upper-layer platform owns them.
- Adapting to hardware that is not a whole rack or to non-standard networks; these do not enter the main flow.

## 4. Architecture

![Figure 1: platform architecture](figures/architecture.png)

### 4.1 Layers and responsibilities

| Layer | Component | Main responsibility | Key objects |
| --- | --- | --- | --- |
| Operator interface | PXEye | Inventory import, reconciliation views, gating of operations, task tracking, audit, profiles | Arrival inventory, profiles, audit, installation tasks |
| Orchestration | NICo REST and Flow | Orders rack-level operations in stages by operation rules, persists tasks, phased firmware rollout | Tasks, operation rules, rollout batches |
| Facts and state | NICo Core | Expected inventory, discovery and ingestion, state machines, health, subnets and addresses, OS definitions and instances | Racks, domains, trays, DPUs, instances |
| Hardware backend | RMS (Rack Management Service) | Carries out power, reset and firmware on trays, switches and power shelves | Hardware protocols and per-device ordering |
| Interconnect | NMX-C | Forms and partitions NVLink domains | NVLink domains, partitions |
| Boot | NICo DHCP, PXE, Scout | Address assignment, network boot, hardware discovery and preparation | Leases, boot artifacts |
| Facility | BMS, DSX Exchange | Leak events, breaker and coolant valve interlocks | Leak events |
| Observability | Prometheus, Grafana, Loki | Metrics, logs | Curves, logs |
| Upper layer | NVKE, CAPNICo, tenant platforms | Receive ready machines and assemble clusters | Clusters, nodes |

### 4.2 Access paths

The platform reaches NICo through two paths, with one rule: an operation that must be ordered across several devices goes through a Flow task, and everything else goes to Core.

| Path | Used for | Why |
| --- | --- | --- |
| NICo REST and Flow | Rack bring-up, power on and off of racks and NVLink domains, rack and tray firmware, expected-versus-actual validation, querying and cancelling tasks | Flow orders the work by operation rules and persists the task; the platform does not orchestrate the order itself |
| NICo Core | All reads; maintenance marks, quarantine, validation and decommissioning of a single device; expected inventory, OS definitions and instances | Single-object operations, with no ordering problem |

### 4.3 Dependencies

| Component | Role | Required |
| --- | --- | --- |
| NICo Core, REST, Flow | Foundation | Yes |
| RMS | Whole-rack hardware backend | Yes |
| NMX-C | NVLink domains | Yes |
| Temporal, PostgreSQL | Workflow engine and state storage | Yes |
| Vault, cert-manager, External Secrets, MetalLB | Credentials, certificates, service addresses | Yes |
| Rack validation service (RVS) | Validation before a rack becomes ready | As the NICo state machine requires |
| BMS and DSX Exchange | Facility-side leak events | Recommended for liquid-cooled sites |
| Prometheus, Grafana, Loki | Metrics and logs | Recommended |

The platform does not configure the internal parameters of these components. It does three things: installs them from a fixed list at deployment; checks on the site page whether they are ready; and when one is missing, shows the operations that depend on it as unavailable, with the reason.

## 5. Operations workflow

Site readiness and network planning are preparation: site readiness is done once, and network planning is extended when subnets are added. After that the main line has seven stages. Each stage has one entry point and one completion condition; while a stage has not passed, the entry point of the next one is unavailable.

![Figure 2: operations workflow](figures/workflow.png)

| Stage | Target state | Main activities | Completion condition |
| --- | --- | --- | --- |
| Site readiness | The platform and its dependencies are usable | Deploy the control plane; check each component and which rack profiles are supported | Every dependency on the site page is ready |
| Network planning | Every kind of device interface has a usable subnet | Plan the three kinds of subnet (out-of-band management, switch system management, host management) and their DHCP pools; confirm that gateways and DHCP relay are configured on the switches | The plan check passes: every purpose has a subnet, and the assignable addresses are no fewer than the device inventory needs |
| Inventory import | NICo holds the complete expected inventory | Upload the arrival inventory; the platform validates it, shows the difference, and writes it after confirmation | The expected inventory matches the file, and the rack profile is derived |
| Onboarding and reconciliation | The hardware matches the inventory | Power on; NICo discovers, probes and ingests through DHCP; the device discovery page shows how far each device has got, and rack reconciliation lists missing devices, wrong slots, wrong serial numbers, probe failures and cabling mismatches | Reconciliation has no blocking item, and the number of ready switches reaches what the rack profile requires |
| Rack bring-up | The rack is deliverable | Start bring-up on the rack; NICo completes firmware, NVOS, NMX-C configuration and rack validation in turn | The rack state is Ready and the NVLink domain is healthy |
| Delivery | Machines become usable resources | Choose a rack or a set of machines, and an installation profile or a tenant; install and accept, or hand over to the upper-layer platform | Instances are ready and accepted, or the upper-layer platform has received them |
| Running | State stays observable | Watch the health and alerts of racks, domains and trays; handle the items marked as needing attention | No unhandled blocking alert |
| Maintenance and change | Deliverable again after the change | Power, firmware update, maintenance, quarantine, tray replacement; the platform checks the impact and tracks the task | The task succeeds and the rack returns to Ready |
| Decommissioning | The device leaves safely | Confirm there is no instance; release, clean, decommission, and remove from the expected inventory | The object is decommissioned and the audit is closed |

How rack states map to stages: Created and Discovering belong to onboarding and reconciliation; Maintenance and Validating belong to bring-up and maintenance; Ready belongs to delivery and running; Error goes back to reconciliation or maintenance. Pages show NICo's state verbatim, and the stages are used for navigation only.

## 6. Module design

The platform has seven modules by responsibility. Every resource has a single place where it is maintained; other modules only refer to it.

| Module | Purpose | Resources it owns | Requirement chapters |
| --- | --- | --- | --- |
| Site | Whether the platform itself is usable | Site connection, component readiness | 6.6 |
| Network | Which subnet each kind of device interface uses, and whether DHCP is working | Nothing local; subnets, pools and address assignments are in NICo | 6.6 |
| Inventory | Turn the arrival inventory into NICo's expected inventory | Inventory versions and difference records | 6.1, 6.2 |
| Rack | The full lifecycle of racks and NVLink domains | Nothing local; everything is in NICo | 6.1, 6.2, 6.3, 6.4, 6.10 |
| Delivery | Turn ready machines into usable resources | Installation tasks and acceptance records | 6.5, 6.9 |
| Health | What is wrong now, whom it affects, where to handle it | Nothing local | 6.7 |
| Profiles and audit | Reusable choices, and who did what | Firmware baselines, installation profiles, operation audit | 6.4, 6.8 |

### 6.0 Navigation

Modules describe responsibilities; the menu describes entry points. The menu goes straight to objects: an operator who wants the address or firmware of a switch, or wants to power it, enters that device type from the menu without first finding which rack it is in. The rack page is the view that relates and summarises: from a rack you see all its members, its reconciliation and the rack-level operations, and from a device's rack and position you get back to the rack.

| Menu group | Menu item | Submenu | Module |
| --- | --- | --- | --- |
| 运维 (Operations) | 机柜管理 (Racks) | — | Rack |
| 运维 | NVLink 域管理 (NVLink domains) | — | Rack |
| 运维 | 设备管理 (Devices) | 计算托盘 (Compute trays), 交换机 (Switches), 供电框 (Power shelves), DPU | Rack |
| 运维 | 健康告警 (Health alerts) | — | Health |
| 运维 | 运维任务 (Operation tasks) | — | Rack |
| 运维 | 操作审计 (Operation audit) | — | Profiles and audit |
| 交付 (Delivery) | 机柜交付 (Rack delivery), 安装任务 (Installation tasks), 实例管理 (Instances) | — | Delivery |
| 接入 (Onboarding) | 网络规划 (Network planning) | — | Network |
| 接入 | 设备清单 (Device inventory) | — | Inventory |
| 接入 | 设备发现 (Device discovery) | — | Rack |
| 配置 (Configuration) | 站点设置 (Site settings) | — | Site |
| 配置 | 固件基线 (Firmware baselines), 安装方案 (Installation profiles) | — | Profiles and audit |

The three onboarding items are in the order they are used: plan the subnets, import the device inventory, then watch device discovery after power-on.

The menu has four groups, and only 设备管理 has a submenu, which can be collapsed. Menu names are formal four-character names, and page titles equal the menu names. A number on a menu item is always the count that needs attention. In the interface the three device types are collectively “设备” (devices); “计算托盘” (compute tray) is only the name of one type.

Interface text is Chinese throughout and does not join an English abbreviation with Chinese into one term: 安装方案, 交换机, 机柜上线, 就绪, 序列号, 开机 and 关机. Only product and component names (such as NICo, NVLink, RMS, BMC, DPU) and the state values reported by NICo state machines stay in their original form.

### 6.1 Site

- Shows whether NICo Core, Flow, RMS, NMX-C, the workflow engine and storage are ready, and the result of checking the current version combination against the hardware compatibility list.
- Subnets, DHCP and boot service addresses are not maintained here; see 6.7 Network.
- Shows the names of the power and firmware operation rules in effect; the rules themselves are site-level configuration.
- When a component is not ready, the operations that depend on it are shown as unavailable across the platform, with the reason.

### 6.2 Inventory

- The arrival inventory is the only manual input of the platform. It comes from DCIM or the shipping list: one table, one row per device, covering all three tray types.
- An import is a whole-table difference: it shows what is added, changed and removed, and writes NICo's expected inventory after confirmation. Removing a device that has an instance or a task in progress is refused.
- The rack profile is not filled in. NICo derives it from the domain's topology and the members' manufacturers; a failed derivation is reported at import.
- Credentials are not part of the inventory. Factory credentials are a site-level profile; NICo rotates and stores them at ingestion.
- Inventory files are versioned and can be used to rebuild the expected inventory.

Columns of the arrival inventory:

| Column | Meaning | Required |
| --- | --- | --- |
| rack | Rack ID, using the DCIM identifier | Yes |
| domain | NVLink domain ID; may equal the rack when a domain has one rack | Yes |
| type | compute, switch, power_shelf | Yes |
| slot | Slot in the rack | Yes |
| serial | Device serial number | Yes |
| bmc_mac | BMC MAC | Yes |
| vendor | Manufacturer, used to derive the rack profile | Yes |
| bmc_ip | Fixed BMC address; NICo assigns one when empty | No |
| host_mac, host_ip | Boot interface and fixed address of a compute tray; NICo assigns when empty | No |

### 6.3 Racks and devices

The same objects can be entered in two ways: through the rack to see how they relate, or through the device to operate it directly.

| View | Question it answers | Content |
| --- | --- | --- |
| Racks | Which step of the flow each rack is in, and which members it has | The rack list; the rack detail has reconciliation, the rack elevation, tasks, health and history, and the rack-level operations |
| NVLink domains | Whether firmware is consistent within a domain, and whether the domain can be delivered | Members, domain state and health, firmware baseline consistency; domain-level firmware update and domain-level power |
| Devices | How the device I am looking for is doing | Search across types (serial number, address, MAC, instance); the devices that need attention |
| Compute trays, switches, power shelves | The addresses, state and firmware of one device type, and which ones have problems | One list per type, with addresses and firmware versions in the table; power and other operations from the row, with batch support |
| DPU | Which DPUs are not ready, and which version they run | A read-only list; operations run through the owning compute tray |
| Tasks | How far rack-level operations have got | The stages and results of all Flow tasks |

- The default home page is the rack list. The rack detail is the view that relates and summarises: members are laid out by slot, and clicking a member opens its running state.
- Device pages are the entry point for daily operations. The table of each device type shows addresses and the main firmware version; each row has “运行状态” (running state), “上电 / 关机” (power on / off) and “操作” (operations).
- Reconciliation compares the expected inventory, what was measured, and the state machine. It lists missing devices, wrong slots, wrong serial numbers, probe failures and cabling mismatches, each with its cause and a way to handle it.
- Device discovery shows, across racks, each device's discovery stage (waiting for power, no DHCP request received, address obtained, probed, ingested), the probe result and a suggestion, and the devices DHCP has seen that are not in the device inventory. NICo completes discovery automatically, with no per-device confirmation. It and rack reconciliation are two views of the same data.
- Rack-level operations: bring-up, power on, power off, restart, firmware update, expected-versus-actual validation, decommissioning. Domain-level operations: domain firmware update (rolled out rack by rack in phases) and domain power.
- Device-level operations: power on, shut down, restart, firmware update, maintenance mark, quarantine, on-demand hardware validation, BMC restart, replacement, decommissioning. The available actions differ by type, and all of them use the same operation dialog.
- Device running state: running state, health alerts, firmware compared with the baseline, state timeline. A compute tray also has DPUs, its instance, hardware capabilities and LLDP neighbours; a switch also has NVOS management ports and Fabric Manager; a power shelf also has capacity and voltage.
- Rack objects are not created by hand. NICo creates one when it discovers a device carrying the same rack ID.

### 6.4 Delivery

- What is delivered is a rack or a set of ready machines. The default is a whole rack as one batch, without per-machine configuration.
- Two ways to deliver: choose an installation profile, install and accept; or hand the ready machines to a tenant or an upper-layer platform.
- Installation uses NICo's DHCP, PXE and templated OS. The installation process and the acceptance result are kept per task.
- Release goes through NICo's cleaning and re-validation; a machine is not shown as deliverable until cleaning has finished.
- Delivery is possible only when the rack is Ready, the NVLink domain is healthy, and there is no alert that prevents allocation.

### 6.5 Health

- Summarises the current health alerts of racks, NVLink domains and the three tray types, grouped by alert or by object, and marks the ones that prevent allocation.
- “需要处理” (needs attention) uses NICo's signals only: the state machine failed to process, the time limit of a state was exceeded, or there is a health alert.
- When no report has been received the page shows “未报告” (not reported), never healthy.
- Leak alerts come from tray sensors and from facility-side events; the site page says so when facility-side events are not connected.
- Curves, power and temperature link to the monitoring system; the pages do not rebuild them.

### 6.6 Profiles and audit

- Firmware baseline: a set of versions bound to a rack profile. A firmware update can only choose a baseline, never an arbitrary version.
- Installation profile: reusable system, disk and login defaults. Delivery can only choose a published profile.
- Audit: every write operation records the operator, object, action, reason, task number and the state read back. Records are append-only and never deleted.
- Roles: read-only cannot run operations; operator can run device, rack and delivery operations; administrator can also change the site, the network and installation profiles. Once the site's identity system is connected, the audit records a person.

### 6.7 Network

Subnets must be planned before the device inventory is imported. A device is discovered only after it gets an address according to the plan when it is powered on.

Device interfaces fall into three purposes, and each purpose has at least one subnet:

| Purpose | Device interfaces | NICo network type | Notes |
| --- | --- | --- | --- |
| Out-of-band management | Compute tray BMC, switch BMC, power shelf PMC | Underlay | The entry point of device discovery: these interfaces send DHCP requests, and NICo probes and ingests from them |
| Switch system management | Switch NVOS management port | Underlay | Configuration and management of a switch after ingestion |
| Host management | Compute tray host interface | HostInband | Network boot, installation and system management of the host |

Device types are discovered differently:

| Device | Discovery entry | Identity and ingestion | Completion criterion |
| --- | --- | --- | --- |
| Compute tray | The BMC sends a DHCP request on the out-of-band management subnet | Probe the BMC and read the serial number; the host then boots from the host management subnet and reports its hardware | The machine object is ready |
| Switch | The BMC on the out-of-band management subnet and the NVOS management port on the switch system management subnet each send a DHCP request | Probe the BMC and read the serial number; associate the NVOS management port, configure the certificate and rotate the password | The switch object is ready |
| Power shelf | The PMC sends a DHCP request on the out-of-band management subnet | Probe the PMC and read the serial number | The power shelf object is ready |
| DPU | Not discovered separately | Identified together with the owning compute tray | The owning compute tray is ready |

- Plan check: every purpose has a subnet, and the assignable addresses are no fewer than the device inventory needs. The device inventory cannot be imported while the check fails; the import preview recomputes it for the devices being added.
- Subnet: name, purpose, prefix, gateway, DHCP pool, assigned and assignable. Only the DHCP pool of an existing subnet can be changed.
- DHCP service: a whole-rack site uses NICo DHCP only. For each subnet the page shows the relay source, when a request was last received, and how much of the pool is used; a subnet that never receives a request is marked “未收到请求” (no request received). The boot service addresses (network boot, installation material, DNS, NTP) are maintained here.
- Address assignment: which interface of which device each address was given to. NICo assigns addresses from the fixed addresses in the device inventory or from the pool; they are not set by hand.
- The platform only creates subnets and pools in NICo and does not configure switches. The VLAN, gateway and DHCP relay of each subnet are site prerequisites.

## 7. Resources and state model

### 7.1 Resources and ownership

![Figure 3: resource relationships](figures/resources.png)

| Resource | Source | Identifier | Maintained in |
| --- | --- | --- | --- |
| Arrival inventory | Imported by hand | File version | Inventory |
| Expected domains, racks, trays | Generated from the arrival inventory, stored in NICo | Domain ID, rack ID, serial number and BMC MAC | Inventory |
| Rack | Created by NICo after discovery | Rack ID | Read-only; operations are in the rack module |
| NVLink domain | NICo and NMX-C | Domain ID | Read-only |
| Compute tray, switch, power shelf | Discovered and ingested by NICo | NICo object ID, serial number | Read-only; operations are in the rack module |
| DPU | Child object of a compute tray | NICo object ID | Read-only |
| Rack profile | Built into NICo, derived from the inventory | Profile ID | Read-only |
| Task | Flow | Task ID | The task view of the rack module |
| Instance | NICo | Instance ID | Delivery |
| Firmware baseline, installation profile | Profiles | Name and version | Profiles and audit |
| Audit record | The platform | Record ID | Read-only |

Relationship rules:

- Membership has one key: the rack ID. A slot has one source: the expected inventory.
- A tray belongs to a rack through the rack ID, and a rack belongs to an NVLink domain through the expected inventory.
- A task is the only execution record of a rack operation; the audit records only who submitted which task, when and why.
- The platform stores locally only inventory versions, profiles, installation tasks and the audit, all keyed by NICo identifiers.

### 7.2 States

Pages show the state reported by NICo's state machines verbatim and define no state names of their own.

| Object | States | What triggers a transition |
| --- | --- | --- |
| Rack | Created, Discovering, Maintenance, Validating, Ready, Error, Deleting | A device is discovered, the number of ready switches is reached, maintenance completes, a validation result, a child device fails, a maintenance request, a tray replacement |
| Tray | The states of NICo's state machine for each tray type | Discovery, ingestion, validation, allocation, release, failure, decommissioning |
| Task | Waiting, running, succeeded, failed, terminated | Submission, a stage completes, a stage fails, cancellation |
| Instance | NICo's instance lifecycle states | Allocation, installation, ready, release |

## 8. Module interaction and dependencies

### 8.1 Module dependencies

![Figure 4: module dependencies](figures/modules.png)

| Upstream | Downstream | What is passed | Gate |
| --- | --- | --- | --- |
| Site | Network | Component readiness | Subnets cannot be created while the site is not ready |
| Network | Inventory | The subnets and assignable addresses of each purpose | Import is refused while the plan check fails |
| Site | Inventory | Supported rack profiles | Import is refused while the site is not ready |
| Inventory | Rack | Expected racks, domains, trays | A rack without an expected inventory does not appear |
| Profiles | Rack | Firmware baseline | A firmware update can only choose a baseline |
| Rack | Delivery | Readiness of racks and trays | Delivery is refused while the rack is not Ready or the domain is unhealthy |
| Profiles | Delivery | Installation profile | Only a published profile can be chosen |
| Health | Rack, Delivery | Alerts that prevent allocation | Power-on and delivery are refused while there is a leak or an alert that prevents allocation |
| Rack, Delivery | Audit | Every submitted operation and its result | An operation is not submitted when the audit cannot be written |

### 8.2 Exclusion rules

- A rack has only one task in progress at a time.
- When a tray has an instance or an installation task in progress, an operation that would interrupt the tray first shows the affected instances and asks for confirmation; operations on switches and power shelves count the instances of the whole rack.

### 8.3 Behaviour when an external dependency is missing

| Missing | Affects | Page behaviour |
| --- | --- | --- |
| Flow | Rack bring-up, rack-level power, firmware rollout, tasks | These operations are unavailable, with the reason; reads and single-device operations continue |
| RMS | Power and firmware of trays, switches and power shelves | Same as above |
| NMX-C | NVLink domain formation and health | The domain is shown as not reported; delivery is refused |
| Facility-side events | Facility-side leak events | Only leaks from tray sensors are shown; the site page says the events are not connected |

## 9. Design of operations

Every write operation has the same shape: choose the object, choose the action, write the reason.

| Operation | Object | Input | Completion condition |
| --- | --- | --- | --- |
| Import inventory | Site | File | The state read back matches the file |
| Start bring-up | Rack | None | The rack is Ready |
| Power on, power off, restart | Rack, domain, tray | Action | The task succeeds and the power state read back matches |
| Firmware update | Rack, domain, tray | Firmware baseline | The task succeeds and the versions match the baseline |
| Expected-versus-actual validation | Rack, tray | None | No difference |
| Maintenance mark, quarantine | Tray | Reason | The state read back matches |
| On-demand hardware validation | Compute tray | None | The validation record completes |
| Delivery | A rack or a set of machines | Installation profile or tenant | Acceptance passes |
| Replace a tray | Tray | New serial number and BMC MAC | The rack returns to Ready |
| Decommission | Rack, device | Reason | The object is decommissioned |

Interaction rules:

- The confirmation shows four things only: object, action, number of affected instances, and the stages the task will go through. A high-risk action requires typing the rack ID or the serial number.
- After submission the user is taken to the task view. A task stops at the stage that fails and does not undo the hardware actions already completed; the pages do not promise a rollback.
- When a result is unknown the platform reads the state back first and never resends automatically; the operator decides the next step.
- Entry points that are not provided: typing an arbitrary firmware version, forcing a check to be skipped, per-machine timeouts and concurrency, direct hardware protocol operations.

## 10. Non-functional design

- Safety interlocks: breaker and coolant valve interlocks belong to the facility. A rack with a leak alert is refused power-on; the checks before power-on are configured in site rules and cannot be skipped by the operator.
- Blast radius: counted by rack and NVLink domain. An operation on one switch or power shelf affects every tenant in the rack, and the confirmation must show the number of affected instances.
- Firmware consistency: the smallest recommended unit of a firmware update is the NVLink domain; updating a single tray warns about version differences within the domain.
- Phased rollout: firmware for several racks goes to one rack first, then in batches with limited concurrency, and stops the remaining batches automatically after a failure.
- Delivery gate: NICo's native gate is used as is; the platform shows the reason and offers no bypass.
- Credentials: neither the inventory nor the pages contain device passwords; NICo rotates and stores them.
- Reliability: tasks are persisted by Flow, so a platform restart loses no task; before an upgrade the platform checks that no task is in progress.
- Backup: NICo's database and credential store must be backed up; arrival inventory files are kept by version.
- Scale: the default views aggregate by rack and domain, and lists do not call an interface per row.
- Version compatibility: the site page shows the current combination of NICo, RMS and rack profile, and the result of checking it against the compatibility list.
- Observability: pages show only the current state and where to handle it; time series go to the monitoring system.
- Delivery form: the platform and all its dependencies are delivered as one version-locked offline bundle.

## 11. Phases

| Phase | Focus | Outcome |
| --- | --- | --- |
| 1: inventory and reconciliation | Site checks, arrival inventory import, reconciliation views, health summary | From inventory import to reconciliation with no blocking item, without the command line |
| 2: rack lifecycle | Bring-up, power, firmware update, task view, audit | A rack bring-up and one complete maintenance done from the pages |
| 3: delivery | Installing and accepting by rack, handing over to the upper-layer platform, release and reuse | All compute trays of one rack delivered |
| 4: scale | Phased firmware rollout, identity system and roles, multi-domain views | Changes across racks are controlled and attributable |

## 12. Acceptance principles

1. Verify the closed loop of the flow: from inventory import to rack delivery, then one maintenance and one replacement, without the command line at any point.
2. Go by state and read-back: every operation has an explicit completion condition, and success is the state NICo reports back, not the request being accepted.
3. Verify failures first: cover missing devices, wrong slots, probe failures, firmware failures, interrupted tasks, leak alerts and unavailable dependencies.
4. Go by simplicity: the inputs of an operation are no more than object, action and reason; a fourth input sends the operation back to design review.
5. Go by auditability: for every write operation the operator, object, reason, task and result can be found.
6. Record three measures: the time from power-on to the rack being Ready, the number of reconciliation items handled by hand, and the number of manual steps per maintenance.

## 13. References

- NVIDIA Infra Controller documentation: https://docs.nvidia.com/infra-controller/documentation/home
- Key Capabilities: https://docs.nvidia.com/infra-controller/documentation/overview/key-capabilities
- Day 0, Day 1, and Day 2 Lifecycle: https://docs.nvidia.com/infra-controller/documentation/overview/day-0-day-1-day-2-lifecycle
- Rack, Machine, Switch and Power Shelf state machines: https://docs.nvidia.com/infra-controller/documentation/architecture/state-machines/rack-machine-switch-power-shelf
- NICo source: https://github.com/dsx-ai-factory/infra-controller
- Rack Management Service documentation: https://docs.nvidia.com/rms/documentation/home/
