# Rack operations: capability requirements

**English** · [简体中文](rack-operations-requirements.zh-CN.md) · [Design documents](README.md)

- Requirements baseline: v1.0, 2026-11-17, compiled from the public NVIDIA Infra Controller (NICo) documentation.
- Status checked: 2026-11-19, against the Core interfaces of a general server site; interfaces and fields are in the [data contract](rack-operations-data-contract.md).
- This document is maintained for the long term. The requirement items describe target capabilities; the “Implementation status” under each functional area records facts and changes with development. The pages and plan of the current stage are in [scope and status](rack-operations.md).

## Use and maintenance

### How to use it

- Planning a feature: find the functional area in section 6 it belongs to, read its implementation status and conclusion, then decide whether and how to build it.
- Reviewing a change: check that it updated the implementation status of its functional area.
- Arriving at a new site: after checking the interfaces with the data contract, update “What NICo Core provides”.

| Status | Meaning |
| --- | --- |
| present | The main requirements of the area have a usable feature |
| partial | Part of the area is usable; the conclusion says what is not |
| not started | No corresponding feature yet |
| not surveyed | Core's actual capability has not been checked |

Requirement items are targets. “Present” or “partial” does not mean every item is met; the current state and conclusion in the table are authoritative.

### When it must be updated

In these cases, update this document in the same commit, in both languages:

1. A feature is added, changed or removed: update “PXEye today”, “Pages” and the status of its functional area.
2. A requirement turns out not to be achievable, or is built differently from what it says: update “Conclusion and next step”; when the requirement item itself no longer holds, change the item.
3. What Core provides changes, for example with a new version or a new kind of site: update “What NICo Core provides”.
4. An item is dropped: say so in the conclusion, with the reason.
5. A new requirement or functional area appears: add it to section 6.

State the current conclusion; do not append dated sections, Git keeps the history. Change the “Status checked” date above with every update. Only conclusions belong here; page details go to scope and status, interface details to the data contract.

## 1. Purpose

This document defines the overall scope, capability layers, lifecycle stages, functional requirements and boundaries of rack-level infrastructure management and installation. It is the common basis for product design, architecture, interface design, work breakdown and acceptance testing. It focuses on a reusable capability model and engineering requirements, and does not prescribe a particular deployment target, industry or business use.

It draws on the bare-metal lifecycle, device orchestration, network isolation, trust management and rack-level operations described in the public NICo documentation, combined with what a rack-level infrastructure platform needs.

## 2. Goals

- Establish one model for racks, devices, topology, resources and lifecycle.
- Manage a device in a closed loop from connection, discovery, validation, initialization, installation, delivery and operation to release and retirement.
- Orchestrate power, network, compute, storage, accelerated interconnect and environmental safety, and keep their states consistent.
- Provide monitoring, alerting, policy response and audit for racks and their parts.
- Support automated operations and integration with higher-level orchestration through standard APIs, state machines and workflows.
- Make delivery, tenant change, fault handling and retirement secure, traceable and verifiable.

## 3. Scope and boundaries

### 3.1 In scope

- Unified management of racks, trays, servers, GPUs, DPUs, BMCs, switches, interconnect devices, storage, power and environmental sensors.
- Device discovery, asset modelling, topology identification, hardware acceptance, firmware baselines, DPU initialization and operating system installation.
- Ethernet, InfiniBand and NVLink, with their isolation, partitioning and resource allocation.
- Rack-level power orchestration, health monitoring, alerting, fault isolation, maintenance and recovery.
- Device delivery, release, secure cleaning, repair, re-enrollment and retirement.

### 3.2 Out of scope

- Tenant business software, applications and scheduling policy.
- Full low-level closed-loop control of data centre facility systems; the platform receives state through standard interfaces and orchestrates above them.
- Every proprietary management function of a vendor's device; these are reached through adapters or standard protocols.
- Application-level configuration and business initialization after the operating system is installed.

## 4. Capability architecture

