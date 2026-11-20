# Documentation

**English** · [简体中文](README.zh-CN.md)

Public PXEye documentation is maintained in English and Simplified Chinese. Start with the pre-installation checklist, deploy PXEye, then install your first server. Use features and architecture to check native mappings and support boundaries.

| Document | English | 简体中文 | Purpose |
| --- | --- | --- | --- |
| External DHCP provisioning | [Read](external-dhcp.md) | [阅读](external-dhcp.zh-CN.md) | Fixed leases, BMC VirtualMedia, Core ownership and recovery. |
| Grace ARM64 boot materials | [Read](arm64-materials.md) | [阅读](arm64-materials.zh-CN.md) | Generation requirements, pinned payload, packaging and hardware acceptance. |
| Unified source build | [Read](source-build.md) | [阅读](source-build.zh-CN.md) | Maintained main commits, Core/libredfish/Scout/Boot/PXEye and build locks. |
| Offline delivery build | [Read](../offline-build/BUILD.md) | [阅读](../offline-build/BUILD.zh-CN.md) | Copyable build sequence, artifacts, scope and handoff boundary. |
| Optional REST management stack | [Read](../charts/pxeye/files/management/README.md) | [阅读](../charts/pxeye/files/management/README.zh-CN.md) | Bundled materials, native child Chart installs/upgrades, onsite image and release identity checks. |
| Onsite offline deployment | [Read](../offline-build/onsite/README.md) | [阅读](../offline-build/onsite/README.zh-CN.md) | Import the verified delivery, optionally select one node, and install resumably. |
| Pre-installation checklist | [Read](pre-installation-checklist.md) | [阅读](pre-installation-checklist.zh-CN.md) | One-sentence checks for discovery, host OS writing and managed DPUs. |
| Onsite DHCP quick check | [Read](dhcp-check.md) | [阅读](dhcp-check.zh-CN.md) | Dependency-free Discover/Offer check through Make, with result diagnosis. |
| Deployment | [Read](deployment.md) | [阅读](deployment.zh-CN.md) | Image build, generic UEFI media, site config, credentials and persistent publication. |
| NICo cluster deployment | [Read](nico-deployment.md) | [阅读](nico-deployment.zh-CN.md) | Independent startup, online/offline Helm deployment, permissions and site connection. |
| Install your first server | [Read](getting-started.md) | [阅读](getting-started.zh-CN.md) | First-device path from enrollment to acceptance. |
| Features and boundaries | [Read](design/features.md) | [阅读](design/features.zh-CN.md) | Native mappings, device capabilities and installation scope. |
| Architecture | [Read](design/architecture.md) | [阅读](design/architecture.zh-CN.md) | Runtime, module responsibilities and authoritative data. |
| Code structure review | [Read](design/code-structure-review.md) | [阅读](design/code-structure-review.zh-CN.md) | Historical findings, delivered refactor and verification limits. |
| Reference cluster | [Read](reference-cluster.md) | [阅读](reference-cluster.zh-CN.md) | GB200-inspired view data and screenshot capture. |
| Documentation references | [Read](design/documentation-references.md) | [阅读](design/documentation-references.zh-CN.md) | Review of NetBox, Tinkerbell, Metal3 and Argo CD. |
| Public release preparation | [Read](publishing.md) | [阅读](publishing.zh-CN.md) | Repository boundary and release responsibilities. |

## Design documents

Scope, system design, interaction rules and data contracts are in [design](design/README.md).

| Document | English | 简体中文 | Purpose |
| --- | --- | --- | --- |
| Design index | [Read](design/README.md) | [阅读](design/README.zh-CN.md) | Where each kind of content lives; naming rules. |
| Interaction rules | [Read](design/interaction-rules.md) | [阅读](design/interaction-rules.zh-CN.md) | Page ownership, wording, state, dangerous operations. |
| Rack operations: capability requirements | [Read](design/rack-operations-requirements.md) | [阅读](design/rack-operations-requirements.zh-CN.md) | Target capabilities and the implementation status of each functional area. |
| Rack operations: scope and status | [Read](design/rack-operations.md) | [阅读](design/rack-operations.zh-CN.md) | What the rack line of work does and has reached. |
| Rack operations: NICo data contract | [Read](design/rack-operations-data-contract.md) | [阅读](design/rack-operations-data-contract.zh-CN.md) | Core interfaces and fields per page, with verification marks. |

