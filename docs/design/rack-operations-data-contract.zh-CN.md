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
- 这个工具只看结构。要原样保存返回，用 `tools/core-capture.py`，见[现场采集指南](../field-survey/README.zh-CN.md)。

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

### 2.5 告警

没有新的 Core 接口。页面 `web/pages/alerts.js` 从 `/api/equipment` 读设备清单，从 `/api/device-status` 读 `servers[]`、`switches[]`、`power_shelves[]` 的 `health`，与 2.1 到 2.3 是同一份数据（`FindMachinesByIds`、`FindSwitches`、`FindPowerShelves`）。

| 页面内容 | `/api/device-status` 中 `health` 的字段 | Core 来源 |
| --- | --- | --- |
| 告警分组和搜索 | `alerts[].id`、`alerts[].target`、`alerts[].message` | `status.health.alerts[]` |
| 开始时间、分组的最早开始时间 | `alerts[].since` | `in_alert_since` |
| 分类筛选、`PreventAllocations` 计数 | `alerts[].classifications[]` | `classifications` |
| 健康等级需要关注但没有告警项的设备 | `level`（`warning`、`alert`、`critical`）且 `alerts` 为空 | `status.health_status`，或存在告警 |

一条记录是一台设备上的一个告警。设备名打开现有的运行状态弹窗。页面只读。

待核对：真实的告警 ID 和文字；除 `PreventAllocations` 外出现哪些分类；`target` 的取值。

### 2.6 PXEye 本地数据

PXEye 自己的 SQLite 数据库中有两张表：`switch_labels` 和 `rack_units`。每次导入替换整张表。不写入 NICo Core，也不写入交换机。只有开启 `rack_operations` 时才有这些接口；只读观察实例拒绝写入，页面也不提供导入。用 `tools/core-capture.py` 做的采集包含这两个接口和这两张表。

| 数据 | 接口 | 后端 | 页面 |
| --- | --- | --- | --- |
| 交换机信息 | `GET /api/switch-labels`；`POST /api/switch-labels` `{"switches_csv", "ports_csv", "revision"}` | `services/switch_labels.py` | 布线，“导入交换机信息” |
| U 位 | `GET /api/rack-units`；`POST /api/rack-units` `{"csv", "revision"}` | `services/rack_units.py` | 服务器，“导入 U 位” |

CSV 格式。交换机表和端口表的表头必须完全一致（列名前后的空格忽略）；U 位的表头不区分大小写：

| 表 | 表头 | 必填 | 唯一键 |
| --- | --- | --- | --- |
| 交换机 | `chassis_mac,name,model,serial,management_ip,rack` | `chassis_mac`、`name` | `chassis_mac` |
| 端口 | `chassis_mac,port_id,port_name` | 全部 | `chassis_mac` + `port_id` |
| U 位 | `serial,rack,unit` 或 `serial,rack,unit,height` | `serial`、`unit` | `serial` |

校验：每张表最多 2000 行；每行列数与表头一致；`chassis_mac` 接受常见的 MAC 写法，保存为小写冒号格式；`port_id` 是 MAC 时同样规范化，否则不区分大小写比较；`unit` 和 `height` 是 1 到 60 的整数（`height` 默认 1），`unit + height - 1` 不超过 60；机柜相同且不为空的位置不能重叠（机柜为空的行不检查重叠）；唯一键不能重复（`serial` 区分大小写，交换机和端口的键不区分大小写）。有任何错误时整次导入被拒绝，返回 HTTP 400 和错误列表，每条带行号和字段（交换机信息还带表名）。HTTP 层对两者都接受最大 2 MiB 的请求体，足够 2000 行。保存时带上次读取的 `revision`；如果期间有人保存过，返回 409（`REVISION_CONFLICT`、`RACK_UNITS_CONFLICT`）。

对应规则：

- 交换机信息对应 `switch_id`（`lldp.id_value`）与 `chassis_mac` 是同一 MAC 的 LLDP 邻居。端口信息还要求 `remote_port`（`lldp.remote_port_value`）按同样规范化后等于 `port_id`。布线页在 LLDP 报告的内容旁显示交换机名称和面板端口名，并统计没有对应上的条目。
- U 位对应设备管理中该序列号的设备。`GET /api/rack-units` 返回 `positions`、`mismatches`（记录的机柜与设备的 `rack_id` 不同）和 `unknown`（设备管理中没有的序列号）。机柜列只用于比对，从不写入。

待核对：真实交换机上 `id_value` 是否就是机箱 MAC；端口类型不是 `mac` 的交换机上 `remote_port_value` 的形式。

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

`lastRun` 失败已在真实站点见过：`success` 为 false，`error` 为 “Site Explorer credentials are missing or invalid”，`failureCategory` 为 `missing_credentials`，计数全为 0、没有端点。页面在顶部显示这次失败和原因。

待核对：成功端点的序列号和型号从未在完整的真实报告上提取过；`machineId` 出现的情况未见过；`failureCategory` 的其他取值。

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

## 5. 现场采集

到站点后怎么采集、核对每个页面，以及需要用户补充哪些数据，见[现场采集指南](../field-survey/README.zh-CN.md)。每个页面一份文档；本文档只记录字段和验证结论，采集到新的情况后回到这里更新。
