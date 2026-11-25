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

- NICo is the source of truth and the execution engine: once a device is written to NICo, its state is what NICo says. The platform adds the interface, the device planning, the enrollment of devices and their matching to the planning, and the gating of operations, and does not rebuild what NICo already provides.
- Device import, device discovery, system configuration and operating system installation follow the flow, fields and backend interfaces of the existing product. Whole-rack operations only add fields to them, and add the rack layer: rack registration, bring-up and rack-level operations.
- The device is the base object, and the rack is a layer on top of devices. The address, state, firmware and single-device operations of a device are managed by device; the rack is the unit of operation only for what holds for a whole rack at once (bring-up, rack-wide power and firmware, rack maintenance). One NVL72 rack is one NVLink domain.
- Objects, states and operations mean what they mean in NICo: a rack offers only the operations NICo defines on the rack object; installing an operating system and instances exist only on a single machine. What the platform adds (device operations started for a whole rack, the inventory check, the rack elevation) is stated as such on the page.
- Device data has a single manual input: the device planning, which gives the type, serial number, rack and slot of each device, and the planned addresses of its management interface and management controller. Models and current addresses come from discovery; site-level configuration is prepared once at deployment and checked item by item by the platform.
- An operation takes at most three inputs: object, action, reason. Order, timeouts and retries are decided by site-level rules and are not filled in per operation. The per-machine configuration used to install an operating system has defaults for every item, so by default it only has to be reviewed.
- Every write operation can be previewed, tracked and audited; an unknown result is never resent automatically.
- Critical safety interlocks stay with the facility. The platform does not replace them and only refuses an operation when it detects a risk.

## 3. Scope and boundaries

### 3.1 In scope

- Inventory, discovery and state management of racks, NVLink domains, compute trays, switch trays (NVLink switches) and power shelves; servers that do not belong to a rack are included as well.
- Enrolling racks and bringing them up; tracking the progress of rack maintenance, terminating it, and running it again after a failure; power on and off and firmware updates of racks and devices; maintenance, quarantine, replacement and decommissioning of devices; deleting a rack.
- Installing an operating system machine by machine with acceptance, and viewing and releasing instances.
- A health summary of racks, domains and trays, with entry points for handling alerts.
- Profiles such as firmware baselines and installation profiles, and the audit of every write operation.

### 3.2 Out of scope

- Closed-loop control on the facility side, such as circuit breakers and coolant valves; the building management system (BMS) owns it.
- Configuration of devices NICo does not manage, such as access switches and rack PDUs.
- Storing and displaying time series such as metric curves, power and temperature; the monitoring system owns them, and the platform only links to it.
- Cluster assembly and workload scheduling, such as Kubernetes and SLURM.
- Multi-tenancy: managing tenants, instance types and quotas, and creating NVLink logical partitions. The platform creates instances one machine at a time under the site's default tenant and does not hand machines out to other platforms.
- Adapting to non-standard networks; this does not enter the main flow. Servers that do not belong to a rack are covered by device management and installation, but adapting to their models is not described in this document.
- Deployments in which NICo manages the DPUs (DPU mode). In this version the BlueField cards of a compute tray are used as network cards only (network-card mode). The DPU page is kept and states what is supported; DPU mode is left to a later phase, and 6.3 describes how the two differ.
- Power and firmware operations at the level of an NVLink domain, and phased firmware rollout across racks.

## 4. Architecture

![Figure 1: platform architecture](figures/architecture.png)

### 4.1 Layers and responsibilities

| Layer | Component | Main responsibility | Key objects |
| --- | --- | --- | --- |
| Operator interface | PXEye | Device planning, device discovery and enrollment, matching to the planning, gating of operations, task tracking, audit, profiles | Device planning, device configuration, credentials of switches and power shelves held until registration, profiles, audit, installation tasks |
| Orchestration | NICo REST and Flow | Orders rack-level power and firmware operations in steps by operation rules and persists tasks; powers a rack off automatically on a rack-level leak | Tasks, operation rules |
| Facts and state | NICo Core | Device declarations, probing and ingestion, the state machines (rack bring-up is run by the rack state machine on its own), health, subnets and addresses, OS definitions and instances | Racks, domains, trays, NVLink partitions, instances |
| Hardware backend | RMS (Rack Management Service) | Carries out power, reset and firmware on trays, switches and power shelves | Hardware protocols and per-device ordering |
| Interconnect | NMX-C | Forms and partitions NVLink domains | NVLink domains, partitions |
| Boot | NICo DHCP, PXE, Scout | Address assignment, network boot, hardware discovery and preparation | Leases, boot artifacts |
| Facility | BMS, DSX Exchange | Leak events, breaker and coolant valve interlocks | Leak events |
| Observability | Prometheus, Grafana, Loki | Metrics, logs | Curves, logs |

### 4.2 Access paths

The platform reaches NICo through two paths, with one rule: an operation that must be ordered across several devices goes through a Flow task, and everything else goes to Core. The bring-up task of a new rack also goes through Flow; the rack maintenance that follows once the switches are ready is not submitted by the platform, and Core's rack state machine runs it on its own.

| Path | Used for | Why |
| --- | --- | --- |
| NICo REST and Flow | Bring-up of a new rack, power on and off and firmware of racks and trays, expected-versus-actual validation, querying and cancelling tasks | Flow orders the work by operation rules and persists the task; the platform does not orchestrate the order itself |
| NICo Core | All reads; device declarations; running rack maintenance again and terminating it; deleting a rack; maintenance marks, quarantine, validation and decommissioning of a single device; OS definitions and instances | Single-object operations, with no ordering problem |

Two accesses do not go through NICo, and both follow the existing product: after a device is powered on and has an address, the operator enters the BMC user name and password in device discovery, and the platform reads the device's BMC once to get the device type, serial number and model; and when a BMC address is updated to the plan, the platform writes to the device's BMC directly. Apart from these the platform does not access devices directly.

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

The workflow has two parts. The first is the onboarding of a new rack, from site preparation to delivery, in eight stages (P1–P8). The second is the running period that follows: running, maintenance and change, and decommissioning (P9–P11). Every stage has a unique identifier, a responsible party, an entry condition and an exit condition; a stage does not start until the exit condition of the stage before it is met.

Onboarding a new rack needs a person's confirmation at four points: enrollment, rack registration, bring-up and delivery. The four are independent: enrollment puts a device under the platform's management, and writes the declaration of a server to NICo at the same time; rack registration writes the rack and its membership to NICo; bring-up makes the rack ready; installing an operating system belongs to delivery and is done machine by machine. Enrollment and delivery follow the flow of the existing product; rack registration and bring-up are new for whole-rack operations.

The workflow in this chapter is about a whole rack. A server that does not belong to a rack goes through only P3 planning import, P5 discovery and enrollment, the matching to the planning in P6, and P8 delivery; it has no rack registration and no P7 bring-up: NICo powers it on and ingests it at its first operating system installation; see P5 and P8 in 5.4.

### 5.1 Overview

![Figure 2: operations workflow](figures/workflow.png)

| ID | Stage | Responsible | How it starts | Entry condition | Exit condition |
| --- | --- | --- | --- | --- | --- |
| P1 | Site preparation | Administrator | Once per site | The management cluster is available | Every dependency on the site page is ready, and rack profiles are configured |
| P2 | Network preparation | On-site staff, administrator | Once per batch of racks | P1 complete | The plan check passes |
| P3 | Planning import | Operator | Once per batch of racks | P1 and P2 complete | The device planning is saved and the rack profile is derived |
| P4 | Racking and cabling | On-site staff | Once per rack | P2 complete | The rack is connected to power, and the three kinds of management interface are on their subnets |
| P5 | Discovery and enrollment | Operator | Manual, once the rack is connected to power | P3 and P4 complete | Every device in the planning is enrolled, or the missing ones are confirmed |
| P6 | Matching and registration | Operator | Manual confirmation | P5 complete | The planning is written to the device configuration; the rack and its members are registered in NICo |
| P7 | Bring-up | Operator | Manual confirmation, then automatic | P6 complete | The rack state is Ready and the NVLink domain is formed |
| P8 | Delivery | Operator | Manual confirmation | P7 complete | Instances are ready and accepted |
| P9 | Running | Operator | Continuous | P8 complete | No unhandled critical alert |
| P10 | Maintenance and change | Operator | On demand | P7 complete | The task succeeds and the rack returns to Ready |
| P11 | Decommissioning | Operator | On demand | No instance on the device | The devices are decommissioned; a rack whose members are all decommissioned is deleted; the audit is closed |

