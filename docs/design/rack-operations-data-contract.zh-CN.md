# 机柜运维：NICo 数据契约

[English](rack-operations-data-contract.md) · **简体中文** · [设计文档](README.zh-CN.md)

每个页面使用 NICo Core 的哪个接口、哪些字段，以及它们有没有在真实站点上验证过。在新站点开发和测试时，对照这份文档取数。

- 依据：2026-11-19 在一个通用服务器站点上，通过接口反射读取 Core 的定义并做只读调用。当时 Core 里有 1 台服务器，没有交换机、供电框、机柜和 SKU。不是按源码或在线文档推断的。
- 换了 Core 版本，先按第 1 节重新核对。
- 标记：**已验证** = 站点上有真实数据并核对过；**仅定义** = 接口存在但返回为空，字段只来自接口定义；**不可用** = 调用报错或不返回所需内容。

## 1. 取数方法

`tools/core-survey.py` 在一个 PXEye 容器里运行，使用该实例已有的 Core 地址和客户端身份，通过 gRPC 反射读取站点上实际部署的 Core。建议在只读观察实例里运行。

```bash
survey() { kubectl -n <namespace> exec -i deploy/<pxeye> -c pxeye -- python3 - "$@" < tools/core-survey.py; }

survey list                          # 可调用的读取方法
survey describe FindSwitches         # 方法的请求和响应定义
survey message forge.Machine         # 某个消息的完整定义
survey call 'FindRackIds={}'         # 实际调用，输出返回结构
survey call 'FindMachineStateHistories={"machineIds":[{"id":"MID"}]}'
```

规则：

- 只能调用名字以 `Find`、`Get`、`List`、`Determine` 开头的方法。
- 返回凭据的方法和装机引导路径的方法即使名字像读取也会被拒绝：名字含 `Credential`、`Password`、`Secret`、`Token` 的，以及 `GetBMCMetaData`、`GetPxeInstructions`、`GetCloudInitInstructions`。
- 输出会遮蔽名字像凭据的字段并截短长值。它展示返回的结构，不是站点数据的副本。
- `call` 请求体里的 `MID` 会替换成 Core 返回的第一台机器的 ID。
- 站点的原始返回不进入本仓库。做成测试样本时换成占位值。
- 这个工具只看结构。要原样保存返回，用第 5 节的 `tools/core-capture.py`。

返回数据的约定：

| 现象 | 处理 |
| --- | --- |
| 字段名是驼峰（proto JSON） | 进入业务代码前用 `services/equipment.py` 的 `snake()` 转成下划线 |
| 空列表、`false`、枚举零值不出现；`{}` 表示没有 | 用 `.get(key) or 默认值`，不假设键存在 |
| ID 有两种形状：机器是 `{"id": …}`，交换机、供电框、机柜是 `{"value": …}` | `object_id()` 两种都认 |
| 机器状态是 `Ready`、`Failed/…` 这类文本；状态历史里是 JSON 文档 | `services/device_status.py` 的 `state_text()` 两种都处理 |
| MAC 为大写 | 转小写再比较 |

只读观察实例的应用层只放行 `Find`、`Get`、`Determine`。页面要使用 `List*` 接口时，先在 `read_only.py` 里加入并确认没有会写入的 `List*` 方法。

## 2. 已实现的页面

后端 `services/device_status.py`，接口 `GET /api/device-status`，以及按机器读取的 `GET /api/device-status/machines/<机器ID>/history` 和 `…/firmware`（机器 ID 只接受 `[a-z0-9]{1,128}`，其他路径返回 404）；前端 `web/pages/device_status.js`；测试 `tests/unit/test_device_status.py`。

设备清单来自现有的 `GET /api/equipment`。运行状态按下面的方式关联到设备：

| 类型 | 关联 |
| --- | --- |
| 服务器 | 先用 `/api/resources` 中该序列号的 `machine_id`；没有则用设备 `host_bmc` 接口的 MAC 对机器的 `bmc.mac` |
| 交换机、供电框 | `/api/equipment` 设备上的 `native_id` 对 Core 对象的 `id.value` |

