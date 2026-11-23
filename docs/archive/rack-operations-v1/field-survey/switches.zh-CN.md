# 现场采集：交换机

[English](switches.md) · **简体中文** · [现场采集指南](README.zh-CN.md)

> **已归档（2026-11-23）。** 本文档属于被整机柜新设计取代的一套设计，不再维护；内容保留归档时的原样，仅供查阅。现行设计见[设计文档](../../../design/README.zh-CN.md)，归档说明见[归档目录](../../README.zh-CN.md)。

页面：设备管理 → 交换机。页面列出 NICo 纳管的 **NVLink 交换机**（整机柜站点）的运行状态、健康、电源、NVOS 管理口和 Fabric Manager 状态，以及设备清单。普通以太网接入交换机不由 NICo 管理，不会出现在这里；它们的连接见[布线](cabling.zh-CN.md)。准备工作（环境变量、观察实例、采集目录）见[现场采集指南](README.zh-CN.md)第 1 节。

## 1. 数据来源

| 页面内容 | 页面代码调用的 gRPC 接口（请求） | 对等的 nico 命令行 | 对等程度 | 能否自动采集 |
| --- | --- | --- | --- | --- |
| 交换机列表、运行状态、健康、电源 | `FindSwitches`（`{}`） | `switch list`、`switch show <交换机ID>` | 相同 | 能 |
| NVOS 管理口、Fabric Manager | `FindSwitches`（`{}`） | `switch show <交换机ID>`；完整记录用 `--json switch show <交换机ID>` | 相同 | 能 |
| 设备清单（序列号、BMC MAC） | `GetAllExpectedSwitches`（`{}`） | `expected-switch show` | 相同 | 能 |
| 健康历史（页面尚未使用） | `FindSwitchHealthHistories`（页面代码不调用） | `switch health-history <交换机ID>` | 相同 | 能，只用命令行 |
| 站点上有没有 NVLink 交换机 | 无 | 无 | 无 | 不能，要用户确认 |

页面代码不使用命令行；核对以 gRPC 接口或采集文件为准（见[现场采集指南](README.zh-CN.md)第 1.3 节）。

所有字段目前都“仅定义”：验证过的站点上没有 NVLink 交换机。字段对照见[数据契约](../design/rack-operations-data-contract.zh-CN.md)第 2.2 节。

## 2. 采集命令

在仓库根目录执行，`SURVEY_*` 变量按[现场采集指南](README.zh-CN.md)第 1.2 节导出。

第一步，数量和 ID：

```bash
tools/site-survey.sh --save switches-ids.txt survey ids switches
```

输出一行一个交换机 ID。行数为 0 时只再执行下面的 `GetAllExpectedSwitches` 和 `expected-switch show`，然后按第 6 节的“数量为 0”分支处理。

第二步，逐项采集。列表和设备清单：

```bash
tools/site-survey.sh --save switches-find.txt survey call 'FindSwitches={}'
tools/site-survey.sh --save switches-list.txt cli switch list
tools/site-survey.sh --save switches-expected-find.txt survey call 'GetAllExpectedSwitches={}'
tools/site-survey.sh --save switches-expected.txt cli expected-switch show
tools/site-survey.sh --save switches-expected.json cli --json expected-switch show
```

单台交换机的详情和健康历史。`<交换机ID>` 取 `switches-ids.txt` 的第一行；另外在 `switches-list.txt` 里找一台状态不是正常就绪、或健康不是正常的交换机，用它的 ID 再执行一遍（没有就只做第一台）：

```bash
tools/site-survey.sh --save switches-show-<交换机ID>.txt cli switch show <交换机ID>
tools/site-survey.sh --save switches-show-<交换机ID>.json cli --json switch show <交换机ID>
tools/site-survey.sh --save switches-health-<交换机ID>.txt cli switch health-history <交换机ID>
tools/site-survey.sh --save switches-health-describe.txt survey describe FindSwitchHealthHistories
```

`survey call` 的输出只有结构（长值截短，列表只留第一项）；完整数据看 `cli --json` 的输出或采集文件。

第三步，原样采集整个站点只做一次（[现场采集指南](README.zh-CN.md)第 2 节），不是每个页面做一次。还没做时执行：

```bash
tools/site-survey.sh capture
```

## 3. 核对

有交换机时，**这是第一次见到真实数据**，要逐字段核对。下表的 `$C` 是采集文件，见[现场采集指南](README.zh-CN.md)第 3.1 节。

