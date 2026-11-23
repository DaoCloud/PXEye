# 现场采集：服务器

[English](servers.md) · **简体中文** · [现场采集指南](README.zh-CN.md)

> **已归档（2026-11-23）。** 本文档属于被整机柜新设计取代的一套设计，不再维护；内容保留归档时的原样，仅供查阅。现行设计见[设计文档](../../../design/README.zh-CN.md)，归档说明见[归档目录](../../README.zh-CN.md)。

页面：设备管理 → 服务器，以及服务器的“运行状态”弹窗（状态时间线、健康历史、硬件校验、固件清单）。页面列出 NICo 已建立对象的服务器及其运行状态、健康、硬件能力、LLDP、电源状态和机柜。准备工作（环境变量、`--save`、采集目录）和通用流程见[现场采集指南](README.zh-CN.md)。

## 1. 数据来源

| 页面内容 | 页面代码调用的 gRPC 接口（请求） | 对等的 nico 命令行 | 对等程度 | 能否自动采集 |
| --- | --- | --- | --- | --- |
| 服务器列表、运行状态、健康、硬件能力、LLDP | `FindMachineIds` `{}`，然后 `FindMachinesByIds` `{"machineIds":[...],"includeHistory":false}` | `machine show --hosts`（列表）、`--json machine show <机器ID>`（完整 JSON，含 `lldp_neighbors`） | 相同 | 能 |
| 设备清单（序列号、BMC MAC） | 页面代码运行命令行 `expected-machine show`（JSON） | `expected-machine show` | 相同 | 能 |
| 电源状态 | `GetPowerOptions` `{"machineId":[]}` | — | 无 | 能 |
| 当前状态（全部主机，仅交叉核对） | `FindMachinesByIds`（同第一行；本行只是拿它的状态做交叉核对） | `machine states --hosts`（`FindMachineStatesByIds`，来源不同） | 近似 | 能 |
| 状态时间线 | `FindMachineStateHistories` `{"machineIds":[{"id":"<机器ID>"}]}` | `machine show <机器ID> --history-count 100` | 近似 | 能 |
| 健康历史 | `FindMachineHealthHistories` `{"machineIds":[{"id":"<机器ID>"}]}` | `machine health-history <机器ID>` | 相同 | 能 |
| 硬件校验 | `GetMachineValidationRuns` `{"machineId":{"id":"<机器ID>"},"includeHistory":true}`、`GetMachineValidationResults` `{"machineId":{"id":"<机器ID>"},"includeHistory":true}` | `machine-validation runs show --machine <机器ID> --history`、`machine-validation results show --machine <机器ID>` | 相同 | 能 |
| 校验和 SKU 的站点配置（仅供参考） | 无（页面不读取站点配置） | `machine-validation tests show`（`GetMachineValidationTests`）、`sku show`；只用命令行读取 | 无 | 能 |
| 固件清单、机型、锁定、安全启动 | `GetComponentInventory` `{"machineIds":{"machineIds":[{"id":"<机器ID>"}]}}` | `site-explorer get-report endpoint <BMC 地址>` | 近似 | 能 |
| 机柜 | 机器的 `rack_id`（`FindMachinesByIds`） | `expected-machine show` 的机柜列 | 相同 | 只能读到已填写的；没填的要用户提供 |
| 槽位、托盘 | 机器的 `placement_in_rack`（`FindMachinesByIds`） | `machine show --hosts` 的 Slot、Tray 列 | 相同 | 通用服务器站点没有，NICo 不提供录入 |
| 主机固件基线 | 无（页面不读取基线） | `firmware show`（`ListHostFirmware`），只作为 NICo 持有内容的参考 | 无 | 只有 NICo 自带的 DPU 条目；主机的要用户提供 |

