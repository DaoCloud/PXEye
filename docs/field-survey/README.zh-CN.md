# 现场采集指南

[English](README.md) · **简体中文** · [文档中心](../README.zh-CN.md)

到一个站点后，按本目录为每个机柜运维页面收集真实数据：用哪些 NICo 命令行和接口、看什么、存到哪里，以及哪些数据 NICo 没有、需要向用户要。每个页面一份文档，本文件是共同的准备和规则。

字段的完整对照见[数据契约](../design/rack-operations-data-contract.zh-CN.md)；页面的目的和范围见[范围与现状](../design/rack-operations.zh-CN.md)。

| 页面 | 文档 | NICo 能自动提供 | 需要用户补充 |
| --- | --- | --- | --- |
| 设备管理 → 服务器（含运行状态的状态时间线、健康历史、硬件校验、固件清单） | [服务器](servers.zh-CN.md) | 运行状态、健康、硬件能力、LLDP、状态和健康历史、校验记录、固件版本 | 机柜归属、主机固件基线、是否启用校验 |
| 设备管理 → 交换机 | [交换机](switches.zh-CN.md) | NVLink 交换机的状态、健康、管理口 | 站点是否有 NVLink 交换机、应有的清单 |
| 设备管理 → 供电框 | [供电框](power-shelves.zh-CN.md) | 供电框的状态、健康、容量、电压 | 站点是否有供电框、应有的清单 |
| 设备管理 → 告警 | [告警](alerts.zh-CN.md) | 服务器、交换机、供电框当前的健康告警 | 不需要；可选提供站点已知的告警 |
| 设备管理 → 布线 | [布线](cabling.zh-CN.md) | 服务器网口到交换机端口的 LLDP 连接 | 交换机名称和型号、端口 MAC 与面板端口名的对应、预期布线 |
| 设备管理 → 发现诊断 | [发现诊断](discovery-diagnostics.zh-CN.md) | 每个 BMC 地址的探测结果、错误码、处理建议 | 应有的 BMC 地址清单、网络可达性 |

## 1. 准备

### 1.1 在哪里执行

- 在站点上运行一个只读观察实例：同一个 PXEye 镜像，开启 `readOnly` 和 `rackOperations`，连接该站点的 Core。它拒绝一切写操作，不参与装机。
- 所有命令都在这个实例的容器里执行，**不在正在装机的控制台里执行**。
- 脚本从本仓库经标准输入传进容器，不需要镜像里带 `tools/`。

### 1.2 入口脚本

所有采集都通过一个脚本 `tools/site-survey.sh` 执行。每次调用都是独立的，不依赖之前定义的函数或变量，AI 可以逐条直接执行。在仓库根目录运行。

先设置环境变量（每个新的 shell 都要设置，或者写在命令前面）：

| 变量 | 含义 | 是否必填 |
| --- | --- | --- |
| `SURVEY_NAMESPACE` | 只读观察实例所在的命名空间 | 必填 |
| `SURVEY_DEPLOYMENT` | 观察实例的 Deployment 名 | 必填 |
| `SURVEY_CONTEXT` | kubectl 的 context | 可选 |
| `SURVEY_SSH` | 本机不能直接用 kubectl 时，先登录到能用的机器，例如 `ssh -p 2022 root@<节点地址>` | 可选 |
| `SURVEY_DIR` | 采集目录，必须在本仓库之外 | 保存输出时必填 |

```bash
export SURVEY_NAMESPACE=<namespace> SURVEY_DEPLOYMENT=<pxeye> SURVEY_DIR=<采集目录>
tools/site-survey.sh check
```

`check` 打印 Core（`carbide-api`）和命令行（`nico-admin-cli`）的版本，以及机器、交换机、供电框的数量。两者的 `build_version`、`git_sha` 都要记下，之后各页面的结论都要注明 Core 版本。两者可能不同：命令行随 PXEye 镜像发布，Core 随站点部署更新。

脚本有四种用法：

| 用法 | 作用 | 底层 |
| --- | --- | --- |
| `tools/site-survey.sh cli <命令>` | 运行只读的 NICo 命令行 `nico-admin-cli`；加 `--json` 在命令前输出 JSON | `tools/core-cli.py`，在容器里调用 `/usr/local/bin/nico-admin-cli`，自动带上 Core 地址和身份证书 |
| `tools/site-survey.sh survey call '<接口>=<请求>'` | 调用 Core 的 gRPC 读取接口，与页面代码发出的请求相同 | `tools/core-survey.py`，在容器里调用 `grpcurl` |
| `tools/site-survey.sh survey ids machines` | 列出完整的机器 ID，一行一个；也可以是 `switches`、`power-shelves`、`racks` | 同上 |
| `tools/site-survey.sh capture` | 把页面用到的全部 Core 返回原样保存到采集目录 | `tools/core-capture.py` |