P3 and P4 do not depend on each other and can run in parallel.

How rack states map to stages: no rack object in NICo yet corresponds to P3–P6; Discovering, Maintenance (with its current stage) and Validating correspond to P7; Ready corresponds to P8–P10; Error needs a person to remove the cause and run rack maintenance again. Pages show NICo's state verbatim, and the stages are used for navigation only.

### 5.2 Roles and responsibilities

| Role | Responsibilities | Stages |
| --- | --- | --- |
| On-site staff | Racking, cabling and connecting the rack to power; configuring subnets and DHCP relay on the management switches | P2, P4 |
| Administrator | Deploying the platform and its dependencies; site configuration; subnet planning | P1, P2 |
| Operator | Importing the device planning; device discovery and enrollment; matching to the planning; confirming rack registration, bring-up and delivery; operations in the running period | P3, P5–P11 |
| Platform | Validating and saving the device planning; reading device identity; writing device configuration and device declarations; submitting and tracking tasks; audit | P2–P11 |
| NICo | Address assignment; probing and ingesting devices; executing the bring-up task and rack maintenance; instances and boot | P5–P11 |

### 5.3 Devices and management interfaces

Every activity in the workflow acts on one interface of one kind of device. An NVL72 rack contains three kinds of device:

| Device | Management interface | Subnet | Purpose |
| --- | --- | --- | --- |
| Compute tray | BMC | Out-of-band management | Power control, reading hardware information, BIOS settings |
| Compute tray | Host interface | Host management | Network boot, operating system installation and system management of the host |
| Compute tray | BMC of a BlueField card | Out-of-band management | In this version a BlueField card works in network-card mode; NICo probes it and does not manage it |
| Switch | BMC | Out-of-band management | Power control, reading hardware information |
| Switch | NVOS management port | Switch system management | Configuring the switch system, certificates and NMX-C |
| Power shelf | PMC | Out-of-band management | Power control, reading state |

Below, BMC and PMC are together called the management controller. The number of devices of each kind is defined by the rack profile. Management switches and facility systems are not managed by NICo: on-site staff configure the subnets, gateways and DHCP relay of the former, and the latter provide power, liquid cooling and leak detection.

### 5.4 Onboarding a new rack

![Figure 3: onboarding a new rack](figures/onboarding.png)

#### P1 Site preparation

- Purpose: make the platform and its dependencies available, and settle the site-level configuration.
- Responsible: administrator.
- Entry condition: the management cluster is available.
- Exit condition: every dependency on the site page is ready, and rack profiles are configured.

| ID | Activity | Performed by |
| --- | --- | --- |
| P1-1 | Deploy the platform, NICo Core, DHCP and the boot services | Administrator |
| P1-2 | Deploy the dependencies a whole rack needs; see 4.3 | Administrator |
| P1-3 | Configure rack profiles: the number of devices of each kind and the firmware list | Administrator |
| P1-4 | Configure site policy: BlueField cards work in network-card mode; storing switch NVOS credentials is enabled; the site credential used after ingestion is set | Administrator |

#### P2 Network preparation

- Purpose: provide usable subnets and addresses for the three kinds of management interface.
- Responsible: on-site staff, administrator.
- Entry condition: P1 complete.
- Exit condition: the plan check passes.

| ID | Activity | Performed by |
| --- | --- | --- |
| P2-1 | On the management switches, configure a VLAN and gateway for each of the three subnets: out-of-band management, switch system management, host management | On-site staff |
| P2-2 | Configure DHCP relay for each subnet, pointing at the service address of NICo DHCP | On-site staff |
| P2-3 | Create the three subnets and their DHCP pools in the platform | Administrator |
| P2-4 | Run the plan check: every purpose has a subnet, and the assignable addresses are no fewer than the interfaces of the racks in the inventory need | Platform |

P2-1 and P2-2 come before P2-3: the platform only creates subnets in NICo and does not configure switches.

#### P3 Planning import

- Purpose: save the plan of each device, as the basis for the matching and registration that follow. The flow, template and saving rules follow “设备规划” (device planning) in the existing product.
- Responsible: operator.
- Entry condition: P1 and P2 complete.
- Exit condition: the device planning is saved and the rack profile is derived.

| ID | Activity | Performed by |
| --- | --- | --- |
| P3-1 | Prepare the device planning: one row per device, with device type, serial number, rack and slot, and the planned addresses of the management interface and the management controller | Operator |
| P3-2 | Fill in device credentials: user name and password of the BMC or PMC; a switch also needs the user name and password of NVOS | Operator |
| P3-3 | Import the planning and choose the rack topology and manufacturer; the platform validates row by row, derives the rack profile and gives a preview: to add, to update, unchanged, validation failed | Operator, platform |
| P3-4 | Check the preview and save. The batch cannot be saved while any row fails validation | Operator, platform |

This stage only saves the planning: nothing is written to NICo, no device is enrolled automatically, and no address is pushed to a device.

#### P4 Racking and cabling

- Purpose: complete the physical installation of the rack and put its management interfaces on their subnets.
- Responsible: on-site staff.
- Entry condition: P2 complete.
- Exit condition: the rack is connected to power, and the three kinds of management interface are on their subnets.

| ID | Activity | Performed by |
| --- | --- | --- |
| P4-1 | Position the rack and connect power and liquid cooling | On-site staff |
| P4-2 | Connect the management cables: BMCs and PMCs to the out-of-band management subnet, NVOS management ports to the switch system management subnet, host interfaces to the host management subnet | On-site staff |
| P4-3 | Check the hardware against the device planning: rack identifier, slots, serial numbers | On-site staff |
| P4-4 | Connect the rack to power | On-site staff |

This stage follows the installation procedures of the device manufacturers; the platform takes no part in it.

#### P5 Discovery and enrollment

- Purpose: confirm what each powered device is, and add it to managed devices. The flow follows “发现设备” (discover devices) in the existing product.
- Responsible: operator; the platform reads the device identity.
- Entry condition: P3 and P4 complete.
- Exit condition: every device in the planning is enrolled, or the missing ones are confirmed.
- Constraint: no power-on, no BIOS change, no disk access, no firmware update; the addresses of the management controllers do not change.

| ID | Activity | Performed by | Compute tray | Switch | Power shelf |
| --- | --- | --- | --- | --- | --- |
| P5-1 | Management controllers request addresses and appear in the device discovery list | NICo | The BMC gets an address from the out-of-band pool | The BMC gets an address from the out-of-band pool | The PMC gets an address from the out-of-band pool |
| P5-2 | Get device information: enter the user name and password of the management controller, for one device or a batch | Operator, platform | Device type, serial number, model | Device type, serial number, model, MAC addresses of the NVOS management ports | Device type, serial number |
| P5-3 | Check the device information and add the device to managed devices | Operator, platform | The device declaration is written to NICo: MAC of the BMC, credentials, serial number; with the pause flag; BlueField in network-card mode | Enrolled locally in the platform only, not written to NICo | Enrolled locally in the platform only, not written to NICo |
| P5-4 | Log in to the management controller and change its password | NICo | The BMC password becomes the site credential | Not done; left to P6 | Not done; left to P6 |

The BMC of a BlueField card also gets an out-of-band address in this stage, but it is not enrolled separately and is handled with its compute tray. A batch get of device information uses one set of credentials for all the selected devices, 1–50 at a time; a device with a different password shows an authentication failure and is then read on its own, and other passwords are never tried one after another. A device that is not in the planning can be enrolled too, and becomes a server with no plan that does not belong to a rack.

#### P6 Matching and registration

- Purpose: write the planning into the configuration of the enrolled devices, and register the rack and its members in NICo.
- Responsible: the operator confirms; the platform and NICo carry it out.
- Entry condition: P5 complete.
- Exit condition: the planning is written to the device configuration; the rack-level declarations are written, and every enrolled member of the rack carries its rack and slot.
- Constraint: no power-on, no BIOS change, no disk access, no firmware update, no operating system installation; the addresses of the management controllers do not change.

| ID | Activity | Performed by | Compute tray | Switch | Power shelf |
| --- | --- | --- | --- | --- | --- |
| P6-1 | One-click match: write the row of the device planning with the same serial number into the device configuration. Only the configuration in the platform changes | Operator, platform | Boot NIC MAC, management IP, management subnet, planned BMC address, rack and slot | Planned BMC address, rack and slot | Planned PMC address, rack and slot |
| P6-2 | Register rack: write the rack-level declarations, namely rack group, rack and NVLink domain | Operator, platform | — | — | — |
| P6-3 | Write or update the device declarations | Platform | The existing declaration gets the rack and slot; the pause flag stays | Written: MAC of the BMC, MAC addresses of the NVOS management ports (the primary one marked), credentials of the BMC and of NVOS, rack | Written: MAC of the PMC, credentials, rack |
| P6-4 | Log in to the management controller and change its password | NICo | Already done in P5 | The BMC password becomes the site credential | The PMC password becomes the site credential |
| P6-5 | Create the device object | NICo | Not created: the pause flag keeps NICo from powering on or ingesting it | Created, waiting for the NVOS management port to come up | Created and Ready |