### 2.1 服务器

接口：`FindMachineIds {}`，再 `FindMachinesByIds {"machineIds":[…],"includeHistory":false}`，返回 `machines[]`（`forge.Machine`）。

| 页面内容 | 字段（下划线形式） | 验证 |
| --- | --- | --- |
| 运行状态 | `status.lifecycle.state`，回退 `state` | 已验证 |
| 状态原因 | `status.lifecycle.state_reason.outcome_msg` | 已验证 |
| 处理结果 | `status.lifecycle.state_reason.outcome`：`ERROR`、`TRANSITION`、`DO_NOTHING`、`TODO`；`WAIT` 是零值，不出现 | 已验证 `ERROR`；其余取值仅定义 |
| 超出状态时限 | `status.lifecycle.sla.time_in_state_above_sla` | 已验证 |
| 健康 | `status.health.alerts[]`：`id`、`target`、`message`、`in_alert_since`、`classifications`；`status.health.source`、`observed_at` | 已验证；`target` 仅定义 |
| 电源 | 沿用 `/api/equipment` 的 `power_state`（来自 `GetPowerOptions`） | 已验证 |
| BMC 地址 | `bmc.ip`、`bmc.mac`，回退 `bmc_info` | 已验证 |
| 上联交换机、LLDP 邻居 | `status.lldp_neighbors[]`：`mac_address`、`lldp.name`、`lldp.local_port`、`lldp.id_value`、`lldp.remote_port_type`、`lldp.remote_port_value`、`lldp.med_inventory.{serial,manufacturer,model}`、`lldp.description` | 已验证 |
| 硬件能力 | `status.capabilities.{cpu,gpu,memory,storage,network,infiniband,dpu}[]`：`name`、`count`、`vendor`、`capacity` | 已验证 `cpu`、`memory`、`storage`、`network`；`gpu`、`infiniband`、`dpu` 仅定义 |
| 故障详情、最近重启、Scout 版本 | `status.failure_details`、`status.last_reboot_time`、`status.last_scout_observed_version` | 已验证 |
| 机柜 | `rack_id.value`。由预期设备声明的 `rack_id` 人工填写，Core 不自动发现 | 仅定义 |
| 槽位、托盘 | `placement_in_rack.{slot_number,tray_index}`。预期设备声明里没有对应的输入字段 | 仅定义 |
| SKU | `config.hw_sku`、`status.hw_sku.last_match_attempt` | 仅定义 |
| BMC 固件 | `status.bmc_status.firmware_version` | 不可用：返回空。固件版本从 `GetComponentInventory` 取，见 3.2 |
| 隔离、维护 | `status.quarantine.{mode,reason}`、`config.maintenance_reference` | 仅定义 |
| 关联 DPU | `status.associated_dpu_machine_ids[]` | 仅定义 |

“需要处理”的判定：`outcome` 为 `ERROR`，或超出状态时限，或有健康告警。

待核对：带 DPU 的机器是否同时返回主机和 DPU；已分配实例的机器的状态文本；机器多时一次传全部 ID 的耗时和返回大小。

### 2.2 交换机

Core 的 Switch 只指 NVLink 交换机。接口：`FindSwitches {}`，返回 `switches[]`（`forge.Switch`）。全部字段仅定义。

| 页面内容 | 字段 |
| --- | --- |
| 运行状态 | `status.lifecycle.state`，回退 `status.controller_state`、`controller_state` |
| 健康 | `status.health_status`（`ok`、`warning`、`critical`）、`status.health.alerts[]` |
| 电源 | `status.power_state`（`on`、`off`、`standby`） |
| NVOS 管理口 | `status.nvos_ports[]`：`mac`、`is_primary`、`service_port`、`addresses[].address` |
| Fabric Manager | `status.fabric_manager_status`、`status.fabric_manager_status_details.{fabric_manager_state,reason,error_message}` |
| BMC | `bmc_info.{ip,mac,firmware_version}` |
| 机柜、槽位 | `rack_id.value`、`placement_in_rack` |
| 其他 | `is_primary`、`nvlink_domain_uuid.value`、`config.enable_nmxc`、`status.serial_number` |

