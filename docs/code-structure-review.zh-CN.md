# 代码结构评审与实施

[English](code-structure-review.md) · **简体中文** · [文档中心](README.zh-CN.md)

## 范围

初次静态评审检查了 2026-11-07 的 `0.20.3` 源码。用户授权后，相关调整纳入 `0.21.0` 软件包。本轮仅涉及 PXEye，不修改上游 NICo、NVKE 或 Provider 仓库。

初次快照包含 32 个运行 Python 文件和九个全局前端脚本。最大模块为 `server.py`（1,094 行）、`executor.py`（1,062）、`resources.py`（984）及 `equipment.py`（956）。这些是历史测量，不代表当前路径或运行故障证据。未认定任一发现是既有实机装机失败根因。

## 历史发现与已完成调整

| 优先级 | 历史发现 | 已完成调整与当前源码 |
| --- | --- | --- |
| P1 | 列表读取通过共享的 `machines.tmp` 导出 CSV。 | [原子文本/JSON 写入](../src/pxeye/common.py)使用唯一排他临时文件、刷新/fsync、替换与清理。[资源刷新](../src/pxeye/services/resources.py)负责导出及缺失规划补录；设备 GET 不再执行这些写入。 |
| P2 | 脚本捕获并覆盖弹窗/页面函数，监听器及旧视图重复。 | [UI 运行模块](../src/pxeye/web/shared/ui_runtime.js)统一页面/操作归属、事件分发和轮询生命周期。具名工具与生命周期钩子替代函数捕获，删除重复页面渲染及旧发现轮询。 |
| P2 | 传输与规划服务互相构造，公共契约藏在大型服务内。 | [客户端](../src/pxeye/clients/core.py)拆分 Core/Redfish/SSH/进程传输。公共工具及 [Machine 契约](../src/pxeye/domain/machines.py)独立，[启动组装](../src/pxeye/bootstrap.py)向执行组合层注入资源、设备规划和方案。 |
| P2 | 构造时重复初始化表结构/历史方案，视图反复扫描操作。 | [Store](../src/pxeye/persistence/store.py)集中初始化表结构及版本记录，复用按路径缓存的包装器，连接仍按操作使用。启动显式导入历史方案。[设备视图](../src/pxeye/services/device_view.py)负责列表组合，地址快照一次读取验证、规划和操作记录。 |
| P2 | HTTP 组装负责恢复、调度与锁。 | [任务协调器](../src/pxeye/services/tasks.py)管理相关操作，[HTTP 传输](../src/pxeye/api/http.py)、查询和命令拆分。Application 保留薄兼容转发。 |
| P2 | 错误缺少安全、一致的定位上下文。 | [错误转换](../src/pxeye/api/errors.py)统一 GET/POST/上传的错误码和请求编号；日志记录堆栈位置，省略原始异常文本、命令参数和凭据内容。 |
| P3 | 运行代码、可选验证和现场工具混放，前端代码密集。 | [软件包元数据](../pyproject.toml)、`src/pxeye/`、`tests/unit/`、`tools/` 和[部署骨架](../deploy/kubernetes.yaml)明确目录边界。统一 Python/JS/CSS/HTML 格式；删除 12 个已被后续覆盖的拓扑基础声明，不移动剩余规则或响应式块。 |

## 运行与兼容

```text
src/pxeye/
├── __main__.py, bootstrap.py
├── api/             # HTTP、认证、查询、命令、错误
├── clients/         # Core、Redfish、SSH、有时限进程
├── domain/          # 资源、身份、输入契约
├── persistence/     # SQLite 表结构与存储
├── services/        # 功能操作、视图与任务协调
├── installation/    # 生成、磁盘策略、启动与验收
└── web/             # 公共 UI、页面与静态资产
```

安装 Python 软件包后提供 `pxeye` 和 `pxeye-sync-certificates` 入口。Dockerfile 安装同一个软件包；wheel 包含 UI 文件及独立安装脚本。既有 HTTP 路由、配置/凭据/数据/材料挂载和任务序列化格式继续使用。默认静态目录为包内 `pxeye/web`，仍可通过 `CONSOLE_STATIC` 覆盖。新增本地刷新入口见[架构说明](architecture.zh-CN.md)。

本轮不重新设计装机状态转换、SN/MAC 核验、冻结版本、签名事件、清盘范围、设备锁、启动交接、验收或未知写入恢复。不删除任务/规划表或数据目录。更新仍需备份并遵守单执行器更新流程。

## 验证与限制

已完成：Python 语法与 Ruff 检查；JavaScript 语法；静态注册审计（11 个脚本、八个页面、124 个唯一操作，顶层名称无重复）；格式检查；不启动服务的包导入与入口核对；wheel 构建及内容检查；中英文配对、本地链接和公开文件范围检查。

未运行回归套件、浏览器功能流程、容器构建、部署、真实数据库迁移或实机安装。既有截图保留为编写的参考视图，本轮未重新截图。静态及包检查证明源码/构建结构一致，不是新一轮端到端兼容认证。

## 后续边界

部分功能服务仍使用函数内导入和直接 SQL。执行组合层保留安装器业务组合，并非纯传输客户端。前端仍共享全局名称并依赖明确加载顺序。文件导出和 SQLite 提交是独立操作，多次 Core 观测并非原子快照。进一步存储/查询拆分或 ES modules 迁移应另行限定范围，不能表述为本轮已完成。
