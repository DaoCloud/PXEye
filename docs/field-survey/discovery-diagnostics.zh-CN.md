# 现场采集：发现诊断

[English](discovery-diagnostics.md) · **简体中文** · [现场采集指南](README.zh-CN.md)

页面：设备管理 → 发现诊断。列出 NICo 站点发现对每个 BMC 地址的探测结果（类型、厂商、接入阶段、错误码和处理建议、是否已组成受管主机）以及上次探测的时间和计数，用来定位设备为什么没有进入 NICo。页面数据来自控制台接口 `/api/exploration`。准备工作（环境变量、`--save`、采集目录）见[现场采集指南](README.zh-CN.md)。

## 1. 数据来源

| 页面内容 | 页面代码调用的 gRPC 接口（请求） | 对等的 nico 命令行 | 对等程度 | 能否自动采集 |
| --- | --- | --- | --- | --- |
| 每个 BMC 地址的类型、厂商、接入阶段 | `GetSiteExplorationReport` `{}`（`endpoints[].report.endpointType`、`vendor`、`endpoints[].preingestionState`） | `--json site-explorer get-report all`；表格：`site-explorer get-report endpoint` | 相同 | 能 |
| 错误码、错误说明、处理建议 | 同上（`endpoints[].report.lastExplorationErrorSchema`、`lastExplorationError`） | `--json site-explorer get-report all`；表格：`site-explorer get-report endpoint --erroronly` | 相同 | 能 |
| 成功端点的序列号、型号 | 同上（`endpoints[].report.systems[]`） | `--json site-explorer get-report all`；单个：`site-explorer get-report endpoint <BMC 地址>` | 相同 | 能 |
| 已组成受管主机的地址 | 同上（`managedHosts[].hostBmcIp`） | `--json site-explorer get-report all`；表格：`site-explorer get-report managed-host` | 相同 | 能 |
| 上次探测的时间和计数 | 同上（`lastRun`） | `--json site-explorer get-report all` | 相同 | 能 |
| 应有的 BMC 地址 | — | — | 无 | 不能：NICo 只知道它探测到的地址，由用户提供 |
| 网络能否到达 BMC | — | — | 无 | 不能，要在 BMC 网络上检查 |
| BMC 的凭据是否正确 | — | — | 无 | 不能读出，要用户确认 |

