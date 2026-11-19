# 现场采集：供电框

[English](power-shelves.md) · **简体中文** · [现场采集指南](README.zh-CN.md)

页面：设备管理 → 供电框。NICo 里的供电框是整机柜站点的 **Power Shelf**。机柜 PDU 不由 NICo 管理，不会出现在这里。准备工作和通用流程见[现场采集指南](README.zh-CN.md)。

## 1. 数据来源

| 页面内容 | NICo 命令行 | gRPC 接口 | 能否自动采集 |
| --- | --- | --- | --- |
| 供电框列表、运行状态、健康、电源 | `power-shelf list`、`power-shelf show <标识>` | `FindPowerShelves` | 能 |
| 容量、电压 | `power-shelf show <标识>` | `FindPowerShelves` | 能 |
| 设备清单（序列号、PMC MAC） | `expected-power-shelf show` | `GetAllExpectedPowerShelves` | 能 |
| 健康历史 | `power-shelf health-history <标识>` | `FindPowerShelfHealthHistories` | 能（页面尚未使用） |
| 实时功率 | — | — | 不能：NICo 不返回功率读数 |
| 站点上有没有供电框 | — | — | 不能，要用户确认 |

所有字段目前都“仅定义”：验证过的站点上没有供电框。字段对照见[数据契约](../design/rack-operations-data-contract.zh-CN.md)第 2.3 节。

## 2. 采集命令

```bash
D=<采集目录>/cli
cli power-shelf list                             > $D/power-shelves-list.txt
cli expected-power-shelf show                    > $D/power-shelves-expected.txt
```

两者都为空时，页面会显示适用范围说明。确认符合实际后（见第 4 节）即可结束。

有供电框时，对每台执行：

```bash
P=<供电框标识>
cli power-shelf show $P                          > $D/power-shelves-$P-show.txt
cli --json power-shelf show $P                   > $D/power-shelves-$P-show.json
cli power-shelf health-history $P                > $D/power-shelves-$P-health.txt
```

整站采集会原样记录 `FindPowerShelves` 的返回。

## 3. 核对

| 项目 | 通过标准 | 不通过时记录 |
| --- | --- | --- |
| 行数 | 页面行数等于设备管理里的供电框数 | 多出或缺少的序列号 |
| 关联 | 每台都关联到了 NICo 的供电框对象 | 关联不上的设备，以及两边的标识 |
| 状态、健康、电源 | 和 `power-shelf show` 一致 | 实际的状态文本、健康取值、电源取值 |
| 容量、电压 | 和 `power-shelf show` 一致，单位为瓦和伏 | 实际的值和单位 |
| 字段 | 数据契约 2.3 节每个“仅定义”的字段实际有没有值 | 每个字段的实际值或“为空” |

## 4. 需要用户补充的数据

| 数据 | 为什么需要 | 用户怎么取得 | 存成 |
| --- | --- | --- | --- |
| 站点有没有供电框 | 命令返回为空时，要区分“站点没有”还是“有但没纳管” | 询问站点负责人；看是否为整机柜 | 写在 `session.md` |
| 应有的供电框清单（有的话） | 判断哪些还没纳管 | 整机柜的出货清单 | `supplements/power-shelves-expected.csv`：`serial,pmc_mac,rack` |
| 机柜 PDU 清单（可选） | NICo 不管理 PDU；如果以后要做机柜功率，需要先知道有哪些 PDU 以及怎么访问 | 机房的配电资料 | `supplements/power-pdus.csv`：`rack,name,model,management_ip,protocol` |

`protocol` 填 PDU 支持的管理协议，例如 `snmp`、`redfish`、`http`。只记录信息，不要求提供口令。

## 5. 常见情况

| 现象 | 判断 |
| --- | --- |
| 列表为空，站点是普通服务器机柜 | 正常。这一页在该站点不适用 |
| 用户问机柜用了多少电 | NICo 不提供，页面也做不到。记录用户的需求和 PDU 清单 |