One-click match follows the existing product, 1–50 devices at a time; whole-rack operations only add two items to what it writes, the rack and the slot. Register rack is a step added for whole-rack operations and takes only the members that are enrolled and already matched; a member enrolled and matched after the registration goes through P6-3 to P6-5 automatically. A planned BMC address written to the device configuration has not taken effect yet; it takes a separate “更新 BMC 地址” (Update BMC address), see P10 in 5.7.

Enrollment and matching apply to devices; the rack itself has only the rack-level declarations of P6-2. A server that does not belong to a rack goes through P6-1 only and is not registered to a rack; it has no P7, and NICo powers it on and ingests it at its first installation in P8.

#### P7 Bring-up

- Purpose: make the rack ready.
- Responsible: the operator confirms; NICo executes the bring-up task, device ingestion and rack maintenance.
- Entry condition: P6 complete.
- Exit condition: the rack state is Ready, all three kinds of device are Ready, and the NVLink domain is formed.
- Constraint: no operating system installation, no instance creation.

The bring-up task, submitted by the operator and executed in order:

| ID | Activity | Performed by | Compute tray | Switch | Power shelf |
| --- | --- | --- | --- | --- | --- |
| P7-1 | Start bring-up and submit the bring-up task | Operator | — | — | — |
| P7-2 | Power on the power shelves | NICo | — | — | Powered on, and the power state confirmed |
| P7-3 | Power on the compute trays and release them for ingestion | NICo | Powered on; the pause flag removed | — | — |
| P7-4 | Compute tray firmware | NICo | Updated when the version differs from the expected one | — | — |
| P7-5 | Power on the switches | NICo | — | Powered on, and the power state confirmed | — |
| P7-6 | Check switch firmware | NICo | — | Version consistency checked, not updated | — |
| P7-7 | Restart the compute trays | NICo | Restarted so that the firmware takes effect | — | — |

Device ingestion, done by NICo on its own after a device is powered on or released:

| ID | Activity | Performed by | Compute tray | Switch | Power shelf |
| --- | --- | --- | --- | --- | --- |
| P7-8 | Ingest the device | NICo | Correct the BMC clock; set BIOS and boot order; boot the discovery program from the host management subnet, which assigns the host management address; report the hardware inventory; validate the hardware; lock the BIOS; read the observed slot. All disks may be cleaned, depending on site policy | Associate the NVOS management port; configure the certificate; change the NVOS password and store it in the credential store; read the observed slot; validate | Already Ready since P6 |

Rack maintenance, done by NICo on its own once the number of ready switches reaches what the rack profile requires:

| ID | Activity | Performed by | Compute tray | Switch | Power shelf |
| --- | --- | --- | --- | --- | --- |
| P7-9 | Firmware upgrade | NICo | Updated from the rack profile's firmware list; skipped when no list is configured | Same | Same |
| P7-10 | NVOS update | NICo | — | The switch system is updated; skipped when no firmware list is configured | — |
| P7-11 | Power sequence | NICo | Powered on again in order when required | Same | Same |
| P7-12 | NMX-C cluster configuration | NICo | — | Switch certificates, Fabric Manager and the primary switch certificate are configured; the NVLink domain is formed when this completes | — |
| P7-13 | Rack validation | NICo | Runs when the site has enabled rack validation | Same | Same |

Rack maintenance has one start condition: the number of ready switches is not less than the switch count in the rack profile. A missing compute tray or power shelf does not affect rack maintenance and only raises an alert that the rack has fewer members than its profile. Rack maintenance has no manual confirmation switch and its order cannot be changed. While it runs, the operator can terminate it; the rack then enters Error and rack maintenance has to be run again.

#### P8 Delivery

- Purpose: install an operating system on ready servers so that they become usable compute resources.
- Responsible: the operator confirms; the platform and NICo carry it out.
- Entry condition: for a compute tray in a rack, P7 complete; for a server that does not belong to a rack, P5 complete and a boot NIC MAC present (from the one-click match of P6-1, or filled in in the system configuration).
- Exit condition: instances are ready and accepted.
- Scope: servers only, that is, compute trays in a rack and servers that do not belong to a rack. Switches and power shelves have no activity in this stage.
- Constraint: installation is per machine, one instance per machine. A rack is not the object of installation, only a filter when choosing devices.

| ID | Activity | Performed by |
| --- | --- | --- |
| P8-1 | Choose devices: filter by rack, choose across racks, or choose servers that do not belong to a rack | Operator |
| P8-2 | Review the configuration each machine will use: host name, installation profile, system disk, management IP and boot NIC. It comes from the system configuration in device management, with defaults for what was not filled in; change a machine when needed. This step runs no check | Operator |
| P8-3 | Installation-condition check: the platform checks device identity, installation configuration and operating system materials on each machine, and the operator confirms once everything passes. The check result is valid for 15 minutes | Platform, operator |
| P8-4 | NICo powers on and ingests a server that has not been ingested yet (only a server outside a rack, at its first installation) | NICo |
| P8-5 | Create one instance per machine; the instance name is the host name | Platform, NICo |
| P8-6 | The server boots the installer from the network and writes the operating system to the system disk | NICo, platform |
| P8-7 | Acceptance: check the host name, system disk and network, and verify with a restart | Platform |

The host name is also the instance name, and after installation it is the host name inside the system; NICo does not assign it, and when it was not filled in the platform generates it from the serial number, by the rule of the existing product. The management IP, boot NIC MAC and management subnet are written from the device planning into the system configuration by the one-click match of P6-1, and this stage only reviews them. The flow, check items, execution stages and acceptance items of this stage follow the installation task of the existing product. All instances are created under the site's default tenant, and the pages do not show a tenant.

### 5.5 Device state and impact on devices

The state of the three kinds of device at the end of each stage:

| At the end of | Compute tray | Switch | Power shelf |
| --- | --- | --- | --- |
| P4 Racking and cabling | BMC powered, host off | BMC powered | PMC powered |
| P5 Discovery and enrollment | Enrolled, declaration written to NICo with the pause flag, not powered on | Enrolled, locally in the platform only | Enrolled, locally in the platform only |
| P6 Matching and registration | Registered to the rack, not powered on, no device object in NICo | Registered, the device object waits for the NVOS management port | Ready |
| P7 Bring-up | Ready, can be allocated | Ready | Ready |
| P8 Delivery | Each chosen compute tray has one instance, operating system installed | Unchanged | Unchanged |

The impact of each stage on devices:

| Stage | Power | Management password | BIOS | Disks | Firmware | Addresses |
| --- | --- | --- | --- | --- | --- | --- |
| P4 Racking and cabling | Only the management controllers are powered | Unchanged | Unchanged | Unchanged | Unchanged | — |
| P5 Discovery and enrollment | Unchanged | The BMC password of compute trays becomes the site credential | Unchanged | Unchanged | Unchanged | The management controllers use the addresses assigned from the pool |
| P6 Matching and registration | Unchanged | The switch BMC and PMC passwords become the site credential | Unchanged | Unchanged | Unchanged | Unchanged; planned addresses are only written to the device configuration, and the address update is run separately |
| P7 Bring-up | Powered on and restarted | The NVOS password is changed | The BIOS of compute trays is changed and locked | All disks may be cleaned, depending on site policy | Updated when it differs from the expected version | The host management address is decided |
| P8 Delivery | Restarted | Unchanged | Unchanged | The system disk is written | Unchanged | Unchanged |

The observed slot is read by NICo from the hardware backend after it ingests a device in P7-8; compute trays and switches have one, power shelves do not. The planned slot is therefore checked against the observed slot after P7; before P6 the only thing that can be checked is whether the devices in the planning have been enrolled.

### 5.6 Manual confirmation points