页面代码不使用命令行（设备清单除外）；核对以 gRPC 接口或采集文件为准，见[指南 1.3 节](README.zh-CN.md#13-命令行和接口的关系)。

## 2. 采集命令

以下命令在仓库根目录执行，假定已按[指南 1.2 节](README.zh-CN.md#12-入口脚本)导出 `SURVEY_*` 变量。

(1) 数量和 ID：

```bash
tools/site-survey.sh --save servers-ids.txt survey ids machines
tools/site-survey.sh --save servers-machine-show.txt cli machine show --hosts
tools/site-survey.sh --save servers-machine-states.txt cli machine states --hosts
```

`<机器ID>` 的取法：
- 第一台：`survey/servers-ids.txt` 的第一行。
- 第二台：在 `cli/servers-machine-states.txt` 里找一台状态含 `Failed`、`Error` 或停留在非 `Ready` 状态的主机，取它的 ID；没有就跳过。
- 带 DPU 的主机（如果有）：`cli/servers-machine-show.txt` 里 DPU 列不为空的一台。

`<BMC 地址>`：`--json machine show <机器ID>` 输出里该机器的 BMC IP。

(2) 每一项。列表和设备清单（站点一次）：

```bash
tools/site-survey.sh --save servers-list.txt survey call 'FindMachineIds={}'
tools/site-survey.sh --save servers-expected-machine.txt cli expected-machine show
tools/site-survey.sh --save servers-power.txt survey call 'GetPowerOptions={"machineId":[]}'
tools/site-survey.sh --save servers-validation-tests.txt cli machine-validation tests show
tools/site-survey.sh --save servers-sku.txt cli sku show
tools/site-survey.sh --save servers-firmware-baseline.txt cli firmware show
```

对每台选出的机器（把 `<机器ID>`、`<BMC 地址>` 换成实际值）：

```bash
tools/site-survey.sh --save servers-<机器ID>-machine.txt survey call 'FindMachinesByIds={"machineIds":[{"id":"<机器ID>"}],"includeHistory":false}'
tools/site-survey.sh --save servers-<机器ID>-machine-json.txt cli --json machine show <机器ID>
tools/site-survey.sh --save servers-<机器ID>-history.txt survey call 'FindMachineStateHistories={"machineIds":[{"id":"<机器ID>"}]}'
tools/site-survey.sh --save servers-<机器ID>-history-cli.txt cli machine show <机器ID> --history-count 100
tools/site-survey.sh --save servers-<机器ID>-health.txt survey call 'FindMachineHealthHistories={"machineIds":[{"id":"<机器ID>"}]}'
tools/site-survey.sh --save servers-<机器ID>-health-cli.txt cli machine health-history <机器ID>
tools/site-survey.sh --save servers-<机器ID>-validation-runs.txt survey call 'GetMachineValidationRuns={"machineId":{"id":"<机器ID>"},"includeHistory":true}'
tools/site-survey.sh --save servers-<机器ID>-validation-runs-cli.txt cli machine-validation runs show --machine <机器ID> --history
tools/site-survey.sh --save servers-<机器ID>-validation-results.txt survey call 'GetMachineValidationResults={"machineId":{"id":"<机器ID>"},"includeHistory":true}'
tools/site-survey.sh --save servers-<机器ID>-validation-results-cli.txt cli machine-validation results show --machine <机器ID>
tools/site-survey.sh --save servers-<机器ID>-firmware.txt survey call 'GetComponentInventory={"machineIds":{"machineIds":[{"id":"<机器ID>"}]}}'
tools/site-survey.sh --save servers-<机器ID>-explore-report.txt cli site-explorer get-report endpoint <BMC 地址>
```

`survey call` 的输出只显示结构（长值截短，列表只留第一项）；完整数据看 `cli --json` 的输出或采集文件。

(3) 整站采集 `tools/site-survey.sh capture` 每个站点只执行一次（[指南第 2 节](README.zh-CN.md#2-通用流程)），不按页面执行。它会记录上面的读取，以及每台机器的四项运行状态。

## 3. 核对

以下 `C` 为采集文件：`C=$SURVEY_DIR/capture-<日期时间>.json`。

| 项目 | 通过标准 | 用什么对照 | 不通过时记录 |
| --- | --- | --- | --- |
| 行数 | 页面服务器数等于 NICo 机器数 | `jq '.pxeye_responses["/api/device-status"].body.servers \| length' $C` 对照 `survey/servers-ids.txt` 的行数 | 多出或缺少的机器 ID |
| 关联 | 每台已在 NICo 建立对象的服务器都关联上设备清单 | `cli/servers-expected-machine.txt` 对照 `cli/servers-machine-show.txt` 的 BMC MAC | 关联不上的设备：它的 BMC MAC，以及对应机器的 BMC MAC |
| 状态和健康 | 页面的运行状态、健康与机器 JSON 一致 | `jq '.pxeye_responses["/api/device-status"].body.servers["<机器ID>"]' $C` 对照 `cli/servers-<机器ID>-machine-json.txt` | 不一致的字段和两边的值 |
| 电源状态 | 每台机器都有电源状态，或明确为未知 | 上一行的 jq 输出对照 `survey/servers-power.txt` | 缺少电源状态的机器 |
| 需要处理 | 列为“需要处理”的机器确实失败、超时或有告警 | 页面的“需要处理”是前端按 `lifecycle.outcome == "error"`、`lifecycle.above_sla` 或 `health.level` 为 warning/alert/critical 算出的：`jq -r '.pxeye_responses["/api/device-status"].body.servers \| to_entries[] \| select(.value.lifecycle.outcome == "error" or .value.lifecycle.above_sla or (.value.health.level \| IN("warning","alert","critical"))) \| .key' $C`，对照 `cli/servers-machine-states.txt` | 误报或漏报的机器 |
| 状态时间线 | 段数和顺序与状态历史一致 | `jq '.pxeye_responses["/api/device-status/machines/<机器ID>/history"].body' $C` 对照 `survey/servers-<机器ID>-history.txt`，交叉参考 `cli/servers-<机器ID>-history-cli.txt` | 原始时间格式；新出现的结构 |
| 健康历史 | 告警的开始和恢复与健康历史一致 | `jq '.pxeye_responses["/api/device-status/machines/<机器ID>/health"].body' $C` 对照 `cli/servers-<机器ID>-health-cli.txt` | 记录条数；带 target 的告警 |
| 硬件校验 | 记录条数和结果一致 | `jq '.pxeye_responses["/api/device-status/machines/<机器ID>/validation"].body' $C` 对照 `cli/servers-<机器ID>-validation-runs-cli.txt`、`cli/servers-<机器ID>-validation-results-cli.txt` | 第一次出现的校验结果字段 |
| 固件清单 | 条目数等于清单条目数；版本为空的条目仍显示 | `jq '.pxeye_responses["/api/device-status/machines/<机器ID>/firmware"].body' $C` 对照 `survey/servers-<机器ID>-firmware.txt`，交叉参考 `cli/servers-<机器ID>-explore-report.txt` | 不同厂商的条目命名；安全启动不为空时的字段 |
| 机柜 | 有 `rack_id` 的机器显示该机柜 | `cli/servers-expected-machine.txt` 的机柜列 | 机柜为空的机器序列号 |
| 带 DPU | 一台主机只出现一次，DPU 不被当成服务器 | `cli/servers-machine-show.txt`（`--hosts` 只列主机）对照第一行的 jq 输出 | `machine show` 里的机器类型 |

## 4. 需要用户补充的数据

| 数据 | 为什么需要 | 用户怎么取得 | 存成 |
| --- | --- | --- | --- |
| 服务器所在机柜 | NICo 不自动发现机柜，只记录人工声明的值；没填的服务器不会出现在机柜拓扑的机柜分组里 | 机房的上架记录或资产表；已填的部分见 `tools/site-survey.sh cli expected-machine show` 的机柜列 | `supplements/servers-rack.csv`：`serial,rack` |
| 服务器在机柜中的 U 位（可选） | 通用服务器站点 NICo 不提供位置 | 上架记录，或现场查看 | `supplements/servers-position.csv`：`serial,rack,unit[,height]` |
| 主机固件基线（可选） | 没有基线就只能展示版本，不能判断是否合规 | 硬件厂商发布的推荐版本，或站点规定的版本；NICo 现有内容见 `tools/site-survey.sh cli firmware show` | `supplements/servers-firmware-baseline.csv`：`vendor,model,component,version` |
| 是否启用机器校验和 SKU | 没有启用时校验记录只有“已跳过”，这是站点设置，不是故障 | 询问站点负责人；现有配置见 `tools/site-survey.sh cli machine-validation tests show` 和 `tools/site-survey.sh cli sku show` | 写在 `session.md` |
| 应有的服务器清单 | 判断有没有服务器根本没进入 NICo | 到货清单或采购清单 | `supplements/servers-expected.csv`：`serial,bmc_mac,rack` |

`component` 列使用固件清单里显示的部件 ID（如 `BMC-Primary`、`UEFI`）。不同厂商的命名不一样，要按该站点实际出现的名称填写。

机柜可以在可写的控制台里，通过设备管理的系统配置逐台填写。观察实例只读，不能在上面填。

U 位可以在可写的控制台上，用服务器页的“导入 U 位”导入，CSV 为 `serial,rack,unit[,height]`。PXEye 把它存在自己的数据库里，不写入 NICo；机柜列只与设备的机柜比对。只读观察实例不能导入。导入后，采集文件里有 `/api/rack-units`，用 `jq '.pxeye_responses["/api/rack-units"].body | {positions: (.positions | length), mismatches, unknown}' $C` 检查。格式和校验见[数据契约](../design/rack-operations-data-contract.zh-CN.md)第 2.6 节。

## 5. 常见情况

| 现象 | 判断 |
| --- | --- |
| `machine show --hosts` 为空，但设备管理里有服务器 | 服务器在 PXEye 里有规划，但还没进入 NICo 的发现流程。看[发现诊断](discovery-diagnostics.zh-CN.md) |
| 机器一直停在某个状态，且超出时限 | 状态时间线里看它在哪一步停留最久，结合健康历史和 `machine show` 的状态原因 |
| 校验记录全部是“已跳过” | 站点没有启用机器校验，问用户确认 |
| 固件清单为空 | 这台机器的 BMC 探测报告不完整，看发现诊断里该地址的结果 |
| `GetPowerOptions` 失败或为空 | 页面电源状态显示未知；单独重试一次，一直失败时记下错误码 |

## 6. AI 执行清单

1. 执行 `tools/site-survey.sh check`。记下 `build_version`、`git_sha`。失败时停下，请用户检查 `SURVEY_*` 变量和集群访问。
2. 执行 `tools/site-survey.sh --save servers-ids.txt survey ids machines`，数行数。
3. 行数为 0：本站点 NICo 里没有服务器对象，页面只会显示“NICo 尚未建立设备对象”。执行 `tools/site-survey.sh --save servers-expected-machine.txt cli expected-machine show`，然后问用户：“NICo 里没有服务器。站点应该有服务器吗？如果有，请按 `serial,bmc_mac,rack` 填写 `supplements/servers-expected.csv`。”记录回答后停止本页面，转到[发现诊断](discovery-diagnostics.zh-CN.md)。
4. 行数大于 0：执行第 2 节 (1) 的另外两条命令，按第 2 节的规则选出 `<机器ID>`（第一行、一台失败的、一台带 DPU 的）和 `<BMC 地址>`。
5. 执行第 2 节 (2) 的站点级命令，再对每台选出的机器执行全部机器级命令。任一命令失败：单独重试一次；仍失败时记下命令、错误码和消息，继续下一条。
6. 如果本站点还没有采集文件，执行一次 `tools/site-survey.sh capture`。退出码 2 时修正原因后重来；其他非 0 值停下并报告。
7. 按第 3 节逐行核对，每行写下通过或不通过及记录内容。
8. 问用户第 4 节的数据：机柜（`supplements/servers-rack.csv`）、应有的服务器清单（`supplements/servers-expected.csv`）、U 位和固件基线（可选，`supplements/servers-position.csv` 列 `serial,rack,unit[,height]`、`supplements/servers-firmware-baseline.csv`）、是否启用校验和 SKU。每项说明要什么、为什么、怎么取得。给不出的不要猜。在可写的控制台上，请用户用服务器页的“导入 U 位”导入 U 位（只读观察实例上不能导入）；下次采集后，记录 `/api/rack-units` 的 `mismatches` 和 `unknown`。
9. 在 `session.md` 写本页面一节：Core 版本；服务器数；选用的机器 ID；第 3 节每项的核对结果；失败的命令和错误码；已收到和缺少的用户数据（缺什么、影响哪一项）；需要更新的文档和测试。
