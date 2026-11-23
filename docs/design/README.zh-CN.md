# 设计文档

[English](README.md) · **简体中文** · [文档中心](../README.zh-CN.md)

这里放现行的目标设计：面向 GB200 / GB300 整机柜的运维设计。它说明要做成什么样、为什么这样做，不是已实现功能的说明。本分支的应用代码目前仍是第一版页面；现有代码的行为见[功能与边界](../features.zh-CN.md)、[系统架构](../architecture.zh-CN.md)和[页面使用指南](../user-guide/README.zh-CN.md)。

## 文档

| 内容 | English | 简体中文 | 回答的问题 |
| --- | --- | --- | --- |
| 设计说明书 | [Read](whole-rack-operations.md) | [阅读](whole-rack-operations.zh-CN.md) | 平台架构、整体流程、模块与资源、模块依赖、操作设计、非功能设计 |
| 前端设计稿 | [Read](frontend/README.md) | [阅读](frontend/README.zh-CN.md) | 每个页面长什么样、能做什么；可点击；菜单与用词规则 |
| 页面功能说明 | — | [阅读](frontend/page-spec.zh-CN.md) | 全部页面的定位、功能点、字段、规则和弹窗；由设计稿生成 |
| 接口契约 | — | [阅读](frontend/interface-contract.zh-CN.md) | 每个页面调用 NICo 的哪些接口和命令行、用到哪些字段、要先准备哪些资源，以及设计与 NICo 之间的缺口；由设计稿生成 |

## 目录结构

| 位置 | 内容 | 维护方式 |
| --- | --- | --- |
| `whole-rack-operations*.md` | 设计说明书，中英两份 | 手工维护；菜单、流程、模块或门控变化时在同一个提交里更新两种语言 |
| `figures/` | 设计说明书的四张图及其源文件 | 改源文件后重新出图，见下 |
| `frontend/` | 前端设计稿：可点击的页面，每个页面脚本带自己的说明 | 改页面时同时改它的说明，再重新生成页面功能说明 |
| `frontend/page-spec.zh-CN.md` | 页面功能说明 | 生成的文件，不直接修改 |
| `frontend/contract.js` | 接口契约的来源：NICo 的资源依赖、接口清单和缺口 | 页面用到的接口变化时修改；各页面在 `spec.calls` 里声明自己用到的接口 |
| `frontend/interface-contract.zh-CN.md`、`frontend/contract.json` | 接口契约的文档和数据 | 生成的文件，不直接修改 |

一份内容只有一个来源：

- 页面层面的内容（页面有什么、字段、按钮、弹窗、门控）只写在 `frontend/pages/*.js` 的 `spec` 里。设计说明书不重复页面细节。
- 平台层面的内容（架构、流程、模块、资源、规则）只写在设计说明书里。
- 菜单和用词规则只写在 `frontend/README` 里；设计说明书的导航一节与它保持一致。

## 重新生成

页面功能说明：

```bash
node docs/design/frontend/tools/build-spec.mjs
```

图。架构图是手工维护的 `architecture.svg`；流程图的源文件是 `workflow.dot`；资源关系图和模块依赖图由 `diagrams.py` 生成。需要本机有 `rsvg-convert` 和 Graphviz 的 `dot`：

```bash
cd docs/design/figures && python3 diagrams.py && for f in architecture resources modules; do rsvg-convert -z 2 $f.svg -o $f.png; done && dot -Tpng -Gdpi=200 workflow.dot -o workflow.png
```

图里的文字是简体中文，中英两份设计说明书共用同一组图。

## 不放在这里的内容

| 内容 | 位置 |
| --- | --- |
| 现有代码的功能、架构 | `docs/features*.md`、`docs/architecture*.md` |
| 现有页面的使用指南 | `docs/user-guide/` |
| 部署、构建、现场操作 | `docs/` 根目录 |
| 被取代的设计 | [归档目录](../archive/README.zh-CN.md) |
| 现场记录、带站点信息的材料、测试计划 | 仓库之外 |