| Confirmation | Stage | What the platform shows before confirmation | Activities that follow automatically | Undo |
| --- | --- | --- | --- | --- |
| Add to managed devices | P5 | The device type, serial number and model that were read, and which row of the planning the device corresponds to | P5-3, P5-4 | The management password of a compute tray has been changed and is not restored automatically; returning devices means decommissioning them one by one |
| Register rack | P6 | The number of members taken, the number enrolled but not yet matched, the number in the planning not yet enrolled, what will and will not be done | P6-2 to P6-5 | The management passwords of switches and power shelves have been changed and are not restored automatically; returning devices means decommissioning them one by one |
| Start bring-up | P7 | The number of registered members, whether the switches are all there, the steps of the bring-up task, the impact on devices | P7-2 to P7-13 | The bring-up task can be cancelled, but hardware actions already done are not undone; rack maintenance can be terminated, and the rack then enters Error |
| Confirm installation | P8 | The chosen devices and the configuration each will use (host name, installation profile, system disk, management IP); the result of the installation-condition check; the devices that have to be ingested first and their disk-cleaning scope | P8-4 to P8-7 | After the instance is deleted, the device is cleaned and validated again and can then be installed again |

### 5.7 Running period

| ID | Stage | Main activities | Completion condition |
| --- | --- | --- | --- |
| P9 | Running | Watch the health and alerts of racks, NVLink domains and devices; handle the items marked as needing attention | No unhandled critical alert |
| P10 | Maintenance and change | Power, firmware update, maintenance mark, quarantine, tray replacement, updating BMC addresses to the plan; the platform checks the impact and tracks the task | The task succeeds and the rack returns to Ready |
| P11 | Decommissioning | Devices are decommissioned one by one: confirm there is no instance, decommission, and remove from the device planning. When all members of a rack are decommissioned, delete the rack | The devices are decommissioned; the rack object is deleted; the audit is closed |

Chapter 9 gives the inputs and completion conditions of the operations in the running period.

### 5.8 Exception handling

| Stage | Exception | Handling |
| --- | --- | --- |
| P2 | The plan check fails | Create the missing subnet, or enlarge the DHCP pool |
| P3 | The derived rack profile is not configured | The administrator configures the profile in site settings, then the planning is imported again |
| P3 | Rows of the planning fail validation | The preview states the reason row by row; correct the file and preview again, and save only when every row passes |
| P5 | A device gets no address | Check that the device has power, that its management cable is on the right subnet, and that DHCP relay works for that subnet |
| P5 | Authentication fails | Enter credentials for that device alone and get its device information again |
| P5 | The serial number is not in the planning | The device can still be enrolled, as a device with no plan; when it has to go into a rack, add or correct its row in the device planning, then run one-click match |
| P6 | Some devices fail to be written | The reason is shown per device and the write can be retried; devices already written are not rolled back |
| P7 | The bring-up task fails at a step | The task stops at that step and hardware actions already done are not undone; submit it again after removing the cause |
| P7 | Switches are missing | Rack maintenance does not start. Add the switches; when the rack must be brought up with fewer, the administrator adjusts the switch count in the rack profile |
| P7 | Rack maintenance fails at a stage | The rack stops in Error and does not recover by itself; run rack maintenance again after removing the cause |
| P7 | Running rack maintenance has to be stopped | Terminate rack maintenance; the rack enters Error; run it again after removing the cause |
| P8 | A host name is not valid, or is the name of an existing instance | Shown per machine before submission; the review step opens only after it is corrected |
| P8 | The installation-condition check does not pass | Each failing item is listed with its device and reason; change the configuration or remove the cause, check again, and submit only after it passes |
| P8 | Installation or acceptance fails | Handled as a failed installation task; see 6.4 |
| P9 | Rack-level leak | NICo forces the whole rack off on its own and refuses power-on; after the facility side has handled it and the alert has cleared, the operator submits power-on |

### 5.9 Design premises and open items

The workflow rests on the premises below. When a premise does not hold, the stages listed for it have to be adjusted.

| ID | Premise | Stages affected |
| --- | --- | --- |
| A1 | After the rack is connected to power only the management controllers are powered; the main power of devices stays off until the bring-up task powers them on | P6, P7 |
| A2 | A management controller can be read with the credentials the operator enters to get the device type, serial number and model | P5 |
| A3 | The BMC of a switch can report the MAC addresses of its NVOS management ports | P5, P6 |
| A4 | Management controllers use addresses assigned dynamically from the out-of-band pool when connected to power; after enrollment they can be updated to the planned fixed addresses | P5, P6, P10 |
| A5 | BlueField cards work in network-card mode, and the host gets its address from the host management subnet | P2, P7, P8 |

Open items: how the bring-up task and rack maintenance interleave when they run at the same time; how the planned management IP becomes an address assignment in NICo (this follows the “同步设备规划” (Sync device plan) stage of the installation task in the existing product, and has not been checked in a whole-rack environment); the entry point that syncs switches and power shelves to NICo is not enabled yet in the existing product, and rack registration depends on it.

## 6. Module design

The platform has seven modules by responsibility. Every resource has a single place where it is maintained; other modules only refer to it.

| Module | Purpose | Resources it owns | Requirement chapters |
| --- | --- | --- | --- |
| Site | Whether the platform itself is usable | Site connection, component readiness | 6.6 |
| Network | Which subnet each kind of device interface uses, and whether DHCP is working | Nothing local; subnets, pools and address assignments are in NICo | 6.6 |
| Inventory | The device planning and how it compares with the configuration of enrolled devices | The planning and its versions, device credentials held until registration | 6.1, 6.2 |
| Racks and devices | The state and single-device operations of devices; the full lifecycle of racks and NVLink domains | Nothing local; everything is in NICo | 6.1, 6.2, 6.3, 6.4, 6.10 |
| Delivery | Install an operating system on ready servers, machine by machine, and manage instances | Installation tasks and acceptance records | 6.5, 6.9 |
| Health | What is wrong now, whom it affects, where to handle it | Nothing local | 6.7 |
| Profiles and audit | Reusable choices, and who did what | Firmware baselines, installation profiles, operation audit | 6.4, 6.8 |

### 6.0 Navigation

Modules describe responsibilities; the menu describes entry points. The menu goes straight to objects. The device is the base object: an operator who wants the address or firmware of a switch, or wants to power it, enters that device type from the menu without first finding which rack it is in. The rack is a layer on top of devices: the rack page holds only what NICo defines on the rack object (state, bring-up, rack-wide power and firmware, rack maintenance, deletion) and a summary of the member devices; the information and operations of a member device are on the device page, and a device's rack and position lead back to the rack. Installing an operating system is per machine, and its entry point is 安装任务 (Installation tasks), not the rack.

| Menu group | Menu item | Submenu | Module |
| --- | --- | --- | --- |
| 运维 (Operations) | 机柜管理 (Racks) | — | Racks and devices |
| 运维 | NVLink 域管理 (NVLink domains) | — | Racks and devices |
| 运维 | 设备管理 (Devices) | 服务器 (Servers), 交换机 (Switches), 供电框 (Power shelves), DPU | Racks and devices |
| 运维 | 健康告警 (Health alerts) | — | Health |
| 运维 | 运维任务 (Operation tasks) | — | Racks and devices |
| 运维 | 操作审计 (Operation audit) | — | Profiles and audit |
| 交付 (Delivery) | 安装任务 (Installation tasks), 实例管理 (Instances) | — | Delivery |
| 接入 (Onboarding) | 网络规划 (Network planning) | — | Network |
| 接入 | 设备清单 (Device inventory) | — | Inventory |
| 接入 | 设备发现 (Device discovery) | — | Racks and devices |
| 配置 (Configuration) | 站点设置 (Site settings) | — | Site |
| 配置 | 固件基线 (Firmware baselines), 安装方案 (Installation profiles) | — | Profiles and audit |

The three onboarding items are in the order they are used: plan the subnets, import the device inventory, then watch device discovery after power-on.

The menu has four groups, and only 设备管理 has a submenu, which can be collapsed. Menu names are formal four-character names, and page titles equal the menu names. A number on a menu item is always the count that needs attention. In the interface the three device types are collectively “设备” (devices): 服务器 (servers), 交换机 (switches) and 供电框 (power shelves). A server need not belong to a rack; a server in a rack is called a “计算托盘” (compute tray).

Interface text is Chinese throughout and does not join an English abbreviation with Chinese into one term: 安装方案, 交换机, 机柜上线, 就绪, 序列号, 开机 and 关机. Only product and component names (such as NICo, NVLink, RMS, BMC, DPU) and the state values reported by NICo state machines stay in their original form.

### 6.1 Site

