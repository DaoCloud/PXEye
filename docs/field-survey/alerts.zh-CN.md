# 现场采集：告警

[English](alerts.md) · **简体中文** · [现场采集指南](README.zh-CN.md)

页面：设备管理 → 告警。页面把服务器、交换机和供电框当前报告的健康告警汇总在一起，可按告警或按设备分组，按设备类型和分类筛选，统计带 `PreventAllocations` 的告警数；设备名打开现有的运行状态弹窗。页面只读，没有新的 Core 接口，数据与服务器、交换机、供电框页相同。准备工作（环境变量、观察实例、采集目录）见[现场采集指南](README.zh-CN.md)第 1 节。

## 1. 数据来源

| 页面内容 | 页面代码调用的 gRPC 接口（请求） | 对等的 nico 命令行 | 对等程度 | 能否自动采集 |
| --- | --- | --- | --- | --- |
| 服务器的当前告警 | `FindMachineIds`（`{}`），再 `FindMachinesByIds`（`{"machineIds":[…],"includeHistory":false}`） | `--json machine show <机器ID>` | 相同 | 能 |
| 交换机的当前告警 | `FindSwitches`（`{}`） | `--json switch show <交换机ID>` | 相同 | 能 |
| 供电框的当前告警 | `FindPowerShelves`（`{}`） | `--json power-shelf show <供电框ID>` | 相同 | 能 |
| 告警历史（页面不使用，运行状态弹窗使用） | `FindMachineHealthHistories`（告警页不调用） | `machine health-history <机器ID>` | 相同 | 能，只作历史参考 |
| 站点认为可忽略的告警 | 无 | 无 | 无 | 不能，要用户提供 |

页面代码不使用命令行；核对以 gRPC 接口或采集文件为准（见[现场采集指南](README.zh-CN.md)第 1.3 节）。

页面使用的字段见[数据契约](../design/rack-operations-data-contract.zh-CN.md)第 2.5 节：`/api/device-status` 中每台设备的 `health.level` 和 `health.alerts[]`（`id`、`target`、`message`、`since`、`classifications`）。

## 2. 采集命令

在仓库根目录执行，`SURVEY_*` 变量按[现场采集指南](README.zh-CN.md)第 1.2 节导出。

第一步，各类设备的 ID：

```bash
tools/site-survey.sh --save alerts-machine-ids.txt survey ids machines
tools/site-survey.sh --save alerts-switch-ids.txt survey ids switches
tools/site-survey.sh --save alerts-power-shelf-ids.txt survey ids power-shelves
```

第二步，有告警的设备的详情。先完成第三步的整站采集，用第 3 节第一条 `jq` 找出有告警的设备；每类各取一台（没有就跳过该类）：

```bash
tools/site-survey.sh --save alerts-machine-<机器ID>.json cli --json machine show <机器ID>
tools/site-survey.sh --save alerts-machine-health-<机器ID>.txt cli machine health-history <机器ID>
tools/site-survey.sh --save alerts-switch-<交换机ID>.json cli --json switch show <交换机ID>
tools/site-survey.sh --save alerts-power-shelf-<供电框ID>.json cli --json power-shelf show <供电框ID>
```

`machine health-history` 只给出历史，用来判断告警是持续的还是反复出现的，不作为当前告警的依据。

第三步，原样采集整个站点只做一次（[现场采集指南](README.zh-CN.md)第 2 节），不是每个页面做一次。还没做时执行：

```bash
tools/site-survey.sh capture
```

## 3. 核对

不需要浏览器。下表的 `$C` 是采集文件，见[现场采集指南](README.zh-CN.md)第 3.1 节。

