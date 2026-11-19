# 现场采集：布线

[English](cabling.md) · **简体中文** · [现场采集指南](README.zh-CN.md)

页面：设备管理 → 布线。按交换机列出每个服务器网口实际接到哪个端口，并列出没有 LLDP 数据的服务器。数据只来自 NICo 机器对象上的 LLDP 邻居：服务器进入发现流程时，Scout 在每个网口上接收交换机发来的 LLDP 报文并上报。NICo 不需要管理这些交换机。按交换机分组和端口冲突判断在浏览器里计算。准备工作（环境变量、`tools/site-survey.sh`、采集目录）见[现场采集指南](README.zh-CN.md)。

## 1. 数据来源

| 页面内容 | 页面代码调用的 gRPC 接口（请求） | 对等的 nico 命令行 | 对等程度 | 能否自动采集 |
| --- | --- | --- | --- | --- |
| 服务器网口（网口名、MAC） | `FindMachineIds` `{}`，再 `FindMachinesByIds` `{"machineIds":[...],"includeHistory":false}`：`status.lldp_neighbors[].mac_address`、`lldp.local_port` | `--json machine show <机器ID>`（表格视图不显示 LLDP） | 相同 | 能 |
| 交换机标识（通常是交换机 MAC） | 同上：`lldp.id_value` | 同上 | 相同 | 能 |
| 交换机名称 | 同上：`lldp.name` | 同上 | 相同 | 交换机发送了才有 |
| 交换机型号、序列号 | 同上：`lldp.med_inventory` | 同上 | 相同 | 交换机发送了才有 |
| 交换机端口 | 同上：`lldp.remote_port_value`、`lldp.remote_port_type` | 同上 | 相同 | 能，但可能是 MAC 而不是端口名 |
| 没有 LLDP 数据的服务器 | 同上：`status.lldp_neighbors` 为空 | 同上 | 相同 | 能 |
| LLDP 的采集时间 | — | — | 无 | 不能：接口和命令行都没有这个字段 |
| 面板端口名（端口标识是 MAC 时） | — | — | 无 | 不能，要到交换机上查（第 4 节） |
| 交换机名称（交换机没发送时） | — | — | 无 | 不能，要用户提供（第 4 节） |
| 预期布线 | — | — | 无 | 不能，要用户提供（第 4 节） |