- Shows whether NICo Core, Flow, RMS, NMX-C, the workflow engine and storage are ready.
- Rack profiles: how many compute trays, switches and power shelves each profile has, and which firmware list it uses. A rack profile is NICo site configuration, and NICo has no interface to change it; an administrator adjusts it here, and the platform updates NICo's site configuration and restarts NICo in a rolling way. The switch count is the minimum threshold for rack maintenance to start.
- Subnets, DHCP and boot service addresses are not maintained here; see 6.7 Network.
- Automation guide: some things the system does on its own, and the operator does not see them happen. One table says, per scenario, when it starts, what the system does on its own and what a person has to do, covering connecting a rack to power, new rack bring-up, power on, power off and restart, firmware update and a rack-level leak. Read-only.
- When firmware is updated: on two occasions only, new rack bring-up (when the rack profile has a firmware list) and a firmware update submitted by a person. Otherwise nothing is updated automatically; a device whose version differs from the baseline is only marked.
- When a component is not ready, the operations that depend on it are shown as unavailable across the platform, with the reason.

### 6.2 Inventory

- The device planning is the only manual input of device data. It comes from DCIM or the shipping list: one table, one row per device, covering all three tray types. The flow, the column names of the template and the saving rules follow “设备规划” (device planning) in the existing product.
- The planning is a separate piece of data. An import only saves the planning: it writes nothing to NICo, enrolls no device automatically and pushes no address. Only after a device is enrolled in device discovery and “一键匹配” (one-click match) is run on the device page are the management interface, the planned address of the management controller, the rack and the slot from the planning written into the device's configuration.
- An import has two steps: validate and preview, then save. The preview marks each row as to add, to update, unchanged or validation failed; the batch cannot be saved while any row fails validation. A preview is valid for 15 minutes. A file is at most 1 MiB and 5000 rows.
- When an existing plan is updated, an empty cell in the file keeps the existing value; to clear a value, change the row with “编辑规划” (edit plan). The device type of an existing plan cannot be changed; the serial number of a plan that is already linked to a NIC collected from the hardware cannot be changed.
- Configuration comparison: each row shows whether the plan and the configuration of the enrolled device agree, in the wording of the existing product: “未纳管” (Not enrolled), “存在差异” (Differs), “配置一致” (Consistent). When a row differs, run one-click match on the device page.
- A server that does not belong to a rack is in the planning too, with the rack and slot left empty. Switches and power shelves must belong to a rack.
- The rack profile is derived from the rack topology and rack manufacturer chosen at import. The rack topology is NICo's name for a rack hardware layout (for example gb200_nvl72r1_c2g4); the choices are read from the rack profiles NICo has configured, and the platform does not maintain that list. The import preview reports an error when NICo has not configured the derived profile.
- Device credentials are written in the rows of the planning. A password is submitted only at import or edit and is held encrypted; it never appears on a page, in a version record or in the audit. After the device declaration is written to NICo the credentials are NICo's, and the platform no longer keeps them.
- Planning files are versioned, and the password columns are removed before a file is kept.

Columns of the device planning. The first 14 are the same as in the existing product, and the last 3 are added for whole-rack operations:

| Column | Meaning | Required |
| --- | --- | --- |
| kind | server, switch, power_shelf | Yes |
| serial | Device serial number, the only thing a device is matched by | Yes |
| management_ip, management_mac, management_subnet | Planned management IP, MAC of the management interface and management subnet of a server, for servers only. When the management IP or the management subnet is filled in, the MAC of the management interface is required | No |
| bmc_ip, bmc_mac, bmc_username, bmc_password | Planned address, MAC and credentials of the BMC of a server or switch | No |
| pmc_ip, pmc_mac, pmc_username, pmc_password | Planned address, MAC and credentials of the PMC of a power shelf | No |
| rack | Rack ID, using the DCIM identifier | Required for a device in a rack |
| slot | Slot in the rack. Added for whole-rack operations | Required for a device in a rack |
| nvos_username, nvos_password | User name and password of the switch NVOS. Added for whole-rack operations | Required for a switch |

The import also asks for the rack topology and rack manufacturer; together they decide the rack profile.

### 6.3 Racks and devices

The device is the base object, and the rack is a layer on top of devices. The same objects can be entered in two ways: through the device to operate it directly, or through the rack to see the rack as a whole. Three rules divide the work:

- The address, state, firmware and single-device operations of a device are maintained on the device page only; the rack page refers to them and summarises, and links to the device page.
- The rack page offers only the operations NICo defines on the rack object, with the state, health and profile of the rack.
- What the platform adds is stated as such on the page: rack registration, the inventory check, the rack elevation.

| View | Question it answers | Content |
| --- | --- | --- |
| Racks | Which step of the flow each rack is in, and which members it has | The rack list; the rack detail has rack registration, starting bring-up, rack maintenance progress, the inventory check, the rack elevation, tasks, health and history, and the rack-level operations |
| NVLink domains | Whether a domain is formed, and which partitions it has | For each domain: whether NMX-C is reachable, the domain health, the number of switches whose Fabric Manager is healthy, and the NVLink partitions. Read-only |
| Devices | How the device I am looking for is doing | Search across types (serial number, address, MAC, instance); the devices that need attention |
| Servers, switches, power shelves | The addresses, state and firmware of one device type, and which ones have problems | One list per type, enrolled devices only, with addresses and firmware versions in the table; power and other operations from the row, with batch support; one-click match and updating BMC addresses are here too. The server page lists both the compute trays in racks and the servers that do not belong to a rack |
| DPU | How each BlueField card is operating, and whether that matches the policy | A read-only list: serial number, owning compute tray, BMC address, policy, observed operating mode, NIC firmware; it states that this version supports network-card mode only |
| Device discovery | Which devices have an address and are not enrolled yet | The discovered endpoints; getting device information and adding to managed devices, for one device or a batch |
| Tasks | How far rack-level power and firmware operations have got | The steps and results of all Flow tasks |