| Capability domain | Main responsibility | Key objects |
| --- | --- | --- |
| Resources and assets | Manage racks, devices, components, resources and topology in one place | Racks, trays, servers, GPUs, DPUs, BMCs, storage, interconnect, power |
| Lifecycle orchestration | Drive device stage transitions through state machines and workflows | Discovery, validation, initialization, installation, operation, release, retirement |
| Devices and firmware | Apply device configuration, firmware baselines and version compliance | BMC, UEFI, DPU, GPU, switches, interconnect devices |
| Network and interconnect | Configure isolation, partitions, addresses and routing resources | Ethernet, InfiniBand, NVLink, VPC, VRF, VNI, P_Key |
| Power and environment | Power on, power off, coordinate power and respond to safety events | Power shelves, trays, power domains, BMS, temperature and leak sensors |
| Installation and delivery | Install systems through PXE/iPXE and deliver resources | OS images, boot configuration, instance types, resource pools |
| Monitoring and operations | Collect metrics, logs and events and trigger policy responses | Health, alerts, events, maintenance, faults, audit |
| Security and trust | Assure device identity, trusted boot, credential safety and tenant cleaning | TPM, Secure Boot, UEFI, BMC credentials, erasure and attestation |

## 5. Lifecycle stages

| Stage | Target state | Main activities | Completion condition |
| --- | --- | --- | --- |
| Connection preparation | Physical and network conditions ready | Racking, cabling, power, management network, sensors and dependent services | The device is reachable on the management network |
| Discovery and modelling | A trusted asset and topology record | Redfish/LLDP/serial discovery, asset registration, component pairing, topology identification | Asset data is complete and relations can be explained |
| Validation and admission | The device meets pre-delivery quality | SKU check, link tests, burn-in, firmware baseline, trust check | Validation passes, or the device is quarantined |
| Initialization and configuration | The device can run | DPU OS, HBN, BMC/UEFI, network, IP, DHCP/DNS configuration | The device is ready for installation |
| System installation | The target operating system is installed and boots | PXE/iPXE, image deployment, boot order, security settings, installation result report | The system boots and pre-delivery checks pass |
| Resource delivery | An allocatable resource unit | Network isolation, interconnect partitioning, instance types and allocation | The resource is usable |
| Continuous operation | Stable, compliant and observable | Health monitoring, firmware maintenance, capacity and power management, alert response | State stays observable and deviations can be handled |
| Release and reuse | Resources recovered safely and prepared for the next delivery | Network cleanup, media erasure, TPM clear, re-validation | No residual configuration, and admission passes again |
| Repair and retirement | A fault closed or a safe exit | Targeted reprovisioning, repair marks, isolation, removal, asset migration | State and audit records are closed |

## 6. Functional requirements

### 6.1 Racks and assets

- A hierarchy of racks, trays, devices, components and resources.
- A unique identifier, serial number, position, role, state, site and relations for each device.
- Automatic discovery, manual entry, bulk import and change audit.
- Relations between a device and its rack, tray, host, DPU, BMC, interconnect and power.
- Asset state queries, change history, labels and search.

**Implementation status: partial**

| What NICo Core provides | PXEye today | Conclusion and next step | Pages |
| --- | --- | --- | --- |
| Device list, serial numbers, hand-declared `rack_id`; rack objects only at whole-rack sites; no rack unit position | Device management and rack topology exist; display order is stored by PXEye; discovery diagnostics lists the exploration result and failure reason of each BMC address; server unit positions are imported by CSV on the server page, stored by PXEye, shown on the server page and used to order the compute section of the rack topology | Present. Unit positions are recorded by PXEye only, not in NICo; the rack in the import is compared with the device's rack, not written. No change audit | Rack topology, device management, device management → Discovery diagnostics |

### 6.2 Topology and connections

- Identify and maintain host–DPU, device–port, node–interconnect domain and device–power domain relations.
- Combine information from LLDP, serial numbers, ports and management interfaces.
- Check topology consistency and identify missing, wrong, duplicate or unexpected links.
- Provide topology data for visualising racks, interconnect domains and resource domains.

**Implementation status: partial**

| What NICo Core provides | PXEye today | Conclusion and next step | Pages |
| --- | --- | --- | --- |
| LLDP neighbours of servers, with the peer switch name, model and serial (verified); the network topology interface returns nothing | The server page shows uplink switches; the status dialog lists every neighbour; the cabling page groups ports by switch and marks a port reported by more than one interface; switch names and panel port names can be imported by CSV, are stored by PXEye and are shown on the cabling page | Viewing actual connections and finding conflicts are done; imported names are for display only and are not written to NICo. Comparing intended and actual cabling is not, for lack of an intended cabling source | Device management → Servers, Cabling |

