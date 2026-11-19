# 现场采集：发现诊断

[English](discovery-diagnostics.md) · **简体中文** · [现场采集指南](README.zh-CN.md)

页面：设备管理 → 发现诊断。列出 NICo 站点发现对每个 BMC 地址的探测结果，用来定位设备为什么没有进入 NICo。准备工作和通用流程见[现场采集指南](README.zh-CN.md)。

## 1. 数据来源

| 页面内容 | NICo 命令行 | gRPC 接口 | 能否自动采集 |
| --- | --- | --- | --- |
| 每个 BMC 地址的类型、厂商、接入阶段、探测结果 | `site-explorer get-report endpoint` | `GetSiteExplorationReport` | 能 |
| 错误码、错误说明、处理建议 | `site-explorer get-report endpoint` | 同上（`lastExplorationErrorSchema`） | 能 |
| 已组成受管主机的地址 | `site-explorer get-report managed-host` | 同上（`managedHosts`） | 能 |
| 上次探测的时间和计数 | — | 同上（`lastRun`） | 能 |
| 应有的 BMC 地址 | — | — | 不能：NICo 只知道它探测到的地址 |
| 网络能否到达 BMC | — | — | 不能，要在 BMC 网络上检查 |
| BMC 的凭据是否正确 | — | — | 不能读出，要用户确认 |

字段对照见[数据契约](../design/rack-operations-data-contract.zh-CN.md)第 3.3 节。

## 2. 采集命令

```bash
D=<采集目录>/cli
cli site-explorer get-report endpoint            > $D/discovery-endpoints.txt
cli site-explorer get-report managed-host        > $D/discovery-managed-hosts.txt
cli --json site-explorer get-report all          > $D/discovery-report.json
```

`get-report all` 的输出包含探测成功的端点的完整 Redfish 报告，文件可能很大，含序列号和地址，只存在采集目录里。

端点为空时，说明 NICo 还没有探测过任何地址：检查站点设置里的发现网段，以及 BMC 是否通过 NICo 的 DHCP 拿到了地址。

## 3. 核对

| 项目 | 通过标准 | 不通过时记录 |
| --- | --- | --- |
| 地址数 | 页面行数等于 `get-report endpoint` 的行数 | 多出或缺少的地址 |
| 结果 | 失败的错误码、说明、处理建议和命令输出一致 | 不一致的地址 |
| 关联 | 已纳管设备的地址关联到了设备 | 关联不上的地址，以及设备管理里该设备记录的 BMC 地址 |
| 成功端点 | 显示的序列号和型号与报告一致 | 报告里实际的序列号、型号字段 |
| 上次探测 | 时间和计数与报告一致 | 探测失败时的原因 |

## 4. 需要用户补充的数据

| 数据 | 为什么需要 | 用户怎么取得 | 存成 |
| --- | --- | --- | --- |
| 应有的 BMC 地址清单 | 页面只显示 NICo 探测到的地址；从未出现的设备看不到 | 设备规划表、到货清单或 DHCP 分配记录。设备管理的“设备规划”页签可以导出 | `supplements/discovery-expected-bmcs.csv`：`serial,bmc_mac,bmc_ip` |
| 网络可达性 | 错误为“连接被拒绝”或超时时，要区分网络不通和 BMC 服务未开 | 在 BMC 网络上的一台机器执行下面的检查 | `supplements/discovery-reachability.txt` |
| BMC 凭据是否已配置 | 认证失败类错误需要确认凭据 | 询问用户；凭据本身不要写进任何文件 | 写在 `session.md`（只写“已确认”或“未确认”） |

### 可达性检查

在能访问 BMC 网络的机器上执行，只读，不登录：

```bash
ping -c 3 <BMC 地址>
curl -sk -o /dev/null -w '%{http_code}\n' --max-time 10 https://<BMC 地址>/redfish/v1
```

`curl` 返回 `200` 或 `401` 说明 Redfish 服务在运行；连接被拒绝或超时，说明网络不通或 BMC 没开 Redfish。

## 5. 常见情况

| 现象 | 判断 |
| --- | --- |
| 错误码 `NICO-SITEEXPLORER-101`，连接被拒绝 | 地址能到，但 BMC 没开 Redfish，或这个地址不是 BMC（例如交换机、PDU 拿到了同网段地址） |
| 类型显示为 `Unknown` | 探测没有成功，NICo 无法判断设备类型 |
| 设备在应有清单里，但页面上没有它的地址 | BMC 没拿到地址，或不在 NICo 探测的网段里 |
| 接入阶段停在 `Initial` | 探测还没成功过 |