| 项目 | 通过标准 | 用什么对照 | 不通过时记录 |
| --- | --- | --- | --- |
| 有告警的设备 | 列出的设备与命令行详情中有告警的设备一致 | `jq '.pxeye_responses["/api/device-status"].body \| [(.servers, .switches, .power_shelves)[] \| select((.health.alerts \| length) > 0)] \| length' $C`；第二步的 `--json … show` 输出 | 多出或缺少的设备 |
| 告警总数和类型 | 按 `id` 汇总的数量与命令行一致 | `jq '[.pxeye_responses["/api/device-status"].body \| (.servers, .switches, .power_shelves)[] \| .health.alerts[]] \| group_by(.id) \| map({id: .[0].id, count: length})' $C` | 实际的告警 ID 和数量 |
| 字段 | 每条告警的 `target`、`message`、`since`、`classifications` 与命令行详情一致 | `jq '.pxeye_responses["/api/device-status"].body.servers[].health.alerts[]' $C`（交换机、供电框同理）；`alerts-machine-<机器ID>.json` | 不一致的字段和两边的值 |
| `PreventAllocations` | 带该分类的告警数与采集一致 | `jq '[.pxeye_responses["/api/device-status"].body \| (.servers, .switches, .power_shelves)[] \| .health.alerts[] \| select(.classifications \| index("PreventAllocations"))] \| length' $C` | 实际数量和出现的其他分类 |
| 没有告警项的异常等级 | 等级为 `warning`、`alert`、`critical` 但 `alerts` 为空的设备都列出 | `jq '[.pxeye_responses["/api/device-status"].body \| (.servers, .switches, .power_shelves)[] \| select((.health.alerts \| length) == 0 and (.health.level \| IN("warning","alert","critical")))] \| length' $C` | 这些设备的等级 |
| 读取错误 | 页面接口没有读取错误 | `jq '.pxeye_responses["/api/device-status"].body.errors' $C`；`jq '.summary' $C` | 错误文字、失败的方法和错误码 |

页面只列出设备管理里已有、并关联上 NICo 对象的设备；jq 统计的是 `/api/device-status` 里的全部对象。jq 统计到而页面上没有的设备，通常是不在设备管理里，记下它的 ID。

核对完成后，把数据契约 2.5 节的待核对项（真实告警 ID、分类、`target` 取值）补上结论。

## 4. 需要用户补充的数据

页面不需要用户补充数据。以下为可选：

| 数据 | 为什么需要 | 用户怎么取得 | 存成 |
| --- | --- | --- | --- |
| 站点认为已知、可以忽略的告警 | 区分需要处理的告警和站点已经接受的告警 | 询问站点负责人；对照第 3 节汇总出的告警 ID | `supplements/alerts-known.csv`：`alert_id,target,reason` |

## 5. 常见情况

| 现象 | 判断 |
| --- | --- |
| 页面没有告警 | 当前没有设备报告告警。这是正常结果；用 `machine health-history` 看过去是否出现过 |
| 设备等级需要关注但没有告警项 | 页面显示“未报告告警项”；记录等级和 `--json … show` 的 `health` 内容 |
| 同一告警出现在很多设备上 | 多为站点级原因（例如同一型号的同一问题）；按告警分组看影响范围，问用户是否已知 |
| 告警带 `PreventAllocations` | NICo 不会把这台设备分配出去；记录告警 ID 和设备 |
| `target` 为空 | 告警针对整台设备，页面显示“—” |
| 某类设备读取失败 | 页面接口的 `errors` 里有对应文字；按[现场采集指南](README.zh-CN.md)第 6 节单独重试并记录 |

## 6. AI 执行清单

1. 执行 `tools/site-survey.sh check`。有输出且有 Core 版本才继续；失败时检查 `SURVEY_*` 变量，仍失败就停下，把错误给用户看。
2. 执行第 2 节第一步的三条命令，记下每类设备的数量。
3. 确认整站采集是否已做（`$SURVEY_DIR` 下有 `capture-*.json`）。没有就执行 `tools/site-survey.sh capture`；退出码 2 时修正原因后重来。
4. 用第 3 节第一条 `jq` 数出有告警的设备。
5. 数量为 0：
   1. 再用第 3 节“没有告警项的异常等级”一条确认没有等级异常的设备。
   2. 取 `alerts-machine-ids.txt` 第一行，执行 `tools/site-survey.sh --save alerts-machine-health-<机器ID>.txt cli machine health-history <机器ID>`，看过去是否有过告警。
   3. 记录“采集时没有告警”，跳到第 9 步。
6. 数量大于 0：每类设备取一台有告警的，执行第 2 节第二步对应的命令。每条退出码为 0 才继续；失败时单独重试一次，仍失败就记下命令、错误码和消息，继续下一条。
7. 按第 3 节逐项核对，每项记“通过”或不通过的内容。
8. 把第 3 节汇总出的告警 ID 给用户看，问：“这些告警里有没有站点已知、可以忽略的？”有的话整理成 `supplements/alerts-known.csv`（列 `alert_id,target,reason`），请用户确认；没有或不回答就不建这个文件。
9. 在 `session.md` 的“告警”一节写：Core 版本；每类设备数和有告警的设备数；各告警 ID 和数量；出现的分类；第 3 节每项的结果；失败的命令和错误码；用户确认的已知告警；数据契约 2.5 节需要补上或更正的内容。
