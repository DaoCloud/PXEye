---
page_id: nico-cluster
language: en
title: NICo cluster
description: Deploy NICo in the current Kubernetes cluster, observe services and connect the site.
navigation_group: configuration
updated_at: "2026-11-08"
product_version: "0.22.0"
---

# NICo cluster

**English** · [简体中文](nico-cluster.zh-CN.md) · [Page guides](README.md)

## 1. Purpose and entry

Open **Configuration → NICo cluster** to deploy NICo through Helm in the Kubernetes cluster running PXEye and inspect service status. Before NICo is connected, this is the default page after login; business pages become available after the site connection succeeds.

Prepare the [Helm package and deployment permissions](../nico-deployment.md) first. PXEye authentication, data storage and startup operate independently of NICo.

## 2. Field values

| Field | Requirement |
| --- | --- |
| Deployment package | Select a versioned directory mounted under `/nico-packages`, containing Charts, values, initialization jobs and file checksums. |
| Site name | Required, 1–100 characters; identifies the site. |
| Release prefix | Lowercase letters, digits and hyphens; must agree with the package's resource naming. |
| Namespace | Read-only, taken from the PXEye deployment configuration. This page operates in the current cluster. |
| Core HTTPS address | `https://host:port`, reachable from PXEye and covered by the Core certificate. |
| External PXE / HTTP address | `http://host:port` or HTTPS, reachable from the machines being installed; omit directory paths. |

Service exposure, database, network and storage settings belong to the package's values. Package variables determine how these fields affect each Chart.

## 3. Actions

1. Fill **Deployment configuration** and click **Check deployment configuration**. Checks run in the background; **Deployment workflow** shows stages and command records.
2. When checks pass, click **Start deployment**, review the site, namespace and addresses, and confirm. Services start in package dependency order.
3. **Service overview** shows services, replicas and ports. Click a service name for workloads and runtime/init container images.
4. Once required services, initialization jobs, certificates, storage and boot artifacts are ready, click **Apply to site**. PXEye verifies the client identity and reads Core before updating connection/material endpoints and enabling business pages.
5. On failure, inspect the stage and service status, resolve the cause and select **Verify and continue**. Pending Helm releases require resolution first.

## 4. Example

| Field | Example |
| --- | --- |
| Site name | `Example site` |
| Release prefix | `mmzhou` |
| Namespace | `mmzhou` |
| Core HTTPS address | `https://mmzhou-nico-api.mmzhou.svc:1079` |
| External PXE / HTTP address | `http://192.0.2.50:31880` |

The package must create the corresponding Services and expose PXE HTTP on that port. Replace these addresses with actual deployment values.

## 5. Notes

- The required catalog covers Core, PXE, DHCP, DNS, NTP, hardware health, SSH Console, database, Vault, certificate management, REST, Temporal and Keycloak. MAT, Flow and DPF are optional.
- Core/PXE init containers or mounted directories supply Boot artifacts; the artifact architecture must match the machine being installed.
- Existing services are observed; the page does not automatically adopt old releases or overwrite matching resources.
- Failures retain releases and persistent data. Verify uncertain stages after a PXEye restart before continuing.
- Service readiness and Boot HTTP access still require separate verification of DHCP, Relay, physical PXE and OS installation.
- Packages disable automatic enrollment and firmware updates; deploying the control plane does not start physical-machine installation.

Related: [Materials and permissions](../nico-deployment.md) · [Site settings](site-settings.md) · [Network management](network-management.md)