### 2.3 供电框

Core 的供电框没有插口，机柜 PDU 不在 Core 里。接口：`FindPowerShelves {}`，返回 `powerShelves[]`（`forge.PowerShelf`）。全部字段仅定义。

| 页面内容 | 字段 |
| --- | --- |
| 运行状态、健康、电源 | 同交换机 |
| 容量、电压 | `config.capacity`（瓦）、`config.voltage`（伏） |
| BMC（PMC） | `bmc_info.{ip,mac,firmware_version}` |
| 机柜 | `rack_id.value` |

### 2.4 布线

没有新的 Core 接口。数据来自 2.1 的 `status.lldp_neighbors`，经 `/api/device-status` 的 `servers[].lldp` 读取，页面按交换机分组（交换机名，没有时用 `id_value`，再没有时用序列号）。同一交换机端口被不同网口报告即为冲突。`remote_port_type` 为 `mac` 时端口显示为 MAC，不推测接口名。

待核对：除 `mac` 外的 `remote_port_type` 取值；真实的端口冲突；只有序列号、没有名字和 ID 的交换机。

## 3. 候选页面的接口

### 3.1 机器状态时间线（已验证，已实现）

`FindMachineStateHistories {"machineIds":[{"id":"<机器ID>"}]}`

```json
{"histories": {"<机器ID>": {"records": [
  {"event": "{\"state\": \"created\"}", "time": "2026-01-01T00:00:00Z", "version": "V2-T…"},
  {"event": "{\"state\": \"hostinit\", \"machine_state\": {\"state\": \"waitingforlockdown\"}}", "time": "…", "version": "…"},
  {"event": "{\"state\": \"ready\"}", "time": "…", "version": "…"}
]}}}
```

`event` 是 JSON 文本，`state` 逐层嵌套。停留时长用相邻记录的 `time` 相减，最后一条算到当前时间。交换机、供电框、机柜有同类接口 `Find…StateHistories`，仅定义。

实现：接口 `/history` 返回 `{observed_at, records:[{state, entered_at, duration_seconds, current}]}`。按 `time` 排序，连续相同的状态文本合并为一段并保留第一段的进入时间；`time` 按 RFC 3339 解析，小数秒可能多于 6 位，读不出的记录跳过。`state_text()` 只沿 `state` 键展开，不带 `state` 键的子对象（如重试计数）不区分，这类子步骤会合并为一段。没有记录时返回空列表。

待核对：记录条数有没有上限；按真实站点再看一次 `time` 的原始格式。

### 3.2 固件清单（已验证，已实现）

`GetComponentInventory {"machineIds":{"machineIds":[{"id":"<机器ID>"}]}}`。请求是多选一，也可传 `switchIds`、`powerShelfIds` 或各类 BMC MAC。

```json
{"entries": [{"result": {"componentId": "<机器ID>"}, "report": {
  "endpointType": "Bmc", "vendor": "<厂商>",
  "systems": [{"id": "1", "manufacturer": "…", "serialNumber": "…", "pcieDevices": [{"id": "…", "name": "…", "firmwareVersion": "…"}], "ethernetInterfaces": [{"macAddress": "…", "linkStatus": "LinkUp"}]}],
  "chassis": [{"id": "1", "model": "…", "partNumber": "…", "serialNumber": "…", "manufacturer": "…"}],
  "service": [{"id": "FirmwareInventory", "inventories": [
    {"id": "BMC-Primary", "description": "…", "version": "…", "releaseDate": "…"},
    {"id": "UEFI", "description": "…", "version": "…", "releaseDate": "…"}]}],
  "machineSetupStatus": {"isDone": true},
  "secureBootStatus": {},
  "lockdownStatus": {"message": "…"}}}]}
```