### 6.3 Power and operation orchestration

- Power on, power off, restart and query state at device, tray, resource domain and rack level.
- Sequencing by dependency, concurrency control, timeouts, retries and rollback.
- Capacity, health, alert and occupancy checks before power-on.
- Power profiles, power budgets and coordination with an external power engine.
- A clear boundary between critical safety interlocks and low-level facility control.

**Implementation status: partial**

| What NICo Core provides | PXEye today | Conclusion and next step | Pages |
| --- | --- | --- | --- |
| Desired and actual power state; host power through the host BMC (`AdminPowerControl`); tray, switch and power shelf power through RMS when the component manager backends are `rms`; rack maintenance (`OnDemandRackMaintenance`) for whole racks only, whose power sequence is a graceful restart of the compute hosts; rack power on/off are stubs in NICo; rack cold reboot exists only in RMS; no power readings | Power state is shown. With `rackActions` on: host power, tray, switch and power shelf power, and rack maintenance from the operation dialog and the Racks page, with server-side preview, serial confirmation for high risk, read-back and an audit record ([rules for operations](rack-operations-actions.md)) | Implemented, not verified at a site. RMS-backed actions need RMS deployed; the operations NICo does not provide are shown disabled with the reason. No sequencing across devices beyond NICo's rack maintenance. A rack power total cannot be built from Core | Device management → Servers, Switches, Power shelves, Racks, Operation records |

### 6.4 Firmware, UEFI and DPU

- Firmware baselines by device type, model, site and version.
- Firmware inventory, difference detection, bulk update, result verification and isolation on failure.
- UEFI/Secure Boot, boot order, IOMMU, SR-IOV and lockdown policy.
- DPU OS, HBN, DPU firmware, DPU agent and configuration synchronisation.
- No unauthorised firmware rollback; versions and operations are audited.

**Implementation status: partial**

| What NICo Core provides | PXEye today | Conclusion and next step | Pages |
| --- | --- | --- | --- |
| Per-machine firmware inventory, lockdown state, secure boot state (verified); update interfaces exist; the verification site has no host firmware baseline | The server status dialog shows the actual firmware version of each component, the model, part number, lockdown and secure boot state | Inventory done. With `rackActions` on, compute tray, switch and rack component firmware updates (`UpdateComponentFirmware`, through RMS) can be started, not verified at a site; NICo does not implement power shelf firmware updates. Difference detection and compliance lack a host firmware baseline | Device management → Servers (status dialog), Switches, Racks |

### 6.5 Operating system installation and boot

- Multiple OS images, versions, architectures and installation parameters.
- DHCP, PXE/iPXE, cloud-init, boot order and installation result reporting.
- Installation templates chosen by device, resource type or instance type.
- Retry, timeout, cancel, rollback, isolation and manual takeover on failure.
- After installation, resource state and connection information that higher-level systems can consume.

**Implementation status: present**

| What NICo Core provides | PXEye today | Conclusion and next step | Pages |
| --- | --- | --- | --- |
| OS definitions, instance allocation and boot intent interfaces; DHCP and PXE services | Installation tasks, operating systems and installation profiles exist; supported scope is in [features and boundaries](features.md) | Main line of the product, outside rack operations development | Installation tasks, operating systems, installation profiles |

### 6.6 Network and interconnect resources

- Management, out-of-band, host, tenant and service networks.
- Resource pools for IP, BGP, DNS, DHCP, loopback and VNI.
- VXLAN/EVPN, VRF and security policy for Ethernet.
- Port partitioning, P_Key and device reset for InfiniBand.
- NVLink domain formation, health check, partitioning and allocation gating.
- Idempotent network configuration, convergence checks and cleanup on tenant release.

**Implementation status: partial**

| What NICo Core provides | PXEye today | Conclusion and next step | Pages |
| --- | --- | --- | --- |
| Segment, VPC, InfiniBand and NVLink partition interfaces exist | Network management covers installation segments only | Not part of this work | Network management |

