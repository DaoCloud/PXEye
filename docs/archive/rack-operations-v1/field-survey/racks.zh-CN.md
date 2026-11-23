# 现场采集：机柜

[English](racks.md) · **简体中文** · [现场采集指南](README.zh-CN.md)

> **已归档（2026-11-23）。** 本文档属于被整机柜新设计取代的一套设计，不再维护；内容保留归档时的原样，仅供查阅。现行设计见[设计文档](../../../design/README.zh-CN.md)，归档说明见[归档目录](../../README.zh-CN.md)。

页面：设备管理 → 机柜。页面显示 NICo Core 为声明的整机柜（例如 GB200 NVL72）保存的机柜对象：名称、机柜型号、状态、健康、成员数量，以及每个机柜的状态和健康历史。通用服务器站点没有机柜对象，页面会说明。开启 `rackActions` 后，页面还能发起机柜维护和机柜固件更新；采集时从不执行这些操作。准备工作（环境变量、采集目录、`--save`）见[现场采集指南](README.zh-CN.md)。

## 1. 数据来源

| 页面内容 | 页面代码调用的 gRPC 接口（请求） | 对等的 nico 命令行 | 对等程度 | 能否自动采集 |
| --- | --- | --- | --- | --- |
| 机柜 ID | `FindRackIds` `{}` | `rack list` | 相同 | 能（整站采集记录 `/api/racks`） |
| 机柜名称、状态、健康、机柜组 | `FindRacksByIds` `{"rackIds":[{"id":"<机柜ID>"}]}` | `rack show <机柜ID>`；完整记录用 `--json rack show <机柜ID>` | 相同 | 能，同上 |
| 机柜型号 | `GetAllExpectedRacks` `{}` | `expected-rack show` | 相同 | 能，同上 |
| 状态历史 | `FindRackStateHistories` `{"rackIds":[{"id":"<机柜ID>"}]}` | `rack state-history <机柜ID>` | 相同 | 不能：采集只读机柜列表，不读每个机柜的历史；用第 2 节命令 |
| 健康历史 | `FindRackHealthHistories` `{"rackIds":[{"id":"<机柜ID>"}]}` | `rack health-history <机柜ID>` | 相同 | 不能，同上 |
| RMS 是否响应（在操作对话框中显示） | `GetRmsVersion` `{}` | `backend rms status`（不在采集白名单中） | 相同 | 不能；只用 `survey call` 读取 |
| 站点是否为整机柜；是否部署了 RMS | — | — | 无 | 不能，要用户确认 |