在第一个参数前加 `--save <文件名>`，输出会同时保存到 `$SURVEY_DIR/cli/` 或 `$SURVEY_DIR/survey/` 下。命令失败时不会留下文件，退出码不为 0。

三个底层工具都只允许读取：

- `cli` 只接受白名单里的命令，执行 `tools/site-survey.sh cli list` 可以看到全部；`machine force-delete`、`site-explorer explore` 这类命令会被拒绝。
- `survey call` 只接受名字以 `Find`、`Get`、`List`、`Determine` 开头的接口，并拒绝返回凭据的接口。
- `survey call` 的输出只显示结构：长值截短，列表只留第一项。要完整数据用 `cli --json` 或 `capture`。

### 1.3 命令行和接口的关系

页面代码只调用 gRPC 接口，不使用命令行。`nico-admin-cli` 是同一个 Core API 的另一个客户端，它的输出经过整理：表格会截断长值，JSON 用下划线字段名。所以各页面文档把两者分开列：

| 对等程度 | 含义 | 核对时 |
| --- | --- | --- |
| 相同 | 命令行调用的就是页面代码用的同一个接口 | 可以直接用命令行的输出核对页面 |
| 近似 | 命令行用别的接口取到相近的数据 | 只能交叉参考，不一致时以 `survey call` 或采集文件为准 |
| 无 | 没有对应的命令行 | 只能用 `survey call` 或采集文件 |

对应关系按站点 Core 版本（`7c7788a8c7f1`）的命令行源码核对过。Core 版本不同时，用 `cli <命令> --help` 和 `survey describe <接口>` 重新确认。

### 1.4 采集目录

每次采集建一个目录，放在**本仓库之外**、只有项目成员能访问的位置，例如 `operations/runs/<运行编号>/`：

```text
<采集目录>/
  session.md                 过程和结论
  capture-<站点>.json         core-capture 的原样采集（权限 600）
  cli/<页面>-<内容>.txt        命令行输出
  survey/<页面>-<内容>.txt     gRPC 调用的输出
  supplements/<名称>.csv      用户补充的数据
```

命令输出用 `--save` 保存，例如：

```bash
tools/site-survey.sh --save servers-machine-show.txt cli machine show --hosts
```

用户补充的数据由 AI 或用户手工放进 `supplements/`。

采集文件和命令输出里有站点地址、序列号和机器 ID，**不能放进本仓库**。

## 2. 通用流程

每个页面按同样的四步走，各页面文档只写差异：

1. **看有没有数据**：执行页面文档第 2 节的命令，记录条数。条数为 0 的，页面在该站点没有内容，跳到第 4 步，确认是否符合实际。
2. **原样采集**：整个站点执行一次即可，覆盖所有页面：

   ```bash
   tools/site-survey.sh capture
   ```

   文件保存为 `$SURVEY_DIR/capture-<日期时间>.json`，权限 600。结束时会打印汇总：采集是否完整、失败的调用、返回为空的方法。退出码 0 表示完整（其中可以有失败的调用，那是站点的事实）；2 表示中途中止，文件名带 `-incomplete`，需要修正原因后重来；其他值表示没能运行，不留下文件。
3. **逐项核对**：按页面文档第 3 节的通过标准，把页面内容和命令输出对照。有浏览器时打开观察实例上的页面；没有浏览器时，用采集文件里控制台接口的输出对照（见 3.1 节）。
4. **向用户补充**：按页面文档第 4 节，把 NICo 没有的数据向用户要，存成指定格式的 CSV。

## 3. 离开站点后

```bash
PYTHONPATH=src python3 tools/core-replay.py check <采集目录>/capture-<站点>.json
PYTHONPATH=src python3 tools/core-replay.py serve <采集目录>/capture-<站点>.json --port 18930
```

- `check` 用当前代码重算控制台每个接口的输出，和采集时逐字段比较。全部一致时退出码为 0。
- `serve` 启动一个本地控制台，Core 的返回都来自采集文件，页面和后端是真实代码。
- 出现 `UNRECORDED`，说明代码读了采集里没有的数据，需要重新采集，不能自己编一个返回。

### 3.1 没有浏览器时核对页面

采集文件的 `pxeye_responses` 就是页面当时从控制台接口拿到的数据。用 `jq` 取出来，和命令输出对照：

```bash
C=$SURVEY_DIR/capture-<日期时间>.json
jq '.pxeye_responses | keys' $C                                        # 采集到的控制台接口
jq '.pxeye_responses["/api/device-status"].body.servers | length' $C   # 页面关联上的服务器数
jq '.pxeye_responses["/api/equipment"].body.devices | map(.kind) | group_by(.) | map({(.[0]): length}) | add' $C
jq '.summary' $C                                                       # 采集汇总
```

页面上的筛选、分组和冲突判断在浏览器里计算，这种方式核对不到；需要时在本地用 `serve` 打开页面看。

### 3.2 修改代码后

