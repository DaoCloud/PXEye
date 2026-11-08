# Documentation design references

**English** · [简体中文](documentation-references.zh-CN.md) · [Documentation](README.md)

Reviewed on **2026-11-07**. These are upstream public documentation references, not claims that PXEye implements their capabilities. Branch pages can change; this review reflects the content available on that date. No project introduction, screenshot or badge was copied into PXEye.

The onboarding structure was extended on **2026-11-08** using [Tinkerbell Getting Started](https://tinkerbell.org/docs/v0.22/setup/getting_started/), [Metal3 Quick Start](https://book.metal3.io/quick-start) and [Argo CD Getting Started](https://argo-cd.readthedocs.io/en/stable/getting_started/): prerequisites precede deployment and a first operation, while detailed configuration stays in separate guides. PXEye places an eight-item summary in its README and maintains the complete [pre-installation checklist](pre-installation-checklist.md) separately.

## What we adopted

| Reference | Observed documentation approach | Application to PXEye |
| --- | --- | --- |
| [NetBox README](https://github.com/netbox-community/netbox/blob/main/README.md) | Names the product's role and source-of-truth boundary, then connects features, getting started and rack/network images. | Explain NICo/PXEye data ownership early and use real product captures before implementation details. |
| [Tinkerbell README](https://github.com/tinkerbell/tinkerbell/blob/main/README.md) | Leads with its provisioning purpose and concrete network/ISO/BMC capabilities; routes governance, contribution and security to separate documents. | Keep the introduction focused and give operational requirements and governance their own entry points. |
| [Metal3 Bare Metal Operator](https://github.com/metal3-io/baremetal-operator/blob/main/README.md) | Maps an inventory resource to inspection, provisioning and cleaning, with links to API and setup guides. | Map modules to native resources and distinguish discovery, site cleanup and OS installation. |
| [Argo CD README](https://github.com/argoproj/argo-cd/blob/master/README.md) | Starts with what/why, then offers complete documentation and community paths. | Organize README around purpose, value, workflow and a short path into task-oriented guides. |

NetBox's role separation is especially useful: intended configuration should not be confused with live device state. PXEye differs because it also executes hardware operations, so it documents the explicit transition from a saved plan to a confirmed write and readback.

Tinkerbell and Metal3 make booting, inspection and cleaning concrete rather than presenting one generic automation claim. PXEye similarly documents Scout preparation separately from unattended OS installation. Argo CD's introductory structure helps keep deployment commands and implementation details out of the first explanation of value.

## Resulting information architecture

- README: positioning, core capabilities, a short checklist under Getting started, deployment and first-server links, product images, operator workflow and current support.
- Pre-installation checklist: one-sentence checks for discovery, host OS writing and managed DPUs, with verification references and handoff fields.
- Install your first server: the complete first-device path with recognizable UI labels.
- Features: effects, resource boundaries and required hardware/network capabilities.
- Architecture: ownership, runtime modules, execution behavior and version compatibility.
- Deployment: configuration, exact credential filenames, mounts, publication paths and persistence.
- Reference cluster: screenshot data provenance and reproducible capture instructions.
- Contribution, security and release preparation: project-maintenance responsibilities.

Each public page has an English/Chinese counterpart with matching intent. Commands, field names and filenames retain their original technical spelling. Screenshots share one dataset and are attributed as illustrative UI views. Existing release numbers, licenses, CI badges, adopters or production claims are not invented.

## Technical references

NICo [templated iPXE](https://docs.nvidia.com/infra-controller/documentation/configuration-day-1/templated-i-pxe-operating-systems), [network configuration](https://docs.nvidia.com/infra-controller/documentation/provisioning-day-0/ip-and-network-configuration), and [Rack state machine](https://docs.nvidia.com/infra-controller/documentation/architecture/state-machines/rack-machine-switch-power-shelf) inform the native terminology. The [reference cluster](reference-cluster.md) identifies the hardware architecture sources. Online docs must be checked against the integrated Core revision.
