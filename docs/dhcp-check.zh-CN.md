# 现场 DHCP 快速检查

[English](dhcp-check.md) · **简体中文** · [文档中心](README.zh-CN.md)

在目标设备所在 VLAN 的 Linux 测试主机上，通过 Make 检查 DHCP 请求和回复。需要 Python 3.11+、Make 及原始报文权限（通常使用 root）；不需要 Nmap、第三方 Python 包或联网安装软件。

脚本使用所选网卡的真实 MAC，从 `0.0.0.0:68` 向 `255.255.255.255:67` 发送 Discover。默认在 15 秒内发送三次，收集并去重显示匹配本次事务和 MAC 的 Offer。不会发送 Request、接受租约、配置主机 IP 或路由，也不修改 Kubernetes、Relay 或防火墙。DHCP/NICo 仍可能记录测试 MAC 或临时地址分配。

## 执行命令

在 Linux 测试主机的 PXEye 仓库根目录执行，选择实际连接目标 VLAN 且已启用的 Ethernet/VLAN 网卡：

```bash
ip -br link
sudo make dhcp-check IFACE=eno1
```

将 `eno1` 替换成实际接口。一个 VLAN 成功不能代表其他 VLAN，ping 通也不能证明 DHCP 广播或 Relay 可用。

已知预期服务器和网段时同时校验，示例地址需替换成现场值：

```bash
sudo make dhcp-check IFACE=eno1 \
  DHCP_SERVER=192.0.2.10 DHCP_SUBNET=192.0.2.0/24
```

`DHCP_SERVER` 比较 Option 54（Server Identifier），不是 UDP 来源 IP；NAT 下两者可能不同。未指定时只能确认收到 Offer，不能自动证明来自 NICo。

保留结果时提供一个尚不存在的 JSON 文件路径，父目录需已存在：

```bash
sudo make dhcp-check IFACE=eno1 \
  DHCP_REPORT="/tmp/dhcp-check-$(date +%Y%m%d%H%M%S).json"
```

报告包含接口、MAC、事务 ID、预期值、各个 Offer、发送次数及结果，不覆盖已有文件。

## 参数

| Make 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `IFACE` | 必填 | 实际客户端网卡 |
| `DHCP_TIMEOUT` | `15` | 总等待时间，1–120 秒 |
| `DHCP_ATTEMPTS` | `3` | Discover 次数，1–5 次，均匀分布在等待时间内 |
| `DHCP_MAC` | 网卡 MAC | 可选客户端 MAC；与二层 MAC 不同可能被 DHCP snooping 拦截 |
| `DHCP_SERVER` | 不检查身份 | 预期的 Option 54 服务器 IPv4 |
| `DHCP_SUBNET` | 不检查网段 | 预期提供地址所属 IPv4 CIDR；不验证地址池起止范围 |
| `DHCP_REPORT` | 不写文件 | 可选 JSON 报告路径 |

固定预留的 MAC 可能收到预留地址；限制为已登记 MAC 的服务器也可能忽略新测试 MAC。脚本不改变这些服务端策略。

## 结果与定位

`OFFER` 显示服务器标识、来源 IP、提供地址、掩码、网关、DNS、NTP 和引导信息；未提供的字段为空。

| RESULT | 脚本退出码 | 含义 |
| --- | --- | --- |
| `pass` | `0` | 至少一个 Offer 符合指定条件；未指定条件时仅代表收到 Offer |
| `no_offer` | `1` | 无匹配 Offer；查 VLAN/Relay/UDP 入口和回程，再查 NICo 子网、地址池和 MAC 策略 |
| `error` | `2` | 参数、接口、原始报文权限或报告文件错误 |
| `mismatch` | `3` | 收到 Offer，但均不符合预期服务器或网段 |
| 中断 | `130` | 用户中断，接口配置未改变 |

多个服务器回复时会提示；即使有符合条件的 Offer，也要核对其他回复是否产生竞争。Make 会显示脚本失败状态，但其自身通常返回 `2`；自动化需准确区分时读取 JSON `exit_code`，或使用 `python3 tools/dhcp-check.py --help` 中的参数直接运行脚本。

客户端发出 Discover，但服务端没有同一 MAC/事务 ID，优先排查入口；服务端已发送 Offer、客户端未收到，优先查回程、ACL、snooping 和 NAT。超时本身不能证明服务进程异常。

## 验收边界

本命令测试实际网卡的广播路径，不进入 Kind 网络命名空间或绕过物理入口。Kind 中仅 ClusterIP 的 DHCP Service 通常无法直接接收物理广播；需要实际可达的 UDP 入口、网络连接或 Relay。NodePort 本身也不转发物理广播。

收到 Offer 后，还需在专用测试设备完成 Discover → Offer → Request → ACK，并从设备网络验证引导 HTTP、DNS、NTP 等。Option 54 或 DNS/NTP 中的 Pod IP/ClusterIP 需要真实可达路径。完整要求见[装机前检查清单](pre-installation-checklist.zh-CN.md)；Helm Ready 或本检测通过均不能替代真实装机验收。

原有 `tools/dhcp-discover.py` 保留为 Nmap 兼容工具，本入口使用独立的 `tools/dhcp-check.py`。