| 项目 | 通过标准 | 用什么对照 | 不通过时记录 |
| --- | --- | --- | --- |
| 行数 | 页面行数等于 Core 的交换机数 | `switches-ids.txt` 行数；`jq '.pxeye_responses["/api/device-status"].body.switches \| length' $C`；`jq '[.pxeye_responses["/api/equipment"].body.devices[] \| select(.kind=="switch")] \| length' $C` | 多出或缺少的交换机 ID 或序列号 |
| 关联 | 设备清单里每台都关联到了 NICo 的交换机对象 | `switches-expected.json` 与 `switches-ids.txt`；`jq '.pxeye_responses["/api/equipment"].body.devices[] \| select(.kind=="switch")' $C` | 关联不上的设备，以及两边的标识 |
| 状态、健康、电源 | 和命令行一致 | `switches-list.txt`、`switches-show-<交换机ID>.json`；`jq '.pxeye_responses["/api/device-status"].body.switches' $C` | 实际的状态文本、健康取值、电源取值 |
| NVOS 管理口 | 管理口的 MAC 和地址与命令行一致 | `switches-show-<交换机ID>.json`；同上的 `jq` | 管理口为空时的原因 |
| Fabric Manager | 状态与命令行一致 | `switches-show-<交换机ID>.json`；同上的 `jq` | 实际出现的状态和原因文字 |
| 字段 | 数据契约 2.2 节每个“仅定义”的字段实际有没有值 | `switches-show-<交换机ID>.json`、`switches-expected.json` | 每个字段的实际值或“为空” |
| 读取错误 | 页面接口没有交换机的读取错误 | `jq '.pxeye_responses["/api/device-status"].body.errors' $C`；`jq '.summary' $C` | 错误文字、失败的方法和错误码 |

核对完成后，把数据契约 2.2 节里核对过的字段从“仅定义”改为“已验证”。

## 4. 需要用户补充的数据

| 数据 | 为什么需要 | 用户怎么取得 | 存成 |
| --- | --- | --- | --- |
| 站点有没有 NVLink 交换机 | 命令返回为空时，要区分“站点没有”还是“有但没纳管” | 询问站点负责人；看机柜型号是否为 GB200、GB300 一类整机柜；可对照 `tools/site-survey.sh cli rack list` 的输出 | 写在 `session.md` |
| 应有的 NVLink 交换机清单（有的话） | 判断哪些还没纳管 | 整机柜的出货清单；已声明的部分见 `tools/site-survey.sh cli expected-switch show` | `supplements/switches-expected.csv`：`serial,bmc_mac,rack` |

## 5. 常见情况

| 现象 | 判断 |
| --- | --- |
| 列表为空，站点只有以太网交换机 | 正常。这一页在该站点不适用，连接情况看布线页 |
| 用户说有 NVLink 交换机，但列表为空 | 没有纳管。看 `expected-switch show` 有没有声明，以及发现诊断里交换机 BMC 地址的探测结果 |
| 设备清单有，`FindSwitches` 没有 | 已声明但还没发现，看发现诊断页对应 `<BMC 地址>` 的探测结果 |
| 有交换机但健康是“未知” | Core 还没有对它跑健康检查，记录下来，过一段时间再看 |
| `FindSwitches` 调用失败 | 页面接口的 `errors` 里有“NICo 未返回交换机运行状态。”；按[现场采集指南](README.zh-CN.md)第 6 节单独重试并记录 |

## 6. AI 执行清单

1. 执行 `tools/site-survey.sh check`。有输出且有 Core 版本才继续；失败时检查 `SURVEY_*` 变量，仍失败就停下，把错误给用户看。
2. 执行 `tools/site-survey.sh --save switches-ids.txt survey ids switches`，数行数。
3. 行数为 0：
   1. 执行 `tools/site-survey.sh --save switches-expected-find.txt survey call 'GetAllExpectedSwitches={}'` 和 `tools/site-survey.sh --save switches-expected.txt cli expected-switch show`。
   2. 含义：Core 没有纳管任何 NVLink 交换机，页面只显示适用范围说明。
   3. 停下问用户：“这个站点有没有 NVLink 交换机（GB200、GB300 一类整机柜）？”有的话，请用户提供出货清单，整理成 `supplements/switches-expected.csv`（列 `serial,bmc_mac,rack`），请用户确认。
   4. 用户说没有：记录“不适用”，跳到第 9 步。用户说有：记录“有但没纳管”，提示看发现诊断页，跳到第 9 步。
4. 行数大于 0：按第 2 节第二步依次执行列表和设备清单的五条命令。每条退出码为 0 才继续；失败时单独重试一次，仍失败就记下命令、错误码和消息，继续下一条。
5. 取 `switches-ids.txt` 第一行作为 `<交换机ID>`，执行第 2 节单台详情的四条命令；在 `switches-list.txt` 里找一台状态或健康不正常的，再执行前三条。
6. 确认整站采集是否已做（`$SURVEY_DIR` 下有 `capture-*.json`）。没有就执行 `tools/site-survey.sh capture`；退出码 2 时修正原因后重来。
7. 按第 3 节逐项核对，每项记“通过”或不通过的内容。
8. 停下问用户：“站点应有多少台 NVLink 交换机？请给出货清单。”整理成 `supplements/switches-expected.csv`（列 `serial,bmc_mac,rack`），请用户确认；给不出就在 `session.md` 记缺少的内容。
9. 在 `session.md` 的“交换机”一节写：Core 版本；`switches-ids.txt` 行数和设备清单条数；站点是否有 NVLink 交换机（用户的回答）；第 3 节每项的结果；失败的命令和错误码；缺少的用户数据；数据契约 2.2 节需要改为“已验证”或需要更正的字段。
