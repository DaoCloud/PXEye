# Rack operations: capability requirements

**English** · [简体中文](rack-operations-requirements.zh-CN.md) · [Design documents](README.md)

- Version: v1.0, compiled on 2026-11-17.
- Nature: a complete description of the **target capabilities**, derived from the public NVIDIA Infra Controller (NICo) documentation, to show the whole of rack-level management. It does not state that PXEye implements them, nor that every item is achievable at a given site.
- Current state: what each item can actually do at a real site and how far PXEye has gone is in [scope and status](rack-operations.md); its capability comparison follows the numbering of section 6 here.

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

### 6.2 Topology and connections

- Identify and maintain host–DPU, device–port, node–interconnect domain and device–power domain relations.
- Combine information from LLDP, serial numbers, ports and management interfaces.
- Check topology consistency and identify missing, wrong, duplicate or unexpected links.
- Provide topology data for visualising racks, interconnect domains and resource domains.

### 6.3 Power and operation orchestration

- Power on, power off, restart and query state at device, tray, resource domain and rack level.
- Sequencing by dependency, concurrency control, timeouts, retries and rollback.
- Capacity, health, alert and occupancy checks before power-on.
- Power profiles, power budgets and coordination with an external power engine.
- A clear boundary between critical safety interlocks and low-level facility control.

### 6.4 Firmware, UEFI and DPU

- Firmware baselines by device type, model, site and version.
- Firmware inventory, difference detection, bulk update, result verification and isolation on failure.
- UEFI/Secure Boot, boot order, IOMMU, SR-IOV and lockdown policy.
- DPU OS, HBN, DPU firmware, DPU agent and configuration synchronisation.
- No unauthorised firmware rollback; versions and operations are audited.

### 6.5 Operating system installation and boot

- Multiple OS images, versions, architectures and installation parameters.
- DHCP, PXE/iPXE, cloud-init, boot order and installation result reporting.
- Installation templates chosen by device, resource type or instance type.
- Retry, timeout, cancel, rollback, isolation and manual takeover on failure.
- After installation, resource state and connection information that higher-level systems can consume.

### 6.6 Network and interconnect resources

- Management, out-of-band, host, tenant and service networks.
- Resource pools for IP, BGP, DNS, DHCP, loopback and VNI.
- VXLAN/EVPN, VRF and security policy for Ethernet.
- Port partitioning, P_Key and device reset for InfiniBand.
- NVLink domain formation, health check, partitioning and allocation gating.
- Idempotent network configuration, convergence checks and cleanup on tenant release.

### 6.7 Monitoring, alerting and rack health

- Collect data from BMCs, DPUs, servers, GPUs, interconnect, storage, power and environmental sensors.
- A health model for devices, trays, racks, interconnect domains and power domains.
- Metrics, logs, events, alerts, state changes and audit records correlated in one place.
- Rack overview, device matrix, topology view, power view and deliverable-resource view.
- Alert severity, suppression, aggregation, notification, acknowledgement, escalation and closure.
- Policy-triggered graceful shutdown, resource isolation, allocation stop and recovery.

### 6.8 Security and trust

- TPM 2.0, Secure Boot, Measured Boot and remote attestation.
- BMC, UEFI and other management credentials maintained per device.
- Out-of-band management first; unsafe in-band management paths are restricted.
- Security checks before delivery and re-attestation after release.
- NVMe/SAS/SATA secure erase, result verification and isolation on failure.
- Audit of security events, policy changes, credential operations and critical actions.

### 6.9 Delivery, release and reuse

- Instance types, resource pools, allocation and reclamation.
- Device, firmware, network, interconnect, power and health checks before delivery.
- Network, route, address, partition and metadata associations withdrawn on release.
- A resource is not marked reusable before cleaning completes.
- Re-discovery, re-validation, reinstallation and re-delivery.

### 6.10 Faults, repair and retirement

- A quarantine state with entry and exit conditions.
- Targeted reprovisioning, repair labels, ticket association and re-acceptance after repair.
- Retirement of devices, switches, power devices and rack resources.
- Access control for asset migration, site migration, record retention and forced deletion.
- Recovery, retry and manual takeover for every exceptional flow.

## 7. Suggested core state model

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

| Stage | Focus | Result |
| --- | --- | --- |
| 1: Basic enrollment | Asset model, device discovery, BMC/Redfish, basic topology, state machine, audit | Devices can be connected, inventoried, queried and operated at a basic level |
| 2: Installation and initialization | Firmware baseline, DPU initialization, DHCP/PXE/iPXE, OS installation, basic network | An automated flow from device connection to system boot |
| 3: Delivery and isolation | Resource pools, instance types, Ethernet/IB/NVLink partitions, release cleanup | Resources can be delivered, isolated, released and safely reused |
| 4: Rack-level orchestration | Power sequencing, tray and NVL domain orchestration, power coordination, rack workflows | Rack-level maintenance and operations with complex dependencies |
| 5: Monitoring and intelligent operations | Rack health, BMS, leak, alert policy, automatic isolation and recovery | Monitoring, alerting, response and closed-loop operations |
| 6: Scale and ecosystem | Multiple sites, adapters, higher-level APIs, ticket, monitoring and identity integration | Large deployments and cooperation with external systems |

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
