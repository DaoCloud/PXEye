# 现场采集：供电框

[English](power-shelves.md) · **简体中文** · [现场采集指南](README.zh-CN.md)

> **已归档（2026-11-23）。** 本文档属于被整机柜新设计取代的一套设计，不再维护；内容保留归档时的原样，仅供查阅。现行设计见[设计文档](../../../design/README.zh-CN.md)，归档说明见[归档目录](../../README.zh-CN.md)。

页面：设备管理 → 供电框。页面显示 NICo 纳管的供电框（整机柜站点的 **Power Shelf**）：列表、运行状态、健康、电源状态、容量、电压，以及设备清单里的序列号和 PMC MAC。机柜 PDU 不由 NICo 管理，不会出现在这里。准备工作（环境变量、采集目录、`--save`）见[现场采集指南](README.zh-CN.md)。

## 1. 数据来源

| 页面内容 | 页面代码调用的 gRPC 接口（请求） | 对等的 nico 命令行 | 对等程度 | 能否自动采集 |
| --- | --- | --- | --- | --- |
| 供电框列表、运行状态、健康、电源状态 | `FindPowerShelves` `{}` | `power-shelf list`、`power-shelf show <供电框ID>`；完整记录用 `--json power-shelf show <供电框ID>` | 相同 | 能 |
| 容量（瓦）、电压（伏） | `FindPowerShelves` `{}` | `power-shelf show <供电框ID>` | 相同 | 能 |
| 设备清单（序列号、PMC MAC） | `GetAllExpectedPowerShelves` `{}` | `expected-power-shelf show` | 相同 | 能 |
| 健康历史（页面尚未使用） | `FindPowerShelfHealthHistories` | `power-shelf health-history <供电框ID>` | 相同 | 能（第 2 节命令，不在原样采集中） |
| 实时功率 | 无：没有接口返回瓦数 | — | 无 | 不能 |
| 站点上有没有供电框 | — | — | 无 | 不能，要用户确认 |

