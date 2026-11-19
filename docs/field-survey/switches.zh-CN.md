# 现场采集：交换机

[English](switches.md) · **简体中文** · [现场采集指南](README.zh-CN.md)

页面：设备管理 → 交换机。NICo 里的交换机只指 **NVLink 交换机**（整机柜站点）。普通以太网接入交换机不由 NICo 管理，不会出现在这里；它们的连接见[布线](cabling.zh-CN.md)。准备工作和通用流程见[现场采集指南](README.zh-CN.md)。

## 1. 数据来源

| 页面内容 | NICo 命令行 | gRPC 接口 | 能否自动采集 |
| --- | --- | --- | --- |
| 交换机列表、运行状态、健康、电源 | `switch list`、`switch show <交换机ID>` | `FindSwitches` | 能 |
| NVOS 管理口、Fabric Manager | `switch show <交换机ID>` | `FindSwitches` | 能 |
| 设备清单（序列号、BMC MAC） | `expected-switch show` | `GetAllExpectedSwitches` | 能 |
| 健康历史 | `switch health-history <交换机ID>` | `FindSwitchHealthHistories` | 能（页面尚未使用） |
| 站点上有没有 NVLink 交换机 | — | — | 不能，要用户确认 |

所有字段目前都“仅定义”：验证过的站点上没有 NVLink 交换机。字段对照见[数据契约](../design/rack-operations-data-contract.zh-CN.md)第 2.2 节。

## 2. 采集命令

```bash
D=<采集目录>/cli
cli switch list                                  > $D/switches-list.txt
cli expected-switch show                         > $D/switches-expected.txt
```

两者都为空时，页面会显示适用范围说明，这一页在该站点没有内容。确认符合实际后（见第 4 节）即可结束。

有交换机时，对每台（或有代表性的几台）执行：

```bash
S=<交换机ID>
cli switch show $S                               > $D/switches-$S-show.txt
cli --json switch show $S                        > $D/switches-$S-show.json
cli switch health-history $S                     > $D/switches-$S-health.txt
```

整站采集会原样记录 `FindSwitches` 的返回。

## 3. 核对

有交换机时，**这是第一次见到真实数据**，要逐字段核对：

| 项目 | 通过标准 | 不通过时记录 |
| --- | --- | --- |
| 行数 | 页面行数等于设备管理里的交换机数 | 多出或缺少的序列号 |
| 关联 | 每台都关联到了 NICo 的交换机对象 | 关联不上的设备，以及两边的标识 |
| 状态、健康、电源 | 和 `switch show` 一致 | 实际的状态文本、健康取值、电源取值 |
| NVOS 管理口 | 管理口的 MAC 和地址与 `switch show` 一致 | 管理口为空时的原因 |
| Fabric Manager | 状态与 `switch show` 一致 | 实际出现的状态和原因文字 |
| 字段 | 数据契约 2.2 节每个“仅定义”的字段实际有没有值 | 每个字段的实际值或“为空” |

核对完成后，把数据契约 2.2 节里核对过的字段从“仅定义”改为“已验证”。

## 4. 需要用户补充的数据

| 数据 | 为什么需要 | 用户怎么取得 | 存成 |
| --- | --- | --- | --- |
| 站点有没有 NVLink 交换机 | 命令返回为空时，要区分“站点没有”还是“有但没纳管” | 询问站点负责人；看机柜型号是否为 GB200、GB300 一类整机柜 | 写在 `session.md` |
| 应有的 NVLink 交换机清单（有的话） | 判断哪些还没纳管 | 整机柜的出货清单 | `supplements/switches-expected.csv`：`serial,bmc_mac,rack` |

## 5. 常见情况

| 现象 | 判断 |
| --- | --- |
| 列表为空，站点只有以太网交换机 | 正常。这一页在该站点不适用，连接情况看布线页 |
| 用户说有 NVLink 交换机，但列表为空 | 没有纳管。看 `expected-switch show` 有没有声明，以及发现诊断里交换机 BMC 地址的探测结果 |
| 有交换机但健康是“未知” | Core 还没有对它跑健康检查，记录下来，过一段时间再看 |