页面代码不使用命令行；核对以 gRPC 接口为准，见[现场采集指南 1.3 节](README.zh-CN.md#13-命令行和接口的关系)。接口和字段见[数据契约](../design/rack-operations-data-contract.zh-CN.md)第 4.3 节。

## 2. 采集命令

假设已按[现场采集指南 1.2 节](README.zh-CN.md#12-入口脚本)导出 `SURVEY_*` 变量，在仓库根目录执行。

（1）数量和 ID：

```bash
tools/site-survey.sh --save racks-ids.txt survey ids racks
```

输出一行一个机柜 ID，行数就是机柜数量。为 0 时跳到第 4 节。

（2）每项内容的 gRPC 调用和对等命令行。`<机柜ID>` 取 `racks-ids.txt` 的第一行；如果 `rack list` 里有处于维护、错误状态或健康有告警的机柜，再取一个这样的 ID 重复执行带 `<机柜ID>` 的命令。

```bash
# 列表、状态、健康
tools/site-survey.sh --save racks-find.txt survey call 'FindRackIds={}'
tools/site-survey.sh --save racks-list.txt cli rack list
tools/site-survey.sh --save racks-show.txt cli rack show <机柜ID>
tools/site-survey.sh --save racks-show-json.txt cli --json rack show <机柜ID>

# 机柜型号
tools/site-survey.sh --save racks-expected-grpc.txt survey call 'GetAllExpectedRacks={}'
tools/site-survey.sh --save racks-expected.txt cli expected-rack show

# 状态和健康历史
tools/site-survey.sh --save racks-state-history.txt cli rack state-history <机柜ID>
tools/site-survey.sh --save racks-health-history.txt cli rack health-history <机柜ID>

# RMS 可达性（只读；报错表示 RMS 没有响应）
tools/site-survey.sh --save racks-rms-version.txt survey call 'GetRmsVersion={}'
```

`survey call` 的输出只显示结构（长值截短，列表只留第一项）；完整数据看 `cli --json` 的输出。

（3）原样采集整个站点执行一次即可（[现场采集指南第 2 节](README.zh-CN.md#2-通用流程)），不按页面重复。它记录 `/api/racks`（机柜列表、状态、健康、成员设备和机柜声明），不含每个机柜的历史：

```bash
tools/site-survey.sh capture
```

## 3. 核对

保存的文件在 `$SURVEY_DIR/cli/` 和 `$SURVEY_DIR/survey/` 下。对照只读观察实例的机柜页。

| 项目 | 通过标准 | 用什么对照 | 不通过时记录 |
| --- | --- | --- | --- |
| 行数 | 页面的机柜数等于 ID 数 | 机柜页对照 `survey/racks-ids.txt` 的行数 | 两边的数量，多出或缺少的 ID |
| 状态、健康 | 和命令行一致 | 机柜页对照 `cli/racks-show-json.txt` | 实际的状态文本和健康取值 |
| 机柜型号 | 页面上的型号和应有机柜一致 | 机柜页对照 `cli/racks-expected.txt` | 机柜 ID、两边的型号 |
| 状态历史 | 页面时间线的状态和顺序相同 | 页面的机柜历史对照 `cli/racks-state-history.txt` | 缺少或顺序不对的状态 |
| 字段 | 数据契约 3.7、4.3 节每个字段实际有没有值 | `cli/racks-show-json.txt`、`survey/racks-expected-grpc.txt` | 每个字段的实际值或“为空” |
| RMS | `GetRmsVersion` 返回版本，或记下错误 | `survey/racks-rms-version.txt` | 错误码和消息 |

字段对照见[数据契约](../design/rack-operations-data-contract.zh-CN.md)第 3.7、4.3 节。目前机柜字段都是“仅定义”或来自演示采集：验证过的站点上没有机柜对象。

## 4. 需要用户补充的数据

| 数据 | 为什么需要 | 用户怎么取得 | 存成 |
| --- | --- | --- | --- |
| 站点是否为整机柜 | 命令返回为空时，要区分“通用服务器”还是“机柜没有声明” | 询问站点负责人；对照 `tools/site-survey.sh cli expected-rack show` | 写在 `session.md` |
| 是否部署了 RMS | Core 的组件管理后端为 `rms` 时，托盘、交换机、供电框、固件和机柜维护操作经 RMS 执行；没有 RMS 会失败 | 向 NICo 运维要 Core 配置中 `component_manager` 的后端以及 RMS 是否在运行；对照 `survey/racks-rms-version.txt` | 写在 `session.md`：三个后端、有无 RMS |
| 机柜型号（整机柜时） | 核对 NICo 中的型号 | 机柜出货清单 | `supplements/racks-expected.csv`：`rack,profile` |

## 5. 常见情况

| 现象 | 判断 |
| --- | --- |
| ID 数为 0，站点是通用服务器 | 正常。这一页在该站点不适用 |
| ID 数为 0，但 `expected-rack show` 不为空 | 机柜已声明，但还没有机柜对象；记下应有的机柜，问用户 |
| 后端为 `rms`，但 `GetRmsVersion` 失败 | RMS 没有部署或不可达；该站点经 RMS 的操作会失败。记录下来 |
| 用户要整柜上电或下电 | NICo 不提供（见[操作类功能规则](../design/rack-operations-actions.zh-CN.md)）。记录需求 |

## 6. AI 执行清单

1. 执行 `tools/site-survey.sh --save racks-ids.txt survey ids racks`。成功后数行数。失败时按[现场采集指南第 5 节](README.zh-CN.md#5-给-ai-的规则)重试一次，仍失败就记下错误并停止本页。
2. 执行 `tools/site-survey.sh --save racks-rms-version.txt survey call 'GetRmsVersion={}'`，记下版本或错误。
3. 行数为 0：执行 `tools/site-survey.sh --save racks-expected.txt cli expected-rack show`。按输出分两种情况：
   - 为空：停下问用户：“这个站点是不是整机柜（例如 GB200/GB300 NVL72）？是否部署了 RMS？Core 配置中 `component_manager` 的后端是什么？”记录回答后结束本页，跳到第 8 步。
   - 不为空：把应有的机柜 ID 和型号记入 `session.md`，停下问用户：“这 N 个机柜已声明，但 NICo 没有它们的机柜对象，这是预期的吗？”记录回答后结束本页，跳到第 8 步。
4. 行数大于 0：按第 2 节（2）依次执行全部命令，`<机柜ID>` 取第一行；`rack list` 中处于维护、错误或有健康告警的，再取一个执行带 ID 的命令。每条成功后再执行下一条。
5. 按第 3 节逐项核对，每项写下通过或不通过和记录内容。
6. 问用户是否部署了 RMS、机柜型号；存成 `supplements/racks-expected.csv`，请用户确认。
7. 不在机柜页或操作对话框执行任何操作，也不执行 `rack maintenance` 或其他写命令。
8. 在 `session.md` 写本页：Core 版本、机柜数量、有没有数据、RMS 的响应、三个后端、每项核对结果、失败的调用、已收到和缺少的用户数据、需要更新的数据契约字段。