- The default home page is the rack list. It contains every rack in the device planning; a rack that has no object in NICo yet is shown as “尚未建立” (not created yet). Rack objects are not created by hand: NICo creates one when the first member device is ingested.
- One NVL72 rack is one NVLink domain, so there are no domain-level power or firmware operations. A domain has two identifiers: the rack group ID from the device planning, and the domain ID reported by NMX-C after rack bring-up. The page shows both. Neither domains nor partitions are maintained on this page: a domain is declared automatically at rack registration from the racks in the device planning; logical partitions are not created in the platform in this version, and the ones that exist in NICo are shown here read-only; the matching NMX partition is created by NICo when the first instance joins.
- Discovery and enrollment, matching and registration, and bring-up of a new rack follow the stage definitions in 5.4; 5.5 gives the impact of each stage on devices and 5.6 the manual confirmation points. Where they appear on the pages: getting device information and adding to managed devices are in “设备发现” (device discovery); one-click match is on the device page; rack registration and starting bring-up are in the rack detail, each as a card that lists in two columns what will and will not be done; the progress of the bring-up task is on the task tab of the rack detail, and the progress of rack maintenance is shown separately at the top of the rack detail.
- Inventory check: two kinds of difference. One is a device that is in the planning but not enrolled yet; the other is a device whose observed slot differs from the slot in the planning. The observed slot is what NICo gets from the hardware backend RMS after ingesting the device, and RMS reads it from the tray's BMC; compute trays and switches have one, power shelves do not, and it exists only after bring-up. The check helps a person see the situation and does not hold bring-up back: rack maintenance does not start while switches are missing, and a missing compute tray or power shelf, or a slot difference, does not affect it. The switch count is the minimum threshold for rack maintenance to start and is written in the rack profile; bringing a rack up with fewer switches requires an administrator to adjust that count in site settings.
- Rack-level operations: starting bring-up, power on, power off, restart, firmware update, expected-versus-actual validation, terminating rack maintenance while it runs and running it again when the rack has stopped in Error, and deleting the rack. These are all the write operations NICo defines on the rack object. A rack has no operation that installs an operating system or creates instances. A rack object has no power state, so the page shows how many of its members are powered on.
- Device discovery and enrollment: follows the existing product. Device discovery lists the endpoints that have an address in the out-of-band subnet and belong to no device yet; the operator enters the BMC user name and password to get device information (one device, or 1–50 devices sharing one set of credentials), checks it, and adds the device to managed devices. The declaration of a server is written to NICo at this point, with the pause flag; switches and power shelves are at first enrolled locally in the platform only.
- One-click match: follows the existing product. Select enrolled devices on the device page, and the row of the device planning with the same serial number is written into the device configuration: the boot NIC MAC, management IP and management subnet of a server, the planned address of the management controller, and for whole-rack operations also the rack and slot. Only the configuration in the platform changes, 1–50 devices at a time; after the planning is changed, the match has to be run again.
- Register rack: new for whole-rack operations. The 登记机柜 (Register rack) on the rack detail writes the rack-level declarations of that rack, syncs the rack's enrolled and matched switches and power shelves into NICo declarations, and adds the rack and slot to the declarations of its compute trays.
- Deleting a rack: it deletes the rack object only and does not handle the member devices. The preconditions are that the rack has no instance, every member device has been decommissioned, and no task is in progress; the page shows whether each one holds, and the deletion cannot be submitted until all of them do.
- Device-level operations: power on, shut down, restart, firmware update, maintenance mark, quarantine, on-demand hardware validation, BMC restart, replacement, decommissioning. The available actions differ by type, and all of them use the same operation dialog. Decommissioning is a per-device operation, and all three device types have it.
- System configuration: the configuration a server uses at its next installation. Its fields follow the existing product: boot NIC MAC, management IP, management subnet, host name, current installation profile and system disk for the next installation, plus the device override settings, which are collapsed by default. Every item has a default: the three management-interface items are brought in from the device planning by one-click match, the host name is generated from the serial number (by the rule of the existing product, and used as it is when none was filled in), the installation profile is the default of the architecture, and the system disk follows the disk rule of the profile. The BMC address in the existing dialog belongs to “更新 BMC 地址” (Update BMC address), and the other interfaces are not managed by the platform; neither part is shown. Saving writes to the platform only, not to NICo. The system configuration has three entry points that open the same dialog and write the same data: the row of each server in the device inventory, the server list and the running state on the device page, and a click on a machine while an installation task reviews the configuration. A device has a system configuration only after it is enrolled; before that, what is changed is the device planning. It can be changed while the device has an instance or an installation task in progress, and the change affects only the next installation.
- Planning and updating BMC addresses: follows the existing product. When a device is connected to power its BMC gets an arbitrary address of the pool; the planned address comes with the device planning and is written to the device configuration by one-click match, and can also be filled in and changed per device on the device page. One update covers 1–256 devices. The update is started by hand: select devices, review current address against planned address, and confirm; four steps then run in turn, namely check address and identity, update the BMC, verify the new address, and synchronise the management record. Only a device that is enrolled and whose planned address is inside the out-of-band subnet and unoccupied is updated, and the reason is stated for the others. An interrupted update has two recovery entries: “重新检查并更新” (Re-check and update) when the update request has not been sent to the device yet, and “核对并完成同步” (Verify and finish sync) when the BMC already uses the new address and the management record is not fully synchronised. The management connection may drop briefly while the address switches; the update triggers no installation and does not affect the system running on the host. It continues after the window is closed, and recent update records can be opened again. It applies to all three device types.
- A server that does not belong to a rack appears on the device pages only, with “未分配机柜” (no rack assigned) as its rack and position. It has neither rack registration nor bring-up: it is enrolled in device discovery, is not powered on after enrollment, and NICo powers it on and ingests it at its first operating system installation.
- Device running state: running state, health alerts, firmware compared with the baseline, state timeline. A compute tray also has its instance, DPUs, hardware capabilities and LLDP neighbours; a switch also has NVOS management ports and Fabric Manager. A power shelf has no readable firmware version or power figures, so only its address, state, health and power are shown.
- The two ways to use a DPU. NICo has a DPU policy per host, with a site default that a host's declaration can override. In network-card mode a BlueField card is an ordinary network card: NICo only probes it, the host gets its address from the host management subnet, and delivery uses a network that does not pass through the DPU. In DPU mode each card is a device NICo manages, with its own system and firmware, and the host's address and tenant networks are provided through it. In this version every policy the platform writes is network-card mode, and onboarding, network planning and delivery are designed for it. When DPU mode is supported later, the policy becomes a column of the device planning, the DPU page adds each card's running state and its pairing with the host, network planning adds the subnets for the DPUs themselves and for hosts behind DPUs, and delivery uses a network that passes through the DPU.
- Open: how the bring-up task and NICo's automatic rack maintenance interleave when they run at the same time. It will be decided after measurement.

### 6.4 Delivery

- What is delivered is a server, one machine at a time: one instance per machine. A rack is not the object of delivery, only a filter when choosing devices; devices can be chosen across racks, and servers that do not belong to a rack can be chosen too.
- The entry point is 新建安装任务 (New installation task) on 安装任务 (Installation tasks). The entries of the same name on the rack detail, the server list and device discovery open the same wizard with the devices already chosen.
- The wizard has three steps: choose devices, review the configuration, check and confirm. Choosing devices, the installation-condition check, submission, the execution stages, the acceptance items and the entries for handling a failure all follow the installation task of the existing product; the only difference is that the “核对配置” (review configuration) step of the existing wizard is split into a review step and a check step. A batch has at most 50 machines; the number installed at the same time is entered at submission and defaults to 5.
- Reviewing the configuration only reviews; it runs no check. It is a list, one row per machine, with the host name, installation profile, management IP and boot NIC, and system disk; these come from the system configuration in device management (see 6.3), every item has a default, and an item that comes from a default is marked as default. By default the operator fills in nothing and moves on after reading the list. To change a machine, click it to open its system configuration; saving returns to the list.
- The host name is also the instance name, and after installation it is the host name inside the system. When it was not filled in it is generated from the serial number, in the form `host-<lowercased serial number>-<first 8 characters of the device record ID>`; before submission the platform checks its form and that it repeats no other name.
- The network is only reviewed: the list shows the management interface alone, that is the management IP and the boot NIC, which are brought in from the device planning by one-click match and are normally not changed; when a change is needed, it is made in the system configuration. A device with no boot NIC MAC shows “待准备” (Needs preparation) as its installation condition, and its system configuration has to be completed first. The platform does not manage the other interfaces.
- A machine can be installed when it is ready, has no instance, has no quarantine or maintenance mark, and has no alert that prevents allocation; a device in a rack also needs the rack to be Ready, with no rack-level leak and no task in progress. The reason a machine cannot be installed is shown per machine in the 安装条件 (installation condition) column, a problem on one device does not affect the others in its rack, and the platform offers no bypass.
- While choosing devices the operator can query the 当前系统 (current system) on demand. The query is read-only and confirms what is on a device before its system disk is overwritten.
- The installation-condition check is a third step of its own, because it logs in to the BMC of every machine and checks address occupancy and the installation materials, which takes time; placed after the review, it is not triggered again and again while configuration is being changed. It runs per machine in three groups, namely device identity, installation configuration and operating system materials, and the check items follow the existing product. A machine that is already ready is checked for: current BMC authentication and the host serial number; the machine being ready and having no instance, the system disk and the network plan; the per-machine installation configuration and the installation materials. A server that has not been ingested yet is checked for: BMC identity, boot network configuration and ingestion protection; device plan, host name and installation profile; installation materials; two items, machine ingestion and readiness and the target disk, are deferred until just before execution. A check result is valid for 15 minutes, and a result that is already 14 minutes old or older at submission is checked again first. If any item fails on any machine the batch cannot be submitted; each failing item is listed with its device, the check name and the reason.
- The system disk is resolved by the disk rule of the installation profile and must resolve to exactly one disk. When it does not, the review list already marks it, and the check opens only after a disk is set in the system configuration of that machine.
- Installation profiles are matched by the architecture of the device, published ones only, and the default profile of the architecture is used when none was chosen; the system disk follows the rule of the installation profile by default and can be set for a machine in its system configuration.
- When the configuration has not changed, returning from the review to the third step reuses the last check result instead of checking again; the check can be run again by hand. A passed check only says the batch could run at that time: on submission the server checks the configuration and occupancy again, and a full digest check of the installation materials is done before execution.
- A server outside a rack that is enrolled but not yet ingested can be installed too: the first step of the installation task has NICo power it on and ingest it, and only then is the system disk written. Its machine readiness and system disk are settled before execution and do not count as failed checks; the first ingestion cleans all disks, non-system disks included, and that needs a separate confirmation.
- Installation uses NICo's DHCP, PXE and templated OS. One submission is one batch, and the installation process and the acceptance result are kept per machine. The execution stages follow the existing product: waiting to run, prepare device, pre-installation check, sync device plan, install system, boot from system disk, installation acceptance, GPU environment check, restart acceptance, done. Acceptance has eight items: installer succeeded, host configuration, system disk and EFI partition verification, network configuration, DNS / HTTP / NTP reachability, SSH reachability, GPU environment check, restart acceptance. A device that fails is paused, and the entries for handling it are Continue preparing device, Re-check and continue, Retry install, Start acceptance and End task.
- On submission the platform saves the configuration each machine has at that moment (host name, installation profile, system disk, management interface) as the snapshot of the task. Changing the system configuration afterwards does not change a task already submitted and affects only the next installation.
- All instances are created under the site's default tenant, and the pages do not show a tenant; the platform does not hand machines out to other platforms.
- Release goes through NICo's cleaning and re-validation; a machine cannot be installed again until cleaning has finished.

