# Provisioning with external DHCP

**English** · [简体中文](external-dhcp.zh-CN.md) · [Documentation](README.md)

Use this optional mode when the network team supplies DHCP addresses but cannot add PXE options or a relay. PXEye publishes a small UEFI boot ISO; NICo Core mounts it through BMC VirtualMedia and controls the boot lifecycle. The ISO starts iPXE with an explicit NICo HTTP endpoint. External DHCP still supplies the host address, mask and route.

## Requirements

- An x86_64 UEFI host without a managed DPU, using Flat networking. BMC must support an optical VirtualMedia slot and one-time `Cd`/`Hdd` boot. Standard Redfish actions and Lenovo XCC1 `EXT` PATCH resources have adapters; a model's actual license and firmware require validation.
- A fixed external DHCP lease for the boot MAC already saved in **Device planning**. iPXE, Scout and the installer must obtain the same IP. The matching HostInband prefix must exist in Core. Do not enter a second copy of this network plan.
- The BMC can fetch the small ISO from the materials HTTP service. The host can reach the boot HTTP service, Core with valid TLS trust, and OS materials. Core identifies the host by the actual source address; SNAT must not conceal it.
- A matching Core and Scout build implementing `SetHostBootIntent`, `GetHostBootIntent`, `AcknowledgeHostBoot`, `CancelHostBoot` and `ReleaseHostBootPolicy`. Old Core builds remain usable in Nico DHCP mode. Updating PXEye alone does not add the Core feature.
- A PXEye image built through the normal `make images` entry point, including the pinned generic EFI/ESP assets. The image includes `mcopy` and `xorriso`; the site does not compile iPXE. See [image building](deployment.md).

## Matching source versions

Use the maintained [Core integration branch](https://github.com/SSmallMonster/infra-controller/tree/mmzhou/nico-site-fixes) when building this feature. Core and Scout are built from the same repository and must use the same source revision.

| Component | Source revision |
| --- | --- |
| NICo Core and Scout | `SSmallMonster/infra-controller` at `ebaadc097c4c72af58bf30a934c3b086ed878778` |
| Lenovo Redfish compatibility | `SSmallMonster/libredfish` at `b6b4fff7277276bb4d0724e7dd4dca9cea2abbd1`, pinned by Core's Cargo manifest and lockfile |

```bash
git clone --branch mmzhou/nico-site-fixes https://github.com/SSmallMonster/infra-controller.git
cd infra-controller
git checkout --detach ebaadc097c4c72af58bf30a934c3b086ed878778
```

A separate sibling `libredfish` checkout is unnecessary. Prepare Cargo's pinned Git dependency while the build environment has network access. Follow the Core repository's build instructions for Core and Scout artifacts.

Merging source code does not update a cluster or offline package. The default Chart image pins remain unchanged; select the matching Core image and Scout files before building an external-DHCP delivery. Updating PXEye alone keeps existing Nico DHCP sites on their saved mode.

## Operator workflow

1. Install the control plane using the existing onsite flow. External DHCP does not change the order of Helm installation.
2. Open **Site → Manage boot network**, select **External DHCP**, and enter the **Boot HTTP endpoint**, including protocol and port. Keep the **Installation materials HTTP** address and port in the same form; these are separate endpoints with different purposes.
3. Preview and apply. PXEye scales this site's Kea Deployment to zero and reads back that it has stopped. It does not change Kea allocation parameters, customer DHCP, relay settings or Services. Active installation tasks block a mode change.
4. Confirm the fixed lease for the planned boot MAC/IP. Register a new OS version with the updated PXEye OS library and select it in the installation profile. Old immutable OS definitions remain unchanged; external mode requires the new boot acknowledgement parameters.
5. Start the existing first-install or reinstall workflow. Task creation freezes the site mode. PXEye publishes immutable boot media and submits a per-device intent; the ordinary Core admission/allocation/reboot flow remains the execution entry point.
6. Follow **Installation task → External DHCP / BMC boot** for the Core phase, generation and media cleanup. Normal installation and target-disk acceptance still determine completion.

The boot HTTP endpoint controls only the bootstrap medium’s first request. It does not rewrite Core/PXE service ports or subsequent script URLs. See [Site settings](user-guide/site-settings.md#3-boot-network-service-addresses) for the fields used by each mode.

The boot HTTP endpoint serves `/api/v0/pxe/boot`. The materials HTTP endpoint serves the small bootstrap ISO and the OS's ISO/kernel/initrd. An existing OS retains the URLs with which it was registered.

## Ownership and recovery

Core is the only external-mode BMC writer. It performs BIOS preparation, selects an empty optical slot, verifies the artifact, mounts and reads it back, sets one-time boot and dispatches reset. It records progress before external writes. An uncertain reset response is not automatically replayed.

Every intended network boot gets a new nonce, including later Scout cleanup boots in the same policy generation. A matching Scout registration or authenticated installer callback permits removal of **only the owned bootstrap medium**. A `Ready` state, HTTP response or consumed PXE flag cannot trigger ejection. Foreign mounted media blocks the operation.

An installer callback carries the nonce from the current kernel command line. The installer runs independently of the small iPXE ISO; Core can then eject that ISO. The OS ISO remains a separate installation material. After installation completion evidence, PXEye requests local-disk handoff; Core applies it without issuing an extra reset. Local-disk handoff sets a one-time `Hdd` override; it does not reorder permanent UEFI boot entries. Keep the system disk ahead of network boot in the permanent firmware order. Otherwise a later ordinary reboot may try every enabled network adapter before falling back to disk and exceed the reboot acceptance window. Manually skipping that check does not certify ordinary reboot acceptance.

On failure, preserve the task and inspect its Core phase/error. Repeat an identical intent to read or resume its recorded state, not to reset again. Closing a stopped external-mode task requests Core cancellation and waits for owned-media cleanup before releasing the task. This does not terminate an installer already running on the host. A cancelled policy remains stopped until explicitly replaced or released.

If the device has no Machine or Instance and Core again reports `WaitingForIngestion`, use the existing admission confirmation to start again. PXEye requires the recorded external generation to be cancelled and cleaned, or its policy to be absent; it archives the old admission internally. External mode declares a new generation, while Nico DHCP mode releases the old policy before ingestion. An uncertain or still-active request cannot be replayed.

Switching the site back to Nico DHCP is explicit and blocked by active tasks. A subsequent native task releases a recorded external policy only after Core confirms cleanup. No policy means the existing native PXE behavior.

## Validation boundary

The implementation has separate checks for media generation/UEFI boot, API/state transitions and orchestration. These are not physical server installation evidence. Before enabling a hardware model, validate mount/readback/eject, Scout registration, installer callbacks, local-disk boot and failure recovery on a designated machine. ARM, DPU initialization, Secure Boot signing and arbitrary changing DHCP leases are outside this mode's support scope.