页面代码不使用命令行；核对以 gRPC 接口或采集文件为准，见[现场采集指南 1.3 节](README.zh-CN.md#13-命令行和接口的关系)。

## 2. 采集命令

假设已按[现场采集指南 1.2 节](README.zh-CN.md#12-入口脚本)导出 `SURVEY_*` 变量，在仓库根目录执行。

（1）数量和 ID：

```bash
tools/site-survey.sh --save power-shelves-ids.txt survey ids power-shelves
```

输出一行一个供电框 ID，行数就是供电框数量。为 0 时跳到第 4 节。

（2）每项内容的 gRPC 调用和对等命令行。`<供电框ID>` 取 `power-shelves-ids.txt` 的第一行；如果 `power-shelf list` 里有状态不是正常就绪或健康有告警的供电框，再取一台这样的 ID 重复执行带 `<供电框ID>` 的命令。

```bash
# 列表、状态、健康、电源、容量、电压
tools/site-survey.sh --save power-shelves-find.txt survey call 'FindPowerShelves={}'
tools/site-survey.sh --save power-shelves-list.txt cli power-shelf list
tools/site-survey.sh --save power-shelves-show.txt cli power-shelf show <供电框ID>
tools/site-survey.sh --save power-shelves-show-json.txt cli --json power-shelf show <供电框ID>

# 设备清单
tools/site-survey.sh --save power-shelves-expected-grpc.txt survey call 'GetAllExpectedPowerShelves={}'
tools/site-survey.sh --save power-shelves-expected.txt cli expected-power-shelf show

# 健康历史（页面尚未使用）
tools/site-survey.sh --save power-shelves-health-describe.txt survey describe FindPowerShelfHealthHistories
tools/site-survey.sh --save power-shelves-health.txt cli power-shelf health-history <供电框ID>
```

`survey call` 的输出只显示结构（长值截短，列表只留第一项）；完整数据看 `cli --json` 的输出或采集文件。

（3）原样采集整个站点执行一次即可（[现场采集指南第 2 节](README.zh-CN.md#2-通用流程)），不按页面重复。没有做过时执行：

```bash
tools/site-survey.sh capture
```

## 3. 核对

下表中 `$C` 指采集文件 `$SURVEY_DIR/capture-<日期时间>.json`，保存的文件在 `$SURVEY_DIR/cli/` 和 `$SURVEY_DIR/survey/` 下。

| 项目 | 通过标准 | 用什么对照 | 不通过时记录 |
| --- | --- | --- | --- |
| 行数 | 页面的供电框数等于 ID 数 | `jq '.pxeye_responses["/api/device-status"].body.power_shelves \| length' $C` 对照 `survey/power-shelves-ids.txt` 的行数 | 两边的数量，多出或缺少的 ID |
| 设备清单 | 设备管理里的供电框数等于清单条数 | `jq '.pxeye_responses["/api/equipment"].body.devices \| map(select(.kind=="power_shelf")) \| length' $C` 对照 `cli/power-shelves-expected.txt` | 多出或缺少的序列号、PMC MAC |
| 状态、健康、电源 | 和命令行一致 | `jq '.pxeye_responses["/api/device-status"].body.power_shelves' $C` 对照 `cli/power-shelves-show-json.txt` | 实际的状态文本、健康取值、电源取值 |
| 容量、电压 | 和命令行一致，单位为瓦和伏 | 同上，看 `capacity_watts`、`voltage` | 实际的值和单位 |
| 字段 | 数据契约 2.3 节每个“仅定义”的字段实际有没有值 | `cli/power-shelves-show-json.txt`、`survey/power-shelves-find.txt` | 每个字段的实际值或“为空” |
| 读取错误 | 没有失败的调用 | `jq '.summary' $C` 中 `failed_calls`、`reads_with_errors` 有没有 `FindPowerShelves`、`GetAllExpectedPowerShelves` | 方法、错误码和消息 |

字段对照见[数据契约](../design/rack-operations-data-contract.zh-CN.md)第 2.3 节。目前所有字段都“仅定义”：验证过的站点上没有供电框。

## 4. 需要用户补充的数据

| 数据 | 为什么需要 | 用户怎么取得 | 存成 |
| --- | --- | --- | --- |
| 站点有没有供电框 | 命令返回为空时，要区分“站点没有”还是“有但没纳管” | 询问站点负责人；看是否为整机柜。可对照 `tools/site-survey.sh cli expected-power-shelf show` 的输出 | 写在 `session.md` |
| 应有的供电框清单（有的话） | 判断哪些还没纳管 | 整机柜的出货清单 | `supplements/power-shelves-expected.csv`：`serial,pmc_mac,rack` |
| 机柜 PDU 清单（可选） | NICo 不管理 PDU；如果以后要做机柜功率，需要先知道有哪些 PDU 以及怎么访问 | 机房的配电资料 | `supplements/power-pdus.csv`：`rack,name,model,management_ip,protocol` |

`protocol` 填 PDU 支持的管理协议，例如 `snmp`、`redfish`、`http`。只记录信息，不要求提供口令。

## 5. 常见情况

| 现象 | 判断 |
| --- | --- |
| ID 数为 0，站点是普通服务器机柜 | 正常。这一页在该站点不适用 |
| ID 数为 0，但设备清单不为空 | 供电框已登记但还没纳管，记下清单里的序列号，问用户 |
| 用户问机柜用了多少电 | NICo 不返回功率读数，页面做不到。记录用户的需求和 PDU 清单 |

## 6. AI 执行清单

1. 执行 `tools/site-survey.sh --save power-shelves-ids.txt survey ids power-shelves`。成功后数行数。失败时按[现场采集指南第 5 节](README.zh-CN.md#5-给-ai-的规则)重试一次，仍失败就记下错误并停止本页。
2. 行数为 0：执行 `tools/site-survey.sh --save power-shelves-expected.txt cli expected-power-shelf show`。这表示页面在该站点没有纳管的供电框。按输出分两种情况：
   - 设备清单为空：停下问用户：“这个站点有没有 NVIDIA 整机柜的供电框（Power Shelf）？如果有，请提供出货清单，填 `supplements/power-shelves-expected.csv`（列 `serial,pmc_mac,rack`）。”同时问是否要记录机柜 PDU（`supplements/power-pdus.csv`）。记录回答后结束本页，跳到第 8 步。
   - 设备清单不为空：把其中的序列号和 PMC MAC 记入 `session.md`，停下问用户：“这 N 个供电框已登记，但没有被 NICo 纳管，是否应该纳管？”记录回答后结束本页，跳到第 8 步。
3. 行数大于 0：按第 2 节（2）依次执行全部命令，`<供电框ID>` 取第一行；`power-shelf list` 中有异常状态或健康告警的，再取一台执行带 ID 的命令。每条成功后再执行下一条。
4. 如果本站点还没做过原样采集，执行 `tools/site-survey.sh capture`。退出码为 0 继续；为 2 时修正原因后重来。
5. 按第 3 节逐项核对，每项写下通过或不通过和记录内容。
6. 设备清单条数和 ID 数不一致，或清单为空时，停下问用户要应有的供电框清单，存成 `supplements/power-shelves-expected.csv`，请用户确认。
7. 问用户是否要记录机柜 PDU；要的话存成 `supplements/power-pdus.csv`，不要口令。
8. 在 `session.md` 写本页：Core 版本、供电框数量、有没有数据、每项核对结果、失败的调用、已收到和缺少的用户数据（缺什么、影响哪一项）、需要更新的数据契约字段。
