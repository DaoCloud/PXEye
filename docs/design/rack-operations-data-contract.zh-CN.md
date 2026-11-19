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

后端 `services/device_status.py`，接口 `GET /api/device-status`；前端 `web/pages/device_status.js`；测试 `tests/unit/test_device_status.py`。

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

## 3. 候选页面的接口

### 3.1 机器状态时间线（已验证）

`FindMachineStateHistories {"machineIds":[{"id":"<机器ID>"}]}`

```json
{"histories": {"<机器ID>": {"records": [
  {"event": "{\"state\": \"created\"}", "time": "2026-01-01T00:00:00Z", "version": "V2-T…"},
  {"event": "{\"state\": \"hostinit\", \"machine_state\": {\"state\": \"waitingforlockdown\"}}", "time": "…", "version": "…"},
  {"event": "{\"state\": \"ready\"}", "time": "…", "version": "…"}
]}}}
```

`event` 是 JSON 文本，`state` 逐层嵌套。停留时长用相邻记录的 `time` 相减，最后一条算到当前时间。交换机、供电框、机柜有同类接口 `Find…StateHistories`，仅定义。待核对：记录条数有没有上限。

### 3.2 固件清单（已验证）

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
- 待核对：一次请求传多台机器是否可行；这个接口读的是缓存还是会访问 BMC。

### 3.3 发现诊断（已验证）

`GetSiteExplorationReport {}`

```json
{"endpoints": [{"address": "<BMC 地址>", "preingestionState": "Initial",
   "report": {"endpointType": "Unknown", "lastExplorationLatency": "10.0s",
     "lastExplorationErrorSchema": {"errorCode": "NICO-SITEEXPLORER-101", "text": "…", "mitigation": "…"}}}],
 "managedHosts": [{"hostBmcIp": "<BMC 地址>"}],
 "lastRun": {"startedAt": "…", "finishedAt": "…", "success": true, "endpointExplorations": "5", "endpointExplorationsSuccess": "1", "endpointExplorationsFailed": "4"}}
```

探测成功的端点，`report` 是和 3.2 相同结构的报告。相关接口：`FindExploredEndpointIds` 和 `FindExploredEndpointsByIds`（现有代码已在用）、`GetAllUnexpectedMachines`。

### 3.4 硬件校验（部分验证）

| 接口 | 返回 | 验证站点 |
| --- | --- | --- |
| `GetMachineValidationRuns {"machineId":{"id":…}}` | `runs[]`：`validationId.value`、`startTime`、`endTime`、`name`、`context`、`status`、`durationToComplete` | 1 次，状态为已跳过 |
| `GetMachineValidationResults {"machineId":{"id":…}}` | `results[]` | 空 |
| `GetMachineValidationTests {}` | `tests[]`：`testId`、`name`、`description`、`contexts`、`command`、`timeout`、`supportedPlatforms`、`isEnabled` | 11 个内置测试 |
| `GetAllSkuIds {}`，再 `FindSkusByIds {"ids":[…]}` | SKU 定义 | 空 |

### 3.5 健康历史（已验证）

`FindMachineHealthHistories {"machineIds":[{"id":…}]}`，可带 `startTime`、`endTime`。返回 `histories.<机器ID>.records[]`，每条有 `time` 和 `health`（结构同 2.1 的健康）。`ListMachineHealthReports`、`ListHealthReportOverrides` 在验证站点返回空。当前告警直接取各对象的 `status.health.alerts`。

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

## 5. 新站点检查清单

1. `list`，和本文档对比方法有没有增减。
2. 对第 2 节三个页面的接口各 `call` 一次，记录返回条数。条数为 0 的类型，对应页面在该站点没有内容。
3. 有交换机或供电框时，按 2.2、2.3 逐字段核对，把“仅定义”改为“已验证”或记下差异。
4. 打开页面，和 `call` 的返回对照：行数、状态、健康，以及服务器与机器的关联是否正确。
5. 对第 3 节各取一台机器的数据，确认结构一致。
6. 把差异更新到本文档和 `tests/unit/test_device_status.py` 的样本。