- 固件条目的 `id` 是厂商自己的命名，不同厂商不同，不能按固定名字匹配。
- 报告就是站点发现的 Redfish 探测结果，同时有机型、部件号、锁定状态、安全启动状态。
- 基线：`GetDesiredFirmwareVersions {}` 返回 `entries[]`（`vendor`、`model`、`componentVersions`）；`ListHostFirmware {}` 返回 `available[]`。验证站点上只有 DPU 的条目，没有主机的基线，所以主机固件只能展示版本，不能判断是否合规。
- 不可用：`ListComponentFirmwareVersions` 对服务器返回 `Unimplemented`。
- `GetComponentFirmwareStatus` 返回 `statuses[]`（`result.componentId`、`state`），含义未弄清。
- 实现：接口 `/firmware` 返回 `vendor`、`endpoint_type`、`chassis.{model,part_number,manufacturer}`（取第一个有型号的机箱）、`lockdown`（`lockdownStatus.message`）、`secure_boot`（原样）、`entries[].{id,description,version,release_date}`，以及 `reported`、`note`、`observed_at`。版本为空的条目保留。没有报告时 `reported` 为 false，不报错。只在打开弹窗时对一台机器读取一次，列表不逐行读取。
- 待核对：一次请求传多台机器是否可行；这个接口读的是缓存还是会访问 BMC；`secureBootStatus` 不为空时的字段。

### 3.3 发现诊断（已验证，已实现）

`GetSiteExplorationReport {}`

```json
{"endpoints": [{"address": "<BMC 地址>", "preingestionState": "Initial",
   "report": {"endpointType": "Unknown", "lastExplorationLatency": "10.0s",
     "lastExplorationErrorSchema": {"errorCode": "NICO-SITEEXPLORER-101", "text": "…", "mitigation": "…"}}}],
 "managedHosts": [{"hostBmcIp": "<BMC 地址>"}],
 "lastRun": {"startedAt": "…", "finishedAt": "…", "success": true, "endpointExplorations": "5", "endpointExplorationsSuccess": "1", "endpointExplorationsFailed": "4"}}
```

探测成功的端点，`report` 是和 3.2 相同结构的报告。相关接口：`FindExploredEndpointIds` 和 `FindExploredEndpointsByIds`（现有代码已在用）、`GetAllUnexpectedMachines`。


实现：接口 `GET /api/exploration`（只在 `rack_operations` 开启时存在）。成功端点的 `report` 是完整的 Redfish 清单，只保留地址、类型、厂商、接入阶段、耗时、错误码/文字/处理建议、`lastExplorationError` 里的 `Type`（不是 JSON 时保留原文）、报告版本、重置和重启时间、是否为已纳管主机，以及成功端点的系统序列号和型号。`lastRun` 的计数原为字符串，转为整数。页面按地址和设备管理里设备的地址关联。

待核对：成功端点的序列号和型号从未在完整的真实报告上提取过；`lastRun` 失败、`machineId` 出现等情况未见过。

### 3.4 硬件校验（部分验证，已实现）

| 接口 | 返回 | 验证站点 |
| --- | --- | --- |
| `GetMachineValidationRuns {"machineId":{"id":…}}` | `runs[]`：`validationId.value`、`startTime`、`endTime`、`name`、`context`、`status`、`durationToComplete` | 1 次，状态为已跳过 |
| `GetMachineValidationResults {"machineId":{"id":…}}` | `results[]` | 空 |
| `GetMachineValidationTests {}` | `tests[]`：`testId`、`name`、`description`、`contexts`、`command`、`timeout`、`supportedPlatforms`、`isEnabled` | 11 个内置测试 |
| `GetAllSkuIds {}`，再 `FindSkusByIds {"ids":[…]}` | SKU 定义 | 空 |


实现：接口 `/api/device-status/machines/<机器ID>/validation` 以 `includeHistory: true` 读取校验记录和结果，按校验 ID 分组；不逐台读取测试项清单。运行状态 `status` 是多选一的对象（如 `{"completed": "Skipped"}`），转成简短文字并保留原样。结果里的 stdout 和 stderr 各截取前 2000 个字符，不在列表中显示。缺少 `exitCode` 视为 0（Core 省略零值），退出码为 0 显示“通过”。