### 6.7 Monitoring, alerting and rack health

- Collect data from BMCs, DPUs, servers, GPUs, interconnect, storage, power and environmental sensors.
- A health model for devices, trays, racks, interconnect domains and power domains.
- Metrics, logs, events, alerts, state changes and audit records correlated in one place.
- Rack overview, device matrix, topology view, power view and deliverable-resource view.
- Alert severity, suppression, aggregation, notification, acknowledgement, escalation and closure.
- Policy-triggered graceful shutdown, resource isolation, allocation stop and recovery.

**Implementation status: partial**

| What NICo Core provides | PXEye today | Conclusion and next step | Pages |
| --- | --- | --- | --- |
| Health alerts and health history per object (verified); no time series; no dedicated leak or liquid-cooling interface | The server page shows health and alerts; the status dialog shows health history (start, last seen and recovery of each alert); the alerts page groups the current alerts of servers, switches and power shelves by alert or by device | Per-device health and history and a read-only roll-up of current alerts are done. Acknowledgement, suppression and notification are not. Policy-triggered actions are not done; the manual operations they would use (graceful shutdown, quarantine, maintenance mark) exist under `rackActions` ([rules for operations](rack-operations-actions.md)). Charts need a monitoring system | Device management → Servers, Switches, Power shelves, Alerts |

### 6.8 Security and trust

- TPM 2.0, Secure Boot, Measured Boot and remote attestation.
- BMC, UEFI and other management credentials maintained per device.
- Out-of-band management first; unsafe in-band management paths are restricted.
- Security checks before delivery and re-attestation after release.
- NVMe/SAS/SATA secure erase, result verification and isolation on failure.
- Audit of security events, policy changes, credential operations and critical actions.

**Implementation status: not surveyed**

| What NICo Core provides | PXEye today | Conclusion and next step | Pages |
| --- | --- | --- | --- |
| Attestation and measurement read interfaces exist | Not covered | Not surveyed; not in this stage | — |

### 6.9 Delivery, release and reuse

- Instance types, resource pools, allocation and reclamation.
- Device, firmware, network, interconnect, power and health checks before delivery.
- Network, route, address, partition and metadata associations withdrawn on release.
- A resource is not marked reusable before cleaning completes.
- Re-discovery, re-validation, reinstallation and re-delivery.

**Implementation status: partial**

| What NICo Core provides | PXEye today | Conclusion and next step | Pages |
| --- | --- | --- | --- |
| Instance allocation and release interfaces; instance type interfaces exist | An instance is created on first installation; instance management lists and releases them | Resource pools, instance types and verification of release cleaning are not done; outside rack operations development | Instance management |

### 6.10 Faults, repair and retirement

- A quarantine state with entry and exit conditions.
- Targeted reprovisioning, repair labels, ticket association and re-acceptance after repair.
- Retirement of devices, switches, power devices and rack resources.
- Access control for asset migration, site migration, record retention and forced deletion.
- Recovery, retry and manual takeover for every exceptional flow.

**Implementation status: partial**

| What NICo Core provides | PXEye today | Conclusion and next step | Pages |
| --- | --- | --- | --- |
| Quarantine, maintenance marks, machine validation, SKU and decommission interfaces exist; at the verification site validation was skipped and there is no SKU | The status dialog shows quarantine, maintenance, the state timeline (states passed through and time in each) and hardware validation runs. With `rackActions` on: maintenance mark, quarantine, host reset, BMC reset, on-demand validation, SKU check, switch and power shelf decommission, each with an audit record ([rules for operations](rack-operations-actions.md)) | Viewing partly done. Operations implemented, not verified at a site; switch reset needs RMS. Ticket association is a free-text reason only | Device management → Servers, Switches, Power shelves, Operation records |

## 7. Suggested core state model

Implementation rule: pages show the state text the NICo state machine reports and define no state names of their own. The table below groups stages conceptually for discussion and documentation; its entries are not values shown on a page.

