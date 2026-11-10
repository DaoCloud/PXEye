---
page_id: nico-cluster
language: en
title: NICo cluster
description: Deploy NICo online or offline with Helm, inspect services and progress, and connect the site.
navigation_group: configuration
updated_at: "2026-11-08"
product_version: "0.22.1"
---

# NICo cluster

**English** · [简体中文](nico-cluster.zh-CN.md) · [Page guides](README.md)

## 1. Purpose and entry

Open **Configuration → NICo cluster** to run Helm in the Kubernetes cluster hosting PXEye and inspect services. PXEye can start before NICo; business pages become available after connecting the site.

## 2. Fields

| Field | Requirement |
| --- | --- |
| Deployment mode | **Online** by default; choose **Offline** without network access. |
| Chart source | Online supports download URLs, Helm repositories and OCI. The default downloads a fixed NICo source revision and prepares its Core Chart. |
| Repository URL / Chart name | Required for a Helm repository; for example `https://charts.example.com` and `nico`. |
| Chart version | Optional for repository or OCI sources; blank uses the source default. A download URL selects its own version. |
| Offline material | Upload a `.tgz` Chart or a complete `.tar.gz` / `.zip` recipe, up to 128 MiB. No server login or deployment-package mount is required. |
| Site name | Site identifier, up to 100 characters. |
| Helm release | Lowercase letters, digits and hyphens, starting with a letter, up to 49 characters; for example `nico-system`. Defaults to the current namespace. Multi-phase recipes also validate names after adding phase suffixes. |
| Namespace | The PXEye namespace; read-only. |
| Timeout | 900 seconds by default; 60–1800 seconds. |
| values YAML | Paste Chart parameters or read a YAML file. Ordinary Charts need no separate component manifest; complete recipes use their per-phase values. |
| Site connection | Optional section for Core HTTPS, public PXE URL, client and CA Secrets, and target architecture. Service URLs can also be supplied when connecting after installation. |

Set image, database, Vault, service exposure and Boot options through the Chart values. A standalone NICo Core Chart uses the selected release prefix for default workload names and mounts the shared PXEye materials PVC. Complete recipes must keep workload names, Service DNS and Secret references aligned through their per-phase values. The materials PVC comes from site configuration and is independent of the Helm release name.

## 3. Steps

1. Select an online source, or choose Offline and upload material.
2. Set the release and values, then click **Check and preview**. PXEye prepares the Chart and checks configuration and permissions in the background.
3. Once prepared, click **Start deployment**, inspect the Helm command and confirm. **Deployment progress** shows actual commands, stages and exit codes.
4. Inspect the full component catalog, replicas, ports and images in **Services**. A successful individual Chart shows **Helm complete**; return to configuration to install further dependency Charts.
5. When required services, dependency resources and Boot HTTP files are ready, click **Apply to site**. PXEye verifies the Core identity before saving site settings and enabling business pages.

## 4. Examples

| Scenario | Input |
| --- | --- |
| Online repository | Select Helm repository and enter its URL, Chart name, optional version and values. |
| OCI | Enter `oci://registry.example.com/charts/nico`, a version and values. |
| Offline | Upload `nico-0.1.1.tgz`, use release `mmzhou` and read its values YAML. |

Replace example URLs with actual sources. See [Deployment](../nico-deployment.md) for parameters and dependencies.

## 5. Notes

- The PXEye ServiceAccount needs installation permissions. PXEye downloads Charts; Kubernetes nodes pull images. Both need suitable network access.
- The Core Chart does not include all PostgreSQL, Vault, certificate management, REST and Temporal dependencies. Install their Charts separately or use a complete ordered recipe.
- Offline Charts must include dependencies, and images must already be available. A Chart upload does not import node images.
- Existing services remain observable; same-name resources are not automatically adopted. Failed installations retain releases and persistent data.
- Service readiness, physical DHCP/Relay, PXE and OS installation require separate checks. Deployment does not automatically install hosts or update firmware.

Related: [Deployment and permissions](../nico-deployment.md) · [Site settings](site-settings.md) · [Network management](network-management.md)