待核对：校验结果（`forge.MachineValidationResult`）的字段从未在站点上出现过，全部仅定义；`Success`、`Failed`、进行中等状态未见过；`durationToComplete` 只见过 `0s`。

### 3.5 健康历史（已验证，已实现）

`FindMachineHealthHistories {"machineIds":[{"id":…}]}`，可带 `startTime`、`endTime`。返回 `histories.<机器ID>.records[]`，每条有 `time` 和 `health`（结构同 2.1 的健康）。`ListMachineHealthReports`、`ListHealthReportOverrides` 在验证站点返回空。当前告警直接取各对象的 `status.health.alerts`。


实现：接口 `/api/device-status/machines/<机器ID>/health` 按时间排序记录，按告警 ID 和 `target` 把连续出现的记录合并为一段：开始取 `inAlertSince`，没有时取第一次出现的记录时间；中间有一条记录不含该告警，这一段就结束，再出现时算新的一段。只有最新一条记录里还有的告警算“仍存在”。同时返回记录条数和时间范围。

待核对：长时间运行的机器记录条数是否有上限；`target` 不为空的告警。

### 3.6 电源详情（已验证）

`GetComponentPowerDetails {"machineIds":{"machineIds":[{"id":…}]}}`，返回 `entries[]`：`componentId`、`actual.{state,source,observedAt}`、`desired.{status,state,source}`、`actions`。比 `GetPowerOptions` 多了来源和观测时间。没有功率读数。

### 3.7 机柜（仅定义）

| 接口 | 返回 | 验证站点 |
| --- | --- | --- |
| `FindRackIds {}`，再 `FindRacksByIds {"rackIds":[…]}` | `racks[]`（`forge.Rack`）：`id`、`rack_state`、`config`、`status.{health,lifecycle}`、`rack_group_id` | 空 |
| `GetAllExpectedRacks {}` | `expected_racks[]`：`rack_id`、`rack_profile_id`、`metadata` | 空 |
| `GetAllExpectedRackGroups {}` | `expected_rack_groups[]`：`rack_group_id`、`topology`、`racks[].{rack_id,members[].{type,manufacturer,id}}` | 空 |
| `ListRackProfiles {}` | 内置的机柜型号，不是站点数据 | 14 个 |

### 3.8 不可用

- `GetNetworkTopology {}` 返回空。布线信息只能从机器的 `status.lldp_neighbors` 取。
- `GetMachinePositionInfo` 只返回机器 ID，没有位置。

## 4. Core 提供但未集成的操作

以下都没有调用过，只列出类别供规划参考：机器和组件的电源控制与复位、供电框上下电、机器维护标记、机柜维护、主机隔离、组件固件更新和更新时间窗口、SKU 的创建分配与校验、按需机器校验、健康报告的人工写入与撤销、机柜和机柜组的声明、交换机和供电框的退役、NVLink 域和分区。

## 5. 现场调研

到一个站点后按本节操作。目的有两个：确认页面在该站点上是否正确；把 Core 的真实返回原样带回来，以后开发和测试都基于它，而不是手写的数据。

### 5.1 准备

- 在站点上运行一个只读观察实例（`readOnly: true`、`rackOperations: true`），连接该站点的 Core。所有命令都在它的容器里执行，不在正在装机的控制台里执行。
- 实例的镜像要包含本仓库当前的 `tools/`，或者像下面的命令那样从本地经标准输入传入脚本。
- 准备一个仓库之外、只有项目成员能访问的目录，用来存放采集文件，例如 `operations/runs/<运行编号>/`。

下文的 `survey`、`capture` 指：

```bash
survey()  { kubectl -n <namespace> exec -i deploy/<pxeye> -c pxeye -- python3 - "$@" < tools/core-survey.py; }
capture() { kubectl -n <namespace> exec -i deploy/<pxeye> -c pxeye -- python3 - < tools/core-capture.py; }
```

### 5.2 核对接口

1. `survey list`，和第 2、3 节对比方法是否齐全。缺少的方法，对应功能在该站点不可用，先记下来。
2. 对第 2 节三个页面的接口各执行一次 `survey call`，记下返回条数：

   ```bash
   survey call 'FindMachineIds={}' 'FindSwitches={}' 'FindPowerShelves={}'
   ```

   条数为 0 的设备类型，对应页面在该站点没有内容，不需要继续核对。