### 6.5 Health

- Summarises the current health alerts of racks and the three tray types, grouped by alert or by object, and marks two classes: prevents allocation, and rack-level leak. Alert identifiers and classes are NICo's own.
- “需要处理” (needs attention) uses NICo's signals only: the state machine failed to process, or there is a health alert.
- When no report has been received the page shows “未报告” (not reported), never healthy.
- “阻止分配” (prevents allocation) affects only the host it is on: that host is not allocated to a new instance. A host with a maintenance mark is in this class too. It does not mean the rack has a problem.
- Leaks have two levels. A tray-level leak is reported by the device's sensor. On a rack-level leak NICo forces every device of the rack off on its own and refuses to power it on again; the devices do not power on by themselves after the alert clears. The page shows this automatic power-off and the affected instances as they are. The site page says so when facility-side events are not connected.
- When a rack has fewer members than its profile there is a rack-level alert that counts by device type, names no slot, and does not prevent allocation.
- Curves, power and temperature link to the monitoring system; the pages do not rebuild them.

### 6.6 Profiles and audit

- Firmware baseline: a set of versions bound to a rack profile, corresponding to the firmware list the site configures for that profile. A firmware update can only choose a baseline, never an arbitrary version. NICo can only tell whether a device's version equals the baseline, not which is newer; NVOS and power shelves have no readable installed version. A firmware update skips devices whose version already equals the chosen baseline.
- Installation profile: reusable system, disk and login defaults, distinguished by architecture. An installation task can only choose a published profile whose architecture matches the device; what differs per machine is not written in a profile.
- Audit: every write operation records the operator, object, action, reason, task number and the state read back. Records are append-only and never deleted.
- Roles: read-only cannot run operations; operator can run device, rack and installation operations; administrator can also change the site, the network and installation profiles. Once the site's identity system is connected, the audit records a person.

### 6.7 Network

Subnets must be planned before the device inventory is imported. A device is discovered only after it gets an address according to the plan when it is powered on.

Device interfaces fall into three purposes, and each purpose has at least one subnet:

| Purpose | Device interfaces | NICo network type | Notes |
| --- | --- | --- | --- |
| Out-of-band management | Compute tray BMC, switch BMC, power shelf PMC, DPU BMC | Underlay | The entry point of device discovery: once these interfaces have an address, the platform reads the device identity |
| Switch system management | Switch NVOS management port | Underlay | Configuration and management of a switch after ingestion |
| Host management | Compute tray host interface | HostInband | Network boot, installation and system management of the host |

- Plan check: every purpose has a subnet, and the assignable addresses are no fewer than needed. The need is counted by interface, not by device: one BMC per device, two more NVOS management ports per switch, and one for the BMC of each DPU. The device inventory cannot be imported while the check fails; the import preview counts the new racks in.
- Subnet: name, purpose, prefix, gateway, DHCP pool, assigned and assignable. Only the DHCP pool of an existing subnet can be changed. The purpose and the switch-side VLAN are recorded by the platform; a NICo subnet has neither. The DNS domain of a subnet is filled in by the platform with the site's default domain; it is neither chosen nor shown, except that a new host management subnet asks for one when the site has several DNS domains.
- DHCP service: a whole-rack site uses NICo DHCP only. For each subnet the page shows when an address was last handed out and how much of the pool is used, and marks a subnet that has never handed one out. The boot service addresses (network boot, installation material, DNS, NTP) are maintained here.
- When addresses are decided: a BMC address is assigned from the pool when the rack is connected to power and is an arbitrary address of the pool; neither enrollment nor bring-up changes it. After enrollment the BMC can be changed to its planned fixed address on the device page; see 6.3. The host management address is the one decided when devices were planned and takes effect when a compute tray is brought up and first boots from the network; without a plan NICo assigns it.
- Address assignment: which interface of which device each address was given to, and the allocation type NICo reports (dynamic, fixed, reserved). The allocation type is decided per device; it is not a property of the subnet and is not set by hand. Addresses that belong to no device yet are handled in device discovery.
- The platform only creates subnets and pools in NICo and does not configure switches. The VLAN, gateway and DHCP relay of each subnet are site prerequisites.

## 7. Resources and state model

### 7.1 Resources and ownership

![Figure 4: resource relationships](figures/resources.png)

| Resource | Source | Identifier | Maintained in |
| --- | --- | --- | --- |
| Device planning | Imported by hand or edited row by row | File version; each row is identified by its serial number | Inventory |
| Device credentials | The rows of the device planning, or entered at device discovery | — | Inventory; the platform no longer keeps them once the declaration is written to NICo |
| Device declarations (rack group, rack, device) | The declaration of a server is written to NICo when it is added to managed devices; the rack-level declarations and the declarations of switches and power shelves are written at rack registration | Rack ID, BMC MAC, serial number | Device discovery (enrollment), rack (rack registration) |
| Rack | Created by NICo when the first member device is ingested | Rack ID | Read-only; operations are in the racks and devices module |
| NVLink domain | NICo and NMX-C | Rack group ID; the domain ID reported by NMX-C | Read-only |
| NVLink partition | NICo | Partition ID | Read-only |
| Server (compute trays included), switch, power shelf | Discovered and ingested by NICo | NICo object ID, serial number | Read-only; operations are in the racks and devices module |
| DPU (BlueField card) | Probed by NICo | Serial number | Read-only |
| Rack profile | NICo's site configuration, derived from the rack topology and manufacturer chosen when the planning is imported | Profile ID | Read-only |
| Task | Flow | Task ID | The task view of the racks and devices module |
| Instance | Created per machine when an installation task is submitted | Instance ID; the instance name is the host name | Delivery |
| Device configuration (including the system configuration of a server and the planned BMC address) | Brought in from the device planning by one-click match, changed by the operator when needed | One per enrolled device | Device page; an installation task only refers to it |
| Firmware baseline, installation profile | Profiles | Name and version | Profiles and audit |
| Audit record | The platform | Record ID | Read-only |

Relationship rules:

- Membership has one key: the rack ID. A device is matched by one thing: its serial number. The expected slot comes from the device planning and the observed slot is read by NICo from the hardware backend after it ingests the device; the inventory check compares them after bring-up.
- A device belongs to a rack through its own rack ID; the rack object does not store its members. The rack ID is optional: a server that does not belong to a rack has none. One NVL72 rack corresponds to one NVLink domain.
- An instance corresponds to exactly one machine and does not belong to a rack.
- A task is the execution record of a bring-up, or of a rack-level power or firmware operation; NICo's automatic rack maintenance is recorded in the rack's state history. The audit records who submitted which task, when and why.
- The platform stores locally only the device planning and its versions, the records and configuration of enrolled devices (including the system configuration of servers), the credentials of switches and power shelves held until registration, the update records of BMC addresses, profiles, installation tasks and the audit. Data written to NICo is keyed by NICo identifiers.

### 7.2 States

Pages show the state reported by NICo's state machines verbatim and define no state names of their own.

| Object | States | What triggers a transition |
| --- | --- | --- |
| Rack | Not created yet (in the inventory only), Discovering, Maintenance (firmware upgrade, NVOS update, power sequence, NMX-C cluster configuration), Validating, Ready, Error, Deleting | The first device is ingested after the bring-up task powers it on; rack maintenance starts on its own once the number of ready switches is reached; a stage completes; a validation result; any stage failing, or the operator terminating rack maintenance, leads to Error; rack maintenance is run again |
| Tray | The states of NICo's state machine for each tray type | Discovery, ingestion, validation, allocation, release, failure, decommissioning |
| Task | Waiting, running, succeeded, failed, terminated | Submission, a step completes, a step fails, cancellation |
| Instance | NICo's instance lifecycle states | Allocation, installation, ready, release |

## 8. Module interaction and dependencies

### 8.1 Module dependencies

![Figure 5: module dependencies](figures/modules.png)

