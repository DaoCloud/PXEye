# 机柜运维：操作类功能规则

[English](rack-operations-actions.md) · **简体中文** · [设计文档](README.zh-CN.md)

- 状态：**已在 `rackActions` 开关下实现，没有在站点验证。** 没有向真实 Core 发出过任何写请求。这些操作只在演示采集上用 `tools/core-replay.py --demo-writes` 运行过。
- 范围：通过 NICo Core 改变设备或机柜状态的操作。只读页面见[范围与现状](rack-operations.zh-CN.md)；各领域的实现状态见[能力需求](rack-operations-requirements.zh-CN.md)；请求结构和审计表见[数据契约](rack-operations-data-contract.zh-CN.md)第 4 节。
- 依据：`src/pxeye/services/rack_actions.py` 和站点 Core 版本 `7c7788a` 的 NICo 源码。命令行一列是调用同一接口的 `nico-admin-cli` 子命令；PXEye 不运行它们。

## 1. 操作

PXEye 只调用 NICo Core，自己从不直接访问 BMC 或 RMS。操作从服务器、交换机、供电框页的操作对话框（“操作”或“批量操作”）和机柜页发起，每个操作都列在操作记录页。

| 操作 | NICo 接口 | 对应的 `nico-admin-cli` | 风险 | 需要 RMS | 状态 |
| --- | --- | --- | --- | --- | --- |
| 上电；正常关机；正常重启 | `AdminPowerControl` (`On`, `GracefulShutdown`, `GracefulRestart`) | `bmc-machine admin-power-control` | 中 | 否：经主机 BMC | 已实现 |
| 强制下电；强制重启；AC 断电重启 | `AdminPowerControl` (`ForceOff`, `ForceRestart`, `ACPowercycle`) | `bmc-machine admin-power-control` | 高 | 否：经主机 BMC | 已实现 |
| 设置 / 清除维护标记 | `SetMaintenance` (`Enable` with `reference`, `Disable`) | `managed-host maintenance on` / `off` | 低 | 否：只改 NICo 状态 | 已实现 |
| 隔离 | `SetManagedHostQuarantineState` (`BLOCK_ALL_TRAFFIC`) | `managed-host quarantine on` | 高 | 否：NICo 网络控制 | 已实现 |
| 解除隔离 | `ClearManagedHostQuarantineState` | `managed-host quarantine off` | 中 | 否：NICo 网络控制 | 已实现 |
| 重置主机 | `TriggerManagedHostReset` | `managed-host reset` | 高 | 否 | 已实现 |
| 重启 BMC | `AdminBmcReset` | `bmc-machine bmc-reset` | 中 | 否：经主机 BMC | 已实现 |
| 按需硬件校验 | `OnDemandMachineValidation` (`Start`) | `machine-validation on-demand start` | 高 | 否 | 已实现 |
| 核对 SKU | `VerifySkuForMachine` | `sku verify` | 低 | 否 | 已实现 |
| 计算托盘上电 / 下电 / 重启 | `ComponentPowerControl` (machine IDs) | `component-manager component-power-control` | 中（上电）、高 | 是，`compute_tray_backend` 为 `rms` 时；为 `core`（NICo 自身的 Redfish）时否 | 已实现 |
| 交换机上电 / 下电 / 重启 | `ComponentPowerControl` (switch IDs) | `component-manager component-power-control` | 中（上电）、高 | 是：交换机电源经 RMS | 已实现 |
| 交换机复位（BMC 复位，BMC / NVOS / SDN 恢复出厂） | `ComponentReset` | `component-manager component-reset` | 高 | 是：组件复位经 RMS | 已实现 |
| 交换机退役 | `DecommissionSwitch` | `managed-switch decommission` | 高 | 否 | 已实现 |
| 供电框上电 / 下电 | `SetPowerShelfMaintenance` (`POWER_ON`, `POWER_OFF`) | `power-shelf maintenance` | 中（上电）、高 | 是，`power_shelf_backend` 为 `rms` 时 | 已实现 |
| 供电框退役 | `DecommissionPowerShelf` | `power-shelf decommission` | 高 | 否 | 已实现 |
| 机柜维护（固件、NVOS、电源序列、NMX-C） | `OnDemandRackMaintenance` | `rack maintenance start` | 高 | 是：NICo 编排，固件、NVOS、NMX-C 步骤经 RMS | 已实现 |
| 终止机柜维护 | `TerminateRackMaintenance` | `rack maintenance terminate` | 中 | 是：同机柜维护 | 已实现 |
| 组件固件更新（计算托盘、交换机、机柜） | `UpdateComponentFirmware` | `component-manager update-firmware` | 高 | 是：组件固件经 RMS | 已实现 |
| 机柜上电 / 下电 | — | — | 高 | — | NICo 不提供 （第 2 节） |
| 机柜冷重启 | — | — | 高 | — | NICo 不提供 （第 2 节） |
| 供电框固件更新 | — | — | — | — | NICo 不提供，不提供入口（第 2 节） |