页面代码不使用命令行；核对以 gRPC 接口或采集文件为准（见[现场采集指南](README.zh-CN.md#13-命令行和接口的关系)）。字段对照见[数据契约](../design/rack-operations-data-contract.zh-CN.md)第 3.3 节。

## 2. 采集命令

在仓库根目录、已按指南 1.2 节导出 `SURVEY_*` 变量的 shell 里逐条执行。

（1）数量和 ID。本页面不按 ID 请求，机器 ID 只用来核对“已纳管设备的地址关联到了设备”：

```bash
tools/site-survey.sh --save discovery-machine-ids.txt survey ids machines
tools/site-survey.sh --save discovery-machine-states.txt cli machine states --hosts
```

本页面只用一个 `<机器ID>`：`discovery-managed-hosts.txt`（第 2 节（2））里某一行的 Machine Id 列，和同一行的 Host BMC Ip 列（即下面的已纳管 `<BMC 地址>`）是同一台机器。

（2）探测报告。页面代码发出的请求：

```bash
tools/site-survey.sh --save discovery-report-structure.txt survey call 'GetSiteExplorationReport={}'
```

`survey call` 的输出只显示结构。完整数据用相同接口的命令行：

```bash
tools/site-survey.sh --save discovery-report.json cli --json site-explorer get-report all
tools/site-survey.sh --save discovery-endpoints.txt cli site-explorer get-report endpoint
tools/site-survey.sh --save discovery-endpoints-failed.txt cli site-explorer get-report endpoint --erroronly
tools/site-survey.sh --save discovery-managed-hosts.txt cli site-explorer get-report managed-host
```

逐个地址查看：`<BMC 地址>` 取 `discovery-endpoints-failed.txt` 的第一个地址，再取 `discovery-managed-hosts.txt` 里一个已纳管的地址：

```bash
tools/site-survey.sh --save discovery-endpoint-failed.txt cli site-explorer get-report endpoint <BMC 地址>
tools/site-survey.sh --save discovery-endpoint-managed.txt cli site-explorer get-report endpoint <BMC 地址>
```

关联核对用的 `<机器ID>`：取 `discovery-managed-hosts.txt` 中与已纳管 `<BMC 地址>` 同一行的 Machine Id。用 JSON 输出确认这台机器记录的 BMC 地址：

```bash
tools/site-survey.sh --save discovery-machine-show.json cli --json machine show <机器ID>
```

`jq -r '.bmc_info.ip' $SURVEY_DIR/cli/discovery-machine-show.json` 应等于 `<BMC 地址>`。受管主机为空时跳过这一步，并记下原因。

`discovery-report.json` 含成功端点的完整 Redfish 报告，文件可能很大，含序列号和地址，只存在采集目录里。

（3）原样采集（`tools/site-survey.sh capture`）每个站点只做一次，覆盖所有页面，见[现场采集指南](README.zh-CN.md)第 2 节；不要为本页面单独再做。

## 3. 核对

`C` 为采集文件：`C=$SURVEY_DIR/capture-<日期时间>.json`。命令行输出在 `$SURVEY_DIR/cli/`。

| 项目 | 通过标准 | 用什么对照 | 不通过时记录 |
| --- | --- | --- | --- |
| 地址数 | 页面行数等于报告里的端点数 | `jq '.pxeye_responses["/api/exploration"].body.endpoints \| length' $C` 对照 `jq '.endpoints \| length' cli/discovery-report.json`（不要数 `cli/discovery-endpoints.txt` 的行数，其中含表头和边框行） | 多出或缺少的地址 |
| 结果 | 失败地址的错误码、说明、处理建议和报告一致 | `jq '.pxeye_responses["/api/exploration"].body.endpoints \| map(select(.failed)) \| map({address, error})' $C` 对照 `cli/discovery-endpoints-failed.txt` | 不一致的地址和字段 |
| 关联 | 已组成受管主机的地址标为已纳管 | `jq '[.pxeye_responses["/api/exploration"].body.endpoints[] \| select(.managed_host) \| .address]' $C` 对照 `cli/discovery-managed-hosts.txt`、`cli/discovery-machine-show.json` 的 `.bmc_info.ip` | 关联不上的地址，以及设备管理里该设备记录的 BMC 地址 |
| 成功端点 | 序列号和型号与报告一致 | `jq '.pxeye_responses["/api/exploration"].body.endpoints \| map(select(.address=="<BMC 地址>")) \| map({address, serial, model})' $C`（`<BMC 地址>` 为第 2 节取的已纳管地址）对照 `cli/discovery-endpoint-managed.txt` | 报告里实际的序列号、型号字段 |
| 上次探测 | 时间和计数与报告一致 | `jq '.pxeye_responses["/api/exploration"].body.last_run' $C` 对照 `jq '.last_run' cli/discovery-report.json` | 探测失败时的原因（`error`、`failure_category`） |

## 4. 需要用户补充的数据

| 数据 | 为什么需要 | 用户怎么取得 | 存成 |
| --- | --- | --- | --- |
| 应有的 BMC 地址清单 | 页面只显示 NICo 探测到的地址；从未出现的设备看不到 | 设备规划表、到货清单或 DHCP 分配记录。设备管理的“设备规划”页签可以导出 | `supplements/discovery-expected-bmcs.csv`：`serial,bmc_mac,bmc_ip` |
| 网络可达性 | 错误为“连接被拒绝”或超时时，要区分网络不通和 BMC 服务未开 | 在 BMC 网络上的一台机器执行下面的检查 | `supplements/discovery-reachability.txt` |
| BMC 凭据是否已配置 | 认证失败类错误需要确认凭据 | 询问用户；凭据本身不要写进任何文件 | 写在 `session.md`（只写“已确认”或“未确认”） |

### 可达性检查

由用户在能访问 BMC 网络的机器上执行，只读，不登录：

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
| 端点数为 0 | NICo 还没有探测过任何地址：检查站点设置里的发现网段，以及 BMC 是否通过 NICo 的 DHCP 拿到了地址 |

## 6. AI 执行清单

1. 执行 `tools/site-survey.sh check`，记下 `build_version` 和 `git_sha`。失败时按指南第 5 节规则 4 重试一次，仍失败则停下，把错误告诉用户。
2. 执行第 2 节（1）的两条命令。成功后继续。
3. 执行 `survey call 'GetSiteExplorationReport={}'`。调用失败：重试一次，仍失败则记下错误码和消息，停下问用户该 Core 是否开启了站点发现。
4. 执行 `cli --json site-explorer get-report all`，用 `jq '.endpoints | length' $SURVEY_DIR/cli/discovery-report.json` 得到端点数。
5. 端点数为 0：本页面在该站点没有内容，说明 NICo 还没探测过任何地址。问用户：“站点设置里是否配置了发现网段？BMC 是否应通过 NICo 的 DHCP 拿地址？”并请用户按第 4 节填 `supplements/discovery-expected-bmcs.csv`。再确认采集文件里页面的端点数也是 0：整个站点还没做过 `tools/site-survey.sh capture` 时先执行一次（指南第 2 节），然后执行 `jq '.pxeye_responses["/api/exploration"].body.endpoints | length' $C`；不是 0 时把两个数都记下并告诉用户。记录回答后停止本页面，跳到第 12 步。
6. 端点数大于 0：执行第 2 节（2）里其余三条表格命令。
7. 按第 2 节的取法选 `<BMC 地址>`，执行逐个地址的两条命令；再从 `discovery-managed-hosts.txt` 同一行取 `<机器ID>`，执行 `--json machine show`，确认 `.bmc_info.ip` 等于该 `<BMC 地址>`。没有失败地址或没有受管主机时，跳过对应命令并记下原因。
8. 确认整个站点已经做过一次 `tools/site-survey.sh capture`；没有则执行一次（指南第 2 节）。退出码 2 时修正原因后重来。
9. 按第 3 节逐项核对，记录通过或差异。
10. 向用户要应有的 BMC 地址清单，说明原因，存成 `supplements/discovery-expected-bmcs.csv`（`serial,bmc_mac,bmc_ip`），整理后请用户确认。清单里有、报告里没有的地址，列给用户。
11. 有“连接被拒绝”或超时的地址时，请用户在 BMC 网络上执行第 4 节的可达性检查，结果存为 `supplements/discovery-reachability.txt`；有认证失败类错误时，问用户凭据是否已配置，只记“已确认”或“未确认”。用户给不出的，不要猜测。
12. 在 `session.md` 写本页面的结论：Core 版本、端点数（失败数、受管主机数）、上次探测的时间和结果、第 3 节每项的核对结果（端点数为 0 时写“第 3 节核对因端点数为 0 跳过”）、缺少的用户数据及其影响、需要对文档和测试做的更新。