| Upstream | Downstream | What is passed | Gate |
| --- | --- | --- | --- |
| Site | Network | Component readiness | Subnets cannot be created while the site is not ready |
| Network | Inventory | The subnets and assignable addresses of each purpose | Import is refused while the plan check fails |
| Site | Inventory | Supported rack profiles | Import is refused while the site is not ready |
| Inventory | Racks and devices | The racks and devices in the inventory | Every rack and device in the inventory appears, whether or not NICo has an object for it |
| Profiles | Racks and devices | Firmware baseline | A firmware update can only choose a baseline |
| Racks and devices | Delivery | Readiness of servers; for those in a rack, also the readiness of the rack | A machine that is not ready cannot be installed; devices in a rack that is not Ready cannot be installed |
| Profiles | Delivery | Installation profile | Only a published profile can be chosen |
| Health | Racks and devices, Delivery | Rack-level leak; prevents allocation | During a rack-level leak power-on is refused and the devices in the rack cannot be installed; a server with an alert that prevents allocation is left out individually |
| Racks and devices, Delivery | Audit | Every submitted operation and its result | An operation is not submitted when the audit cannot be written |

### 8.2 Exclusion rules

- A rack has only one task in progress at a time. A rack that is being brought up accepts no power or firmware task.
- When a tray has an instance or an installation task in progress, an operation that would interrupt the tray first shows the affected instances and asks for confirmation; operations on switches and power shelves count the instances of the whole rack.

### 8.3 Behaviour when an external dependency is missing

| Missing | Affects | Page behaviour |
| --- | --- | --- |
| Flow | Bring-up of a new rack, rack-level power, firmware update, tasks; the automatic power-off on a rack-level leak | These operations are unavailable, with the reason; reads, enrollment and single-device operations continue |
| RMS | Power and firmware of trays, switches and power shelves; rack bring-up and rack maintenance | Bring-up, power and firmware operations are unavailable; a rack in rack maintenance stops in Error, and rack maintenance has to be run again after RMS is back |
| NMX-C | NVLink domain formation and partitioning | The domain is shown as not formed; the rack cannot reach Ready, and the devices in it cannot be installed |
| Facility-side events | Facility-side leak events | Only leaks from tray sensors are shown; the site page says the events are not connected |

## 9. Design of operations

Every write operation has the same shape: choose the object, choose the action, write the reason. A new installation task and the system configuration of a server are the exceptions: an installation task uses a three-step wizard to choose devices, review the configuration of each, and check and confirm, and the configuration itself is maintained per machine in the system configuration; see 6.3 and 6.4.

| Operation | Object | Input | Completion condition |
| --- | --- | --- | --- |
| Import planning | Site | File, rack topology and manufacturer | The preview passes for every row and the planning is saved |
| Get device information | One or more discovered endpoints | User name and password | The device type, serial number and model are read |
| Add to managed devices | One or more endpoints whose device information has been read | None | The devices are enrolled; the declaration of a server is written to NICo, and the devices are not powered on |
| One-click match | One or more enrolled devices | None | The planning is written to the device configuration |
| Register rack | The enrolled and matched devices of one rack | None | The rack and its members are registered in NICo, and the devices are not powered on |
| Start bring-up | A registered rack | None | The bring-up task succeeds and the rack is Ready |
| Run rack maintenance again | A rack stopped in Error | None | The rack is Ready |
| Terminate rack maintenance | A rack in a maintenance stage | None | The rack enters Error |
| Power on, power off, restart | Rack, tray | Action | The task succeeds and the power state read back matches |
| Update BMC address | One or more enrolled devices | Planned address | The new address is verified and the management record is synchronised |
| Firmware update | Rack, tray | Firmware baseline | The task succeeds and the versions equal the baseline |
| Expected-versus-actual validation | Rack, tray | None | No difference |
| Maintenance mark, quarantine | Tray | Reason | The state read back matches |
| On-demand hardware validation | Compute tray | None | The validation record completes |
| Change system configuration | One server | Boot NIC MAC, management IP, management subnet, host name, installation profile, system disk; all have defaults | Saved; takes effect at the next installation |
| New installation task | One or more servers | None; the system configuration of each is reviewed | The instance of each machine is ready and accepted |
| Replace a tray | Tray | Serial number and credentials of the new device | The new device is ingested and the rack returns to Ready |
| Decommission | Device | Reason | The device is decommissioned |
| Delete rack | A rack with no instance whose member devices are all decommissioned | None | The rack object is deleted |

Interaction rules:

- The confirmation shows four things only: object, action, number of affected instances, and the steps the task will go through. A high-risk action requires typing the rack ID or the serial number.
- A disruptive power or firmware task does not run the moment it is submitted: the task first waits for the affected hosts to become operable, checking every 5 seconds for up to 30 minutes, and fails if they do not. The confirmation says how many hosts do not qualify now and why, and what will happen in turn after submission; waiting for hosts is a step of its own in the task.
- After submission the user is taken to the task view. A task stops at the step that fails and does not undo the hardware actions already completed; the pages do not promise a rollback.
- Cancelling a task is best effort: no new step is started, and an action already handed to the hardware backend does not stop.
- When a result is unknown the platform reads the state back first and never resends automatically; the operator decides the next step.
- Entry points that are not provided: typing an arbitrary firmware version, forcing a check to be skipped, per-machine timeouts and concurrency, direct hardware protocol operations.

## 10. Non-functional design

- Safety interlocks: breaker and coolant valve interlocks belong to the facility. On a rack-level leak NICo forces the whole rack off on its own and refuses power-on; the operator cannot skip this.
- Blast radius: counted by rack. An operation on one switch or power shelf affects every instance in the rack, and the confirmation must show the number of affected instances.
- Firmware consistency: the recommended unit of a firmware update is the rack, which is one NVLink domain; updating a single tray warns about version differences within the rack.
- Installation gate: when it creates an instance NICo checks only the machine itself; whether the rack is Ready and whether it has a rack-level leak are checked by the platform when devices are chosen. The platform shows the reason and offers no bypass.
- Credentials: a device password is submitted only when the planning is imported or edited, or when device information is read, and is held encrypted; it never appears on a page, in a version record or in the audit. After the declaration is written to NICo the password is NICo's and the platform no longer keeps it; NICo rotates it after ingestion. Reading a device identity never tries one password after another.
- Reliability: tasks are persisted by Flow, so a platform restart loses no task; before an upgrade the platform checks that no task is in progress.
- Backup: NICo's database and credential store must be backed up; device planning files are kept by version.
- Scale: the default views aggregate by rack, and lists do not call an interface per row.
- Transparency: the site page has one table saying what NICo does in each situation; for every action that happens on its own (bring-up, the power-off on a rack-level leak) the pages show what caused it and how it went.
- Observability: pages show only the current state and where to handle it; time series go to the monitoring system.
- Delivery form: the platform and all its dependencies are delivered as one version-locked offline bundle.

## 11. Phases

| Phase | Focus | Outcome |
| --- | --- | --- |
| 1: inventory and onboarding | Site checks, network planning, device planning import, device discovery and enrollment, one-click match, rack registration, health summary | From planning import to a registered rack, without the command line |
| 2: rack lifecycle | Bring-up, rack maintenance progress and running it again, power, firmware update, task view, audit | A rack bring-up and one complete maintenance done from the pages |
| 3: delivery | Installing and accepting machine by machine; the system configuration of servers and its defaults; the installation-condition check; release and reuse | All compute trays of one rack and one server outside a rack installed |
| 4: scale | Phased firmware rollout across racks, identity system and roles, DPU mode | Changes across racks are controlled and attributable |

## 12. Acceptance principles

1. Verify the closed loop of the flow: from planning import to a completed installation, then one maintenance and one replacement, without the command line at any point.
2. Go by state and read-back: every operation has an explicit completion condition, and success is the state NICo reports back, not the request being accepted.
3. Verify failures first: cover missing devices, authentication failures, devices not in the planning, bring-up stopping in Error, firmware failures, interrupted tasks, rack-level leaks and unavailable dependencies.
4. Go by simplicity: the inputs of an operation are no more than object, action and reason; a fourth input sends the operation back to design review.
5. Go by auditability: for every write operation the operator, object, reason, task and result can be found.
6. Record three measures: the time from power-on to the rack being Ready, the number of endpoints handled by hand, and the number of manual steps per maintenance.

## 13. References

- NVIDIA Infra Controller documentation: https://docs.nvidia.com/infra-controller/documentation/home
- Key Capabilities: https://docs.nvidia.com/infra-controller/documentation/overview/key-capabilities
- Day 0, Day 1, and Day 2 Lifecycle: https://docs.nvidia.com/infra-controller/documentation/overview/day-0-day-1-day-2-lifecycle
- Rack, Machine, Switch and Power Shelf state machines: https://docs.nvidia.com/infra-controller/documentation/architecture/state-machines/rack-machine-switch-power-shelf
- NICo source: https://github.com/dsx-ai-factory/infra-controller
- Rack Management Service documentation: https://docs.nvidia.com/rms/documentation/home/
