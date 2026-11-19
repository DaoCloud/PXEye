# 现场采集：服务器

[English](servers.md) · **简体中文** · [现场采集指南](README.zh-CN.md)

页面：设备管理 → 服务器，以及服务器的“运行状态”弹窗（状态时间线、健康历史、硬件校验、固件清单）。准备工作和通用流程见[现场采集指南](README.zh-CN.md)。

## 1. 数据来源

| 页面内容 | NICo 命令行 | gRPC 接口 | 能否自动采集 |
| --- | --- | --- | --- |
| 服务器列表、运行状态、健康、硬件能力、LLDP | `machine show --hosts`、`machine show <机器ID>` | `FindMachineIds`、`FindMachinesByIds` | 能 |
| 设备清单（序列号、BMC MAC） | `expected-machine show` | （PXEye 用命令行） | 能 |
| 电源状态 | — | `GetPowerOptions` | 能 |
| 当前状态（全部机器） | `machine states --hosts` | `FindMachinesByIds` | 能 |
| 状态时间线 | `machine show <机器ID> --history-count 100` | `FindMachineStateHistories` | 能 |
| 健康历史 | `machine health-history <机器ID>` | `FindMachineHealthHistories` | 能 |
| 硬件校验 | `machine-validation runs show --machine <机器ID> --history`、`machine-validation results show --machine <机器ID>` | `GetMachineValidationRuns`、`GetMachineValidationResults` | 能 |
| 固件清单、机型、锁定、安全启动 | `site-explorer get-report endpoint` | `GetComponentInventory` | 能 |
| 机柜 | `expected-machine show` 的机柜列 | 机器的 `rack_id` | 只能读到已填写的；没填的要用户提供 |
| 槽位、托盘 | `machine show --hosts` 的 Slot、Tray 列 | `placement_in_rack` | 通用服务器站点没有，NICo 不提供录入 |
| 主机固件基线 | `firmware show` | `GetDesiredFirmwareVersions` | 只有 NICo 自带的 DPU 条目；主机的要用户提供 |

字段对照见[数据契约](../design/rack-operations-data-contract.zh-CN.md)第 2.1 节和第 3.1、3.2、3.4、3.5 节。

## 2. 采集命令

```bash
D=<采集目录>/cli
cli machine show --hosts                         > $D/servers-machine-show.txt
cli --json machine show --hosts                  > $D/servers-machine-show.json
cli expected-machine show                        > $D/servers-expected-machine.txt
cli machine states --hosts                       > $D/servers-states.txt
```

服务器数量为 0 时，页面上的设备都会显示“NICo 尚未建立设备对象”，后面的命令不用再执行，直接看第 4 节。

再挑两三台有代表性的机器：一台已就绪、一台卡住或失败、一台带 DPU（如果有）。对每台执行：

```bash
M=<机器ID>
cli machine show $M --history-count 100        > $D/servers-$M-show.txt
cli machine health-history $M                    > $D/servers-$M-health.txt
cli machine-validation runs show --machine $M --history > $D/servers-$M-validation-runs.txt
cli machine-validation results show --machine $M > $D/servers-$M-validation-results.txt
survey call 'GetComponentInventory={"machineIds":{"machineIds":[{"id":"'$M'"}]}}' > $D/servers-$M-firmware.txt
```

站点级的配置各取一次：

```bash
cli machine-validation tests show                > $D/servers-validation-tests.txt
cli sku show                                     > $D/servers-sku.txt
cli firmware show                                > $D/servers-firmware-baseline.txt
```

最后执行一次整站采集（见指南第 2 节），它会把上面这些读取以及每台机器的四项运行状态都原样记录下来。

## 3. 核对

| 项目 | 通过标准 | 不通过时记录 |
| --- | --- | --- |
| 行数 | 页面行数等于设备管理里的服务器数 | 多出或缺少的序列号 |
| 关联 | 每台已在 NICo 建立对象的服务器都关联上（汇总条“NICo 已建立对象”的数字等于 `machine show --hosts` 的行数） | 关联不上的设备：它的 BMC MAC，以及 `machine show` 里对应机器的 BMC MAC |
| 状态和健康 | 页面上的运行状态、健康和 `machine show <机器ID>` 一致 | 不一致的字段和两边的值 |
| 需要处理 | 列在“需要处理”里的机器，确实是处理失败、超出状态时限或有告警 | 误报或漏报的机器 |
| 状态时间线 | 段数和顺序与 `machine show <机器ID> --history-count 100` 的历史一致；当前状态与 `machine states` 一致 | 原始时间格式；时间线里出现的新结构 |
| 健康历史 | 告警的开始和恢复与 `machine health-history` 一致 | 记录条数；带 target 的告警 |
| 硬件校验 | 记录条数和结果与 `machine-validation runs show` 一致 | 第一次出现的校验结果字段 |
| 固件清单 | 条目数等于报告里的固件条目数；版本为空的条目仍显示 | 不同厂商的条目命名；安全启动不为空时的字段 |
| 带 DPU | 一台主机只出现一次，DPU 不被当成服务器 | `machine show` 里的机器类型 |

## 4. 需要用户补充的数据

| 数据 | 为什么需要 | 用户怎么取得 | 存成 |
| --- | --- | --- | --- |
| 服务器所在机柜 | NICo 不自动发现机柜，只记录人工声明的值；没填的服务器不会出现在机柜拓扑的机柜分组里 | 机房的上架记录或资产表 | `supplements/servers-rack.csv`：`serial,rack` |
| 服务器在机柜中的 U 位（可选） | 通用服务器站点 NICo 不提供位置 | 上架记录，或现场查看 | `supplements/servers-position.csv`：`serial,rack,unit` |
| 主机固件基线（可选） | 没有基线就只能展示版本，不能判断是否合规 | 硬件厂商发布的推荐版本，或站点规定的版本 | `supplements/servers-firmware-baseline.csv`：`vendor,model,component,version` |
| 是否启用机器校验和 SKU | 没有启用时校验记录只有“已跳过”，这是站点设置，不是故障 | 询问站点负责人 | 写在 `session.md` |
| 应有的服务器清单 | 判断有没有服务器根本没进入 NICo | 到货清单或采购清单 | `supplements/servers-expected.csv`：`serial,bmc_mac,rack` |

`component` 列使用固件清单里显示的部件 ID（如 `BMC-Primary`、`UEFI`）。不同厂商的命名不一样，要按该站点实际出现的名称填写。

机柜可以在可写的控制台里，通过设备管理的系统配置逐台填写。观察实例只读，不能在上面填。

## 5. 常见情况

| 现象 | 判断 |
| --- | --- |
| `machine show --hosts` 为空，但设备管理里有服务器 | 服务器在 PXEye 里有规划，但还没进入 NICo 的发现流程。看[发现诊断](discovery-diagnostics.zh-CN.md) |
| 机器一直停在某个状态，且超出时限 | 状态时间线里看它在哪一步停留最久，结合健康历史和 `machine show` 的状态原因 |
| 校验记录全部是“已跳过” | 站点没有启用机器校验，问用户确认 |
| 固件清单为空 | 这台机器的 BMC 探测报告不完整，看发现诊断里该地址的结果 |