| Object | Suggested states | Transition triggers |
| --- | --- | --- |
| Rack | Pending, connecting, validating, available, in maintenance, isolated, retired | Physical connection, validation result, maintenance task, fault policy, retirement |
| Device | Discovered, validating, compliant, configuring, installable, running, releasing, isolated, retired | Discovery, validation, initialization, installation, allocation, release, fault, removal |
| Resource unit | Allocatable, reserved, configuring, allocated, releasing, cleaning, unavailable | Allocation, workflow execution, release, cleaning result |
| Workflow | Pending, running, succeeded, failed, timed out, cancelled, rolling back | Operation request, dependencies met, exception, manual intervention |

## 8. Non-functional requirements

- Reliability: critical workflows are idempotent and support retry, timeout, resumption and persisted state.
- Security: control-plane services use mutual authentication; sensitive credentials are managed centrally; critical operations use least privilege and are fully audited.
- Observability: every resource, workflow, device operation and state change can be queried in relation to the others.
- Extensibility: device integration uses an adapter model for different vendors, models and protocols.
- Consistency: resource state, network state, observed device state and desired state are distinguishable and converge.
- High availability: the control plane runs on multiple nodes, and the failure of a critical service does not lose asset data.
- Performance: scale horizontally by site, rack and device count, with configurable concurrency and rate limits.
- Compatibility: prefer standard interfaces such as Redfish, IPMI, LLDP, PXE/iPXE, BGP, DNS, DHCP and Prometheus.

## 9. Suggested stages

| Stage | Focus | Result | PXEye progress |
| --- | --- | --- | --- |
| 1: Basic enrollment | Asset model, device discovery, BMC/Redfish, basic topology, state machine, audit | Devices can be connected, inventoried, queried and operated at a basic level | Partial: discovery, enrollment and basic topology exist; operations and their audit records are implemented under `rackActions`, not verified at a site |
| 2: Installation and initialization | Firmware baseline, DPU initialization, DHCP/PXE/iPXE, OS installation, basic network | An automated flow from device connection to system boot | Partial: OS installation exists; firmware baseline not started; DPU initialization is done by NICo, not PXEye |
| 3: Delivery and isolation | Resource pools, instance types, Ethernet/IB/NVLink partitions, release cleanup | Resources can be delivered, isolated, released and safely reused | Partial: instances are created and released; partitions and pools not started |
| 4: Rack-level orchestration | Power sequencing, tray and NVL domain orchestration, power coordination, rack workflows | Rack-level maintenance and operations with complex dependencies | Partial: the Racks page shows NICo rack objects and starts or terminates NICo rack maintenance (through RMS), not verified at a site; rack power on/off and cold reboot are not provided by NICo |
| 5: Monitoring and intelligent operations | Rack health, BMS, leak, alert policy, automatic isolation and recovery | Monitoring, alerting, response and closed-loop operations | Partial: read-only per-device health |
| 6: Scale and ecosystem | Multiple sites, adapters, higher-level APIs, ticket, monitoring and identity integration | Large deployments and cooperation with external systems | Not started |

These stages follow the capability targets. The order PXEye actually takes is in section 9 of [scope and status](rack-operations.md).

## 10. Acceptance principles

1. Verify along the lifecycle loop: not only single device operations but the full flow from connection to release.
2. Judge by state and result: every asynchronous operation has a defined desired state, observed state, success condition and failure reason.
3. Verify faults first: device offline, firmware failure, network not converging, power anomaly, sensor alert, erase failure and workflow interruption.
4. Require safe reuse: a released resource is delivered again only after network cleanup, data cleaning and re-validation.
5. Require audit: a critical operation records who started it, the object, time, parameters, result, error and the recovery action that followed.

## 11. References

- [What is NICo?](https://docs.nvidia.com/infra-controller/documentation/overview/what-is-nico)
- [Key Capabilities](https://docs.nvidia.com/infra-controller/documentation/overview/key-capabilities)
- [Day 0, Day 1, and Day 2 Lifecycle](https://docs.nvidia.com/infra-controller/documentation/overview/day-0-day-1-day-2-lifecycle)
- [Hardware Prerequisites](https://docs.nvidia.com/infra-controller/documentation/getting-started/prerequisites/hardware)
- [Reference Installation](https://docs.nvidia.com/infra-controller/documentation/getting-started/installation-options/reference-installation)
