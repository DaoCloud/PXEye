# 参考集群与截图

[English](reference-cluster.md) · **简体中文** · [文档中心](README.zh-CN.md)

## 架构依据

截图使用编写的 **Grace Blackwell Cluster** 场景，参考 NVIDIA 的 [DGX GB 机柜硬件指南](https://docs.nvidia.com/dgx/dgxgb200-user-guide/hardware.html)和 [GB200 系统与网络说明](https://docs.nvidia.com/multi-node-nvlink-systems/multi-node-tuning-guide/system.html)。官方文档描述计算托盘、BlueField-3 管理端点、NVLink 交换托盘、供电框及独立管理网络。

这是局部逻辑管理视图，不是完整 NVL72 BOM 或布线图。截图包含 `AI-R01` 中的四个计算条目、两台 NVLink 交换机和一个供电框，以及 `MGMT-R01` 中的两台管理服务器；其余机柜组件和业务 Fabric 未展示。

| 对象 | 示例命名 | 地址域 |
| --- | --- | --- |
| 计算条目 | `gb200-r01-c01` … `c04` | BMC `10.251.1.0/24`；管理 `10.252.1.0/24`。 |
| BlueField 端点 | 每个计算条目含两个 DPU BMC 接口 | 机柜 BMC 子网。 |
| NVLink 交换机 | `nvlink-r01-s01`、`s02` | BMC 子网；NVOS `10.251.31.0/24`。 |
| 供电框 | `power-r01-p01` | PMC 使用机柜 BMC 子网。 |
| 管理服务器 | `control-01`、`control-02` | BMC `10.251.10.0/24`；管理 `10.252.10.0/24`。 |

机柜标识、序列号、本地管理 MAC 和私网地址均为本场景编写，不对应客户现场。任务状态是展示数据，不是部署成功的观测结果。单个供电框表示局部组件，不是供电容量设计；当前渲染器的 DPU 标记统计接口条目，不能据此证明实物 DPU 数量。

## 截图来源

三张图使用 PXEye 真实 `src/pxeye/web/` 前端和[本地展示数据](../examples/ai-factory-view.json)。工具仅启动回环地址上的静态服务，提供只读 API 响应并阻止外部请求，不启动 NICo、DHCP、Redfish、SSH 或装机后端，也不修改部署环境的设备清单。

示例文件是 UI 响应数据，**不是** `site.json`、CSV 清单或装机输入。两种语言文档共用当前中文界面截图；ARM64/GB200 装机不属于已有实机验证范围。

## 重新生成截图

在文档工具环境准备 Node.js、Playwright 和 Chromium：

```bash
npm ci --ignore-scripts
npx playwright install chromium
npm run docs:screenshots
```

依赖安装在其他目录时，将 `PLAYWRIGHT_MODULE` 指向实际模块路径；可用 `CHROMIUM_EXECUTABLE` 指定 Chromium 二进制。工具使用真实样式和渲染器，检查页面脚本错误及横向溢出。

| 图片 | 展示页面 |
| --- | --- |
| [机柜拓扑](assets/screenshots/rack-topology.png) | 机柜归属、序列号、地址和已回报电源状态。 |
| [设备管理](assets/screenshots/device-management.png) | 设备清单与地址操作。 |
| [安装任务](assets/screenshots/installation-tasks.png) | 批次、逐机进度和控制台/日志入口。 |

修改示例时，保持三页身份和地址一致，保留参考范围说明，并同步中英文文档。