3. 对第 3 节已实现的两项，各取一台机器：

   ```bash
   survey call 'FindMachineStateHistories={"machineIds":[{"id":"MID"}]}' \
               'GetComponentInventory={"machineIds":{"machineIds":[{"id":"MID"}]}}'
   ```

4. 输出只显示结构（长值截短、列表只留第一项），用来和本文档的字段表对照，不能当作测试数据。

### 5.3 原样采集

```bash
capture > operations/runs/<运行编号>/capture-<站点>.json
chmod 600 operations/runs/<运行编号>/capture-<站点>.json
```

`tools/core-capture.py` 在实例容器里另起一个私有的控制台副本，只监听本机回环地址，使用实例数据的副本：未完成的任务被取消，Core 和 Redfish 只允许读取，不能写 Kubernetes。它依次请求设备相关页面的接口，结束后关闭副本。正在运行的实例不受影响。

采集文件包含：

| 部分 | 内容 |
| --- | --- |
| `core_calls` | 每一次 Core RPC、Core 命令行和 Redfish 请求，以及原样的返回 |
| `pxeye_responses` | 控制台接口当时的返回，回放时作为期望结果 |
| `inputs` | 页面依赖的本地数据：站点配置、设备规划、拓扑排列、任务等 |

只有名字像凭据的字段（含 password、secret、token、key 等）被替换为 `<redacted>`，其余都是原样。所以文件里有站点地址、序列号和机器 ID：**不能放进本仓库**，只存放在受控目录。

#### 空数据和失败

采集不会因为某一项读不到而中止，每种情况都原样记录，回放时按同样的方式出现：

| 情况 | 采集文件里的记录 | 回放时 |
| --- | --- | --- |
| Core 返回空（没有这类设备、没有记录）。Core 省略空列表，常见的返回是 `{}` | 原样的空返回，方法列在 `summary.empty_calls` | 返回同样的空数据 |
| Core 调用失败（方法不存在、参数错误、超时、连接失败） | 错误的类型、消息和属性（如错误码），列在 `summary.failed_calls` | 抛出同一类型的错误，控制台给出和现场相同的状态码和错误码 |
| 一个页面接口里部分数据失败（例如交换机读不到，服务器正常） | 接口返回 200，失败写在它的 `errors` 里，列在 `summary.reads_with_errors` | 相同 |
| 控制台接口返回错误状态 | 状态码和返回内容；不是 JSON 的返回保存原文 | 逐字段比较 |
| 控制台接口本身没有返回（超时、连接断开） | `status` 为空，记录原因 | 跳过比较，标为 `SKIP` |
| 采集中途出错（例如登录失败） | 仍然输出已读到的部分，`summary.complete` 为 false，`aborted` 写明原因 | 只回放已有的部分 |

命令结束时在标准错误上打印汇总：完整还是中断、每个失败的调用、每个失败或部分失败的接口、返回为空的方法。退出码为 0 表示采集完整（其中可以有失败的调用，这本身是站点的事实），为 2 表示中途中止。

看到汇总后：

- **空返回**：先判断是否符合站点实际。例如通用服务器站点上 `FindSwitches` 为空是正常的；服务器数量为 0 而设备管理里有服务器，则要查 Core 的纳管状态。
- **失败的调用**：用 `survey call` 单独再调一次，确认是偶发还是一直失败。一直失败时把方法、错误码和消息记到本文档对应的字段表里；如果是该 Core 版本不支持的方法，在第 2、3 节注明。
- **中止**：修正原因后重新采集。中止的文件可以保留，用作排查依据，不用作测试基准。

### 5.4 用采集文件开发和测试

在本地仓库根目录执行，不需要站点和 Core：

```bash
PYTHONPATH=src python3 tools/core-replay.py check capture-<站点>.json
PYTHONPATH=src python3 tools/core-replay.py serve capture-<站点>.json --port 18930
```

