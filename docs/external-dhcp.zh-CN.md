# 使用外部 DHCP 装机

[English](external-dhcp.md) · **简体中文** · [文档索引](README.zh-CN.md)

当网络团队可以分配 DHCP 地址，但不能增加 PXE 选项或 Relay 时，可选择此模式。PXEye 发布小型 UEFI 引导 ISO，NICo Core 通过 BMC VirtualMedia 挂载并管理启动。ISO 内的 iPXE 使用明确的 NICo HTTP 端点；外部 DHCP 仍提供主机地址、掩码和路由。

## 前置条件

- x86_64 UEFI 主机、无托管 DPU、Flat 网络。BMC 支持光盘 VirtualMedia 槽位及单次 `Cd`/`Hdd` 启动。提供标准 Redfish 和 Lenovo XCC1 `EXT` PATCH 适配；具体机型的许可与固件能力仍需验收。
- 外部 DHCP 为**设备规划**中的启动 MAC 配置固定租约，保证 iPXE、Scout、安装器使用同一 IP。Core 中已存在对应 HostInband 网段；不另填一份网络规划。
- BMC 能访问材料 HTTP 服务中的小型 ISO；主机能访问引导 HTTP、证书信任有效的 Core 和 OS 材料。Core 按实际源地址识别主机，不能由 SNAT 隐藏身份。
- 配套 Core 和 Scout 实现 `SetHostBootIntent`、`GetHostBootIntent`、`AcknowledgeHostBoot`、`CancelHostBoot`、`ReleaseHostBootPolicy`。旧 Core 继续使用 Nico DHCP 模式；只更新 PXEye 不会增加 Core 能力。
- 按正常 `make images` 入口构建 PXEye，包含固定版本的通用 EFI/ESP。镜像提供 `mcopy`、`xorriso`，现场无需编译 iPXE。见[镜像构建](deployment.zh-CN.md)。

## 配套源码版本

构建此功能时使用已固定的 [Core 集成提交](https://github.com/SSmallMonster/infra-controller/tree/ebaadc097c4c72af58bf30a934c3b086ed878778)。Core 与 Scout 来自同一个仓库，必须使用同一源码版本。

| 组件 | 源码版本 |
| --- | --- |
| NICo Core 与 Scout | `SSmallMonster/infra-controller` 的 `ebaadc097c4c72af58bf30a934c3b086ed878778` |
| 联想 Redfish 兼容补丁 | `SSmallMonster/libredfish` 的 `b6b4fff7277276bb4d0724e7dd4dca9cea2abbd1`，由 Core 的 Cargo 清单和锁文件固定 |

```bash
git clone https://github.com/SSmallMonster/infra-controller.git
cd infra-controller
git checkout --detach ebaadc097c4c72af58bf30a934c3b086ed878778
```

无需另外准备同级 `libredfish` 目录。构建环境联网时提前获取 Cargo 固定的 Git 依赖，再按 Core 仓库的构建说明生成 Core 和 Scout 制品。

合并源码不会更新集群或离线包。默认 Chart 镜像引用保持原样；准备外部 DHCP 交付时，需要选择配套 Core 镜像和 Scout 文件。仅更新 PXEye 会保留已有 Nico DHCP 站点保存的模式。

## 操作流程

1. 按原现场流程安装控制面；Helm 安装顺序不变。
2. 打开**站点设置 → 管理引导网络**，选择**外部 DHCP**，填写带协议和端口的**引导 HTTP 端点**。同一入口维护**安装材料 HTTP**地址与端口，两者用途不同。
3. 预览并应用。PXEye 将本站点 Kea Deployment 缩放至零并读回确认，不修改 Kea 分配参数、客户 DHCP、Relay 或 Service。存在活动安装任务时不能切换模式。
4. 核对规划启动 MAC/IP 的固定租约。通过更新后的 OS 库创建新 OS 版本并在安装方案中选择；既有不可变 OS 保持原样，外部模式需要新版本中的引导回执参数。
5. 沿用首次安装或重装入口。任务创建时冻结站点模式；PXEye 发布不可变引导介质并提交逐机意图，执行仍由 Core 原生接入、分配和重启流程触发。
6. 在**安装记录 → 外部 DHCP / BMC 引导**查看 Core 阶段、请求代次和介质清理状态。装机是否成功仍由安装器及目标盘验收决定。

引导 HTTP 端点只控制小型介质的首段启动请求，不会改写 Core/PXE 自身的端口或后续脚本地址。两种模式的字段区别见[站点设置](user-guide/site-settings.zh-CN.md#3-引导网络服务地址)。

引导 HTTP 端点提供 `/api/v0/pxe/boot`；材料 HTTP 端点提供小型引导 ISO 和 OS 的 ISO、kernel、initrd。既有 OS 始终使用登记时冻结的材料 URL。

## 责任与恢复

Core 是外部模式下唯一执行 BMC 写操作的组件。它完成 BIOS 准备、选择空闲光盘槽位、校验材料、挂载并读回、设置单次启动及发送重启。在外部写入前保存进度；重启响应不确定时不会自动重复发送。

每次明确的网络启动都会生成新随机标识，包括同一策略代次中后续的 Scout 清理启动。匹配本次标识的 Scout 注册或认证安装器回执，才允许清理**本轮拥有的小型引导介质**。`Ready`、HTTP 响应或已消费的 PXE 标记不能触发卸载；发现其他已挂载介质时停止操作。

安装器回执携带当前内核命令行中的启动标识。安装器已脱离小型 iPXE ISO 运行，Core 才可弹出该 ISO；操作系统 ISO 属于另一份安装材料。收到安装完成证据后，PXEye 请求本地盘交接，由 Core 应用启动设置，不额外发送重启。本地盘交接设置的是单次 `Hdd` 启动，不会修改永久 UEFI 启动顺序。永久顺序应让系统盘优先于网络启动；否则后续普通重启可能逐个尝试已启用的网卡，再回退硬盘，从而超过重启验收等待时间。手动跳过该检查不代表普通重启验收通过。

失败时保留原任务，查看 Core 阶段和错误。同代次的相同意图用于读取或继续已记录进度，不代表再次重启。结束已停止的外部模式任务时，请求 Core 取消并等待本轮介质清理后释放占用；不会终止主机上已运行的安装器。取消的策略保持停止，直到显式替换或释放。

设备没有 Machine/Instance，且 Core 重新处于 `WaitingForIngestion` 时，可通过现有接管确认重新开始。PXEye 要求记录中的外部代次已取消并完成清理，或其策略已不存在，并在内部归档旧接管记录。外部模式声明新代次；Nico DHCP 模式先释放旧策略再接管。结果不确定或仍在进行的请求不能重复发送。

切回 Nico DHCP 必须显式保存，活动任务期间禁止切换。后续原生任务仅在 Core 确认清理后释放已有外部策略。没有外部策略的设备沿用原生 PXE 行为。

## 验证边界

介质生成/UEFI 启动、API/状态转换和编排分别验证，不能代替物理机装机证据。启用某个机型前，需要在指定设备验收挂载/读回/卸载、Scout 注册、安装器回执、本地盘启动和失败恢复。本模式不覆盖 ARM、DPU 初始化、Secure Boot 签名或地址不断变化的 DHCP 租约。
