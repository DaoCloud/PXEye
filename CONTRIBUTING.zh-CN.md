# 贡献指南

[English](CONTRIBUTING.md) · **简体中文**

参与修改时，先说明运维场景、对应 NICo 资源，以及复现所需的硬件或网络条件。调整流程前阅读[系统架构](docs/architecture.zh-CN.md)和[功能边界](docs/features.zh-CN.md)。

## 设计原则

- 保存规划与硬件执行分离。
- 区分 NICo 原生资源、PXEye 组合资源和现场网络配置。
- 按设备解析身份，不将某个站点 IP、网口名、盘符或 OEM 例外作为通用默认值。
- 记录非幂等写操作是否已发送，结果未知时先读回，不盲目重放。
- 只展示有决策价值的信息，失败应有明确恢复入口。

## 修改流程

1. 说明问题、目标 NICo 版本和当前行为。
2. 在已授权环境或隔离示例中复现。
3. 完成最小且完整的修改，同步两种语言的文档。
4. 检查 Python/JavaScript 语法，只执行现场已授权的验证；硬件写入使用专用设备并明确影响范围。
5. 在变更说明中记录最终行为、验证证据和剩余限制。

修改前安装本地工具：

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
npm ci --ignore-scripts
make syntax lint PYTHON=.venv/bin/python
npm run format:check
npm run check:structure
make wheel PYTHON=.venv/bin/python
```

Python 要求 3.11 或以上。运行代码位于 `src/pxeye/`，可选单元测试源码位于 `tests/unit/`。格式化使用 Ruff 和固定版本的 Prettier。安装软件包后提供 `pxeye` 和 `pxeye-sync-certificates` 入口。`pxeye --help` 和 `pxeye --version` 不启动服务；无参数启动会读取站点与凭据并执行启动恢复。单纯导入模块不会启动服务。

`make syntax` 用于静态语法检查，`make test` 是可选单元测试入口，不能证明硬件兼容。项目或操作员明确排除回归及硬件测试时，不自动启动这些流程。

报告分别说明示例渲染、部署健康、硬件操作和完整 OS 验收，写明镜像/Core 版本与所需 API 或设备能力。不能将渲染出的成功状态写成实际执行结果。

## 文档要求

每份公开 Markdown 提供英文 `.md` 和简体中文 `.zh-CN.md`，并互相链接。两种语言的命令、路径、API 名称和行为保持一致，同时更新[文档中心](docs/README.zh-CN.md)。公开截图只使用有来源说明的编写数据，方法见[参考场景](docs/reference-cluster.zh-CN.md)。

## 不纳入贡献的文件

不提交凭据、私钥、运行证书、生产部署配置、真实硬件清单、SQLite 数据、原始 SOL 日志、安装 user-data 或第三方二进制。新示例和截图也需要检查。PXEye 采用 [Apache-2.0](LICENSE)，依赖保留各自许可证。