## Field survey

At a site, follow the [field survey guide](field-survey/README.md) to collect real data for each rack operations page: which NICo CLI commands and interfaces to use, how to check, where to keep results and what the user has to provide.

| Page | English | 简体中文 |
| --- | --- | --- |
| Common preparation and rules | [Read](field-survey/README.md) | [阅读](field-survey/README.zh-CN.md) |
| Servers | [Read](field-survey/servers.md) | [阅读](field-survey/servers.zh-CN.md) |
| Switches | [Read](field-survey/switches.md) | [阅读](field-survey/switches.zh-CN.md) |
| Power shelves | [Read](field-survey/power-shelves.md) | [阅读](field-survey/power-shelves.zh-CN.md) |
| Alerts | [Read](field-survey/alerts.md) | [阅读](field-survey/alerts.zh-CN.md) |
| Cabling | [Read](field-survey/cabling.md) | [阅读](field-survey/cabling.zh-CN.md) |
| Discovery diagnostics | [Read](field-survey/discovery-diagnostics.md) | [阅读](field-survey/discovery-diagnostics.zh-CN.md) |
| Racks | [Read](field-survey/racks.md) | [阅读](field-survey/racks.zh-CN.md) |

## Page guides

Browse by menu for purpose, field values, actions and result verification. Each main page has its own guide; see the [page guide index](user-guide/README.md) for the shared structure.

| Menu location | English | 简体中文 |
| --- | --- | --- |
| Overview → Rack topology (总览 → 机柜拓扑) | [Read](user-guide/rack-topology.md) | [阅读](user-guide/rack-topology.zh-CN.md) |
| Installation → Tasks (装机 → 安装任务) | [Read](user-guide/installation-tasks.md) | [阅读](user-guide/installation-tasks.zh-CN.md) |
| Resources → Devices / NIC inventory (资源 → 设备管理 / 网卡信息) | [Read](user-guide/device-management.md) | [阅读](user-guide/device-management.zh-CN.md) |
| Resources → Instances (资源 → 实例管理) | [Read](user-guide/instance-management.md) | [阅读](user-guide/instance-management.zh-CN.md) |
| Resources → Operating systems (资源 → 操作系统) | [Read](user-guide/operating-systems.md) | [阅读](user-guide/operating-systems.zh-CN.md) |
| Resources → Networks (资源 → 网络管理) | [Read](user-guide/network-management.md) | [阅读](user-guide/network-management.zh-CN.md) |
| Configuration → Installation profiles (配置 → 安装方案) | [Read](user-guide/installation-profiles.md) | [阅读](user-guide/installation-profiles.zh-CN.md) |
| Configuration → Site settings (配置 → 站点设置) | [Read](user-guide/site-settings.md) | [阅读](user-guide/site-settings.zh-CN.md) |
| Configuration → NICo cluster | [Read](user-guide/nico-cluster.md) | [阅读](user-guide/nico-cluster.zh-CN.md) |

## Project maintenance

| Document | English | 简体中文 |
| --- | --- | --- |
| Project overview | [Read](../README.md) | [阅读](../README.zh-CN.md) |
| Contributing | [Read](../CONTRIBUTING.md) | [阅读](../CONTRIBUTING.zh-CN.md) |
| Security | [Read](../SECURITY.md) | [阅读](../SECURITY.zh-CN.md) |
| Changelog | [Read](../CHANGELOG.md) | [阅读](../CHANGELOG.zh-CN.md) |
| Runtime tools | [Read](../bin/README.md) | [阅读](../bin/README.zh-CN.md) |

Commands, fields and paths retain their technical spelling in both languages. The current interface is Simplified Chinese; bilingual documentation does not imply UI localization. Historical environment records and upstream documentation remain in the development workspace outside the public PXEye documents.