| `check` 结果 | 处理 |
| --- | --- |
| 全部 OK | 无 |
| DIFF，是这次改动预期的 | 逐条确认后用 `--write <新文件>` 另存；新文件里的 Core 返回仍是原样 |
| DIFF，不是预期的 | 回归，修代码 |
| UNRECORDED | 回站点重新采集 |

采集不会因为某项读不到而中止，空返回、失败的调用、部分失败的接口都会原样记录，回放时同样出现，见第 6 节。

### 3.3 演示数据

没有站点和 Core 时，用演示采集展示所有机柜运维页面：

```bash
python3 tools/demo-capture.py > /tmp/demo.json
PYTHONPATH=src python3 tools/core-replay.py serve /tmp/demo.json --writable
```

- 数据是编写的示例占位数据（站点“演示站点（示例数据）”，`"demo": true`，序列号 `DEMO-…`，MAC `02:…`，地址取自 192.0.2.0/24 和 198.51.100.0/24），从来不是站点结果：不能作为已验证依据，也不能据此标记数据契约字段。
- `tools/demo-capture.py` 列出了每个页面有意展示的内容（各类状态、告警、端口冲突、交换机信息、U 位机柜不一致、发现失败）；`tests/unit/test_demo_capture.py` 校验它。
- `--writable` 解除控制台的整个只读限制，所有命令都可用，不只是 PXEye 本地导入（交换机信息、U 位，回放停止后即丢弃）。写 Core 和 Redfish 仍以 `UNRECORDED` 失败；SSH 因回放没有 SSH 密钥和 known hosts 而失败。`--host` 指定监听地址（默认 127.0.0.1）。
- 生成的文件与其他采集一样不放进仓库。

## 4. 用户补充的数据

NICo 没有的数据由用户提供，统一存成 CSV：

- 文件放在 `<采集目录>/supplements/`，文件名和列按各页面文档第 4 节的规定。
- 第一行是列名，UTF-8 编码，一行一条。
- 用户给的是表格、截图或口头说明时，整理成规定的 CSV 后请用户确认。
- 用户暂时给不出的，在 `session.md` 里写明“缺少什么、影响哪个页面的哪一项”，不要用猜测的值填。

这些 CSV 目前只作为核对和后续开发的依据。PXEye 里还没有录入它们的地方，除机柜外（机柜在设备管理的系统配置里填写，需要在可写的控制台上操作）。

## 5. 给 AI 的规则

在站点上协助采集的 AI 按以下规则工作：

1. 只通过 `tools/site-survey.sh` 运行命令，只用本目录列出的命令，以及 `tools/site-survey.sh cli list` 里的命令。不要执行写操作，不要在正在装机的控制台里执行命令。
2. 每条命令都加 `--save` 保存到采集目录，不只看一眼。
3. 页面文档第 4 节列出的数据，NICo 里没有，必须问用户。提问时说明：要什么、为什么需要、用户可以怎么取得（给出命令）、存成什么格式。不要从别的数据推测。
4. 命令失败时，先单独重试一次，区分偶发和一直失败；一直失败的，记下命令、错误码和消息。
5. 结束时在 `session.md` 里写：Core 版本、每个页面有没有数据、核对结果、缺少的用户数据、对文档和测试需要的更新。
6. 有新的发现时，按第 7 节更新文档和测试样本；实现状态有变化时，更新[能力需求](../design/rack-operations-requirements.zh-CN.md)。

## 6. 空数据和失败

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
- **失败的调用**：用 `survey call` 单独再调一次，确认是偶发还是一直失败。一直失败时把方法、错误码和消息记到[数据契约](../design/rack-operations-data-contract.zh-CN.md)对应的字段表里；如果是该 Core 版本不支持的方法，在第 2、3 节注明。
- **中止**：修正原因后重新采集。中止的文件可以保留，用作排查依据，不用作测试基准。

## 7. 带回来的内容

1. 采集文件，放在受控目录，记下站点类型（通用服务器或整机柜）和 Core 版本。
2. 按各页面文档第 3 节核对的结果：把[数据契约](../design/rack-operations-data-contract.zh-CN.md)里“仅定义”改为“已验证”，或者记下差异。
3. 第一次出现的结构（新的状态、告警、设备类型），补进 `tests/unit/test_device_status.py`：只取需要的字段，换成占位值。单元测试不读取采集文件。
4. 实现状态有变化时，按[能力需求](../design/rack-operations-requirements.zh-CN.md)的维护规则更新。

## 8. 局限

- 采集的是某一时刻。状态的变化过程只能多次采集，或者从状态历史里看。
- 站点没有的设备类型，采集里也没有；交换机和供电框要等到有这类设备的站点。
- 回放不包括 Kubernetes，站点设置页依赖集群的部分在回放中显示为不可用。
- 采集的是读取。写操作（电源、维护、固件更新等）不能用回放验证。
