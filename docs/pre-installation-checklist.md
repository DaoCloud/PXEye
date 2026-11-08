# Pre-installation checklist

**English** · [简体中文](pre-installation-checklist.zh-CN.md) · [Documentation](README.md)

Use this checklist when preparing a site and installing its first server. Complete section 1 before the first Scout boot, section 2 before writing the host OS, and section 3 when using a managed DPU. OS materials and device settings can be prepared through PXEye after deploying the service.

This checklist covers preparation requirements; PXEye's automatic preflight covers only the checks implemented for the selected workflow.

## 1. Before discovery and the first Scout boot

### Platform and NICo

- NICo and its dependencies are deployed with recorded versions and working Core, DHCP, PXE, DNS, NTP and credential services.
- Control-plane images and administrative binaries match their execution nodes' CPU architectures and are available in the target environment.
- The PXEye runtime can authenticate to Core using the configured CA, client certificate and private key.
- PXEye configuration, secrets, data and material volumes have the required mounts, permissions, capacity and backup arrangements.
- The actual Kubernetes or Kind entry points for DHCP, boot HTTP, Core, UI and installer callbacks are reachable from their intended networks.

Configuration, filenames and mount locations: [Deployment guide](deployment.md).

### Hardware and access

- Each server's serial number, CPU architecture, permanent BMC/PXE MAC addresses and physical switch connections match the inventory.
- The control-plane path reaches the correct BMC over HTTPS, and its account can read identity and perform the required boot, power and management operations.
- Initial BMC credentials and the site-managed BMC/UEFI defaults required by the selected NICo version are securely configured before ingestion.
- The owner has approved the maintenance window, backups and disks that first-ingestion cleanup may erase.
- The server's UEFI network boot, relevant firmware and Secure Boot settings are compatible with the selected boot artifacts, and a recovery console is available.

Ingestion preparation: [NVIDIA BMC and Out-of-Band Setup](https://docs.nvidia.com/infra-controller/documentation/getting-started/prerequisites/bmc-and-out-of-band-setup).

### Networks and DHCP

- The BMC and host boot/management networks have agreed CIDRs, gateways, VLAN/VRF, MTU, DNS and NTP settings.
- Required DHCP relays target NICo's actual DHCP entry point, and their `giaddr` or enabled Link Selection address matches the intended NICo subnet.
- NICo subnet policies and fixed MAC reservations are applied without conflicts with dynamic pools, infrastructure addresses or other DHCP servers.
- Routes, ACLs, firewalls and DHCP snooping permit requests and replies, and host-facing dynamic PXE/metadata routes preserve the client identity required by NICo.
- An authorized client on each installation network completes DHCP Discover, Offer, Request and ACK with the expected address and boot options.
- A test client on the real installation network can reach the required boot HTTP, Core, DNS, NTP and software sources.

Configuration and verification: [NVIDIA IP and Network Configuration](https://docs.nvidia.com/infra-controller/documentation/provisioning-day-0/ip-and-network-configuration).

## 2. Before writing the host OS

Owners: the OS supplier, hardware/network teams and PXEye operator. Follow [Install your first server](getting-started.md) to prepare and check the effective configuration.

- Scout has reported the intended server's identity, boot interface and disks, and the machine meets the chosen installation path's readiness requirements.
- The ISO has a recorded source, version, CPU architecture and checksum, with a supported unattended-install interface and kernel/initrd from that same ISO.
- The selected OS definition is registered in NICo with the correct boot URLs and parameters, while matching EFI and Scout discovery artifacts remain available.
- The installation profile resolves its disk and partition rules to the approved target storage, with any hardware RAID prepared through the appropriate hardware tooling.
- The effective hostname, interface MAC, address, gateway and DNS settings match the device plan and selected installation profile.
- The OS account, SSH authentication and acceptance access are configured for the installed system, independently of the BMC credentials.
- The actual host network can download and verify the published ISO, kernel/initrd and installation metadata, and reach the installer callback; OS installation does not require an external package mirror.
- The operator has reviewed the selected devices, OS and cleanup scope, and the task preflight has passed with the effective installation settings.

PXEye prepares or reuses the required Machine/Instance and per-host installation data during its workflow; do not create a second manual configuration merely to satisfy this checklist. First-ingestion cleanup can affect more disks than the OS system-disk selection.

## 3. Additional checks for a managed DPU

Owners: hardware, networking, platform and NICo teams. Mark this section not applicable when the selected workflow does not provision a DPU OS; confirm any remaining hardware/network requirements separately.

- Each DPU's model, PN/PSID, serial number, host association, operating mode and NICo management policy are recorded and supported by the chosen software combination.
- DPU BMC/OOB interfaces, addresses and credentials match the inventory and are reachable with the permissions required for provisioning.
- The matching BFB system bundle, firmware/DOCA versions and required DPF charts and container dependencies are complete and downloadable by their actual consumers.
- DPU runtime images match the DPU architecture, independently of the NICo control-node and host-OS architectures.
- The selected DPU workflow has the required management/underlay and tenant networks, including routing and fabric settings where applicable.
- DPU recovery materials and access are available, with separate acceptance criteria for DPU provisioning, its services and host OS installation.

BFB is the DPU system bundle; DPF is the management framework. PXEye's server OS task does not replace NICo/DPF's DPU provisioning configuration.

## Maintaining this checklist

Keep each check to one sentence; put commands and explanations in the relevant guide and link them here. Maintain the English and Chinese versions together. Use this page for the complete checklist and the root README for its short summary.

NVIDIA documentation is the primary technical reference; confirm its requirements against the integrated NICo version and the actual hardware workflow. Prepared ARM64 artifacts, a Ready Pod or a simulated run do not establish physical ARM64/Grace compatibility; see [Features and support boundaries](features.md).
