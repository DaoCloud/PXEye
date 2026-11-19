# 现场采集：布线

[English](cabling.md) · **简体中文** · [现场采集指南](README.zh-CN.md)

页面：设备管理 → 布线。按交换机列出每个服务器网口实际接到哪个端口。数据只来自 NICo 机器对象上的 LLDP 邻居：服务器进入发现流程时，Scout 在每个网口上接收交换机发来的 LLDP 报文并上报。NICo 不需要管理这些交换机。准备工作和通用流程见[现场采集指南](README.zh-CN.md)。

## 1. 数据来源

| 页面内容 | NICo 命令行 | gRPC 接口 | 能否自动采集 |
| --- | --- | --- | --- |
| 服务器网口（网口名、MAC） | `machine show <机器ID>` | `FindMachinesByIds` 的 `status.lldpNeighbors[].macAddress`、`lldp.localPort` | 能 |
| 交换机标识（通常是交换机 MAC） | 同上 | `lldp.idValue` | 能 |
| 交换机名称 | 同上 | `lldp.name` | 交换机发送了才有 |
| 交换机型号、序列号 | 同上 | `lldp.medInventory` | 交换机发送了才有 |
| 交换机端口 | 同上 | `lldp.remotePortValue`、`remotePortType` | 能，但可能是 MAC 而不是端口名 |
| 采集时间 | — | — | 不能：记录里没有时间字段 |
| 面板端口名（端口标识是 MAC 时） | — | — | 不能，要到交换机上查 |
| 预期布线 | — | — | 不能，要用户提供 |

LLDP 标准规定交换机标识和端口标识必须发送；名称、型号、序列号是可选的。字段对照见[数据契约](../design/rack-operations-data-contract.zh-CN.md)第 2.4 节。

## 2. 采集命令

```bash
D=<采集目录>/cli
cli --json machine show --hosts                  > $D/cabling-machines.json
```

每台机器的 LLDP 邻居在机器详情里。挑几台机器查看：

```bash
M=<机器ID>
survey call 'FindMachinesByIds={"machineIds":[{"id":"'$M'"}]}' > $D/cabling-$M.txt
```

`status.lldpNeighbors` 为空，说明这台机器还没跑过 Scout，或者它的交换机没开 LLDP。

整站采集会把每台机器的全部 LLDP 邻居原样记录下来，布线页不需要单独采集。

## 3. 核对

| 项目 | 通过标准 | 不通过时记录 |
| --- | --- | --- |
| 网口数 | 每台服务器在页面上的网口数等于它的 LLDP 邻居数 | 不一致的服务器 |
| 交换机分组 | 同一台物理交换机的端口在同一组里 | 被拆成多组或混在一组的情况，以及当时的交换机标识 |
| 交换机名称 | 有名称的显示名称；没有的显示交换机 MAC | 交换机没有发送的项（名称、型号、序列号） |
| 端口标识 | 记下端口标识的类型（`mac`、端口名或其他） | 每种类型的示例 |
| 端口冲突 | 标红的冲突在现场确认是否真实 | 真实冲突的位置；误报的原因 |
| 没有 LLDP 数据 | 列出的服务器确实没有邻居记录 | 原因：没跑 Scout，还是交换机没开 LLDP |

页面上的冲突只说明数据本身矛盾（同一端口被两个网口报告），不说明接错了线。

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

## 5. 常见情况

| 现象 | 判断 |
| --- | --- |
| 端口显示成一串 MAC | 交换机用端口的 MAC 作端口标识（例如 H3C 的默认设置）。用上面的命令补充对应关系 |
| 某台服务器没有任何邻居 | 还没跑过 Scout，或者交换机没开 LLDP，或者中间隔着不转发 LLDP 的设备 |
| 交换机标识相同、名称不同 | 可能是交换机堆叠，记录下来 |
| 改了线后页面没变 | LLDP 记录是 Scout 上一次运行时的快照，要等 Scout 再次运行 |