- `check` 用当前代码重新计算每个接口的返回，并和采集时的返回逐字段比较。忽略每次读取都会变化的时间和摘要。全部一致时退出码为 0。
- `serve` 启动一个本地控制台，所有 Core 读取都从采集文件里取，页面、后端转换和关联逻辑全部是真实代码。用于手工检查页面和浏览器测试。
- 代码向 Core 发出了采集里没有的请求时，该请求失败，并以 `UNRECORDED` 列出。这说明代码读了新的接口或参数变了，需要到站点重新采集。

修改代码后的判断：

| `check` 结果 | 含义 | 处理 |
| --- | --- | --- |
| 全部 OK | 行为没变 | 无 |
| 有 DIFF，是这次改动预期的 | 输出按预期变化 | 逐条确认后，用 `--write <新文件>` 另存，新文件里的 Core 返回仍是原样 |
| 有 DIFF，不是预期的 | 回归 | 修代码 |
| 有 UNRECORDED | 代码需要新的 Core 数据 | 到站点重新采集 |

### 5.5 逐页核对

在观察实例上打开页面，和 5.2 的结果对照：

| 页面 | 核对什么 | 不一致时记录什么 |
| --- | --- | --- |
| 服务器 | 行数等于设备管理里的服务器数；每行都关联到了 Core 的机器（“NICo 已建立对象”计数）；状态、健康、电源和 `FindMachinesByIds` 一致；“需要处理”的设备确实是处理失败、超出时限或有告警 | 没关联上的设备：它的 BMC MAC 和 Core 机器的 `bmc.mac` |
| 服务器 → 运行状态 → 状态时间线 | 段数和顺序与 `FindMachineStateHistories` 一致；当前状态与列表一致；时间按本地时区显示 | 原始 `time` 的格式；`event` 里出现的新结构 |
| 服务器 → 运行状态 → 固件清单 | 条目数等于 `FirmwareInventory` 的条目数；版本为空的条目仍显示 | `secureBootStatus` 不为空时的字段；没有报告的机器 |
| 服务器 → 运行状态 → 健康历史 | 告警段和 `FindMachineHealthHistories` 一致；“仍存在”的告警和列表的健康一致 | 记录条数；`target` 不为空的告警 |
| 服务器 → 运行状态 → 硬件校验 | 记录条数和状态与 `GetMachineValidationRuns` 一致 | 校验结果的实际字段（第一次出现时） |
| 布线 | 每台服务器的网口数等于它的 LLDP 邻居数；交换机分组正确 | `remote_port_type` 的取值；冲突是否真实 |
| 发现诊断 | 地址数等于 `GetSiteExplorationReport` 的端点数；失败的错误码、处理建议与之一致；已纳管设备能关联上 | 关联不上的地址；成功端点的序列号和型号 |
| 交换机、供电框 | 只在 5.2 返回不为 0 时核对；逐字段对照 2.2、2.3 | 每个“仅定义”的字段实际有没有值 |
| 带 DPU 的站点 | 一台主机是否同时返回主机和 DPU 机器；DPU 是否没有被当成服务器 | `machineType` 的取值 |

### 5.6 带回来的内容

1. 采集文件，放在受控目录，记下站点类型（通用服务器或整机柜）和 Core 版本。
2. 按 5.5 核对的结果：把本文档里“仅定义”改为“已验证”，或者记下差异。
3. 第一次出现的结构（新的状态、告警、设备类型），补进 `tests/unit/test_device_status.py`：只取需要的字段，换成占位值。单元测试不读取采集文件。
4. 实现状态有变化时，按[能力需求](rack-operations-requirements.zh-CN.md)的维护规则更新。

### 5.7 局限

- 采集的是某一时刻。状态的变化过程只能多次采集，或者从状态历史里看。
- 站点没有的设备类型，采集里也没有；交换机和供电框要等到有这类设备的站点。
- 回放不包括 Kubernetes，站点设置页依赖集群的部分在回放中显示为不可用。
- 采集的是读取。写操作（电源、维护、固件更新等）不能用回放验证。
