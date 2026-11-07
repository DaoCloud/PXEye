# Reference cluster and screenshots

**English** · [简体中文](reference-cluster.zh-CN.md) · [Documentation](README.md)

## Architectural reference

The screenshots use an authored **Grace Blackwell Cluster** scenario inspired by NVIDIA's [DGX GB rack hardware guide](https://docs.nvidia.com/dgx/dgxgb200-user-guide/hardware.html) and [GB200 system/network overview](https://docs.nvidia.com/multi-node-nvlink-systems/multi-node-tuning-guide/system.html). Those documents describe compute trays, BlueField-3 management endpoints, NVLink switch trays, power shelves and separate management networks.

This is a partial logical management view, not a full NVL72 bill of materials or cable map. The screenshot subset has four compute entries, two NVLink switches and one power shelf in `AI-R01`, plus two management servers in `MGMT-R01`. It deliberately omits most rack components and the workload fabric.

| Object | Example naming | Address domain |
| --- | --- | --- |
| Compute entries | `gb200-r01-c01` … `c04` | BMC `10.251.1.0/24`; management `10.252.1.0/24`. |
| BlueField endpoints | Two DPU BMC interfaces per compute entry | Rack BMC subnet. |
| NVLink switches | `nvlink-r01-s01`, `s02` | BMC subnet; NVOS `10.251.31.0/24`. |
| Power shelf | `power-r01-p01` | PMC on the rack BMC subnet. |
| Management servers | `control-01`, `control-02` | BMC `10.251.10.0/24`; management `10.252.10.0/24`. |

Rack IDs, serial numbers, locally administered MACs and private addresses are authored for this scenario. They do not refer to a customer site. Task states are display data, not observations of a successful deployment. The single power shelf is a subset, not a power-capacity design; the DPU indicator counts interface entries in the current renderer rather than proving physical device inventory.

## Image provenance

The three images are rendered from PXEye's actual `src/pxeye/web/` frontend with [local view data](../examples/ai-factory-view.json). The capture tool starts a loopback-only static server, supplies read-only API responses and blocks external requests. It starts no NICo, DHCP, Redfish, SSH or installation backend. It does not mutate the deployed site's inventory.

These files are UI response examples, **not** a `site.json`, CSV inventory or provisioning input. The currently Chinese UI is shared by both documentation languages. ARM64/GB200 OS provisioning remains outside the established physical validation scope.

## Reproduce the captures

Use Node.js with Playwright and its Chromium installed in a documentation tooling environment:

```bash
npm ci --ignore-scripts
npx playwright install chromium
npm run docs:screenshots
```

If dependencies are installed elsewhere, set `PLAYWRIGHT_MODULE` to the installed module path and, optionally, `CHROMIUM_EXECUTABLE` to its Chromium binary. The tool uses the real stylesheet and renderer and checks page errors and horizontal overflow.

| Image | Page |
| --- | --- |
| [Rack topology](assets/screenshots/rack-topology.png) | Rack membership, serials, addresses and reported power. |
| [Device management](assets/screenshots/device-management.png) | Inventory and address actions. |
| [Installation tasks](assets/screenshots/installation-tasks.png) | Batch and per-device progress with console/log entries. |

When changing the dataset, keep identities and addresses consistent across all three pages, preserve the reference scope and update the paired documents.