页面代码不使用命令行；核对以 gRPC 接口或采集文件为准（见[现场采集指南 1.3 节](README.zh-CN.md#13-命令行和接口的关系)）。

LLDP 标准规定交换机标识和端口标识必须发送；名称、型号、序列号是可选的。字段对照见[数据契约](../design/rack-operations-data-contract.zh-CN.md)第 2.4 节。

## 2. 采集命令

以下命令在仓库根目录执行，`SURVEY_*` 变量已按[现场采集指南 1.2 节](README.zh-CN.md#12-入口脚本)导出。

（1）机器 ID 和条数：

```bash
tools/site-survey.sh --save cabling-machine-ids.txt survey ids machines
tools/site-survey.sh --save cabling-machine-states.txt cli machine states --hosts
```

`<机器ID>` 的取法：取 `cabling-machine-ids.txt` 的第一行；再从 `cabling-machine-states.txt` 里找一台处于失败状态（状态名含 `Failed` 或 `Error`）的主机，取它的 ID 作为第二个 `<机器ID>`。没有失败状态的机器时只用第一个。

（2）LLDP 邻居。gRPC 调用，请求和页面代码相同（页面代码把全部 ID 放进 `machineIds`，这里只放一个）：

```bash
tools/site-survey.sh --save cabling-find-machines-by-ids.txt survey call 'FindMachinesByIds={"machineIds":[{"id":"<机器ID>"}],"includeHistory":false}'
```

对等的命令行，输出完整的机器记录，包括 `lldp_neighbors`：

```bash
tools/site-survey.sh --save cabling-machine-show-<机器ID>.txt cli --json machine show <机器ID>
```

对每个选出的 `<机器ID>` 各执行一次。`survey call` 的输出只显示结构（长值截短，列表只留第一项）；完整的邻居列表看 `cli --json` 的输出或采集文件。`lldp_neighbors` 为空，说明这台机器还没跑过 Scout，或者它的交换机没开 LLDP。

（3）原样采集按[现场采集指南第 2 节](README.zh-CN.md#2-通用流程)整个站点执行一次 `tools/site-survey.sh capture`，覆盖所有页面，布线页不单独采集。

## 3. 核对

`C` 是采集文件，例如 `C=$SURVEY_DIR/capture-<日期时间>.json`（见[现场采集指南 3.1 节](README.zh-CN.md#31-没有浏览器时核对页面)）。

| 项目 | 通过标准 | 用什么对照 | 不通过时记录 |
| --- | --- | --- | --- |
| 有 LLDP 的服务器数 | 页面列出的服务器数等于有邻居的机器数 | `jq '[.pxeye_responses["/api/device-status"].body.servers[] \| select((.lldp // []) \| length > 0)] \| length' $C` | 两个数和差异的机器 ID |
| 网口数 | 每台服务器的网口数等于它的 LLDP 邻居数 | `cli/cabling-machine-show-<机器ID>.txt` 的 `lldp_neighbors` 条数，对照 `jq '.pxeye_responses["/api/device-status"].body.servers[] \| select(.id=="<机器ID>") \| .lldp \| length' $C` | 不一致的服务器 |
| 网口字段 | 网口名、MAC、交换机标识、端口与命令行一致 | `cli/cabling-machine-show-<机器ID>.txt` 对照 `jq '.pxeye_responses["/api/device-status"].body.servers[] \| select(.id=="<机器ID>") \| .lldp' $C` | 不一致的字段和两边的值 |
| 交换机分组 | 同一台物理交换机的端口在同一组里 | `jq '[.pxeye_responses["/api/device-status"].body.servers[].lldp[]? \| {switch_id, switch}] \| unique' $C`；分组本身在浏览器里计算，需要时用 `core-replay.py serve` 看 | 被拆成多组或混在一组的情况，以及当时的交换机标识 |
| 交换机名称 | 有名称的显示名称；没有的显示交换机 MAC | 上一行的输出中 `switch` 是否为空 | 交换机没有发送的项（名称、型号、序列号） |
| 端口标识 | 记下端口标识的类型（`mac`、端口名或其他） | `jq '[.pxeye_responses["/api/device-status"].body.servers[].lldp[]?.remote_port_type] \| unique' $C` | 每种类型的示例 |
| 端口冲突 | 标红的冲突在现场确认是否真实 | `jq '[.pxeye_responses["/api/device-status"].body.servers[] \| .id as $m \| .lldp[]? \| select((.remote_port // "") != "" and ((.switch_id // .switch // .switch_serial // "") != "")) \| {k:((.switch_id // .switch // .switch_serial) + " " + .remote_port), m:$m, mac_address:(.mac_address // .local_port)}] \| group_by(.k) \| map(unique_by({m, mac_address})) \| map(select(length>1))' $C` | 真实冲突的位置；误报的原因 |
| 没有 LLDP 数据 | 列出的服务器确实没有邻居记录 | `jq '[.pxeye_responses["/api/device-status"].body.servers[] \| select((.lldp // []) \| length == 0) \| .id]' $C`，抽一台用 `cli --json machine show <机器ID>` 确认 | 原因：没跑 Scout，还是交换机没开 LLDP |
| 没有 NICo 机器的服务器 | 页面“没有 LLDP 数据的服务器”总数 = 上一行的台数 + 控制台里没有对应 NICo 机器的服务器台数（页面按 `machine_id`，再按 BMC MAC 匹配） | 页面总数减去上一行台数；逐台用 `jq '.pxeye_responses["/api/device-status"].body.servers \| keys' $C` 查该服务器的机器ID是否存在 | 没有机器的服务器序列号；原因：未纳管或 BMC MAC 不一致 |

页面上的冲突只说明数据本身矛盾（同一端口被两个网口报告），不说明接错了线。冲突的 jq 按交换机标识和端口分组，同一台机器的同一网口重复出现时也会列出，要再看一眼是否来自不同网口。

## 4. 需要用户补充的数据

| 数据 | 为什么需要 | 用户怎么取得 | 存成 |
| --- | --- | --- | --- |
| 交换机名称、型号、管理地址 | 交换机没发送名称时，页面只能显示 MAC，看不出是哪台 | 网络管理员的设备清单；或在交换机上查看本机信息（见下） | `supplements/cabling-switches.csv`：`chassis_mac,name,model,serial,management_ip,rack` |
| 端口 MAC 与面板端口名的对应 | 端口标识是 MAC 时，现场不能直接对着面板找口 | 在交换机上查看各端口的本机 LLDP 信息（见下） | `supplements/cabling-switch-ports.csv`：`chassis_mac,port_id,port_name` |
| 预期布线（可选） | 没有它就只能看到实际连接，不能判断接错 | 布线规划表或施工图 | `supplements/cabling-expected.csv`：`server_serial,server_port,switch_name,switch_port` |
| 交换机的 LLDP 是否开启 | 解释“没有 LLDP 数据”的服务器 | 网络管理员确认 | 写在 `session.md` |

`chassis_mac` 和 `port_id` 填页面上显示的值，用来把补充数据和 LLDP 记录对上。

### 在交换机上查看本机信息

由网络管理员在交换机上执行。命令以设备手册为准，下面是常见厂商的写法：

| 交换机系统 | 本机标识和各端口的端口标识 | 邻居列表（用来对照） |
| --- | --- | --- |
| H3C Comware、华为 VRP | `display lldp local-information` | `display lldp neighbor-information list` |
| Arista EOS | `show lldp local-info` | `show lldp neighbors detail` |
| 使用 lldpd 的系统（Cumulus Linux；SONiC 在 `lldp` 容器里执行） | `lldpcli show interfaces` | `lldpcli show neighbors` |

其他系统按设备手册查找“LLDP 本机信息”的查看命令。

输出保存为 `supplements/cabling-<交换机名>-lldp.txt`，再整理成上面的两个 CSV。只需要只读的查看命令，不需要修改交换机配置。

这两个 CSV 可以在可写的控制台上，用布线页的“导入交换机信息”导入。PXEye 把它们存在自己的数据库里，不写入 NICo；只读观察实例不能导入。导入后，采集文件里有 `/api/switch-labels`，可以和文件对照，例如 `jq '.pxeye_responses["/api/switch-labels"].body | {switches: (.switches | length), ports: (.ports | length)}' $C`。格式和对应规则见[数据契约](../design/rack-operations-data-contract.zh-CN.md)第 2.6 节。

## 5. 常见情况

| 现象 | 判断 |
| --- | --- |
| 端口显示成一串 MAC | 交换机用端口的 MAC 作端口标识（例如 H3C 的默认设置）。用上面的命令补充对应关系 |
| 某台服务器没有任何邻居 | 还没跑过 Scout，或者交换机没开 LLDP，或者中间隔着不转发 LLDP 的设备 |
| 所有服务器都没有邻居 | 交换机普遍没开 LLDP，或者机器都还没进入发现流程；问网络管理员 |
| 交换机标识相同、名称不同 | 可能是交换机堆叠，记录下来 |
| 改了线后页面没变 | LLDP 记录是 Scout 上一次运行时的快照，要等 Scout 再次运行；记录里没有时间，无法从数据判断新旧 |
| `machine show` 表格里看不到 LLDP | 表格视图不显示 LLDP，要加 `--json` |

## 6. AI 执行清单

1. 执行 `tools/site-survey.sh --save cabling-machine-ids.txt survey ids machines`。成功且有输出时，记下行数，进入第 2 步。命令失败时按[现场采集指南第 5 节](README.zh-CN.md#5-给-ai-的规则)重试一次，仍失败则记下错误并停止。
2. 行数为 0：NICo 里没有机器，布线页在该站点没有内容。问用户：“这个站点的服务器是否已经纳管到 NICo？设备管理里是否有服务器？”把回答写进 `session.md`，本页停止。
3. 执行 `tools/site-survey.sh --save cabling-machine-states.txt cli machine states --hosts`，按第 2 节选出一到两个 `<机器ID>`。
4. 对每个 `<机器ID>` 执行第 2 节的 `survey call 'FindMachinesByIds=...'` 和 `cli --json machine show <机器ID>`。两条都成功即进入下一步。
5. 看 `cli/cabling-machine-show-<机器ID>.txt` 的 `lldp_neighbors`。全部为空时，问用户：“交换机是否开启了 LLDP？这些机器是否已经跑过发现（Scout）？”记下回答。
6. 确认本站点已执行过一次 `tools/site-survey.sh capture`；没有就执行，退出码为 0 才继续，为 2 时修正原因后重来。
7. 按第 3 节逐项执行 jq 并对照，记录每项通过或不通过。
8. 交换机名称为空或端口类型是 `mac` 时，停下来问用户：“请提供交换机名称、型号、序列号、管理地址和所在机柜，填 `supplements/cabling-switches.csv`（列 `chassis_mac,name,model,serial,management_ip,rack`）；以及端口 MAC 与面板端口名的对应，填 `supplements/cabling-switch-ports.csv`（列 `chassis_mac,port_id,port_name`）。可以在交换机上执行第 4 节的只读命令取得。”在可写的控制台上，请用户用布线页的“导入交换机信息”导入这两个文件（只读观察实例上不能导入）；下次采集后，把 `/api/switch-labels` 和文件对照，记录结果。
9. 问用户是否有预期布线；有则存成 `supplements/cabling-expected.csv`（列 `server_serial,server_port,switch_name,switch_port`），没有就记“未提供”。用户整理的 CSV 请用户确认后保存。
10. 在 `session.md` 里写本页：Core 版本；机器数和有 LLDP 的服务器数；端口标识类型；第 3 节每项的核对结果和差异；端口冲突及现场确认结果；没有 LLDP 的服务器及原因（分两组：有机器但 LLDP 为空；没有 NICo 机器）；已收到和缺少的补充数据（缺什么、影响哪一项）；失败的命令及错误码。