RMS 是 NVIDIA Rack Management Service，以 Apache-2.0 开源（[源码](https://github.com/dsx-ai-factory/nv-rms)，[文档](https://docs.nvidia.com/rms/documentation/home/)）。组件管理后端为 `rms`（NICo chart 默认值）时，NICo 把托盘、交换机和供电框电源、组件复位、组件固件和机柜维护的步骤交给 RMS；`compute_tray_backend` 也可以是 `core`，即 NICo 自己的 Redfish 路径。RMS 只支持 NVIDIA 整机柜硬件：GB200 和 GB300 计算托盘、NVSwitch 托盘、LiteOn 和 Delta 供电框；VR NVL72 在开发中。Core 配置为 `rms` 而没有部署 RMS 时，这些操作会失败。对话框把 `GetRmsVersion` 的结果作为信息显示，不据此阻止操作。

PXEye 没有实现：健康覆盖（`InsertHealthReportOverride`、`RemoveHealthReportOverride`）。

## 2. NICo 不提供的机柜级操作

- **机柜上电和下电。** NICo 机柜状态机中电源序列的 `PoweringOn` 和 `PoweringOff` 是空实现。只实现了 `PowerReset`，即正常重启机柜内的计算主机；它通过机柜维护的 `power_sequence` 项目执行。
- **机柜冷重启。** 只有 RMS 提供（`ExecuteColdReboot`），NICo 不调用。
- **供电框固件更新。** NICo 没有实现。

机柜页把机柜上电/下电和机柜冷重启显示为不可用的按钮，并写明原因。供电框固件更新不提供入口。

## 3. 和装机的避让

1. 目标有状态为 `queued`、`running` 或 `needs_attention` 的安装任务时，任何操作都拒绝。机柜检查放在其中的机器的序列号。
2. 机器的 NICo 生命周期状态与装机相关时（以 `HostInit` 开头，或以 `Assigned` 开头但不是 `Assigned/Ready`），拒绝电源、隔离、重置主机、校验和计算托盘固件操作。维护标记和核对 SKU 不受此限制。
3. 检查在服务端预览时执行，执行时再执行一次；页面上的判断不能代替服务端检查。
4. 未做：操作进行中时，安装预检不会拒绝同一设备的新安装任务。这需要预检读取操作记录，属于受保护的安装代码，要单独评审。

## 4. 确认

- 预览在服务端执行，逐个检查目标：在 Core 中存在、没有进行中的安装任务、生命周期状态允许、必填参数齐全。一次最多 10 个目标。
- 预览逐个列出目标的序列号、当前状态、操作的影响；未通过的目标列出原因。只执行通过的目标。
- 预览有效 5 分钟，只能使用一次；过期后重新预览。
- 高风险操作要求逐个输入目标的序列号（没有序列号时输入对象 ID）。
- 设置维护标记和隔离必须填写原因或工单链接；维护标记的原因写入 Core 的 `reference`。

## 5. 执行和结果

- 先以 `sent` 状态写入记录，再调用 Core。每个目标调用一次。
- 超时或结果未知时**从不自动重发**。调用后读回状态：电源读 `GetComponentPowerDetails`，维护、隔离和核对 SKU 读机器对象，机柜维护读机柜对象，退役读交换机或供电框列表。
- 读回一致才记为 `succeeded`；Core 报告失败或请求没有发出时记为 `failed`；其他情况记为 `unknown`，并附上读回的值。下一步由操作人决定。
- 批量操作逐个执行；一个失败不影响其他目标，不回滚。
- PXEye 不在机柜内编排设备顺序；机柜级工作由 NICo 的机柜维护完成。

## 6. 审计

每次执行的每个目标在 SQLite 表 `rack_actions` 中有一行：时间、操作者、操作、目标、参数（类似凭据的键已脱敏）、原因、检查、状态、Core 返回的消息和读回的状态。各列见[数据契约](rack-operations-data-contract.zh-CN.md)第 4 节。记录不删除；操作记录页列出记录，不提供删除。

## 7. 开关和环境

- `rackActions`（chart）/ `rack_actions`（`site.json`），默认关闭。只在 `rackOperations` 开启且实例不是只读观察实例时生效。
- 只读观察实例永远不能执行操作：它在 HTTP 层拒绝写请求，也不显示操作按钮。
- 验证必须在可写环境中的指定测试设备上做，不在装机批次进行时做。验证站点是通用服务器，没有 NICo 机柜对象；它的 Core 把三个后端都配置为 `rms`，但没有部署 RMS，所以经 RMS 的操作在那里会失败。

## 8. 已实现和剩余

| 事项 | 状态 |
| --- | --- |
| 操作目录、预览、执行、读回、审计表、记录接口 | 已实现 |
| 服务器、交换机、供电框页的操作对话框；机柜页；操作记录页 | 已实现 |
| 带 GB200 NVL72 机柜的演示采集和 `tools/core-replay.py --demo-writes` | 已实现；只用于演示采集，其他命令仍然拒绝 |
| 在站点验证，经 RMS 的操作要部署 RMS | 未做 |
| 安装预检读取操作记录（第 3 节第 4 条） | 未做；受保护代码 |

## 9. 待决定

1. 操作者身份：现在只有一个登录口令，记录里只有会话和来源地址。是否需要区分操作人。
2. 用哪个环境、哪几台设备验证写操作，该环境是否有 RMS。
