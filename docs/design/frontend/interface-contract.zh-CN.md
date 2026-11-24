# 整机柜运维接口契约

[设计稿说明](README.zh-CN.md) · [页面功能说明](page-spec.zh-CN.md) · [设计文档](../README.zh-CN.md)

本文件由 `tools/build-spec.mjs` 从 `contract.js` 生成，不要直接修改。它是内部实现参考，不用于对外展示；可点击的版本是 `internal.html`。

每个页面调用 NICo 的哪些接口、对应什么命令行、用到哪些字段，以及要让页面有数据必须先准备好哪些资源。接口、参数和字段取自 NICo 源码 `dsx-ai-factory/infra-controller` 的提交 `856eb1665`（v2.5.0 之后）。接口、参数和字段取自这个提交的源码。换版本时逐项重新核对。

证据等级：**定义** = 只读过源码里的定义；**调用** = 在没有整机柜硬件的 NICo 环境里实际调用过，“实测”一列写着看到了什么；**模拟** = 在模拟整机柜的环境里调用过；**现场** = 在真实整机柜环境核对过。实际调用所用的环境运行的是提交 28e4e9824，比上面的提交早 2 个，在同一条线上。 目前 26 个接口实际调用过。共 38 个资源、79 个接口（其中写操作 32 个，现有产品已调用 43 个）、26 个缺口。

## 组件：功能需要部署什么

一个接口需要某个组件，是由它的类型、执行方和前置资源推出来的。“必需”是任何功能都需要；“整机柜”是机柜级功能需要；“可选”缺了只影响一部分信息。

| 组件 | 工作负载 | 级别 | 提供什么 | 部署方式 | 缺失时 | 接口数 | 依赖它的页面 | 出处 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| NICo Core | nico-api（含站点发现和各状态机）、数据库、密钥库 | 必需 | 全部 Core gRPC：子网、设备声明、发现、设备读取与单设备操作、实例、健康报告 | 随产品的 Chart 安装 | 平台不可用 | 78 | 全部调用 NICo 的页面 | `helm/charts/nico-api` |
| DHCP 服务 | nico-dhcp | 必需 | 给各管理网段的设备分配地址，并在 Core 里留下设备接口；设备发现从这里开始 | 随 Core 的 Chart 安装 | 新设备拿不到地址，不会被发现；已发现的设备不受影响 | 3 | 接入 › 网络规划 › DHCP 服务；接入 › 网络规划 › 地址分配；接入 › 设备发现；运维 › 设备管理 › 服务器；运维 › 设备管理 › 交换机；运维 › 设备管理 › 供电框；交付 › 安装任务 | `helm/charts/nico-dhcp` |
| 引导服务 | nico-pxe、nico-dns、nico-ntp | 必需 | iPXE 引导、装机材料、名称解析和时间 | 随 Core 的 Chart 安装 | 不能装机；新主机走不完接管流程 | 2 | 交付 › 安装任务；配置 › 安装方案 | `helm/charts/nico-pxe` |
| 硬件健康服务 | nico-hardware-health | 必需 | 采集 BMC 传感器和托盘泄漏检测，写成设备的健康报告 | 随 Core 的 Chart 安装 | 健康告警页只剩站点发现和手工写入的报告；托盘泄漏不会阻止分配 | 2 | 运维 › NVLink 域管理；运维 › 机柜管理 › 机柜详情；运维 › 健康告警；交付 › 安装任务 | `helm/charts/nico-hardware-health` |
| RMS | Rack Management Service | 整机柜 | 整机柜里计算托盘、交换机、供电框的电源和固件；交换机的证书与口令配置、复位、退役；设备的槽位信息 | 官方 Chart rack-manager；镜像从公开源码自己构建。已在没有整机柜硬件的环境里部署，Core 探测结果为已连通 | 设备和机柜的电源、固件操作不可用；交换机过不了配置阶段，机柜走不到就绪 | 13 | 配置 › 站点设置 › 站点概况；配置 › 站点设置 › 控制面；运维 › 机柜管理 › 机柜详情；运维 › 设备管理 › 服务器；运维 › 设备管理 › 交换机；运维 › 设备管理 › 供电框；配置 › 固件基线 | `docs/configuration/rms.md` |
| REST 接口 | REST API、工作流、站点管理、站点代理、Temporal | 整机柜 | 机柜、托盘、NVLink 域和任务的 REST 接口；期望与实际的对账 | 官方 Chart nico-rest、nico-rest-site-agent、temporal；镜像自己构建，要和 Core 同一个源码提交。已部署，接口实际调用通过 | 机柜对账、机柜立面的槽位、任务列表不可用；机柜级任务无法提交 | 13 | 配置 › 站点设置 › 站点概况；配置 › 站点设置 › 控制面；运维 › 机柜管理；运维 › NVLink 域管理；运维 › 机柜管理 › 机柜详情；运维 › 设备管理 › 服务器；运维 › 设备管理 › 交换机；运维 › 设备管理 › 供电框；运维 › 运维任务 | `rest-api/INSTALLATION.md` |
| Flow | nico-flow | 整机柜 | 机柜级任务的编排：上线、电源、固件、分阶段发布；机柜与托盘的清单和任务记录 | 官方 Chart nico-flow；镜像自己构建，要和 Core 同一个源码提交。已部署，已从 Core 同步到清单 | 机柜级电源与固件、运维任务不可用，整柜泄漏时也不会自动下电；机柜上线由 Core 的状态机进行，不受影响；单设备的状态类操作照常 | 12 | 配置 › 站点设置 › 站点概况；运维 › 机柜管理；运维 › NVLink 域管理；运维 › 机柜管理 › 机柜详情；运维 › 设备管理 › 服务器；运维 › 设备管理 › 交换机；运维 › 设备管理 › 供电框；运维 › 运维任务 | `docs/architecture/flow.md` |
| NMX-C | 交换机上的 NMX-C | 整机柜 | NVLink 域的集群配置和域编号 | 不在集群里部署：它运行在交换机上，由 RMS 配置，Core 通过交换机的管理地址访问 | NVLink 域管理没有数据；机柜上线里的 NMX-C 配置阶段无法完成 | 5 | 配置 › 站点设置 › 站点概况；运维 › NVLink 域管理 | `docs/development/machine-a-tron-nmxc-mock.md` |
| 设施事件接入 | nico-dsx-exchange-consumer、消息总线 | 可选 | 把楼宇管理系统的泄漏事件写成机柜的健康报告 | Core Chart 里的一个开关；另外需要现场楼宇系统的消息总线。未部署 | 机柜级泄漏不会进入 NICo，不会自动阻止分配；安全联锁本来就不依赖它 | 0 | 运维 › 机柜管理 › 机柜详情；运维 › 健康告警 | `docs/operations/leak-detection-handling.md` |
| 监控系统 | Prometheus | 可选 | DHCP 的请求、应答和丢弃计数；各子网的空闲地址数 | 现场已有的监控系统 | DHCP 服务页没有请求计数，其余不受影响 | 1 | 接入 › 网络规划 › DHCP 服务 | `docs/observability/core_metrics.md` |

## 各页面的接口数与前置资源

| 页面 | 需要的组件 | 读 | 写 | 前置资源（按准备顺序） |
| --- | --- | --- | --- | --- |
| 运维 › 机柜管理 | NICo Core、REST 接口、Flow | 4 | 0 | NICo Core → 正向 DNS 域 → VLAN 与 VNI 资源池 → 机柜规格配置 → 站点默认凭据 → DHCP 与引导服务 → 集群级证书签发者 → 编排用数据库 → Temporal → RMS → 组件管理器 → REST 身份认证 → REST 站点 → Flow → 子网 → 机柜组声明 → 机柜声明 → 设备声明 → 现场 DHCP 中继 → 设备接口与地址 → 探测结果 → 交换机对象 → 机柜对象 → Flow 的机柜与托盘清单 → 任务 |
| 运维 › 机柜管理 › 机柜详情 | NICo Core、硬件健康服务、RMS、REST 接口、Flow、设施事件接入 | 13 | 11 | NICo Core → 正向 DNS 域 → VLAN 与 VNI 资源池 → 机柜规格配置 → 机柜固件清单 → 站点默认凭据 → DHCP 与引导服务 → 集群级证书签发者 → 编排用数据库 → Temporal → RMS → 组件管理器 → REST 身份认证 → REST 站点 → Flow → 操作规则 → 子网 → 机柜组声明 → 机柜声明 → 设备声明 → 现场 DHCP 中继 → 设备接口与地址 → 探测结果 → 计算托盘对象 → 交换机对象 → 供电框对象 → 机柜对象 → Flow 的机柜与托盘清单 → 任务 → 健康报告 |
| 运维 › NVLink 域管理 | NICo Core、硬件健康服务、REST 接口、Flow、NMX-C | 6 | 0 | NICo Core → 正向 DNS 域 → VLAN 与 VNI 资源池 → 机柜规格配置 → 站点默认凭据 → DHCP 与引导服务 → 集群级证书签发者 → 编排用数据库 → Temporal → RMS → 组件管理器 → REST 身份认证 → REST 站点 → Flow → NMX-C 接入 → 子网 → 机柜组声明 → 机柜声明 → 设备声明 → 现场 DHCP 中继 → 设备接口与地址 → 探测结果 → 计算托盘对象 → 交换机对象 → 机柜对象 → Flow 的机柜与托盘清单 → NVLink 域 → 健康报告 |
| 运维 › 设备管理 | NICo Core | 5 | 0 | NICo Core → 正向 DNS 域 → VLAN 与 VNI 资源池 → 机柜规格配置 → 站点默认凭据 → DHCP 与引导服务 → 集群级证书签发者 → 编排用数据库 → RMS → 组件管理器 → 子网 → 设备声明 → 现场 DHCP 中继 → 设备接口与地址 → 探测结果 → 计算托盘对象 → 交换机对象 → 供电框对象 |
| 运维 › 设备管理 › 服务器 | NICo Core、DHCP 服务、RMS、REST 接口、Flow | 12 | 9 | NICo Core → 正向 DNS 域 → VLAN 与 VNI 资源池 → 机柜规格配置 → 机柜固件清单 → 站点默认凭据 → DHCP 与引导服务 → 集群级证书签发者 → 编排用数据库 → Temporal → RMS → 组件管理器 → REST 身份认证 → REST 站点 → Flow → 子网 → 机柜组声明 → 机柜声明 → 设备声明 → 现场 DHCP 中继 → 设备接口与地址 → 探测结果 → 计算托盘对象 → 交换机对象 → 机柜对象 → Flow 的机柜与托盘清单 → 任务 → 系统定义 → 默认租户与 VPC → 实例 |
| 运维 › 设备管理 › 交换机 | NICo Core、DHCP 服务、RMS、REST 接口、Flow | 6 | 5 | NICo Core → 正向 DNS 域 → VLAN 与 VNI 资源池 → 机柜规格配置 → 机柜固件清单 → 站点默认凭据 → DHCP 与引导服务 → 集群级证书签发者 → 编排用数据库 → Temporal → RMS → 组件管理器 → REST 身份认证 → REST 站点 → Flow → 子网 → 机柜组声明 → 机柜声明 → 设备声明 → 现场 DHCP 中继 → 设备接口与地址 → 探测结果 → 计算托盘对象 → 交换机对象 → 机柜对象 → Flow 的机柜与托盘清单 → 任务 |
| 运维 › 设备管理 › 供电框 | NICo Core、DHCP 服务、RMS、REST 接口、Flow | 8 | 3 | NICo Core → 正向 DNS 域 → VLAN 与 VNI 资源池 → 机柜规格配置 → 站点默认凭据 → DHCP 与引导服务 → 集群级证书签发者 → 编排用数据库 → Temporal → RMS → 组件管理器 → REST 身份认证 → REST 站点 → Flow → 子网 → 机柜组声明 → 机柜声明 → 设备声明 → 现场 DHCP 中继 → 设备接口与地址 → 探测结果 → 计算托盘对象 → 交换机对象 → 供电框对象 → 机柜对象 → Flow 的机柜与托盘清单 → 任务 |
| 运维 › 设备管理 › DPU | NICo Core | 3 | 0 | NICo Core → 正向 DNS 域 → VLAN 与 VNI 资源池 → 站点默认凭据 → DHCP 与引导服务 → 子网 → 设备声明 → 现场 DHCP 中继 → 设备接口与地址 → 探测结果 → 计算托盘对象 |
| 运维 › 健康告警 | NICo Core、硬件健康服务、设施事件接入 | 6 | 0 | NICo Core → 正向 DNS 域 → VLAN 与 VNI 资源池 → 机柜规格配置 → 站点默认凭据 → DHCP 与引导服务 → 集群级证书签发者 → 编排用数据库 → RMS → 组件管理器 → 子网 → 机柜组声明 → 机柜声明 → 设备声明 → 现场 DHCP 中继 → 设备接口与地址 → 探测结果 → 计算托盘对象 → 交换机对象 → 供电框对象 → 机柜对象 → 健康报告 |
| 运维 › 运维任务 | NICo Core、REST 接口、Flow | 1 | 1 | NICo Core → 正向 DNS 域 → VLAN 与 VNI 资源池 → 机柜规格配置 → 站点默认凭据 → DHCP 与引导服务 → 集群级证书签发者 → 编排用数据库 → Temporal → RMS → 组件管理器 → REST 身份认证 → REST 站点 → Flow → 子网 → 机柜组声明 → 机柜声明 → 设备声明 → 现场 DHCP 中继 → 设备接口与地址 → 探测结果 → 交换机对象 → 机柜对象 → Flow 的机柜与托盘清单 → 任务 |
| 运维 › 操作审计 | — | 0 | 0 | 不调用 NICo，数据由平台自己保存 |
| 交付 › 安装任务 | NICo Core、DHCP 服务、引导服务、硬件健康服务 | 10 | 2 | NICo Core → 正向 DNS 域 → VLAN 与 VNI 资源池 → 机柜规格配置 → 站点默认凭据 → DHCP 与引导服务 → 集群级证书签发者 → 编排用数据库 → RMS → 组件管理器 → 子网 → 机柜组声明 → 机柜声明 → 设备声明 → 现场 DHCP 中继 → 设备接口与地址 → 探测结果 → 计算托盘对象 → 交换机对象 → 机柜对象 → 系统定义 → 默认租户与 VPC → 实例 → 健康报告 |
| 交付 › 实例管理 | NICo Core | 2 | 1 | NICo Core → 正向 DNS 域 → VLAN 与 VNI 资源池 → 站点默认凭据 → DHCP 与引导服务 → 子网 → 设备声明 → 现场 DHCP 中继 → 设备接口与地址 → 探测结果 → 计算托盘对象 → 系统定义 → 默认租户与 VPC → 实例 |
| 接入 › 网络规划 › 子网 | NICo Core | 5 | 3 | NICo Core → 正向 DNS 域 → VLAN 与 VNI 资源池 → 子网 → 设备声明 |
| 接入 › 网络规划 › DHCP 服务 | NICo Core、DHCP 服务、监控系统 | 5 | 0 | NICo Core → 正向 DNS 域 → VLAN 与 VNI 资源池 → DHCP 与引导服务 → 子网 → 现场 DHCP 中继 → 设备接口与地址 |
| 接入 › 网络规划 › 地址分配 | NICo Core、DHCP 服务 | 2 | 0 | NICo Core → 正向 DNS 域 → VLAN 与 VNI 资源池 → DHCP 与引导服务 → 子网 → 现场 DHCP 中继 → 设备接口与地址 |
| 接入 › 设备清单 › 到货清单 | NICo Core | 7 | 0 | NICo Core → 正向 DNS 域 → VLAN 与 VNI 资源池 → 机柜规格配置 → 子网 → 机柜组声明 → 机柜声明 → 设备声明 |
| 接入 › 设备清单 › 版本记录 | — | 0 | 0 | 不调用 NICo，数据由平台自己保存 |
| 接入 › 设备发现 | NICo Core、DHCP 服务 | 12 | 6 | NICo Core → 正向 DNS 域 → VLAN 与 VNI 资源池 → 机柜规格配置 → 站点默认凭据 → DHCP 与引导服务 → 集群级证书签发者 → 编排用数据库 → RMS → 组件管理器 → 子网 → 机柜组声明 → 设备声明 → 现场 DHCP 中继 → 设备接口与地址 → 探测结果 → 计算托盘对象 → 交换机对象 → 供电框对象 |
| 配置 › 站点设置 › 站点概况 | NICo Core、RMS、REST 接口、Flow、NMX-C | 8 | 2 | NICo Core → 机柜规格配置 → 集群级证书签发者 → 编排用数据库 → Temporal → RMS → 组件管理器 → REST 身份认证 → REST 站点 → Flow → 操作规则 → NMX-C 接入 |
| 配置 › 站点设置 › 控制面 | NICo Core、RMS、REST 接口 | 3 | 0 | NICo Core → 机柜规格配置 → 集群级证书签发者 → 编排用数据库 → Temporal → RMS → REST 身份认证 → REST 站点 |
| 配置 › 固件基线 | NICo Core、RMS | 3 | 0 | NICo Core → 正向 DNS 域 → VLAN 与 VNI 资源池 → 机柜规格配置 → 站点默认凭据 → DHCP 与引导服务 → 集群级证书签发者 → 编排用数据库 → RMS → 组件管理器 → 子网 → 设备声明 → 现场 DHCP 中继 → 设备接口与地址 → 探测结果 |
| 配置 › 安装方案 | NICo Core、引导服务 | 1 | 1 | NICo Core → 系统定义 |

每个页面具体用到哪些接口，见本文末尾的“各页面用到的接口”。

## 资源依赖与准备顺序

按“先准备的在前”排列。一个页面要有数据，它用到的接口的全部前置资源都要先就位。

| 顺序 | 资源 | NICo 对象 | 怎么得到 | 依赖 | 没有真实整机柜时 | 说明 | 出处 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | NICo Core | `nico-api` | 部署 NICo Core 及其数据库和密钥库；平台用客户端证书访问 | — | 部署时配置 | Core 按证书里的服务身份做权限判断，每个接口允许哪些身份写在权限表里 | `crates/api-core/src/auth/internal_rbac_rules.rs:30` |
| 2 | 正向 DNS 域 | `Domain` | 站点配置 initial_domain_name（只在域表为空时生效），或 CreateDomain | NICo Core | 部署时配置 | 配置里的子网只有在恰好存在一个正向域时才会创建；子网没有子域时，设备拿不到 DHCP 记录 | `crates/api-core/src/db_init.rs:46` |
| 3 | VLAN 与 VNI 资源池 | `resource pool` | 站点配置；nico-admin-cli resource-pool list / grow | NICo Core | 部署时配置 | 带外管理以外的子网类型，创建时要从这两个池里各取一个值 | `crates/api-core/src/handlers/network_segment.rs:773` |
| 4 | 机柜规格配置 | `[rack_profiles]` | 写在 nico-api 的站点配置里，随部署下发；接口和命令行都不能新增 | NICo Core | 部署时配置 | 规格名由机柜组的拓扑和成员厂商推导，推导出的名字必须在这里配置过 | `crates/api-core/src/cfg/file.rs:857` |
| 5 | 机柜固件清单 | `[rack_profiles.<规格>.firmware_object]` | 站点配置里给每个机柜规格填一个固件清单的地址和访问凭据 | 机柜规格配置 | 部署时配置 | 固件操作不带版本时使用它。NICo 里没有可以命名、可以列出的“固件基线”对象 | `docs/configuration/rms.md:183` |
| 6 | 站点默认凭据 | `SiteWideBmcRoot、主机 UEFI、DPU UEFI` | InitializeSiteCredentials，或逐项 CreateCredential | NICo Core | 可直接创建 | 三项都配置后，站点发现才会去探测设备 | `crates/site-explorer/src/credentials.rs:113` |
| 7 | DHCP 与引导服务 | `nico-dhcp、nico-pxe` | 随 NICo 部署；域名服务器、时间服务器和引导服务器地址写在 DHCP 服务的部署参数里 | NICo Core | 部署时配置 | 这些参数没有读取接口，只能从部署配置里看 | `helm/charts/nico-dhcp/values.yaml:149` |
| 8 | 集群级证书签发者 | `ClusterIssuer vault-nico-issuer` | 在 Vault 里建一个签发角色并让 cert-manager 用它签发；RMS、Flow、站点代理和编排用数据库的证书都由它签，和 Core 的证书出自同一个站点 CA | NICo Core | 可直接创建 | 官方 Chart 申请的是椭圆曲线证书，签发角色要接受这种密钥。证书最长 30 天，自动续期，但 RMS 和数据库不会自动重新加载 | `helm-prereqs/templates/vault-nico-issuer.yaml:8` |
| 9 | 编排用数据库 | `nico-pg-cluster` | 单独的 PostgreSQL，按官方的名称、账号和凭据密钥提供 REST、Flow、Temporal、Keycloak、RMS 各自的库 | 集群级证书签发者 | 可直接创建 | 不和 Core 的数据库共用。REST 的库要有 pg_trgm 扩展；REST 和 Flow 的账号是超级用户，Temporal 的账号可建库 | `helm-prereqs/templates/postgresql.yaml:46` |
| 10 | Temporal | `temporal` | 官方 Chart 安装后，用它的管理工具建逻辑命名空间 cloud、site、flow，以及每个站点一个以站点 UUID 命名的 | 编排用数据库 | 可直接创建 | Flow 启动时要求 flow 这个逻辑命名空间已经存在。Temporal 自己的证书由 REST 的 CA 签发，不是站点 CA | `helm-prereqs/setup.sh:2406` |
| 11 | RMS | `Rack Management Service` | 官方 Chart rack-manager，发布名 rack，命名空间固定为 rack-manager；镜像要从公开源码自己构建。Core 配置里的 RMS 地址默认就指向它，装好后 Core 不用重启 | 机柜规格配置、集群级证书签发者、编排用数据库 | 部署时配置：RMS 本身可以在没有硬件时部署并连通；要让它有设备可管，需要 RMS 模拟服务或真实机柜 | 任一后端选了 rms，启动时就要求机柜规格配置里有产品系列和厂商 | `docs/configuration/rms.md:243` |
| 12 | 组件管理器 | `[component_manager]` | 站点配置里为计算托盘、交换机、供电框各选一个后端，默认都是 rms | RMS | 部署时配置 | 没有这段配置时，设备电源、复位、固件接口返回未实现。当前生效的后端没有读取接口 | `crates/api-core/src/handlers/component_manager.rs:130` |
| 13 | REST 身份认证 | `JWT 签发方与声明映射` | REST 的部署配置：外部签发方或内置 Keycloak，二选一；从声明映射出组织名和角色 | — | 部署时配置 |  | `rest-api/openapi/auth.md:43` |
| 14 | REST 站点 | `Infrastructure Provider、Site、站点代理` | 官方 Chart nico-rest 和 nico-rest-site-agent，命名空间 nico-rest。在 REST 的库里登记站点，站点代理安装时向站点管理服务换取一次性口令完成握手；之后清单上报，站点由 Pending 变为 Registered | NICo Core、REST 身份认证、Temporal、集群级证书签发者 | 可直接创建 | 机柜、托盘、域和任务接口都要带 siteId。站点代理上线后回报是否启用了 Flow | `rest-api/INSTALLATION.md:773` |
| 15 | Flow | `nico-flow` | 官方 Chart nico-flow，发布名 flow，命名空间固定为 flow；镜像要自己构建，并且和 Core 出自同一个源码提交。站点代理打开 Flow 开关后经它转发 | REST 站点、组件管理器、Temporal | 部署时配置 | REST 经 Temporal 和站点代理转发到 Flow。直接访问 Flow 要用双向证书，并且身份在允许名单里 | `docs/architecture/flow.md:3` |
| 16 | 操作规则 | `OperationRule` | 默认规则写在 Flow 的代码里；自定义规则用 POST /task/rule 创建，只有电源和固件两类 | Flow | NICo 自动生成 | 选用顺序：请求里指定的规则、机柜关联的规则、该类操作的全局默认、内置规则 | `docs/operations/flow/operation-rules.md:553` |
| 17 | NMX-C 接入 | `NvlinkNmxcEndpoint` | 机柜里的设备不需要登记：Core 取机柜里第一台就绪且 Fabric Manager 已配置的交换机的 NVOS 地址，端口 9370。只有不属于任何机柜的设备才用 CreateNvlinkNmxcEndpoint 登记（机箱序列号和地址） | NICo Core | 可直接创建：NMX-C 运行在交换机上，由 RMS 配置；没有交换机时只能接 NMX-C 模拟服务 | 没有专门的状态接口，只能从机柜健康报告里的 NmxcUnreachable 判断。交换机要先由 RMS 配好，Core 才找得到 NMX-C | `crates/nvlink-manager/src/nmx_c_endpoint.rs:102` |
| 18 | 子网 | `NetworkSegment` | 站点配置 [networks.<名称>] 在启动时创建并直接就绪；或 CreateNetworkSegment，创建后由控制器从 Provisioning 转为 Ready | 正向 DNS 域、VLAN 与 VNI 资源池 | 可直接创建 | 没有修改接口。创建后只能给带外管理子网补另一个地址族、改 IPv4 的 DHCP 地址池、改 VPC 挂接；配置文件后续的修改不会更新已创建的子网 | `crates/rpc/proto/forge.proto:129` |
| 19 | 机柜组声明 | `ExpectedRackGroup` | AddExpectedRackGroup：拓扑、协议、每个机柜及其成员的类型和厂商 | NICo Core | 可直接创建 | 成员只是（类型、厂商、编号）三元组，只用于推导机柜规格，不与设备声明关联 | `crates/rpc/proto/forge.proto:3528` |
| 20 | 机柜声明 | `ExpectedRack` | AddExpectedRack：只需机柜 ID；规格和所属机柜组由 NICo 推导 | 机柜组声明、机柜规格配置 | 可直接创建 | 要求恰好一个机柜组包含这个机柜 ID，且该机柜至少有一个计算成员和一个交换机成员 | `crates/api-core/src/handlers/expected_rack.rs:29` |
| 21 | 设备声明 | `ExpectedMachine / ExpectedSwitch / ExpectedPowerShelf` | 逐条新增或批量新增：BMC MAC、序列号、机柜 ID、出厂凭据；交换机另需 NVOS 管理口 | NICo Core | 可直接创建 | 新增时不校验机柜、子网和凭据是否存在；机柜 ID 是自由文本 | `crates/api-core/src/handlers/expected_machine.rs:77` |
| 22 | NVLink 域声明 | `ExpectedNvLinkDomain` | CreateExpectedNvLinkDomain：机柜组 ID 和成员的 BMC MAC；创建后不可修改，只能删除重建 | 机柜组声明、设备声明 | 可直接创建 | 每个 MAC 必须对应机柜组内某个机柜里的计算托盘或交换机声明，且至少各有一个 | `crates/api-db/src/expected_nvlink_domain.rs:19` |
| 23 | 现场 DHCP 中继 | `—` | 现场网络设备把各管理网段的 DHCP 请求中继到 NICo 的 DHCP 服务 | 子网、DHCP 与引导服务 | 只有真实硬件才有：模拟器直接带着中继地址调用 Core，不经过真实网络 | NICo 按中继地址落在哪个子网前缀里来选子网，不看网关 | `crates/api-core/src/dhcp/discover.rs:563` |
| 24 | 设备接口与地址 | `MachineInterface` | 设备发出 DHCP 请求时由 Core 创建；声明了固定地址的接口由站点发现预先创建 | 现场 DHCP 中继 | 需要模拟器或真实硬件 | 没有声明的设备也会拿到地址，留下一条没有归属的接口记录 | `crates/api-core/src/dhcp/discover.rs:716` |
| 25 | 探测结果 | `ExploredEndpoint` | 站点发现按周期用 Redfish 探测带外管理子网上的接口 | 设备接口与地址、站点默认凭据、设备声明 | 需要模拟器或真实硬件 | 主机 BMC 要用设备声明里的出厂凭据，没有声明就报缺少凭据；一次认证失败后停止重试，直到清除错误 | `crates/site-explorer/src/bmc_endpoint_explorer.rs:445` |
| 26 | 计算托盘对象 | `Machine（主机）` | 站点发现在预检完成、主机与 DPU 配对成功后创建，随后由状态机推进到 Ready | 探测结果 | 需要模拟器或真实硬件 | 设备声明带暂停标记时要先放行；开启度量启动时还要人工批准 | `crates/site-explorer/src/lib.rs:3234` |
| 27 | DPU 对象 | `Machine（类型 DPU）` | DPU 的 BMC 被探测到并与主机配对后，随主机一起创建 | 探测结果 | 需要模拟器或真实硬件 | DPU 不需要设备声明，用出厂凭据探测；与主机按序列号配对 | `crates/site-explorer/src/lib.rs:1196` |
| 28 | 交换机对象 | `Switch` | 站点发现探测到与交换机声明匹配的 BMC 后创建 | 探测结果、组件管理器 | 需要模拟器或真实硬件 | 需要声明里的 NVOS 管理口 MAC 和主口，且该管理口已拿到地址，否则状态机进入 Error；随后的证书和口令配置经过硬件后端 | `crates/switch-controller/src/initializing.rs:48` |
| 29 | 供电框对象 | `PowerShelf` | 站点发现探测到与供电框声明匹配的 PMC 后创建 | 探测结果 | 需要模拟器或真实硬件 |  | `crates/site-explorer/src/inventory_creator/power_shelf_creator.rs:121` |
| 30 | 机柜对象 | `Rack` | 某个成员设备被接管时，如果它的机柜声明存在，由站点发现创建；没有创建接口 | 机柜声明、交换机对象 | NICo 自动生成 | 状态机只看交换机数量：发现的交换机数达到规格要求进入 Discovering，就绪的交换机数达到要求进入 Maintenance。计算托盘和供电框的数量不是条件 | `docs/architecture/state_machines/rackstatemachine.md:142` |
| 31 | Flow 的机柜与托盘清单 | `Rack / Tray（REST）` | Flow 从 Core 同步机柜、设备和设备声明 | Flow、机柜对象 | NICo 自动生成 | REST 的机柜、托盘、域读的是这份清单，不是直接读 Core。单个机柜的操作按外部 ID 定位，批量操作按机柜名定位 | `rest-api/api/pkg/api/handler/rack.go:154` |
| 32 | 任务 | `Task` | 机柜、托盘、域的每个写操作都返回任务编号，每个机柜一个任务 | Flow 的机柜与托盘清单 | NICo 自动生成 | REST 的返回只表示任务已创建。要轮询任务直到成功、失败或终止 | `rest-api/openapi/spec.yaml:28731` |
| 33 | NVLink 域 | `NVLinkDomain（REST）、nvlink_domain_uuid（Core）` | REST 的域编号就是机柜组编号；Core 一侧在机柜上线配置好 NMX-C 集群后，在交换机和计算托盘上回报域 UUID | 机柜组声明、Flow 的机柜与托盘清单、NMX-C 接入 | 需要模拟器或真实硬件 |  | `rest-api/openapi/spec.yaml:27724` |
| 34 | 系统定义 | `OperatingSystem` | CreateOperatingSystem：直接给 iPXE 脚本，或选一个内置 iPXE 模板并填参数和制品地址 | NICo Core | 可直接创建 | 脚本方式创建后立即可用。模板方式里标为“只用缓存”的制品，要由外部程序下载后回填缓存地址，系统定义才变为可用；NICo 不下载制品 | `docs/configuration/templated-ipxe-operating-systems.md:263` |
| 35 | 默认租户与 VPC | `Tenant、Vpc` | 平台只用一个默认租户。CreateTenant、CreateVpc。计算托盘的 DPU 处于 DPU 模式时用 FNN 或 ETHERNET_VIRTUALIZER，网卡模式或没有 DPU 时用 FLAT | NICo Core | 可直接创建 | Core 的权限表只允许站点代理（以及模拟器）调用这两个创建接口，管理端证书不能调用 | `crates/api-core/src/auth/internal_rbac_rules.rs:75` |
| 36 | 实例 | `Instance` | AllocateInstances：每个实例一个机器 ID，加实例配置（默认租户和主机名、系统、网络） | 计算托盘对象、系统定义、默认租户与 VPC | 需要模拟器或真实硬件 | 托盘必须是 Ready，没有维护标记、阻止分配的告警、待处理的实例或退役。机柜的健康报告会并入柜内每台主机的健康，所以机柜上阻止分配的告警会挡住整柜 | `crates/api-model/src/machine/mod.rs:543` |
| 37 | 健康报告 | `HealthReport` | 硬件健康服务、DPU 代理、站点发现和设施事件消费者写入；也可以用 Insert…HealthReport 手工写入一条 | 计算托盘对象 | 可直接创建：设备对象存在后，可以手工写入报告来验证页面：nico-admin-cli machine health-report add |  | `crates/api-core/src/handlers/health.rs:98` |
| 38 | 设施事件接入 | `nico-dsx-exchange-consumer` | 部署事件消费者并连到楼宇管理系统的消息总线；泄漏事件被写成机柜的健康报告 | 机柜对象 | 部署时配置 | 消费者是否连上没有读取接口，只有它自己的指标和存活探针 | `crates/dsx-exchange-consumer/src/health_updater.rs:184` |

## 接口：站点与依赖

| 接口 | 类型 | 命令行 | 请求参数 | 用到的字段 | 前置资源 | 执行方 | 使用的页面 | 证据 | 实测 | 说明 | 出处 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `Version` | Core gRPC · 读 | `nico-admin-cli version --show-runtime-config` | display_config 为真时带回运行配置 | build_version、git_sha、capabilities[]、runtime_config.dhcp_servers、runtime_config.networks、runtime_config.initial_domain_name、runtime_config.attestation_enabled | NICo Core | Core | 配置 › 站点设置 › 站点概况；配置 › 站点设置 › 控制面；接入 › 网络规划 › DHCP 服务 | 调用；现有产品已调用 | 返回 build_version（形如 0.0.0-main-<提交号>）、build_date、git_sha、rust_version、capabilities 和 runtime_config。运行配置里有 dhcp_servers、networks、initial_domain_name、site_fabric_prefixes、attestation_enabled | 运行配置里没有时间服务器、组件管理器后端和配额执行方式 | `forge.proto:36` |
| `GetRmsVersion` | Core gRPC · 读 | `nico-admin-cli backend rms status` | — | status、message、version | RMS | Core → RMS | 配置 › 站点设置 › 站点概况；配置 › 站点设置 › 控制面 | 调用；现有产品已调用 | RMS 部署之前 Core 的配置就指向它；部署后返回 status: connected 和 RMS 的版本号，Core 没有重启。命令行的输出是 status、message、version 三项 | 没有配置 RMS 时返回 UNAVAILABLE；30 秒超时。命令行只有在连通时退出码才是 0 | `crates/api-core/src/handlers/rms.rs:75` |
| `GET /site、GET /site/{id}` | REST · 读 | `nicocli site list` | — | id、status（Pending、Registered、Error）、isOnline、siteAgentVersion、siteControllerVersion、capabilities.flow、machineStats | REST 站点 | REST | 配置 › 站点设置 › 站点概况；配置 › 站点设置 › 控制面 | 调用 | 返回 200。字段与这里一致：id、name、org、status、isOnline、siteAgentVersion、siteControllerVersion、machineStats，以及 capabilities 下的 flow 等七项。站点登记后先是 Pending，站点代理上报清单后约 5 分钟变为 Registered | Flow 是否可用只能从这里的 capabilities.flow 看，Core 没有对应接口 | `spec.yaml:946` |
| `GetSiteCredentialReadiness` | Core gRPC · 读 | — | — | configured[]、missing[]、requires_recovery[] | NICo Core | Core | 配置 › 站点设置 › 站点概况 | 定义；现有产品已调用 | — |  | `forge.proto:589` |
| `InitializeSiteCredentials / CreateCredential` | Core gRPC · 写 | `nico-admin-cli credential add-bmc；nico-admin-cli credential add-uefi` | generate_missing，或逐项给 BMC、主机 UEFI、DPU UEFI 口令 | — | NICo Core | Core | 配置 › 站点设置 › 站点概况 | 定义；现有产品已调用 | — | 口令经标准输入或安全文件传入，不出现在命令行和日志里 | `forge.proto:586` |
| `GetSiteExplorerLastRun` | Core gRPC · 读 | — | — | started_at、finished_at、success、error、endpoint_explorations、endpoint_explorations_success、endpoint_explorations_failed、failure_category、last_successful_finished_at | NICo Core | Core | 配置 › 站点设置 › 站点概况；接入 › 设备发现 | 定义；现有产品已调用 | — |  | `site_explorer.proto:112` |
| `SetDynamicConfig` | Core gRPC · 写 | — | SITE_EXPLORER_ENABLED、CREATE_MACHINES | — | NICo Core | Core | 配置 › 站点设置 › 站点概况 | 定义 | — | 创建交换机和供电框的开关只在配置文件里，不能在运行时改 | `forge.proto:502` |
| `ListRackProfiles / GetRackProfile` | Core gRPC · 读 | `nico-admin-cli rack profile list；nico-admin-cli rack profile show <RACK_ID>` | — | rack_profile_id、profile.rack_hardware_topology、profile.capabilities.{compute,switch,power_shelf}.count、profile.product_family | 机柜规格配置 | Core | 配置 › 站点设置 › 站点概况；接入 › 设备清单 › 到货清单；运维 › 机柜管理 › 机柜详情；配置 › 固件基线 | 调用 | 返回 14 个机柜规格。每个有 rack_profile_id 和 profile 下的 rack_hardware_type、rack_hardware_topology、rack_hardware_class、capabilities、product_family | 从运行配置读出；只允许管理端证书调用 | `crates/api-core/src/handlers/rack.rs:511` |
| `GET /task/rule` | REST · 读 | `nicocli rule list --site-id <SITE>` | siteId 必填；operationType 可选（PowerControl、FirmwareControl） | id、name、operationType、operationCode、isDefault、ruleDefinition.steps[] | 操作规则 | Flow | 配置 › 站点设置 › 站点概况 | 调用 | 新装的环境返回 200 和空列表，内置的默认规则确实不在里面 | 只返回存进数据库的规则；内置的默认规则不在列表里 | `spec.yaml:14592` |
| `ListNvlinkNmxcEndpoints` | Core gRPC · 读 | `nico-admin-cli nvlink-nmxc-endpoints` | — | chassis_serial、endpoint | NMX-C 接入 | Core | 配置 › 站点设置 › 站点概况 | 定义 | — |  | `forge.proto:1116` |

## 接口：网络与地址

| 接口 | 类型 | 命令行 | 请求参数 | 用到的字段 | 前置资源 | 执行方 | 使用的页面 | 证据 | 实测 | 说明 | 出处 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `FindNetworkSegmentIds → FindNetworkSegmentsByIds` | Core gRPC · 读 | `nico-admin-cli network-segment show` | include_num_free_ips 为真才返回空闲地址数 | id、metadata.name、config.segment_type、config.mtu、config.subdomain_id、config.prefixes[].{prefix,gateway,reserve_first,free_ip_count_v2}、status.lifecycle.state | 子网 | Core | 接入 › 网络规划 › 子网；接入 › 网络规划 › DHCP 服务；接入 › 设备清单 › 到货清单；运维 › 设备管理 › 服务器 | 调用；现有产品已调用 | 返回 2 个子网。每个有 id、config、status、metadata 和创建、更新、删除时间。config 和 status 里面的字段没有逐项核对 | 类型：TENANT、ADMIN、UNDERLAY、HOST_INBAND | `forge.proto:129` |
| `CreateNetworkSegment / CreateNetworkSegmentWithDhcpRange` | Core gRPC · 写 | `nico-admin-cli network-segment create --name --segment-type --prefix --gateway --reserve-first --mtu --subdomain-id` | prefixes 必填（每个地址族至多一个，各含 prefix、gateway、reserve_first）、segment_type 必填；name、mtu、subdomain_id 可选。带地址池的接口另需 range{start,end} | — | 正向 DNS 域、VLAN 与 VNI 资源池 | Core | 接入 › 网络规划 › 子网 | 定义；现有产品已调用 | — | 前缀不能与已有子网重叠。接口不强制子域，但没有子域的子网发不出 DHCP 记录，平台要自己把它当必填 | `crates/rpc/src/model/network_segment.rs:78` |
| `DeleteNetworkSegment` | Core gRPC · 写 | `nico-admin-cli network-segment delete` | id | — | 子网 | Core | 接入 › 网络规划 › 子网 | 定义；现有产品已调用 | — | 进入 Deleting，先等已分配的地址清空再删除 | `crates/api-core/src/handlers/network_segment.rs:523` |
| `FindNetworkSegmentDhcpRanges` | Core gRPC · 读 | — | 子网 ID 列表 | segment_id、prefix、range.{start,end}、revision | 子网 | Core | 接入 › 网络规划 › 子网；接入 › 网络规划 › DHCP 服务 | 定义；现有产品已调用 | — | 命令行没有对应命令 | `forge.proto:148` |
| `SetNetworkSegmentDhcpRange` | Core gRPC · 写 | — | segment_id 必填；range 省略表示清除；if_revision 填上次读到的修订号，0 表示还没有地址池 | range.{start,end}、revision | 子网 | Core | 接入 › 网络规划 › 子网 | 定义；现有产品已调用 | — | 只对有且只有一个 IPv4 前缀的 ADMIN、UNDERLAY、HOST_INBAND 子网有效；已有动态地址落在新范围之外时拒绝。命令行没有对应命令 | `forge.proto:149` |
| `FindInterfaces` | Core gRPC · 读 | `nico-admin-cli machine-interfaces show` | id 或 ip；都不填返回全部 | id、mac_address、address[]、segment_id、hostname、vendor、last_dhcp、machine_id、switch_id、power_shelf_id、association_type、interface_type、primary_interface | 设备接口与地址 | Core | 接入 › 网络规划 › DHCP 服务；接入 › 网络规划 › 地址分配；接入 › 设备发现；运维 › 设备管理 › 服务器；交付 › 安装任务 | 调用；现有产品已调用 | 返回 8 个接口。字段与这里一致，另外还有 is_bmc、attached_dpu_machine_id、domain_id、created | 没有租约到期时间。association_type 为 NONE 的就是拿到地址但没有归属的设备 | `forge.proto:318` |
| `FindInterfaceAddresses / FindIpAddress` | Core gRPC · 读 | `nico-admin-cli machine-interfaces show-addresses；nico-admin-cli ip find <IP>` | — | addresses[].{address,allocation_type}、matches[].{ip_type,owner_id,message} | 设备接口与地址 | Core | 接入 › 网络规划 › 地址分配；运维 › 设备管理 › 服务器；运维 › 设备管理 › 交换机；运维 › 设备管理 › 供电框；交付 › 安装任务 | 定义；现有产品已调用 | — | 按地址反查归属：地址可能属于设备接口、BMC、实例、资源池或子网本身 | `forge.proto:315` |
| `carbide_dhcp_requests_total、carbide_dhcp_dropped_requests_total、carbide_dhcp_replies_sent_total、carbide_available_ips_count` | 指标 · 读 | — | — | message_type、reason、name、type、prefix | DHCP 与引导服务 | 监控系统 | 接入 › 网络规划 › DHCP 服务 | 定义 | — | DHCP 的请求计数只按报文类型和丢弃原因分，不按子网或中继分；空闲地址数按子网前缀分 | `crates/dhcp-server/src/metrics.rs:495` |

## 接口：设备清单

| 接口 | 类型 | 命令行 | 请求参数 | 用到的字段 | 前置资源 | 执行方 | 使用的页面 | 证据 | 实测 | 说明 | 出处 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `GetAllExpectedRackGroups` | Core gRPC · 读 | `nico-admin-cli expected-rack-group show` | — | rack_group_id、topology、protocol、racks[].rack_id、racks[].members[].{type,manufacturer,id} | 机柜组声明 | Core | 接入 › 设备清单 › 到货清单 | 调用 | 调用成功，没有机柜组，字段没法核对 |  | `forge.proto:746` |
| `AddExpectedRackGroup / UpdateExpectedRackGroup / DeleteExpectedRackGroup` | Core gRPC · 写 | `nico-admin-cli expected-rack-group add [--rack <JSON>]... <RACK_GROUP_ID> <PROTOCOL> <TOPOLOGY>` | rack_group_id、topology 必填；protocol、racks、metadata 可选。更新是整条替换 | — | NICo Core | Core | 运维 › 机柜管理 › 机柜详情 | 定义 | — | 有 NVLink 域声明引用时，不能改 racks，也不能删除 | `forge.proto:737` |
| `GetAllExpectedRacks` | Core gRPC · 读 | `nico-admin-cli expected-rack show` | — | rack_id、rack_profile_id、rack_group_id、metadata | 机柜声明 | Core | 接入 › 设备清单 › 到货清单；运维 › 机柜管理 | 调用；现有产品已调用 | 调用成功，没有机柜声明，字段没法核对 |  | `forge.proto:719` |
| `AddExpectedRack / UpdateExpectedRack / DeleteExpectedRack` | Core gRPC · 写 | `nico-admin-cli expected-rack add [--label K:V] <RACK_ID>` | rack_id 必填；metadata 可选。规格和机柜组是输出字段，写入时忽略 | — | 机柜组声明、机柜规格配置 | Core | 运维 › 机柜管理 › 机柜详情 | 定义 | — | 推导失败返回 INVALID_ARGUMENT 并说明原因：没有机柜组包含它、多个机柜组包含它、缺计算或交换机成员、规格未配置 | `expected_rack.rs:29` |
| `GetAllExpectedMachines / GetAllExpectedMachinesLinked` | Core gRPC · 读 | `nico-admin-cli expected-machine show` | — | chassis_serial_number、bmc_mac_address、rack_id、bmc_ip_address、host_nics[]、metadata.labels、linked: interface_id、explored_endpoint_address、machine_id | 设备声明 | Core | 接入 › 网络规划 › 子网；接入 › 设备清单 › 到货清单；接入 › 设备发现；运维 › 设备管理 › DPU | 调用；现有产品已调用 | 返回 1 条声明。这个版本里网口列表的字段名是 interfaces，不是 host_nics；另有 sku_id、dpu_mode、bmc_ip_allocation、server_name、default_pause_ingestion_and_poweron 等。读取结果里带着 bmc_username 和 bmc_password。带关联关系的读取没有核对 | 带关联的读取一次给出每条声明走到了哪一步：有没有接口、有没有探测结果、有没有设备对象。读取结果里带着 BMC 的用户名和口令，后端不能把它们传给前端，也不能写进日志 | `forge.proto:646` |
| `CreateExpectedMachines / UpdateExpectedMachines / PatchExpectedMachine / DeleteExpectedMachine` | Core gRPC · 写 | `nico-admin-cli expected-machine add -a <BMC_MAC> -u <BMC_USER> -p <BMC_PASS> -s <SERIAL> [--rack_id] [--bmc-ip-address] [--interfaces] [--label]` | bmc_mac_address、chassis_serial_number 必填（序列号 4–32 位字母数字下划线连字符）；rack_id、bmc_ip_address、host_nics、metadata 可选。批量接口带 accept_partial_results | — | NICo Core | Core | 接入 › 设备发现；运维 › 机柜管理 › 机柜详情 | 定义；现有产品已调用 | — | 不要用 ReplaceAllExpectedMachines 做增量导入：它替换整张表 | `forge.proto:8268` |
| `GetAllExpectedSwitches / GetAllExpectedSwitchesLinked` | Core gRPC · 读 | `nico-admin-cli expected-switch show` | — | switch_serial_number、bmc_mac_address、nvos_interfaces[]、rack_id、linked: switch_id、explored_endpoint_address | 设备声明 | Core | 接入 › 网络规划 › 子网；接入 › 设备清单 › 到货清单；接入 › 设备发现 | 调用；现有产品已调用 | 调用成功，没有交换机声明，字段没法核对 |  | `forge.proto:701` |
| `AddExpectedSwitch / PatchExpectedSwitch / DeleteExpectedSwitch` | Core gRPC · 写 | `nico-admin-cli expected-switch add -a <BMC_MAC> -u <USER> -p <PASS> -s <SERIAL> --nvos-interface <MAC[,primary]> [--rack_id]` | bmc_mac_address 必填；nvos_interfaces 至少一个，多于一个时恰好一个为主口；NVOS 用户名和口令要么都填要么都不填 | — | NICo Core | Core | 接入 › 设备发现；运维 › 机柜管理 › 机柜详情 | 定义 | — |  | `forge.proto:691` |
| `GetAllExpectedPowerShelves / GetAllExpectedPowerShelvesLinked` | Core gRPC · 读 | `nico-admin-cli expected-power-shelf show` | — | shelf_serial_number、bmc_mac_address、rack_id、linked: power_shelf_id、explored_endpoint_address | 设备声明 | Core | 接入 › 网络规划 › 子网；接入 › 设备清单 › 到货清单；接入 › 设备发现；运维 › 设备管理 › 供电框 | 调用；现有产品已调用 | 调用成功，没有供电框声明，字段没法核对 |  | `forge.proto:681` |
| `AddExpectedPowerShelf / PatchExpectedPowerShelf / DeleteExpectedPowerShelf` | Core gRPC · 写 | `nico-admin-cli expected-power-shelf add -a <BMC_MAC> -u <USER> -p <PASS> -s <SERIAL> [--rack_id]` | bmc_mac_address 必填；序列号、rack_id、bmc_ip_address 可选 | — | NICo Core | Core | 接入 › 设备发现；运维 › 机柜管理 › 机柜详情 | 定义 | — |  | `forge.proto:671` |
| `CreateExpectedNvLinkDomain / DeleteExpectedNvLinkDomain / FindExpectedNvLinkDomainIds` | Core gRPC · 写 | `nico-admin-cli expected-nvlink-domain create --member <MAC>... [--name] <RACK_GROUP_ID>` | rack_group_id、member_bmc_mac_addresses 必填 | — | 机柜组声明、设备声明 | Core | 接入 › 设备发现 | 定义 | — | REST 规范里没有对应的端点 | `forge.proto:725` |

## 接口：设备发现

| 接口 | 类型 | 命令行 | 请求参数 | 用到的字段 | 前置资源 | 执行方 | 使用的页面 | 证据 | 实测 | 说明 | 出处 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `FindExploredEndpointIds → FindExploredEndpointsByIds` | Core gRPC · 读 | `nico-admin-cli site-explorer get-report endpoint` | — | address、report.endpoint_type、report.vendor、report.systems[].serial_number、report.chassis[].serial_number、report.last_exploration_error_schema.{error_code,mitigation,text}、report.firmware_versions、preingestion_state、pause_remediation | 探测结果 | Core | 接入 › 设备发现；运维 › 设备管理；运维 › 设备管理 › DPU | 调用；现有产品已调用 | 返回 6 个探测结果。字段与这里一致：address、report（endpoint_type、vendor、systems、chassis、firmware_versions、last_exploration_error_schema 等）、preingestion_state、pause_remediation | 探测结果的编号就是 BMC 的 IP 地址 | `site_explorer.proto:53` |
| `FindExploredManagedHostIds → FindExploredManagedHostsByIds` | Core gRPC · 读 | `nico-admin-cli site-explorer get-report managed-host` | — | host_bmc_ip、dpus[].{bmc_ip,host_pf_mac_address} | 探测结果 | Core | 接入 › 设备发现 | 调用 | 返回 1 组配对。字段是 host_bmc_ip、dpu_bmc_ip、host_pf_mac_address、dpus | 主机与 DPU 的配对结果 | `site_explorer.proto:84` |
| `GetAllUnexpectedMachines` | Core gRPC · 读 | — | — | address、bmc_mac_address、machine_id | 探测结果 | Core | 接入 › 设备发现 | 定义 | — | 只列出探测成功、类型是主机 BMC、MAC 不在任何声明里的设备。探测失败的未声明设备不在这里；命令行没有对应命令 | `crates/api-db/src/expected_machine.rs:283` |
| `ReExploreEndpoint / RefreshEndpointReport / ClearSiteExplorationError` | Core gRPC · 写 | `nico-admin-cli site-explorer re-explore；nico-admin-cli site-explorer refresh；nico-admin-cli site-explorer clear-error` | ip_address | — | 探测结果 | Core | 接入 › 设备发现 | 定义 | — | 重新探测排到下一轮；刷新立即探测并保存；认证失败之后要先清除错误才会再试 | `forge.proto:390` |
| `DetermineMachineIngestionState` | Core gRPC · 读 | `nico-admin-cli managed-host power-options get-machine-ingestion-state --mac-address <MAC>` | mac_address 必填 | NotDiscovered、WaitingForIngestion、IngestionMachineNotCreated、IngestionMachineCreated | 设备声明 | Core | 接入 › 设备发现；交付 › 安装任务 | 定义；现有产品已调用 | — |  | `crates/api-core/src/handlers/power_options.rs:143` |
| `AllowIngestionAndPowerOn` | Core gRPC · 写 | `nico-admin-cli managed-host power-options allow-ingestion-and-power-on --mac-address <MAC>` | mac_address 必填 | — | 探测结果 | Core | 接入 › 设备发现；交付 › 安装任务 | 定义；现有产品已调用 | — | 只对设备声明里带暂停标记的主机有意义 | `crates/api-core/src/handlers/power_options.rs:213` |

## 接口：机柜与 NVLink 域

| 接口 | 类型 | 命令行 | 请求参数 | 用到的字段 | 前置资源 | 执行方 | 使用的页面 | 证据 | 实测 | 说明 | 出处 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `FindRackIds → FindRacksByIds` | Core gRPC · 读 | `nico-admin-cli rack list；nico-admin-cli rack show <RACK_ID>` | — | id、rack_group_id、status.lifecycle.{state,state_reason}、status.health、status.health_sources、metadata、created、updated | 机柜对象 | Core | 运维 › 机柜管理；运维 › 机柜管理 › 机柜详情；运维 › 健康告警；交付 › 安装任务 | 调用；现有产品已调用 | 调用成功，没有机柜。没有数据时命令行即使指定 JSON 格式也只输出一行文字，后端解析时要单独处理 | 机柜对象不带规格和成员列表：规格另读，成员按机柜 ID 去各类设备里筛 | `forge.proto:9860` |
| `FindRackStateHistories` | Core gRPC · 读 | `nico-admin-cli rack state-history <RACK_ID>` | — | histories[rack_id].records[].{state,version,time} | 机柜对象 | Core | 运维 › 机柜管理 › 机柜详情 | 定义；现有产品已调用 | — |  | `forge.proto:331` |
| `GET /rack、GET /rack/{id}` | REST · 读 | `nicocli rack list --site-id <SITE>` | siteId 必填；includeComponents、name、分页可选 | id、name、operationStatus、operationStatusDetails.trayCountsByType、nvLinkDomainIds、taskStats.{pendingTaskCount,activeTaskCount}、health、components[] | Flow 的机柜与托盘清单 | Flow | 运维 › 机柜管理；运维 › 机柜管理 › 机柜详情 | 调用 | 返回 200 和空列表（环境里没有机柜），字段没法核对 | 站点没有启用 Flow 时返回 412 | `spec.yaml:13522` |
| `GET /rack/{id}/validation、GET /rack/validation` | REST · 读 | `nicocli rack validate --site-id <SITE>` | siteId 必填 | diffs[].{type,id,macAddress,fieldDiffs}、totalDiffs、missingCount、unexpectedCount、mismatchCount、matchCount | Flow 的机柜与托盘清单、设备声明 | Flow | 运维 › 机柜管理 › 机柜详情 | 调用 | 返回 200，结构是 diffs、totalDiffs、missingCount、unexpectedCount、mismatchCount、matchCount，与这里一致。没有机柜时各计数都是 0 | 差异类型：Missing、Unexpected、Mismatch。按 BMC MAC 比对，不比对序列号 | `spec.yaml:13745` |
| `GET /tray、GET /tray/{id}` | REST · 读 | `nicocli tray list --site-id <SITE> --rack-id <RACK>` | siteId 必填；rackId 或 rackName、type、slotId 可选 | id、type（Compute、NVSwitch、PowerShelf）、position.{slotId,trayIdx,hostId}、firmwareVersion、powerState、operationStatus、leakStatus、bmcs、rackId、nvLinkDomainId、taskStats、health | Flow 的机柜与托盘清单 | Flow | 运维 › 机柜管理 › 机柜详情；运维 › 设备管理 › 供电框 | 调用 | 返回 200，列表和单个都调用过。字段与这里完全一致，包括 position 下的 slotId、trayIdx、hostId，以及 bmcs、nvosPorts、rackId、nvLinkDomainId、taskStats、health、leakHandlingStatus。列表里有一台不属于任何机柜的普通服务器，类型是 Compute | 机柜立面要的槽位在这里；Core 的供电框对象没有位置字段。不属于任何机柜的普通服务器也在这个列表里 | `spec.yaml:14412` |
| `GET /domain/nvlink、GET /domain/nvlink/{id}` | REST · 读 | `nicocli domain list --site-id <SITE>` | siteId 必填；includeComponents 可选 | id（等于机柜组编号）、name、nmxcClusterId、topology、operationStatus、components | NVLink 域 | Flow | 运维 › NVLink 域管理 | 调用 | 返回 200 和空列表，字段没法核对 | nicocli 的子命令名由接口规范生成，这里的写法没有实际运行核对 | `spec.yaml:13335` |
| `ListNVLinkDomainHealthReports` | Core gRPC · 读 | — | — | health_report_entries[] | NVLink 域 | Core | 运维 › NVLink 域管理 | 定义 | — | 按 NMX-C 的域编号记录，不是按机柜组编号 | `forge.proto:262` |
| `FindNVLinkPartitionIds → FindNVLinkPartitionsByIds` | Core gRPC · 读 | — | — | id、name、nmx_m_id、domain_uuid、logical_partition_id | NVLink 域 | Core | 运维 › NVLink 域管理 | 定义 | — | 要先在 Core 的配置里启用 NVLink 分区 | `forge.proto:1294` |
| `FindNVLinkLogicalPartitionIds → FindNVLinkLogicalPartitionsByIds` | Core gRPC · 读 | — | — | id、config.metadata.name、config.tenant_organization_id、status.state、created | NVLink 域 | Core | 运维 › NVLink 域管理 | 定义 | — | 创建、修改、删除分区属于交付，这一页只读 | `forge.proto:1300` |

## 接口：设备读取

| 接口 | 类型 | 命令行 | 请求参数 | 用到的字段 | 前置资源 | 执行方 | 使用的页面 | 证据 | 实测 | 说明 | 出处 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `FindMachineIds → FindMachinesByIds` | Core gRPC · 读 | `nico-admin-cli machine show [--hosts]` | 筛选：rack_id、include_dpus、exclude_hosts、only_maintenance、only_quarantine、only_with_health_alert；include_history 带回状态事件 | id、rack_id、placement_in_rack.{slot_number,tray_index}、state、state_reason.{outcome,outcome_msg}、state_sla.time_in_state_above_sla、status.health.alerts[]、bmc.{ip,mac}、status.bmc_status.firmware_version、status.discovery_info.dmi_data.chassis_serial、status.associated_dpu_machine_ids、config.maintenance_reference、status.quarantine、status.nvlink_info.domain_uuid、status.lldp_neighbors[]、inventory.components[] | 计算托盘对象 | Core | 接入 › 设备发现；运维 › 机柜管理 › 机柜详情；运维 › 设备管理 › 服务器；运维 › 设备管理；运维 › 设备管理 › DPU；运维 › 健康告警；交付 › 安装任务；交付 › 实例管理 | 调用；现有产品已调用 | 返回 1 台主机。顶层字段与这里一致：id、state、state_reason、state_sla、rack_id、placement_in_rack、bmc、config、status、inventory、metadata、version。config 和 status 里面的字段没有逐项核对 | 没有电源状态和实例字段，这两项另读。一次按编号读取的数量有上限 | `forge.proto:5137` |
| `FindHostStatesByIds` | Core gRPC · 读 | — | host_ids | state、state_reason、rack_id、nvlink_domain_id、bmc_ip、dpu_ids、health_alerts、quarantine、allocation.{allocatable,blocking_reason,blocking_detail}、explored.{bmc_version,uefi_version} | 计算托盘对象 | Core | 交付 › 安装任务 | 定义 | — | 一次给出“能不能分配，被什么挡住”。只允许管理端证书调用；命令行没有对应命令 | `forge.proto:13734` |
| `FindSwitchIds → FindSwitchesByIds` | Core gRPC · 读 | `nico-admin-cli switch list；nico-admin-cli switch show <SWITCH_ID>` | 筛选：rack_id、controller_state、bmc_mac、nvos_mac、only_with_health_alert | id、rack_id、placement_in_rack、nvlink_domain_uuid、bmc_info.{ip,mac,firmware_version}、status.serial_number、status.power_state、status.controller_state、status.state_reason、status.health、status.fabric_manager_status_details、status.nvos_ports[].{mac,addresses,is_primary} | 交换机对象 | Core | 接入 › 设备发现；运维 › NVLink 域管理；运维 › 机柜管理 › 机柜详情；运维 › 设备管理 › 交换机；运维 › 设备管理；运维 › 健康告警 | 调用；现有产品已调用 | 调用成功，没有交换机。没有数据时命令行只输出一行文字，不是 JSON |  | `forge.proto:3332` |
| `FindPowerShelfIds → FindPowerShelvesByIds` | Core gRPC · 读 | `nico-admin-cli power-shelf list；nico-admin-cli power-shelf show <ID>` | 筛选：rack_id、controller_state、bmc_mac | id、rack_id、bmc_info.{ip,mac,firmware_version}、config.{capacity,voltage}、status.power_state、status.controller_state、status.state_reason、status.health | 供电框对象 | Core | 接入 › 设备发现；运维 › 机柜管理 › 机柜详情；运维 › 设备管理 › 供电框；运维 › 设备管理；运维 › 健康告警 | 调用；现有产品已调用 | 调用成功，没有供电框。没有数据时命令行只输出一行文字，不是 JSON | 没有槽位字段，也没有序列号字段 | `forge.proto:3087` |
| `FindMachineStateHistories / FindSwitchStateHistories / FindPowerShelfStateHistories` | Core gRPC · 读 | `nico-admin-cli machine show <ID> -c <条数>` | — | histories[id].records[].{state 或 event,version,time} | 计算托盘对象 | Core | 运维 › 设备管理 › 服务器；运维 › 设备管理 › 交换机；运维 › 设备管理 › 供电框 | 定义；现有产品已调用 | — |  | `forge.proto:329` |
| `GetComponentInventory` | Core gRPC · 读 | — | machine_ids、switch_ids、power_shelf_ids 三选一 | entries[].result.{component_id,status,error}、entries[].report.firmware_versions、entries[].report.systems[]、entries[].report.chassis[] | 探测结果 | Core | 运维 › 设备管理 › 服务器；运维 › 设备管理 › 交换机；运维 › 设备管理 › 供电框；交付 › 安装任务；配置 › 固件基线 | 定义；现有产品已调用 | — | 读的是保存下来的探测报告，不经过硬件后端。命令行没有对应命令 | `forge.proto:1373` |
| `GetComponentPowerDetails / GetPowerOptions` | Core gRPC · 读 | `nico-admin-cli managed-host power-options show <MACHINE>` | machine_ids、switch_ids、power_shelf_ids 三选一，1–64 个 | entries[].actual.{state,source,observed_at}、entries[].desired.state、entries[].actions[].{status,operation,requested_at,initiator} | 组件管理器 | Core 或硬件后端 | 运维 › 机柜管理 › 机柜详情；运维 › 设备管理 › 服务器；运维 › 设备管理 › 交换机；运维 › 设备管理 › 供电框 | 调用；现有产品已调用 | 只调用了 GetPowerOptions 这一半：返回 desired_state、actual_state 和各自的更新时间、host_id、off_counter 等。GetComponentPowerDetails 没有命令行，没有调用 | 整机柜里的主机、交换机和供电框经硬件后端读取；交换机和供电框对象上另有一个文本形式的 status.power_state | `forge.proto:11423` |
| `GetDesiredFirmwareVersions / ListComponentFirmwareVersions` | Core gRPC · 读 | `nico-admin-cli component-manager get-firmware-versions {compute-tray\|switch\|power-shelf\|rack}` | — | entries[].{vendor,model,component_versions}、devices[].versions[]、devices[].compute_fw_versions[] | 组件管理器 | Core | 配置 › 固件基线 | 定义 | — | 前者是按厂商型号配置的主机期望版本；后者是硬件后端可用的固件包。以机柜为目标时返回未实现 | `forge.proto:998` |
| `GetComponentFirmwareStatus` | Core gRPC · 读 | `nico-admin-cli component-manager get-firmware-update-status {compute-tray\|switch\|power-shelf\|rack}` | — | statuses[].state（QUEUED、IN_PROGRESS、VERIFYING、COMPLETED、FAILED、CANCELLED）、statuses[].target_version、statuses[].updated_at | 组件管理器 | Core 或硬件后端 | 运维 › 机柜管理 › 机柜详情 | 定义 | — |  | `forge.proto:1375` |
| `GetMachineValidationRuns / GetMachineValidationResults` | Core gRPC · 读 | `nico-admin-cli machine-validation runs show -m <MACHINE>` | — | runs[].{validation_id,status,start_time,end_time}、results[].{name,exit_code,std_out,std_err} | 计算托盘对象 | Core | 运维 › 设备管理 › 服务器 | 定义；现有产品已调用 | — |  | `forge.proto:878` |
| `IdentifySerial / IdentifyMac / FindIpAddress` | Core gRPC · 读 | `nico-admin-cli ip find <IP>` | 序列号、MAC 或 IP | machine_id、matches[].{ip_type,owner_id} | 计算托盘对象 | Core | 运维 › 设备管理 | 定义 | — | 跨类型搜索用。序列号只能反查主机；交换机和供电框要在各自的列表里按 BMC MAC 筛 | `forge.proto:350` |

## 接口：设备操作

| 接口 | 类型 | 命令行 | 请求参数 | 用到的字段 | 前置资源 | 执行方 | 使用的页面 | 证据 | 实测 | 说明 | 出处 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `PATCH /tray/{id}/power、PATCH /tray/power` | REST · 写 | `nicocli tray power --site-id <SITE> --data '{"state":"Off"}' <TRAY_ID>` | siteId、state 必填（On、Off、Cycle、ForceOff、ForceCycle、ACPowerCycle）；ruleId、overrideReadinessCheck 可选。批量接口的 filter 为空表示站点内全部托盘 | taskIds[] | Flow 的机柜与托盘清单 | Flow → Core → 硬件后端 | 运维 › 设备管理 › 服务器；运维 › 设备管理 › 交换机；运维 › 设备管理 › 供电框 | 定义 | 只调用过读回用的 GET /tray/{id}/power：返回 actual（state、source、observed、error）、desired（status、state、error）和 operations（actions、tasks 及各自的错误）。写操作没有调用 | 读回用 GET /tray/{id}/power，它分别给出实际状态、期望状态和进行中的动作 | `spec.yaml:16691` |
| `PATCH /tray/{id}/firmware、PATCH /tray/firmware` | REST · 写 | `nicocli tray firmware --site-id <SITE> <TRAY_ID>` | siteId 必填；version 省略表示用机柜固件清单；targets 可选（bmc、cpld、bios、nvos、pmc、psu、dpu）；ruleId、overrideVersionCheck、overrideReadinessCheck 可选 | taskIds[] | Flow 的机柜与托盘清单、机柜固件清单 | Flow → Core → 硬件后端 | 运维 › 设备管理 › 服务器；运维 › 设备管理 › 交换机 | 定义 | — | 内置的固件规则只覆盖计算托盘和交换机，不含供电框 | `spec.yaml:16743` |
| `ComponentPowerControl` | Core gRPC · 写 | `nico-admin-cli component-manager component-power-control --action <on\|graceful-shutdown\|force-off\|graceful-restart\|force-restart\|a-c-powercycle> {compute-tray\|switch\|power-shelf} --machine-id <ID>` | machine_ids、switch_ids、power_shelf_ids 三选一；action 必填 | results[].{component_id,status,error} | 组件管理器 | Core → 硬件后端 | 运维 › 设备管理 › 服务器；运维 › 设备管理 › 交换机 | 定义；现有产品已调用 | — | Flow 的托盘电源最终也调这个接口。结果里的 OUTCOME_UNKNOWN 表示不确定是否执行，不能自动重发。读回用 GetComponentPowerDetails | `forge.proto:1347` |
| `SetPowerShelfMaintenance` | Core gRPC · 写 | `nico-admin-cli power-shelf maintenance power-off --power-shelf-id <ID> [--reference] [--graceful]；… power-on` | power_shelf_ids、operation 必填（POWER_ON、POWER_OFF）；reference、graceful 可选 | — | 供电框对象、组件管理器 | 供电框状态机 → 硬件后端 | 运维 › 设备管理 › 供电框 | 定义；现有产品已调用 | — | 供电框在 Ready 或 Error 时才会被处理。读回看供电框状态从 Maintenance 回到 Ready | `crates/api-core/src/handlers/power_shelf.rs:330` |
| `SetMaintenance` | Core gRPC · 写 | `nico-admin-cli managed-host maintenance on --host <ID> --reference <原因>；… off --host <ID>` | operation、host_id 必填；开启时 reference 必填，至少 5 个字符 | — | 计算托盘对象 | Core | 运维 › 设备管理 › 服务器 | 定义；现有产品已调用 | — | 实现方式是给主机写一条健康报告，带阻止分配。读回看 config.maintenance_reference 或按 only_maintenance 筛选 | `crates/api-core/src/handlers/managed_host.rs:200` |
| `SetManagedHostQuarantineState / ClearManagedHostQuarantineState` | Core gRPC · 写 | `nico-admin-cli managed-host quarantine on --host <ID> --reason <原因>；… off --host <ID>` | machine_id、quarantine_state.{mode,reason} | prior_quarantine_state | 计算托盘对象 | Core | 运维 › 设备管理 › 服务器 | 定义；现有产品已调用 | — | 模式只有 BLOCK_ALL_TRAFFIC。读回看 status.quarantine | `crates/api-core/src/handlers/machine_quarantine.rs:28` |
| `OnDemandMachineValidation` | Core gRPC · 写 | `nico-admin-cli machine-validation on-demand start -m <MACHINE>` | machine_id、action 必填（只有 Start 可用） | validation_id | 计算托盘对象 | Core | 运维 › 设备管理 › 服务器 | 定义；现有产品已调用 | — | 主机要在 Ready 或 Failed 状态 | `forge.proto:974` |
| `VerifySkuForMachine` | Core gRPC · 写 | `nico-admin-cli sku verify <MACHINE_ID>` | machine_id | — | 计算托盘对象 | Core | 运维 › 设备管理 › 服务器 | 定义；现有产品已调用 | — | 读回看 status.hw_sku.verify_request_time | `crates/api-core/src/handlers/sku.rs:186` |
| `AdminBmcReset` | Core gRPC · 写 | `nico-admin-cli bmc-machine bmc-reset [--machine <ID>\|--switch <ID>\|--power-shelf <ID>]` | device_id（machine_id、switch_id、power_shelf_id 之一）；reset_type 可选 | — | 探测结果 | Core（Redfish） | 运维 › 设备管理 › 服务器；运维 › 设备管理 › 交换机 | 定义；现有产品已调用 | — | 没有读回接口：返回成功只表示 BMC 接受了请求 | `crates/api-core/src/handlers/bmc_endpoint_explorer.rs:302` |
| `DecommissionSwitch / DecommissionPowerShelf / DecommissionManagedHost` | Core gRPC · 写 | `nico-admin-cli managed-switch decommission <SWITCH_ID>；nico-admin-cli power-shelf decommission <ID>；nico-admin-cli managed-host decommission <ID>` | 设备 ID | — | 交换机对象、组件管理器 | 设备状态机 → 硬件后端 | 运维 › 设备管理 › 服务器；运维 › 设备管理 › 交换机；运维 › 设备管理 › 供电框 | 定义；现有产品已调用 | — | 设备要在 Ready；交换机和供电框还要求所在机柜没有已分配的主机；交换机要求后端是 rms。退役后要强制删除并清掉 BMC 抑制记录，设备才能被重新发现 | `crates/api-core/src/handlers/switch.rs:389` |

## 接口：机柜级任务

| 接口 | 类型 | 命令行 | 请求参数 | 用到的字段 | 前置资源 | 执行方 | 使用的页面 | 证据 | 实测 | 说明 | 出处 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `POST /rack/{id}/bringup` | REST · 写 | `nicocli rack bringup --site-id <SITE> <RACK_ID>` | siteId 必填；description、ruleId、overrideReadinessCheck 可选 | taskIds[] | Flow 的机柜与托盘清单、机柜固件清单、操作规则 | Flow → Core → 硬件后端 | 运维 › 机柜管理 › 机柜详情 | 定义 | — | 默认规则的阶段：供电框上电、计算托盘上电、计算托盘固件、交换机上电、交换机固件一致性核对、计算托盘重新上电。完成后还要看 Core 的机柜状态走到 Ready | `spec.yaml:14357` |
| `PATCH /rack/{id}/power` | REST · 写 | `nicocli rack power --site-id <SITE> --data '{"state":"On"}' <RACK_ID>` | siteId、state 必填（On、Off、Cycle、ForceOff、ForceCycle、ACPowerCycle）；ruleId、overrideReadinessCheck 可选 | taskIds[] | Flow 的机柜与托盘清单、操作规则 | Flow → Core → 硬件后端 | 运维 › 机柜管理 › 机柜详情 | 定义 | — | 机柜级上下电只有 Flow 提供，Core 的设备电源接口没有机柜这个目标。相同的进行中请求会合并成同一个任务 | `spec.yaml:14125` |
| `PATCH /rack/{id}/firmware` | REST · 写 | `nicocli rack firmware --site-id <SITE> <RACK_ID>` | siteId 必填；version 省略表示用机柜固件清单；ruleId、overrideVersionCheck、overrideReadinessCheck 可选 | taskIds[] | Flow 的机柜与托盘清单、机柜固件清单、操作规则 | Flow → Core → 硬件后端 | 运维 › 机柜管理 › 机柜详情 | 定义 | — | 走硬件后端时 version 是一整份固件清单文本，不是版本号。机柜接口不转发 targets | `spec.yaml:14245` |
| `GET /task、GET /rack/{id}/task、GET /tray/{id}/task、GET /task/{id}` | REST · 读 | `nicocli rack task get --site-id <SITE> <RACK_ID>` | siteId 必填；activeOnly、includeReport、分页可选 | id、status（Pending、Running、Succeeded、Failed、Terminated）、description、message、ruleId、started、finished、report | 任务 | Flow | 运维 › 机柜管理；运维 › 机柜管理 › 机柜详情；运维 › 设备管理 › 服务器；运维 › 设备管理 › 交换机；运维 › 设备管理 › 供电框；运维 › 运维任务 | 调用 | 返回 200 和空列表（没有提交过任务），按站点和按托盘两种都调用过，字段没法核对 | 任务里没有操作者和原因，这两项由平台的审计记录 | `spec.yaml:14768` |
| `POST /task/{id}/cancel` | REST · 写 | `nicocli task cancel --site-id <SITE> <TASK_ID>` | siteId 必填 | status | 任务 | Flow | 运维 › 机柜管理 › 机柜详情；运维 › 运维任务 | 定义 | — | 已经成功或失败的任务返回 412；已终止的任务重复取消不报错 | `spec.yaml:14913` |
| `OnDemandRackMaintenance / TerminateRackMaintenance` | Core gRPC · 写 | `nico-admin-cli rack maintenance start --rack <ID> --activities <firmware-upgrade,nvos-update,power-sequence,configure-nmx-cluster>；nico-admin-cli rack maintenance terminate --rack <ID>` | rack_id 必填；scope 可选（设备范围和活动） | — | 机柜对象、RMS | 机柜状态机 → RMS | 运维 › 机柜管理 › 机柜详情 | 定义；现有产品已调用 | — | 发起：机柜要在 Ready 或 Error。终止：只在机柜处于 Maintenance 时接受，终止后机柜进入 Error，已发给设备的请求和当前阶段的状态会被清理；重复终止不报错。NVOS 更新和 NMX-C 集群配置只有这条路径提供，REST 和 Flow 都没有 | `forge.proto:977` |
| `DeleteRack / AdminForceDeleteRack` | Core gRPC · 写 | `nico-admin-cli rack delete <RACK_ID>；nico-admin-cli rack force-delete` | 机柜 ID | — | 机柜对象 | Core | 运维 › 机柜管理 › 机柜详情 | 定义 | — | DeleteRack 只把机柜标记为删除；AdminForceDeleteRack 立即删除并保留状态历史。两个接口都不检查机柜里还有没有设备，也不处理成员设备。配套还要 DeleteExpectedRack 删掉机柜声明 | `crates/api-core/src/handlers/rack.rs:201` |

## 接口：交付与实例

| 接口 | 类型 | 命令行 | 请求参数 | 用到的字段 | 前置资源 | 执行方 | 使用的页面 | 证据 | 实测 | 说明 | 出处 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `FindOperatingSystemIds → FindOperatingSystemsByIds` | Core gRPC · 读 | `nico-admin-cli operating-system show` | — | id、name、type、status、is_active、ipxe_template_id、ipxe_template_parameters、ipxe_template_artifacts[].{name,url,cached_url} | 系统定义 | Core | 运维 › 设备管理 › 服务器；交付 › 安装任务；配置 › 安装方案 | 调用；现有产品已调用 | 返回 1 个系统定义。字段与这里一致，制品另有 sha、auth_type、cache_strategy |  | `forge.proto:1380` |
| `CreateOperatingSystem / UpdateOperatingSystem / DeleteOperatingSystem` | Core gRPC · 写 | `nico-admin-cli operating-system create；nico-admin-cli operating-system set-cached-url` | name 必填；ipxe_script，或 ipxe_template_id 加参数和制品，二选一；is_active、user_data 可选 | — | NICo Core | Core | 配置 › 安装方案 | 定义；现有产品已调用 | — | 删除时 Core 不检查是否还有实例在引用，平台要自己检查 | `crates/api-core/src/handlers/operating_system.rs:196` |
| `AllocateInstances / AllocateInstance` | Core gRPC · 写 | `nico-admin-cli instance allocate --machine-id <ID>... --transactional --os <OS_ID> [--flat-vpc-id\|--vpc-prefix-id]` | 每个实例：machine_id、config 必填（config.tenant、config.os、config.network）；instance_type_id、metadata、allow_unhealthy_machine 可选 | instances[].{id,machine_id,status} | 计算托盘对象、系统定义、默认租户与 VPC | Core | 交付 › 安装任务 | 定义；现有产品已调用 | — | 批量接口在一个事务里，全部成功或全部失败。不满足条件时的错误带有 nico-error-code、nico-error-text、nico-error-mitigation 三个附加信息 | `crates/api-core/src/instance/mod.rs:2009` |
| `FindInstanceIds → FindInstancesByIds / FindInstanceByMachineID` | Core gRPC · 读 | `nico-admin-cli instance show` | — | id、machine_id、config.tenant.{tenant_organization_id,hostname}、config.os、status.tenant.state、status.network、metadata | 实例 | Core | 运维 › 设备管理 › 服务器；交付 › 安装任务；交付 › 实例管理 | 调用；现有产品已调用 | 返回 1 个实例。顶层字段是 id、machine_id、instance_type_id、config、status、metadata 和各配置的版本号。config 和 status 里面的字段没有逐项核对 | 状态：PROVISIONING、READY、CONFIGURING、UPDATING、TERMINATING、TERMINATED、FAILED、REPAIRING | `forge.proto:230` |
| `ReleaseInstance / ReleaseInstances` | Core gRPC · 写 | `nico-admin-cli instance release --instance <ID>` | id 必填 | results[].{id,status,error} | 实例 | Core | 交付 › 实例管理 | 定义；现有产品已调用 | — | 重复调用不报错。主机健康带“阻止删除实例”时拒绝。回收是异步的：读回看实例消失，以及主机状态回到 Ready 且可分配 | `crates/api-core/src/handlers/instance.rs:822` |

## 接口：健康

| 接口 | 类型 | 命令行 | 请求参数 | 用到的字段 | 前置资源 | 执行方 | 使用的页面 | 证据 | 实测 | 说明 | 出处 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `ListMachineHealthReports / ListSwitchHealthReports / ListPowerShelfHealthReports / ListRackHealthReports / ListNVLinkDomainHealthReports` | Core gRPC · 读 | `nico-admin-cli machine health-report show <ID>；nico-admin-cli nvl-domain health-report show` | 设备、机柜或域的 ID | health_report_entries[].mode、report.source、report.alerts[].{id,target,in_alert_since,message,classifications[]} | 健康报告 | Core | 运维 › NVLink 域管理；运维 › 机柜管理 › 机柜详情；运维 › 健康告警；交付 › 安装任务 | 定义 | — | 一条告警是否阻止分配，看 classifications 里有没有 PreventAllocations。泄漏告警的编号：BmsLeakDetectRack、BmsLeakSensorFaultRack、BmcLeakDetection | `forge.proto:238` |
| `FindMachineHealthHistories / FindSwitchHealthHistories / FindPowerShelfHealthHistories / FindRackHealthHistories` | Core gRPC · 读 | `nico-admin-cli machine health-history <ID>；nico-admin-cli rack health-history <RACK_ID>` | ids 必填；start_time、end_time 可选 | histories[id].records[].{health,time} | 健康报告 | Core | 运维 › 健康告警 | 定义 | — |  | `forge.proto:330` |

## 缺口：设计需要、NICo 没有直接提供

| 设计需要 | 涉及页面 | 源码里的情况 | 可选的处理 | 出处 |
| --- | --- | --- | --- | --- |
| 到货清单里的槽位写入 NICo 的期望清单 | 设备清单 | Core 的设备声明没有槽位字段。REST 的设备声明有 slotId、trayIdx、hostId，存在 REST 自己的数据库里，并以 slot_id、tray_idx、host_id 三个标签写进 Core 的 metadata。实际位置来自 RMS 或 BMC 的探测报告，不来自声明 | 走 Core 时把槽位写成同样的三个 metadata 标签，与 REST 保持一致；或者设备声明改走 REST | `rest-api/db/pkg/db/model/common.go:100` |
| 到货清单没有 MAC：设备的身份由平台读取 | 设备发现、设备清单 | NICo 的设备声明以 BMC 的 MAC 为键，没有 MAC 就写不进去；NICo 也不会去读一个没有声明的地址背后是什么设备。Core 的站点发现在设备有声明之后才比对序列号，结果只是一个计数指标和一条 SerialNumberMismatch 告警 | 平台自己做：对拿到地址但没有归属的接口，用清单里的凭据读设备 BMC 的 Redfish，得到设备类型、序列号和型号，按序列号匹配清单后再写声明。现有产品已有这套读取（discovery.py、device_identity.py），但没有在 GB200/GB300 的计算托盘、NVLink 交换机和供电框上验证过分类是否正确。清单里的口令按批还是按台、每台不同时如何避免触发登录锁定，待确认 | `crates/site-explorer/src/lib.rs:1046` |
| 交换机 NVOS 管理口的 MAC 从哪来 | 设备发现 | 交换机声明至少要一个 NVOS 管理口的 MAC，多于一个时要标主口。NVOS 管理口自己也会申请地址，但 NICo 不知道哪个 NVOS 口属于哪台交换机 | 设计按“从交换机的 BMC 读出 NVOS 管理口的 MAC”写，读不到时人工关联。这个读取现有代码里没有，要在模拟环境或真实设备上验证 | `crates/api-db/src/expected_switch.rs` |
| 对账里的“未声明的设备” | 设备发现、机柜详情 | 没有一个接口能列全。GetAllUnexpectedMachines 只含探测成功的主机 BMC；探测失败的、交换机和供电框都不在里面。未声明的主机 BMC 因为没有凭据，通常就是探测失败 | 用设备接口列表里没有归属的记录，加上探测结果，由平台与声明对比得出 | `crates/api-db/src/expected_machine.rs:292` |
| “没有收到 DHCP 请求”按子网定位 | 网络规划、设备发现 | NICo 不记录每个子网或每个中继最近一次收到请求的时间和次数。DHCP 的指标只按报文类型和丢弃原因分；接口上只有该设备最近一次请求的时间 | DHCP 服务页的“最近请求”改成从设备接口的 last_dhcp 按子网汇总得出：只能反映拿到过地址的设备。完全没有请求到达的情况，页面只能提示去看中继配置和 DHCP 的丢弃计数 | `crates/dhcp-server/src/metrics.rs:496` |
| 引导服务地址和时间服务器的展示 | 网络规划 | 域名服务器、时间服务器、引导服务器地址在 DHCP 服务的部署参数里，没有接口可读；运行配置里只有 DHCP 服务器地址 | 从平台自己保存的部署配置读，并标明来源是部署配置而不是 NICo 的回报 | `helm/charts/nico-dhcp/values.yaml:199` |
| 固件基线 | 固件基线、机柜详情、设备管理 | NICo 里没有可命名的固件基线对象。期望版本有两处：每个机柜规格的固件清单地址，和按厂商型号配置的主机期望版本。固件操作要么不带版本（用机柜规格的清单），要么带一整份清单文本 | 固件基线做成平台自己的档案：一条基线对应一份清单文件。操作时把清单内容作为 version 传入，或者只允许选择与机柜规格配置一致的那一份。“低于基线”由平台对比探测到的版本和清单得出 | `docs/configuration/rms.md:183` |
| 站点概况里的硬件后端和设施接入状态 | 站点设置 | 当前生效的组件管理器后端没有读取接口；设施事件消费者是否连上也没有接口，只有它自己的指标。NMX-C 没有状态接口 | RMS 用版本接口判断；NMX-C 从机柜健康报告里的 NmxcUnreachable 判断；设施接入读消费者的指标，读不到就显示未知，不显示正常 | `crates/api-core/src/cfg/README.md:140` |
| 平台访问 REST 接口的身份 | 机柜管理、机柜详情、运维任务、NVLink 域管理 | REST 接口用的是身份系统签发的令牌，按组织和角色授权，和 Core 的客户端证书是两套。平台现在只有访问 Core 的证书，没有访问 REST 的身份。令牌必须从集群内的地址获取，否则签发者地址对不上 | 给平台建一个服务账号，用客户端凭据方式取令牌并缓存、到期前刷新；组织名作为站点配置的一项。身份系统用官方的 Keycloak 还是现场已有的，按站点决定 | `rest-api/openapi/auth.md:43` |
| 依赖组件的证书到期 | 站点设置 | RMS、Flow、站点代理和编排用数据库的证书最长 30 天，会自动续期，但 RMS 和数据库不会自动重新加载，过期后 Core 就连不上 RMS。NICo 没有接口报告这些证书的到期时间 | 站点概况的依赖组件里显示各证书的到期时间，数据从集群里的证书对象读；临近到期而组件还没重启时给出提示 | `docs/configuration/rms.md:82` |
| 任务里的操作者和原因 | 运维任务、操作审计 | Flow 的任务只有描述、规则和阶段报告，没有操作者和原因字段。REST 有自己的审计接口，记录的是调用它的账号 | 操作者和原因由平台审计保存，用任务编号关联；提交时把原因写进任务的 description | `rest-api/openapi/spec.yaml:28731` |
| 单台设备电源走任务还是直接执行 | 设备管理 | 两条路径都能用：REST 的托盘电源提交为 Flow 任务，可取消、有阶段；Core 的设备电源接口立即执行。供电框在 Core 里另有一个走状态机的专用接口。现有产品用的是 Core 的直接接口 | 设计稿目前写的是走任务。建议保持：有 Flow 时走任务，电源动作因此受“同一机柜只有一个任务”的约束；Flow 不可用时这些操作不可用，不悄悄改走直接接口 | `crates/api-core/src/handlers/component_manager.rs:3244` |
| 设备声明和机柜读取走 Core 还是走 REST | 设备清单、机柜管理、机柜详情 | REST 和 Core 是两套存储，靠工作流和定时任务同步；REST 的资源编号是它自己的 UUID。机柜的状态机状态只在 Core，任务计数、槽位和对账只在 REST | 写入只走 Core。读取分工：状态、健康、历史读 Core；槽位、对账、任务读 REST。两边用机柜 ID 和 BMC MAC 关联，页面上不显示 REST 的编号 | `rest-api/api/pkg/api/handler/expectedrack.go:161` |
| 新机柜的纳管、上线和机柜维护怎么衔接 | 机柜详情 | 三件事已经分清。纳管：现有产品写设备声明时带暂停标记（discovery.py:269），NICo 不上电也不接管，首次安装时才放行（onboarding.py:640）。上线：Flow 有内置的上线规则，六步，其中计算托盘上电这一步会打开 NICo 的上电闸门（AllowIngestionAndPowerOn）。机柜维护：Core 的机柜状态机在就绪的交换机数不少于机柜规格里的数量时自动开始，没有等人确认的开关，顺序是固件升级、NVOS 更新、上电顺序（需要时）、配置 NMX-C 集群、校验。没有核实的是这两条线同时进行时的衔接：Flow 上线里的计算托盘固件走状态机路径时要求机柜已经在 Ready 或 Error；交换机没有上电时能否被 NICo 建立对象；计算托盘带暂停标记时机柜能否走到 Ready | 设计按“人确认纳管 → 人开始上线（Flow 上线任务）→ NICo 自动机柜维护”来画，各阶段的定义、对设备的影响和人工确认点写在说明书 5.4 至 5.6，设计前提写在 5.9。衔接问题要在现场版本的模拟环境里把 Flow 上线任务和机柜状态机一起跑一遍才能定；旧版本模拟环境只测过机柜状态机这一半 | `rest-api/flow/internal/task/operationrules/resolver_defaults.go:775；crates/rack-controller/src/discovering.rs:65；crates/rack-controller/src/maintenance.rs:1496` |
| 更换设备后机柜重新发现 | 机柜详情 | 文档说更换托盘会让机柜因 topology_changed 回到 Discovering，但源码里没有找到设置这个标志的非测试代码。更换的实际步骤是：打上待更换标记并等 NVLink 隔离完成、强制删除旧设备、改设备声明、等新设备被发现 | 更换设备做成平台编排的分步流程，每步读回；机柜状态是否变化以实测为准，页面不预先承诺 | `crates/rack-controller/src/ready.rs:50` |
| 删除机柜 | 机柜详情 | DeleteRack 只把机柜标记为删除，不检查机柜里还有没有设备，状态机进入 Deleting 后一直等待；真正删除只有强制删除，同样不处理成员设备。命令行的说明写着“机柜不应再有关联的计算托盘、交换机和供电框”，但接口不做这项检查。Flow 有退役任务，但只在 Flow 自己的接口上，REST 没有端点 | 机柜页只提供“删除机柜”，不提供“机柜退役”。删除的前提由平台检查并逐项显示：没有实例、成员设备都已逐台退役、没有进行中的任务。满足后平台删除机柜声明，再强制删除机柜对象。成员设备的退役是逐台设备的操作，在设备管理里做，机柜操作不代做 | `crates/api-core/src/handlers/rack.rs:201` |
| 跨机柜的固件分阶段发布 | 固件基线 | 一个 NVL72 机柜就是一个 NVLink 域，所以没有“域内按机柜分批”。Flow 的分阶段发布目标是站点内所有符合条件的机柜，按百分比抽取，不能传入机柜列表；只调用过它的列表接口，返回空 | 这一版不设计：域级电源、域级固件和分阶段发布都已从设计稿里去掉。以后作为站点级功能单独设计 | `docs/operations/flow/operation-runs.md:123` |
| 装系统前的“机柜就绪”和“无整柜泄漏” | 安装任务 | NICo 建实例时只看主机自己：状态、维护标记和阻止分配的告警。机柜的健康报告会并入主机，所以泄漏会挡住整柜；但机柜状态不是 Ready、域的健康报告有告警，都不会让建实例失败 | 机柜里的设备，平台在选择设备时另外检查机柜是否就绪、有没有整柜泄漏、有没有进行中的任务，并在每一行写明原因；页面上标明这是平台的规则。“可以装系统”的判断用主机状态接口里的 allocatable，与 NICo 保持一致 | `crates/api-model/src/machine/mod.rs:543` |
| 实例用的租户和 VPC | 安装任务 | NICo 里每个实例都要属于一个租户、接入一个网络。Core 的创建租户和创建 VPC 接口只对站点代理放行，管理端证书调不了。现有产品用一个固定的默认租户（site_network_context.py:40），只读取已有的 VPC | 平台不做多租户：所有实例建在站点的默认租户下，页面上不显示也不让选。默认租户和 VPC 是部署前提，由部署步骤建好。实例类型和配额是 NICo 向多个租户分发机器时用的，平台不使用 | `crates/api-core/src/auth/internal_rbac_rules.rs:75` |
| 一次给多台机器建实例 | 安装任务 | 实例是逐台机器的：建实例的请求里每个实例带一个机器 ID。REST 的批量建实例按实例类型和数量挑设备，不能指定设备列表。Core 的批量接口可以传入明确的设备列表，并且是一个事务。机柜上没有建实例或装系统的接口 | 走 Core：向导里选了几台就提交几个实例，每个实例明确给出机器 ID、主机名和系统，一次提交在一个事务里。机柜只是选择设备时的筛选条件，不是装系统的对象 | `crates/api-core/src/instance/mod.rs:2009` |
| 安装条件检查由谁做 | 安装任务 | NICo 建实例时只检查主机状态。现有产品在提交前自己做一组检查（execution.py:387、onboarding.py:960、onboarding.py:1120）：设备规划与地址占用、引导方式、既有实例与目标盘基线、BMC 认证与序列号、管理地址与安装网络配置、安装材料的 HTTP 可达与长度。还没有接入的设备把“就绪”和“目标盘”推迟到执行前。页面把这些归成三组显示：设备身份、安装配置、操作系统材料 | 整机柜方向照搬这组检查和页面。其中 BMC 认证是平台直接读设备的 BMC，不经 NICo；材料检查是平台对自己的材料服务的请求；主机状态、实例和地址占用读 NICo。选盘规则解析不出唯一的系统盘时，检查不通过，在向导里逐台指定 | `crates/api-model/src/machine/mod.rs:543` |
| 主机名在哪里确定 | 安装任务、实例管理 | 实例配置的租户部分有一个主机名字段；实例名称合法时，NICo 把它作为 cloud-init 的 local-hostname 传给系统。机器在 NICo 里自己的 DNS 名由站点的命名策略决定（默认按地址生成），那不是系统里的主机名。现有产品在建实例时逐台传主机名（executor.py:2022） | 主机名在新建安装任务时逐台确定，同时用作实例名称。它是设备系统配置里的一项：没有填时平台按管理地址生成（node-加上把点换成连字符的地址），可以逐台改；平台在提交前检查写法和重名。站点的命名策略不动 | `crates/api-core/src/handlers/client_resolution.rs:512` |
| 主机的网络配置在哪里确定 | 安装任务 | NICo 给主机管理口分配地址，分配方式有动态、固定、保留三种，接口已有分配后再改声明不会改地址。现有产品在设备的系统配置里逐台保存：启动网卡 MAC、管理 IP、管理子网，以及其他网口各自的 IP、子网和网关；装机时把这些写进系统的网络配置，不含 Bond、VLAN 和 IPv6（现有产品的设备管理使用指南第 6 节） | 只取管理口：管理地址在设备规划时和启动网口的 MAC 对应（到货清单可带 management_ip 一列），在系统配置和安装向导里只读显示。其他网口平台不管理，也不显示，装好后由使用者自己配置。规划的管理地址如何落到 NICo 的地址分配上（改声明还是固定租约），沿用现有产品的做法，没有在整机柜环境里核对 | `docs/provisioning/expected-machine-interfaces.md` |
| BMC 按规划改址 | 设备管理 | 设备接电时 BMC 从地址池动态拿地址；接口已有分配后，再改设备声明不会改变它的地址。现有产品的做法：在设备上保存规划地址，纳管之后由人发起“更新 BMC 地址”，平台直接经 Redfish 关闭 BMC 的 DHCP、写入固定地址，用新地址核对身份，再把新地址同步为 NICo 里这个接口的静态分配；不创建也不修改交换机和供电框的原生声明（现有产品的设备管理使用指南“保存配置与更新地址”一节） | 整机柜方向照搬页面和四步流程，三类设备都适用；规划地址可以随到货清单的 bmc_ip 列带入。同步到 NICo 用的具体接口沿用现有产品，没有在整机柜环境里核对；RMS 管理的设备改址后 RMS 一侧是否需要跟着更新，也没有核对 | `docs/provisioning/expected-machine-interfaces.md` |
| 不属于机柜的服务器 | 设备管理、设备清单、设备发现、安装任务 | 设备声明里的机柜编号是可选的，机器、交换机、供电框通过各自的机柜编号指向机柜，机柜对象里不存成员。Flow 的上线任务按机柜提交，没有机柜的服务器走不了这条路。现有产品写声明时带暂停标记（discovery.py:269），首次安装时才放行（onboarding.py:640） | 设备是基础对象，机柜是叠在上面的一层。不属于机柜的服务器进同一份清单，机柜和槽位留空；在设备发现里逐台确认纳管；没有上线这一步，安装任务的第一步放行，由 NICo 上电接管。机柜里的设备由上线任务放行。这是从两边的定义推出来的设计，没有在同一个环境里把两种设备一起跑过 | `crates/rpc/proto/forge.proto:8191` |
| 供电框的槽位和序列号 | 设备管理、机柜详情 | Core 的供电框对象没有位置字段，也没有序列号字段；交换机的序列号取自探测报告 | 供电框的槽位读 REST 的托盘，序列号读设备声明或探测报告 | `crates/rpc/proto/forge.proto:3087` |

## 各页面用到的接口

### 运维 › 机柜管理

| 用途 | 接口 | 类型 | 命令行 | 用到的字段 |
| --- | --- | --- | --- | --- |
| 机柜状态（含上线所在的阶段）与健康 | `FindRackIds → FindRacksByIds` | Core gRPC · 读 | `nico-admin-cli rack list；nico-admin-cli rack show <RACK_ID>` | id、rack_group_id、status.lifecycle.{state,state_reason}、status.health、status.health_sources、metadata、created、updated |
| 机柜规格 | `GetAllExpectedRacks` | Core gRPC · 读 | `nico-admin-cli expected-rack show` | rack_id、rack_profile_id、rack_group_id、metadata |
| 托盘计数与任务计数 | `GET /rack、GET /rack/{id}` | REST · 读 | `nicocli rack list --site-id <SITE>` | id、name、operationStatus、operationStatusDetails.trayCountsByType、nvLinkDomainIds、taskStats.{pendingTaskCount,activeTaskCount}、health、components[] |
| 当前任务 | `GET /task、GET /rack/{id}/task、GET /tray/{id}/task、GET /task/{id}` | REST · 读 | `nicocli rack task get --site-id <SITE> <RACK_ID>` | id、status（Pending、Running、Succeeded、Failed、Terminated）、description、message、ruleId、started、finished、report |

### 运维 › 机柜管理 › 机柜详情

| 用途 | 接口 | 类型 | 命令行 | 用到的字段 |
| --- | --- | --- | --- | --- |
| 状态、所在阶段、原因与健康 | `FindRackIds → FindRacksByIds` | Core gRPC · 读 | `nico-admin-cli rack list；nico-admin-cli rack show <RACK_ID>` | id、rack_group_id、status.lifecycle.{state,state_reason}、status.health、status.health_sources、metadata、created、updated |
| 机柜规格和它要求的各类设备数量 | `ListRackProfiles / GetRackProfile` | Core gRPC · 读 | `nico-admin-cli rack profile list；nico-admin-cli rack profile show <RACK_ID>` | rack_profile_id、profile.rack_hardware_topology、profile.capabilities.{compute,switch,power_shelf}.count、profile.product_family |
| 状态历史 | `FindRackStateHistories` | Core gRPC · 读 | `nico-admin-cli rack state-history <RACK_ID>` | histories[rack_id].records[].{state,version,time} |
| 确认纳管：写入机柜组 | `AddExpectedRackGroup / UpdateExpectedRackGroup / DeleteExpectedRackGroup` | Core gRPC · 写 | `nico-admin-cli expected-rack-group add [--rack <JSON>]... <RACK_GROUP_ID> <PROTOCOL> <TOPOLOGY>` | — |
| 确认纳管：写入机柜声明；删除机柜时删掉机柜声明 | `AddExpectedRack / UpdateExpectedRack / DeleteExpectedRack` | Core gRPC · 写 | `nico-admin-cli expected-rack add [--label K:V] <RACK_ID>` | — |
| 确认纳管：写入已匹配的计算托盘，带暂停标记（default_pause_ingestion_and_poweron），不上电、不接管 | `CreateExpectedMachines / UpdateExpectedMachines / PatchExpectedMachine / DeleteExpectedMachine` | Core gRPC · 写 | `nico-admin-cli expected-machine add -a <BMC_MAC> -u <BMC_USER> -p <BMC_PASS> -s <SERIAL> [--rack_id] [--bmc-ip-address] [--interfaces] [--label]` | — |
| 确认纳管：写入已匹配的交换机 | `AddExpectedSwitch / PatchExpectedSwitch / DeleteExpectedSwitch` | Core gRPC · 写 | `nico-admin-cli expected-switch add -a <BMC_MAC> -u <USER> -p <PASS> -s <SERIAL> --nvos-interface <MAC[,primary]> [--rack_id]` | — |
| 确认纳管：写入已匹配的供电框 | `AddExpectedPowerShelf / PatchExpectedPowerShelf / DeleteExpectedPowerShelf` | Core gRPC · 写 | `nico-admin-cli expected-power-shelf add -a <BMC_MAC> -u <USER> -p <PASS> -s <SERIAL> [--rack_id]` | — |
| 重新执行机柜维护；终止进行中的机柜维护 | `OnDemandRackMaintenance / TerminateRackMaintenance` | Core gRPC · 写 | `nico-admin-cli rack maintenance start --rack <ID> --activities <firmware-upgrade,nvos-update,power-sequence,configure-nmx-cluster>；nico-admin-cli rack maintenance terminate --rack <ID>` | — |
| 删除机柜 | `DeleteRack / AdminForceDeleteRack` | Core gRPC · 写 | `nico-admin-cli rack delete <RACK_ID>；nico-admin-cli rack force-delete` | — |
| 开始上线：提交上线任务。内置规则六步：供电框上电、计算托盘上电并放行接管、计算托盘固件、交换机上电、核对交换机固件、计算托盘重启 | `POST /rack/{id}/bringup` | REST · 写 | `nicocli rack bringup --site-id <SITE> <RACK_ID>` | taskIds[] |
| 任务计数与所属域 | `GET /rack、GET /rack/{id}` | REST · 读 | `nicocli rack list --site-id <SITE>` | id、name、operationStatus、operationStatusDetails.trayCountsByType、nvLinkDomainIds、taskStats.{pendingTaskCount,activeTaskCount}、health、components[] |
| 期望与实际校验 | `GET /rack/{id}/validation、GET /rack/validation` | REST · 读 | `nicocli rack validate --site-id <SITE>` | diffs[].{type,id,macAddress,fieldDiffs}、totalDiffs、missingCount、unexpectedCount、mismatchCount、matchCount |
| 实测槽位（与清单比对）；电源和固件确认页上各主机现在能否被操作 | `GET /tray、GET /tray/{id}` | REST · 读 | `nicocli tray list --site-id <SITE> --rack-id <RACK>` | id、type（Compute、NVSwitch、PowerShelf）、position.{slotId,trayIdx,hostId}、firmwareVersion、powerState、operationStatus、leakStatus、bmcs、rackId、nvLinkDomainId、taskStats、health |
| 设备表：计算托盘 | `FindMachineIds → FindMachinesByIds` | Core gRPC · 读 | `nico-admin-cli machine show [--hosts]` | id、rack_id、placement_in_rack.{slot_number,tray_index}、state、state_reason.{outcome,outcome_msg}、state_sla.time_in_state_above_sla、status.health.alerts[]、bmc.{ip,mac}、status.bmc_status.firmware_version、status.discovery_info.dmi_data.chassis_serial、status.associated_dpu_machine_ids、config.maintenance_reference、status.quarantine、status.nvlink_info.domain_uuid、status.lldp_neighbors[]、inventory.components[] |
| 设备表：交换机 | `FindSwitchIds → FindSwitchesByIds` | Core gRPC · 读 | `nico-admin-cli switch list；nico-admin-cli switch show <SWITCH_ID>` | id、rack_id、placement_in_rack、nvlink_domain_uuid、bmc_info.{ip,mac,firmware_version}、status.serial_number、status.power_state、status.controller_state、status.state_reason、status.health、status.fabric_manager_status_details、status.nvos_ports[].{mac,addresses,is_primary} |
| 设备表：供电框 | `FindPowerShelfIds → FindPowerShelvesByIds` | Core gRPC · 读 | `nico-admin-cli power-shelf list；nico-admin-cli power-shelf show <ID>` | id、rack_id、bmc_info.{ip,mac,firmware_version}、config.{capacity,voltage}、status.power_state、status.controller_state、status.state_reason、status.health |
| 成员电源 | `GetComponentPowerDetails / GetPowerOptions` | Core gRPC · 读 | `nico-admin-cli managed-host power-options show <MACHINE>` | entries[].actual.{state,source,observed_at}、entries[].desired.state、entries[].actions[].{status,operation,requested_at,initiator} |
| 机柜电源 | `PATCH /rack/{id}/power` | REST · 写 | `nicocli rack power --site-id <SITE> --data '{"state":"On"}' <RACK_ID>` | taskIds[] |
| 固件更新 | `PATCH /rack/{id}/firmware` | REST · 写 | `nicocli rack firmware --site-id <SITE> <RACK_ID>` | taskIds[] |
| 固件步骤的逐台进度 | `GetComponentFirmwareStatus` | Core gRPC · 读 | `nico-admin-cli component-manager get-firmware-update-status {compute-tray\|switch\|power-shelf\|rack}` | statuses[].state（QUEUED、IN_PROGRESS、VERIFYING、COMPLETED、FAILED、CANCELLED）、statuses[].target_version、statuses[].updated_at |
| 任务卡与步骤 | `GET /task、GET /rack/{id}/task、GET /tray/{id}/task、GET /task/{id}` | REST · 读 | `nicocli rack task get --site-id <SITE> <RACK_ID>` | id、status（Pending、Running、Succeeded、Failed、Terminated）、description、message、ruleId、started、finished、report |
| 取消任务 | `POST /task/{id}/cancel` | REST · 写 | `nicocli task cancel --site-id <SITE> <TASK_ID>` | status |
| 机柜健康与整柜泄漏 | `ListMachineHealthReports / ListSwitchHealthReports / ListPowerShelfHealthReports / ListRackHealthReports / ListNVLinkDomainHealthReports` | Core gRPC · 读 | `nico-admin-cli machine health-report show <ID>；nico-admin-cli nvl-domain health-report show` | health_report_entries[].mode、report.source、report.alerts[].{id,target,in_alert_since,message,classifications[]} |

### 运维 › NVLink 域管理

| 用途 | 接口 | 类型 | 命令行 | 用到的字段 |
| --- | --- | --- | --- | --- |
| 域（机柜组编号）、拓扑和 NMX-C 集群 | `GET /domain/nvlink、GET /domain/nvlink/{id}` | REST · 读 | `nicocli domain list --site-id <SITE>` | id（等于机柜组编号）、name、nmxcClusterId、topology、operationStatus、components |
| 交换机回报的 NMX-C 域编号和 Fabric Manager 状态 | `FindSwitchIds → FindSwitchesByIds` | Core gRPC · 读 | `nico-admin-cli switch list；nico-admin-cli switch show <SWITCH_ID>` | id、rack_id、placement_in_rack、nvlink_domain_uuid、bmc_info.{ip,mac,firmware_version}、status.serial_number、status.power_state、status.controller_state、status.state_reason、status.health、status.fabric_manager_status_details、status.nvos_ports[].{mac,addresses,is_primary} |
| 机柜健康里的 NMX-C 不可达 | `ListMachineHealthReports / ListSwitchHealthReports / ListPowerShelfHealthReports / ListRackHealthReports / ListNVLinkDomainHealthReports` | Core gRPC · 读 | `nico-admin-cli machine health-report show <ID>；nico-admin-cli nvl-domain health-report show` | health_report_entries[].mode、report.source、report.alerts[].{id,target,in_alert_since,message,classifications[]} |
| 域的健康报告 | `ListNVLinkDomainHealthReports` | Core gRPC · 读 | — | health_report_entries[] |
| NMX 分区 | `FindNVLinkPartitionIds → FindNVLinkPartitionsByIds` | Core gRPC · 读 | — | id、name、nmx_m_id、domain_uuid、logical_partition_id |
| 逻辑分区和状态 | `FindNVLinkLogicalPartitionIds → FindNVLinkLogicalPartitionsByIds` | Core gRPC · 读 | — | id、config.metadata.name、config.tenant_organization_id、status.state、created |

### 运维 › 设备管理

| 用途 | 接口 | 类型 | 命令行 | 用到的字段 |
| --- | --- | --- | --- | --- |
| 计算托盘的数量和需要处理的设备 | `FindMachineIds → FindMachinesByIds` | Core gRPC · 读 | `nico-admin-cli machine show [--hosts]` | id、rack_id、placement_in_rack.{slot_number,tray_index}、state、state_reason.{outcome,outcome_msg}、state_sla.time_in_state_above_sla、status.health.alerts[]、bmc.{ip,mac}、status.bmc_status.firmware_version、status.discovery_info.dmi_data.chassis_serial、status.associated_dpu_machine_ids、config.maintenance_reference、status.quarantine、status.nvlink_info.domain_uuid、status.lldp_neighbors[]、inventory.components[] |
| 交换机的数量和需要处理的设备 | `FindSwitchIds → FindSwitchesByIds` | Core gRPC · 读 | `nico-admin-cli switch list；nico-admin-cli switch show <SWITCH_ID>` | id、rack_id、placement_in_rack、nvlink_domain_uuid、bmc_info.{ip,mac,firmware_version}、status.serial_number、status.power_state、status.controller_state、status.state_reason、status.health、status.fabric_manager_status_details、status.nvos_ports[].{mac,addresses,is_primary} |
| 供电框的数量和需要处理的设备 | `FindPowerShelfIds → FindPowerShelvesByIds` | Core gRPC · 读 | `nico-admin-cli power-shelf list；nico-admin-cli power-shelf show <ID>` | id、rack_id、bmc_info.{ip,mac,firmware_version}、config.{capacity,voltage}、status.power_state、status.controller_state、status.state_reason、status.health |
| 按序列号、MAC、地址搜索 | `IdentifySerial / IdentifyMac / FindIpAddress` | Core gRPC · 读 | `nico-admin-cli ip find <IP>` | machine_id、matches[].{ip_type,owner_id} |
| DPU 卡片上 BlueField 卡的数量和工作方式 | `FindExploredEndpointIds → FindExploredEndpointsByIds` | Core gRPC · 读 | `nico-admin-cli site-explorer get-report endpoint` | address、report.endpoint_type、report.vendor、report.systems[].serial_number、report.chassis[].serial_number、report.last_exploration_error_schema.{error_code,mitigation,text}、report.firmware_versions、preingestion_state、pause_remediation |

### 运维 › 设备管理 › 服务器

| 用途 | 接口 | 类型 | 命令行 | 用到的字段 |
| --- | --- | --- | --- | --- |
| BMC 地址：当前的分配方式；规划地址有没有被占用；更新后同步为静态分配（见缺口） | `FindInterfaceAddresses / FindIpAddress` | Core gRPC · 读 | `nico-admin-cli machine-interfaces show-addresses；nico-admin-cli ip find <IP>` | addresses[].{address,allocation_type}、matches[].{ip_type,owner_id,message} |
| 列表、状态、健康和地址；机柜编号为空的是不属于机柜的服务器 | `FindMachineIds → FindMachinesByIds` | Core gRPC · 读 | `nico-admin-cli machine show [--hosts]` | id、rack_id、placement_in_rack.{slot_number,tray_index}、state、state_reason.{outcome,outcome_msg}、state_sla.time_in_state_above_sla、status.health.alerts[]、bmc.{ip,mac}、status.bmc_status.firmware_version、status.discovery_info.dmi_data.chassis_serial、status.associated_dpu_machine_ids、config.maintenance_reference、status.quarantine、status.nvlink_info.domain_uuid、status.lldp_neighbors[]、inventory.components[] |
| 电源状态 | `GetComponentPowerDetails / GetPowerOptions` | Core gRPC · 读 | `nico-admin-cli managed-host power-options show <MACHINE>` | entries[].actual.{state,source,observed_at}、entries[].desired.state、entries[].actions[].{status,operation,requested_at,initiator} |
| 固件版本 | `GetComponentInventory` | Core gRPC · 读 | — | entries[].result.{component_id,status,error}、entries[].report.firmware_versions、entries[].report.systems[]、entries[].report.chassis[] |
| 所属实例 | `FindInstanceIds → FindInstancesByIds / FindInstanceByMachineID` | Core gRPC · 读 | `nico-admin-cli instance show` | id、machine_id、config.tenant.{tenant_organization_id,hostname}、config.os、status.tenant.state、status.network、metadata |
| 运行状态里的状态历史 | `FindMachineStateHistories / FindSwitchStateHistories / FindPowerShelfStateHistories` | Core gRPC · 读 | `nico-admin-cli machine show <ID> -c <条数>` | histories[id].records[].{state 或 event,version,time} |
| 硬件校验结果 | `GetMachineValidationRuns / GetMachineValidationResults` | Core gRPC · 读 | `nico-admin-cli machine-validation runs show -m <MACHINE>` | runs[].{validation_id,status,start_time,end_time}、results[].{name,exit_code,std_out,std_err} |
| 上电、关机、重启 | `PATCH /tray/{id}/power、PATCH /tray/power` | REST · 写 | `nicocli tray power --site-id <SITE> --data '{"state":"Off"}' <TRAY_ID>` | taskIds[] |
| 固件更新 | `PATCH /tray/{id}/firmware、PATCH /tray/firmware` | REST · 写 | `nicocli tray firmware --site-id <SITE> <TRAY_ID>` | taskIds[] |
| 任务进度 | `GET /task、GET /rack/{id}/task、GET /tray/{id}/task、GET /task/{id}` | REST · 读 | `nicocli rack task get --site-id <SITE> <RACK_ID>` | id、status（Pending、Running、Succeeded、Failed、Terminated）、description、message、ruleId、started、finished、report |
| 设置和清除维护标记 | `SetMaintenance` | Core gRPC · 写 | `nico-admin-cli managed-host maintenance on --host <ID> --reference <原因>；… off --host <ID>` | — |
| 隔离和解除隔离 | `SetManagedHostQuarantineState / ClearManagedHostQuarantineState` | Core gRPC · 写 | `nico-admin-cli managed-host quarantine on --host <ID> --reason <原因>；… off --host <ID>` | prior_quarantine_state |
| 按需硬件校验 | `OnDemandMachineValidation` | Core gRPC · 写 | `nico-admin-cli machine-validation on-demand start -m <MACHINE>` | validation_id |
| 核对 SKU | `VerifySkuForMachine` | Core gRPC · 写 | `nico-admin-cli sku verify <MACHINE_ID>` | — |
| 重启 BMC | `AdminBmcReset` | Core gRPC · 写 | `nico-admin-cli bmc-machine bmc-reset [--machine <ID>\|--switch <ID>\|--power-shelf <ID>]` | — |
| 退役 | `DecommissionSwitch / DecommissionPowerShelf / DecommissionManagedHost` | Core gRPC · 写 | `nico-admin-cli managed-switch decommission <SWITCH_ID>；nico-admin-cli power-shelf decommission <ID>；nico-admin-cli managed-host decommission <ID>` | — |
| 电源的直接执行路径（见缺口） | `ComponentPowerControl` | Core gRPC · 写 | `nico-admin-cli component-manager component-power-control --action <on\|graceful-shutdown\|force-off\|graceful-restart\|force-restart\|a-c-powercycle> {compute-tray\|switch\|power-shelf} --machine-id <ID>` | results[].{component_id,status,error} |
| 系统配置：这台机器上的主机网口和 NICo 引导时用的网口 | `FindInterfaces` | Core gRPC · 读 | `nico-admin-cli machine-interfaces show` | id、mac_address、address[]、segment_id、hostname、vendor、last_dhcp、machine_id、switch_id、power_shelf_id、association_type、interface_type、primary_interface |
| 系统配置：管理地址有没有被占用 | `FindInterfaceAddresses / FindIpAddress` | Core gRPC · 读 | `nico-admin-cli machine-interfaces show-addresses；nico-admin-cli ip find <IP>` | addresses[].{address,allocation_type}、matches[].{ip_type,owner_id,message} |
| 系统配置：管理子网的范围和网关 | `FindNetworkSegmentIds → FindNetworkSegmentsByIds` | Core gRPC · 读 | `nico-admin-cli network-segment show` | id、metadata.name、config.segment_type、config.mtu、config.subdomain_id、config.prefixes[].{prefix,gateway,reserve_first,free_ip_count_v2}、status.lifecycle.state |
| 系统配置：这种架构已发布的安装方案 | `FindOperatingSystemIds → FindOperatingSystemsByIds` | Core gRPC · 读 | `nico-admin-cli operating-system show` | id、name、type、status、is_active、ipxe_template_id、ipxe_template_parameters、ipxe_template_artifacts[].{name,url,cached_url} |

### 运维 › 设备管理 › 交换机

| 用途 | 接口 | 类型 | 命令行 | 用到的字段 |
| --- | --- | --- | --- | --- |
| BMC 地址：当前的分配方式；规划地址有没有被占用；更新后同步为静态分配（见缺口） | `FindInterfaceAddresses / FindIpAddress` | Core gRPC · 读 | `nico-admin-cli machine-interfaces show-addresses；nico-admin-cli ip find <IP>` | addresses[].{address,allocation_type}、matches[].{ip_type,owner_id,message} |
| 列表、状态、健康、地址和 Fabric Manager | `FindSwitchIds → FindSwitchesByIds` | Core gRPC · 读 | `nico-admin-cli switch list；nico-admin-cli switch show <SWITCH_ID>` | id、rack_id、placement_in_rack、nvlink_domain_uuid、bmc_info.{ip,mac,firmware_version}、status.serial_number、status.power_state、status.controller_state、status.state_reason、status.health、status.fabric_manager_status_details、status.nvos_ports[].{mac,addresses,is_primary} |
| 电源状态 | `GetComponentPowerDetails / GetPowerOptions` | Core gRPC · 读 | `nico-admin-cli managed-host power-options show <MACHINE>` | entries[].actual.{state,source,observed_at}、entries[].desired.state、entries[].actions[].{status,operation,requested_at,initiator} |
| 固件与 NVOS 版本 | `GetComponentInventory` | Core gRPC · 读 | — | entries[].result.{component_id,status,error}、entries[].report.firmware_versions、entries[].report.systems[]、entries[].report.chassis[] |
| 运行状态里的状态历史 | `FindMachineStateHistories / FindSwitchStateHistories / FindPowerShelfStateHistories` | Core gRPC · 读 | `nico-admin-cli machine show <ID> -c <条数>` | histories[id].records[].{state 或 event,version,time} |
| 上电、关机、重启 | `PATCH /tray/{id}/power、PATCH /tray/power` | REST · 写 | `nicocli tray power --site-id <SITE> --data '{"state":"Off"}' <TRAY_ID>` | taskIds[] |
| 固件更新 | `PATCH /tray/{id}/firmware、PATCH /tray/firmware` | REST · 写 | `nicocli tray firmware --site-id <SITE> <TRAY_ID>` | taskIds[] |
| 任务进度 | `GET /task、GET /rack/{id}/task、GET /tray/{id}/task、GET /task/{id}` | REST · 读 | `nicocli rack task get --site-id <SITE> <RACK_ID>` | id、status（Pending、Running、Succeeded、Failed、Terminated）、description、message、ruleId、started、finished、report |
| 重启 BMC | `AdminBmcReset` | Core gRPC · 写 | `nico-admin-cli bmc-machine bmc-reset [--machine <ID>\|--switch <ID>\|--power-shelf <ID>]` | — |
| 退役 | `DecommissionSwitch / DecommissionPowerShelf / DecommissionManagedHost` | Core gRPC · 写 | `nico-admin-cli managed-switch decommission <SWITCH_ID>；nico-admin-cli power-shelf decommission <ID>；nico-admin-cli managed-host decommission <ID>` | — |
| 电源的直接执行路径（见缺口） | `ComponentPowerControl` | Core gRPC · 写 | `nico-admin-cli component-manager component-power-control --action <on\|graceful-shutdown\|force-off\|graceful-restart\|force-restart\|a-c-powercycle> {compute-tray\|switch\|power-shelf} --machine-id <ID>` | results[].{component_id,status,error} |

### 运维 › 设备管理 › 供电框

| 用途 | 接口 | 类型 | 命令行 | 用到的字段 |
| --- | --- | --- | --- | --- |
| BMC 地址：当前的分配方式；规划地址有没有被占用；更新后同步为静态分配（见缺口） | `FindInterfaceAddresses / FindIpAddress` | Core gRPC · 读 | `nico-admin-cli machine-interfaces show-addresses；nico-admin-cli ip find <IP>` | addresses[].{address,allocation_type}、matches[].{ip_type,owner_id,message} |
| 列表、状态、健康、地址和供电规格 | `FindPowerShelfIds → FindPowerShelvesByIds` | Core gRPC · 读 | `nico-admin-cli power-shelf list；nico-admin-cli power-shelf show <ID>` | id、rack_id、bmc_info.{ip,mac,firmware_version}、config.{capacity,voltage}、status.power_state、status.controller_state、status.state_reason、status.health |
| 槽位 | `GET /tray、GET /tray/{id}` | REST · 读 | `nicocli tray list --site-id <SITE> --rack-id <RACK>` | id、type（Compute、NVSwitch、PowerShelf）、position.{slotId,trayIdx,hostId}、firmwareVersion、powerState、operationStatus、leakStatus、bmcs、rackId、nvLinkDomainId、taskStats、health |
| 序列号 | `GetAllExpectedPowerShelves / GetAllExpectedPowerShelvesLinked` | Core gRPC · 读 | `nico-admin-cli expected-power-shelf show` | shelf_serial_number、bmc_mac_address、rack_id、linked: power_shelf_id、explored_endpoint_address |
| 电源状态 | `GetComponentPowerDetails / GetPowerOptions` | Core gRPC · 读 | `nico-admin-cli managed-host power-options show <MACHINE>` | entries[].actual.{state,source,observed_at}、entries[].desired.state、entries[].actions[].{status,operation,requested_at,initiator} |
| 固件版本 | `GetComponentInventory` | Core gRPC · 读 | — | entries[].result.{component_id,status,error}、entries[].report.firmware_versions、entries[].report.systems[]、entries[].report.chassis[] |
| 运行状态里的状态历史 | `FindMachineStateHistories / FindSwitchStateHistories / FindPowerShelfStateHistories` | Core gRPC · 读 | `nico-admin-cli machine show <ID> -c <条数>` | histories[id].records[].{state 或 event,version,time} |
| 上电、关机 | `PATCH /tray/{id}/power、PATCH /tray/power` | REST · 写 | `nicocli tray power --site-id <SITE> --data '{"state":"Off"}' <TRAY_ID>` | taskIds[] |
| 任务进度 | `GET /task、GET /rack/{id}/task、GET /tray/{id}/task、GET /task/{id}` | REST · 读 | `nicocli rack task get --site-id <SITE> <RACK_ID>` | id、status（Pending、Running、Succeeded、Failed、Terminated）、description、message、ruleId、started、finished、report |
| 退役 | `DecommissionSwitch / DecommissionPowerShelf / DecommissionManagedHost` | Core gRPC · 写 | `nico-admin-cli managed-switch decommission <SWITCH_ID>；nico-admin-cli power-shelf decommission <ID>；nico-admin-cli managed-host decommission <ID>` | — |
| 电源的直接执行路径（见缺口） | `SetPowerShelfMaintenance` | Core gRPC · 写 | `nico-admin-cli power-shelf maintenance power-off --power-shelf-id <ID> [--reference] [--graceful]；… power-on` | — |

### 运维 › 设备管理 › DPU

| 用途 | 接口 | 类型 | 命令行 | 用到的字段 |
| --- | --- | --- | --- | --- |
| BlueField 卡的部件号、序列号、网卡固件、工作方式和 BMC 地址（命令行 site-explorer mlx-devices 列的是同一批数据） | `FindExploredEndpointIds → FindExploredEndpointsByIds` | Core gRPC · 读 | `nico-admin-cli site-explorer get-report endpoint` | address、report.endpoint_type、report.vendor、report.systems[].serial_number、report.chassis[].serial_number、report.last_exploration_error_schema.{error_code,mitigation,text}、report.firmware_versions、preingestion_state、pause_remediation |
| 每台主机声明的 DPU 策略 | `GetAllExpectedMachines / GetAllExpectedMachinesLinked` | Core gRPC · 读 | `nico-admin-cli expected-machine show` | chassis_serial_number、bmc_mac_address、rack_id、bmc_ip_address、host_nics[]、metadata.labels、linked: interface_id、explored_endpoint_address、machine_id |
| 所属主机 | `FindMachineIds → FindMachinesByIds` | Core gRPC · 读 | `nico-admin-cli machine show [--hosts]` | id、rack_id、placement_in_rack.{slot_number,tray_index}、state、state_reason.{outcome,outcome_msg}、state_sla.time_in_state_above_sla、status.health.alerts[]、bmc.{ip,mac}、status.bmc_status.firmware_version、status.discovery_info.dmi_data.chassis_serial、status.associated_dpu_machine_ids、config.maintenance_reference、status.quarantine、status.nvlink_info.domain_uuid、status.lldp_neighbors[]、inventory.components[] |

### 运维 › 健康告警

| 用途 | 接口 | 类型 | 命令行 | 用到的字段 |
| --- | --- | --- | --- | --- |
| 各对象当前的告警与分类 | `ListMachineHealthReports / ListSwitchHealthReports / ListPowerShelfHealthReports / ListRackHealthReports / ListNVLinkDomainHealthReports` | Core gRPC · 读 | `nico-admin-cli machine health-report show <ID>；nico-admin-cli nvl-domain health-report show` | health_report_entries[].mode、report.source、report.alerts[].{id,target,in_alert_since,message,classifications[]} |
| 告警历史 | `FindMachineHealthHistories / FindSwitchHealthHistories / FindPowerShelfHealthHistories / FindRackHealthHistories` | Core gRPC · 读 | `nico-admin-cli machine health-history <ID>；nico-admin-cli rack health-history <RACK_ID>` | histories[id].records[].{health,time} |
| 机柜级告警 | `FindRackIds → FindRacksByIds` | Core gRPC · 读 | `nico-admin-cli rack list；nico-admin-cli rack show <RACK_ID>` | id、rack_group_id、status.lifecycle.{state,state_reason}、status.health、status.health_sources、metadata、created、updated |
| 有告警的计算托盘 | `FindMachineIds → FindMachinesByIds` | Core gRPC · 读 | `nico-admin-cli machine show [--hosts]` | id、rack_id、placement_in_rack.{slot_number,tray_index}、state、state_reason.{outcome,outcome_msg}、state_sla.time_in_state_above_sla、status.health.alerts[]、bmc.{ip,mac}、status.bmc_status.firmware_version、status.discovery_info.dmi_data.chassis_serial、status.associated_dpu_machine_ids、config.maintenance_reference、status.quarantine、status.nvlink_info.domain_uuid、status.lldp_neighbors[]、inventory.components[] |
| 有告警的交换机 | `FindSwitchIds → FindSwitchesByIds` | Core gRPC · 读 | `nico-admin-cli switch list；nico-admin-cli switch show <SWITCH_ID>` | id、rack_id、placement_in_rack、nvlink_domain_uuid、bmc_info.{ip,mac,firmware_version}、status.serial_number、status.power_state、status.controller_state、status.state_reason、status.health、status.fabric_manager_status_details、status.nvos_ports[].{mac,addresses,is_primary} |
| 有告警的供电框 | `FindPowerShelfIds → FindPowerShelvesByIds` | Core gRPC · 读 | `nico-admin-cli power-shelf list；nico-admin-cli power-shelf show <ID>` | id、rack_id、bmc_info.{ip,mac,firmware_version}、config.{capacity,voltage}、status.power_state、status.controller_state、status.state_reason、status.health |

### 运维 › 运维任务

| 用途 | 接口 | 类型 | 命令行 | 用到的字段 |
| --- | --- | --- | --- | --- |
| 任务、阶段和状态 | `GET /task、GET /rack/{id}/task、GET /tray/{id}/task、GET /task/{id}` | REST · 读 | `nicocli rack task get --site-id <SITE> <RACK_ID>` | id、status（Pending、Running、Succeeded、Failed、Terminated）、description、message、ruleId、started、finished、report |
| 取消任务 | `POST /task/{id}/cancel` | REST · 写 | `nicocli task cancel --site-id <SITE> <TASK_ID>` | status |

### 运维 › 操作审计

不调用 NICo，数据由平台自己保存。

### 交付 › 安装任务

| 用途 | 接口 | 类型 | 命令行 | 用到的字段 |
| --- | --- | --- | --- | --- |
| 可选的服务器：机柜里的计算托盘和不属于机柜的服务器 | `FindMachineIds → FindMachinesByIds` | Core gRPC · 读 | `nico-admin-cli machine show [--hosts]` | id、rack_id、placement_in_rack.{slot_number,tray_index}、state、state_reason.{outcome,outcome_msg}、state_sla.time_in_state_above_sla、status.health.alerts[]、bmc.{ip,mac}、status.bmc_status.firmware_version、status.discovery_info.dmi_data.chassis_serial、status.associated_dpu_machine_ids、config.maintenance_reference、status.quarantine、status.nvlink_info.domain_uuid、status.lldp_neighbors[]、inventory.components[] |
| “安装条件”一列：每台能不能装系统，被什么挡住 | `FindHostStatesByIds` | Core gRPC · 读 | — | state、state_reason、rack_id、nvlink_domain_id、bmc_ip、dpu_ids、health_alerts、quarantine、allocation.{allocatable,blocking_reason,blocking_detail}、explored.{bmc_version,uefi_version} |
| 机柜里的设备：所在机柜是否就绪 | `FindRackIds → FindRacksByIds` | Core gRPC · 读 | `nico-admin-cli rack list；nico-admin-cli rack show <RACK_ID>` | id、rack_group_id、status.lifecycle.{state,state_reason}、status.health、status.health_sources、metadata、created、updated |
| 整柜泄漏和阻止分配的告警 | `ListMachineHealthReports / ListSwitchHealthReports / ListPowerShelfHealthReports / ListRackHealthReports / ListNVLinkDomainHealthReports` | Core gRPC · 读 | `nico-admin-cli machine health-report show <ID>；nico-admin-cli nvl-domain health-report show` | health_report_entries[].mode、report.source、report.alerts[].{id,target,in_alert_since,message,classifications[]} |
| 已发布的安装方案，按架构列出 | `FindOperatingSystemIds → FindOperatingSystemsByIds` | Core gRPC · 读 | `nico-admin-cli operating-system show` | id、name、type、status、is_active、ipxe_template_id、ipxe_template_parameters、ipxe_template_artifacts[].{name,url,cached_url} |
| 已有的实例名称（主机名查重）和实例状态；安装条件检查：机器没有实例 | `FindInstanceIds → FindInstancesByIds / FindInstanceByMachineID` | Core gRPC · 读 | `nico-admin-cli instance show` | id、machine_id、config.tenant.{tenant_organization_id,hostname}、config.os、status.tenant.state、status.network、metadata |
| 安装条件检查：管理地址与地址占用 | `FindInterfaceAddresses / FindIpAddress` | Core gRPC · 读 | `nico-admin-cli machine-interfaces show-addresses；nico-admin-cli ip find <IP>` | addresses[].{address,allocation_type}、matches[].{ip_type,owner_id,message} |
| 核对配置：启动网口的 MAC | `FindInterfaces` | Core gRPC · 读 | `nico-admin-cli machine-interfaces show` | id、mac_address、address[]、segment_id、hostname、vendor、last_dhcp、machine_id、switch_id、power_shelf_id、association_type、interface_type、primary_interface |
| 安装条件检查：读硬件里的磁盘，按安装方案的规则解析系统盘 | `GetComponentInventory` | Core gRPC · 读 | — | entries[].result.{component_id,status,error}、entries[].report.firmware_versions、entries[].report.systems[]、entries[].report.chassis[] |
| 不属于机柜的服务器是否还在等待放行 | `DetermineMachineIngestionState` | Core gRPC · 读 | `nico-admin-cli managed-host power-options get-machine-ingestion-state --mac-address <MAC>` | NotDiscovered、WaitingForIngestion、IngestionMachineNotCreated、IngestionMachineCreated |
| 不属于机柜的服务器第一次装系统时放行，由 NICo 上电接管 | `AllowIngestionAndPowerOn` | Core gRPC · 写 | `nico-admin-cli managed-host power-options allow-ingestion-and-power-on --mac-address <MAC>` | — |
| 逐台建实例：机器 ID、主机名和系统；一次提交在一个事务里 | `AllocateInstances / AllocateInstance` | Core gRPC · 写 | `nico-admin-cli instance allocate --machine-id <ID>... --transactional --os <OS_ID> [--flat-vpc-id\|--vpc-prefix-id]` | instances[].{id,machine_id,status} |

### 交付 › 实例管理

| 用途 | 接口 | 类型 | 命令行 | 用到的字段 |
| --- | --- | --- | --- | --- |
| 实例名称、系统和状态 | `FindInstanceIds → FindInstancesByIds / FindInstanceByMachineID` | Core gRPC · 读 | `nico-admin-cli instance show` | id、machine_id、config.tenant.{tenant_organization_id,hostname}、config.os、status.tenant.state、status.network、metadata |
| 机器状态与回收进度 | `FindMachineIds → FindMachinesByIds` | Core gRPC · 读 | `nico-admin-cli machine show [--hosts]` | id、rack_id、placement_in_rack.{slot_number,tray_index}、state、state_reason.{outcome,outcome_msg}、state_sla.time_in_state_above_sla、status.health.alerts[]、bmc.{ip,mac}、status.bmc_status.firmware_version、status.discovery_info.dmi_data.chassis_serial、status.associated_dpu_machine_ids、config.maintenance_reference、status.quarantine、status.nvlink_info.domain_uuid、status.lldp_neighbors[]、inventory.components[] |
| 删除（退租回收） | `ReleaseInstance / ReleaseInstances` | Core gRPC · 写 | `nico-admin-cli instance release --instance <ID>` | results[].{id,status,error} |

### 接入 › 网络规划 › 子网

| 用途 | 接口 | 类型 | 命令行 | 用到的字段 |
| --- | --- | --- | --- | --- |
| 子网、状态和空闲地址 | `FindNetworkSegmentIds → FindNetworkSegmentsByIds` | Core gRPC · 读 | `nico-admin-cli network-segment show` | id、metadata.name、config.segment_type、config.mtu、config.subdomain_id、config.prefixes[].{prefix,gateway,reserve_first,free_ip_count_v2}、status.lifecycle.state |
| 新增子网 | `CreateNetworkSegment / CreateNetworkSegmentWithDhcpRange` | Core gRPC · 写 | `nico-admin-cli network-segment create --name --segment-type --prefix --gateway --reserve-first --mtu --subdomain-id` | — |
| 读取 DHCP 地址池 | `FindNetworkSegmentDhcpRanges` | Core gRPC · 读 | — | segment_id、prefix、range.{start,end}、revision |
| 修改 DHCP 地址池 | `SetNetworkSegmentDhcpRange` | Core gRPC · 写 | — | range.{start,end}、revision |
| 删除子网 | `DeleteNetworkSegment` | Core gRPC · 写 | `nico-admin-cli network-segment delete` | — |
| 规划检查：计算托盘接口的数量 | `GetAllExpectedMachines / GetAllExpectedMachinesLinked` | Core gRPC · 读 | `nico-admin-cli expected-machine show` | chassis_serial_number、bmc_mac_address、rack_id、bmc_ip_address、host_nics[]、metadata.labels、linked: interface_id、explored_endpoint_address、machine_id |
| 规划检查：交换机接口的数量 | `GetAllExpectedSwitches / GetAllExpectedSwitchesLinked` | Core gRPC · 读 | `nico-admin-cli expected-switch show` | switch_serial_number、bmc_mac_address、nvos_interfaces[]、rack_id、linked: switch_id、explored_endpoint_address |
| 规划检查：供电框接口的数量 | `GetAllExpectedPowerShelves / GetAllExpectedPowerShelvesLinked` | Core gRPC · 读 | `nico-admin-cli expected-power-shelf show` | shelf_serial_number、bmc_mac_address、rack_id、linked: power_shelf_id、explored_endpoint_address |

### 接入 › 网络规划 › DHCP 服务

| 用途 | 接口 | 类型 | 命令行 | 用到的字段 |
| --- | --- | --- | --- | --- |
| DHCP 服务器地址 | `Version` | Core gRPC · 读 | `nico-admin-cli version --show-runtime-config` | build_version、git_sha、capabilities[]、runtime_config.dhcp_servers、runtime_config.networks、runtime_config.initial_domain_name、runtime_config.attestation_enabled |
| 各子网的地址余量 | `FindNetworkSegmentIds → FindNetworkSegmentsByIds` | Core gRPC · 读 | `nico-admin-cli network-segment show` | id、metadata.name、config.segment_type、config.mtu、config.subdomain_id、config.prefixes[].{prefix,gateway,reserve_first,free_ip_count_v2}、status.lifecycle.state |
| 各子网的地址池范围 | `FindNetworkSegmentDhcpRanges` | Core gRPC · 读 | — | segment_id、prefix、range.{start,end}、revision |
| 各子网最近一次请求 | `FindInterfaces` | Core gRPC · 读 | `nico-admin-cli machine-interfaces show` | id、mac_address、address[]、segment_id、hostname、vendor、last_dhcp、machine_id、switch_id、power_shelf_id、association_type、interface_type、primary_interface |
| 请求、应答和丢弃计数 | `carbide_dhcp_requests_total、carbide_dhcp_dropped_requests_total、carbide_dhcp_replies_sent_total、carbide_available_ips_count` | 指标 · 读 | — | message_type、reason、name、type、prefix |

### 接入 › 网络规划 › 地址分配

| 用途 | 接口 | 类型 | 命令行 | 用到的字段 |
| --- | --- | --- | --- | --- |
| 地址、MAC、归属和最近请求 | `FindInterfaces` | Core gRPC · 读 | `nico-admin-cli machine-interfaces show` | id、mac_address、address[]、segment_id、hostname、vendor、last_dhcp、machine_id、switch_id、power_shelf_id、association_type、interface_type、primary_interface |
| 分配方式，按地址反查归属 | `FindInterfaceAddresses / FindIpAddress` | Core gRPC · 读 | `nico-admin-cli machine-interfaces show-addresses；nico-admin-cli ip find <IP>` | addresses[].{address,allocation_type}、matches[].{ip_type,owner_id,message} |

### 接入 › 设备清单 › 到货清单

| 用途 | 接口 | 类型 | 命令行 | 用到的字段 |
| --- | --- | --- | --- | --- |
| 核对清单里的机柜拓扑和厂商能推导出已配置的机柜规格 | `ListRackProfiles / GetRackProfile` | Core gRPC · 读 | `nico-admin-cli rack profile list；nico-admin-cli rack profile show <RACK_ID>` | rack_profile_id、profile.rack_hardware_topology、profile.capabilities.{compute,switch,power_shelf}.count、profile.product_family |
| 哪些机柜组已经写入 | `GetAllExpectedRackGroups` | Core gRPC · 读 | `nico-admin-cli expected-rack-group show` | rack_group_id、topology、protocol、racks[].rack_id、racks[].members[].{type,manufacturer,id} |
| 哪些机柜的声明已经写入 | `GetAllExpectedRacks` | Core gRPC · 读 | `nico-admin-cli expected-rack show` | rack_id、rack_profile_id、rack_group_id、metadata |
| 哪些计算托盘已经写入 NICo | `GetAllExpectedMachines / GetAllExpectedMachinesLinked` | Core gRPC · 读 | `nico-admin-cli expected-machine show` | chassis_serial_number、bmc_mac_address、rack_id、bmc_ip_address、host_nics[]、metadata.labels、linked: interface_id、explored_endpoint_address、machine_id |
| 哪些交换机已经写入 NICo | `GetAllExpectedSwitches / GetAllExpectedSwitchesLinked` | Core gRPC · 读 | `nico-admin-cli expected-switch show` | switch_serial_number、bmc_mac_address、nvos_interfaces[]、rack_id、linked: switch_id、explored_endpoint_address |
| 哪些供电框已经写入 NICo | `GetAllExpectedPowerShelves / GetAllExpectedPowerShelvesLinked` | Core gRPC · 读 | `nico-admin-cli expected-power-shelf show` | shelf_serial_number、bmc_mac_address、rack_id、linked: power_shelf_id、explored_endpoint_address |
| 导入预览：各用途的地址够不够 | `FindNetworkSegmentIds → FindNetworkSegmentsByIds` | Core gRPC · 读 | `nico-admin-cli network-segment show` | id、metadata.name、config.segment_type、config.mtu、config.subdomain_id、config.prefixes[].{prefix,gateway,reserve_first,free_ip_count_v2}、status.lifecycle.state |

### 接入 › 设备清单 › 版本记录

不调用 NICo，数据由平台自己保存。

### 接入 › 设备发现

| 用途 | 接口 | 类型 | 命令行 | 用到的字段 |
| --- | --- | --- | --- | --- |
| 拿到了地址、但还没有归属的接口，以及最近一次申请地址的时间 | `FindInterfaces` | Core gRPC · 读 | `nico-admin-cli machine-interfaces show` | id、mac_address、address[]、segment_id、hostname、vendor、last_dhcp、machine_id、switch_id、power_shelf_id、association_type、interface_type、primary_interface |
| 机柜已确认纳管时，新匹配上的计算托盘直接写入：MAC、凭据、序列号、机柜、槽位和 DPU 策略。不属于机柜的服务器逐台确认纳管时写入，不带机柜，带暂停标记 | `CreateExpectedMachines / UpdateExpectedMachines / PatchExpectedMachine / DeleteExpectedMachine` | Core gRPC · 写 | `nico-admin-cli expected-machine add -a <BMC_MAC> -u <BMC_USER> -p <BMC_PASS> -s <SERIAL> [--rack_id] [--bmc-ip-address] [--interfaces] [--label]` | — |
| 机柜已确认纳管时，新匹配上的交换机直接写入：BMC 与 NVOS 管理口的 MAC、两组凭据 | `AddExpectedSwitch / PatchExpectedSwitch / DeleteExpectedSwitch` | Core gRPC · 写 | `nico-admin-cli expected-switch add -a <BMC_MAC> -u <USER> -p <PASS> -s <SERIAL> --nvos-interface <MAC[,primary]> [--rack_id]` | — |
| 机柜已确认纳管时，新匹配上的供电框直接写入 | `AddExpectedPowerShelf / PatchExpectedPowerShelf / DeleteExpectedPowerShelf` | Core gRPC · 写 | `nico-admin-cli expected-power-shelf add -a <BMC_MAC> -u <USER> -p <PASS> -s <SERIAL> [--rack_id]` | — |
| 机柜的声明齐了之后写入 NVLink 域声明 | `CreateExpectedNvLinkDomain / DeleteExpectedNvLinkDomain / FindExpectedNvLinkDomainIds` | Core gRPC · 写 | `nico-admin-cli expected-nvlink-domain create --member <MAC>... [--name] <RACK_GROUP_ID>` | — |
| 计算托盘声明走到了哪一步 | `GetAllExpectedMachines / GetAllExpectedMachinesLinked` | Core gRPC · 读 | `nico-admin-cli expected-machine show` | chassis_serial_number、bmc_mac_address、rack_id、bmc_ip_address、host_nics[]、metadata.labels、linked: interface_id、explored_endpoint_address、machine_id |
| 交换机声明走到了哪一步 | `GetAllExpectedSwitches / GetAllExpectedSwitchesLinked` | Core gRPC · 读 | `nico-admin-cli expected-switch show` | switch_serial_number、bmc_mac_address、nvos_interfaces[]、rack_id、linked: switch_id、explored_endpoint_address |
| 供电框声明走到了哪一步 | `GetAllExpectedPowerShelves / GetAllExpectedPowerShelvesLinked` | Core gRPC · 读 | `nico-admin-cli expected-power-shelf show` | shelf_serial_number、bmc_mac_address、rack_id、linked: power_shelf_id、explored_endpoint_address |
| NICo 的探测结果和失败原因 | `FindExploredEndpointIds → FindExploredEndpointsByIds` | Core gRPC · 读 | `nico-admin-cli site-explorer get-report endpoint` | address、report.endpoint_type、report.vendor、report.systems[].serial_number、report.chassis[].serial_number、report.last_exploration_error_schema.{error_code,mitigation,text}、report.firmware_versions、preingestion_state、pause_remediation |
| 主机的接管进度 | `FindExploredManagedHostIds → FindExploredManagedHostsByIds` | Core gRPC · 读 | `nico-admin-cli site-explorer get-report managed-host` | host_bmc_ip、dpus[].{bmc_ip,host_pf_mac_address} |
| NICo 探测到、但没有声明的主机 | `GetAllUnexpectedMachines` | Core gRPC · 读 | — | address、bmc_mac_address、machine_id |
| 重新探测、清除探测错误 | `ReExploreEndpoint / RefreshEndpointReport / ClearSiteExplorationError` | Core gRPC · 写 | `nico-admin-cli site-explorer re-explore；nico-admin-cli site-explorer refresh；nico-admin-cli site-explorer clear-error` | — |
| 是否在等待放行 | `DetermineMachineIngestionState` | Core gRPC · 读 | `nico-admin-cli managed-host power-options get-machine-ingestion-state --mac-address <MAC>` | NotDiscovered、WaitingForIngestion、IngestionMachineNotCreated、IngestionMachineCreated |
| 放行等待中的主机 | `AllowIngestionAndPowerOn` | Core gRPC · 写 | `nico-admin-cli managed-host power-options allow-ingestion-and-power-on --mac-address <MAC>` | — |
| 计算托盘的状态 | `FindMachineIds → FindMachinesByIds` | Core gRPC · 读 | `nico-admin-cli machine show [--hosts]` | id、rack_id、placement_in_rack.{slot_number,tray_index}、state、state_reason.{outcome,outcome_msg}、state_sla.time_in_state_above_sla、status.health.alerts[]、bmc.{ip,mac}、status.bmc_status.firmware_version、status.discovery_info.dmi_data.chassis_serial、status.associated_dpu_machine_ids、config.maintenance_reference、status.quarantine、status.nvlink_info.domain_uuid、status.lldp_neighbors[]、inventory.components[] |
| 交换机的状态 | `FindSwitchIds → FindSwitchesByIds` | Core gRPC · 读 | `nico-admin-cli switch list；nico-admin-cli switch show <SWITCH_ID>` | id、rack_id、placement_in_rack、nvlink_domain_uuid、bmc_info.{ip,mac,firmware_version}、status.serial_number、status.power_state、status.controller_state、status.state_reason、status.health、status.fabric_manager_status_details、status.nvos_ports[].{mac,addresses,is_primary} |
| 供电框的状态 | `FindPowerShelfIds → FindPowerShelvesByIds` | Core gRPC · 读 | `nico-admin-cli power-shelf list；nico-admin-cli power-shelf show <ID>` | id、rack_id、bmc_info.{ip,mac,firmware_version}、config.{capacity,voltage}、status.power_state、status.controller_state、status.state_reason、status.health |
| 最近一次扫描 | `GetSiteExplorerLastRun` | Core gRPC · 读 | — | started_at、finished_at、success、error、endpoint_explorations、endpoint_explorations_success、endpoint_explorations_failed、failure_category、last_successful_finished_at |

### 配置 › 站点设置 › 站点概况

| 用途 | 接口 | 类型 | 命令行 | 用到的字段 |
| --- | --- | --- | --- | --- |
| Core 版本与运行配置 | `Version` | Core gRPC · 读 | `nico-admin-cli version --show-runtime-config` | build_version、git_sha、capabilities[]、runtime_config.dhcp_servers、runtime_config.networks、runtime_config.initial_domain_name、runtime_config.attestation_enabled |
| RMS 是否就绪 | `GetRmsVersion` | Core gRPC · 读 | `nico-admin-cli backend rms status` | status、message、version |
| Flow 与站点代理是否在线 | `GET /site、GET /site/{id}` | REST · 读 | `nicocli site list` | id、status（Pending、Registered、Error）、isOnline、siteAgentVersion、siteControllerVersion、capabilities.flow、machineStats |
| NMX-C 接入 | `ListNvlinkNmxcEndpoints` | Core gRPC · 读 | `nico-admin-cli nvlink-nmxc-endpoints` | chassis_serial、endpoint |
| 站点发现最近一次扫描 | `GetSiteExplorerLastRun` | Core gRPC · 读 | — | started_at、finished_at、success、error、endpoint_explorations、endpoint_explorations_success、endpoint_explorations_failed、failure_category、last_successful_finished_at |
| 开关站点发现和自动建机 | `SetDynamicConfig` | Core gRPC · 写 | — | — |
| 接管凭据是否齐备 | `GetSiteCredentialReadiness` | Core gRPC · 读 | — | configured[]、missing[]、requires_recovery[] |
| 补齐接管凭据 | `InitializeSiteCredentials / CreateCredential` | Core gRPC · 写 | `nico-admin-cli credential add-bmc；nico-admin-cli credential add-uefi` | — |
| 支持的机柜规格 | `ListRackProfiles / GetRackProfile` | Core gRPC · 读 | `nico-admin-cli rack profile list；nico-admin-cli rack profile show <RACK_ID>` | rack_profile_id、profile.rack_hardware_topology、profile.capabilities.{compute,switch,power_shelf}.count、profile.product_family |
| 生效的电源和固件规则 | `GET /task/rule` | REST · 读 | `nicocli rule list --site-id <SITE>` | id、name、operationType、operationCode、isDefault、ruleDefinition.steps[] |

### 配置 › 站点设置 › 控制面

| 用途 | 接口 | 类型 | 命令行 | 用到的字段 |
| --- | --- | --- | --- | --- |
| Core 版本 | `Version` | Core gRPC · 读 | `nico-admin-cli version --show-runtime-config` | build_version、git_sha、capabilities[]、runtime_config.dhcp_servers、runtime_config.networks、runtime_config.initial_domain_name、runtime_config.attestation_enabled |
| RMS 版本 | `GetRmsVersion` | Core gRPC · 读 | `nico-admin-cli backend rms status` | status、message、version |
| 站点代理与 Flow 的版本和在线状态 | `GET /site、GET /site/{id}` | REST · 读 | `nicocli site list` | id、status（Pending、Registered、Error）、isOnline、siteAgentVersion、siteControllerVersion、capabilities.flow、machineStats |

### 配置 › 固件基线

| 用途 | 接口 | 类型 | 命令行 | 用到的字段 |
| --- | --- | --- | --- | --- |
| 机柜规格 | `ListRackProfiles / GetRackProfile` | Core gRPC · 读 | `nico-admin-cli rack profile list；nico-admin-cli rack profile show <RACK_ID>` | rack_profile_id、profile.rack_hardware_topology、profile.capabilities.{compute,switch,power_shelf}.count、profile.product_family |
| NICo 里配置的期望版本和可用固件包 | `GetDesiredFirmwareVersions / ListComponentFirmwareVersions` | Core gRPC · 读 | `nico-admin-cli component-manager get-firmware-versions {compute-tray\|switch\|power-shelf\|rack}` | entries[].{vendor,model,component_versions}、devices[].versions[]、devices[].compute_fw_versions[] |
| 偏差统计：探测到的版本 | `GetComponentInventory` | Core gRPC · 读 | — | entries[].result.{component_id,status,error}、entries[].report.firmware_versions、entries[].report.systems[]、entries[].report.chassis[] |

### 配置 › 安装方案

| 用途 | 接口 | 类型 | 命令行 | 用到的字段 |
| --- | --- | --- | --- | --- |
| 方案列表与状态 | `FindOperatingSystemIds → FindOperatingSystemsByIds` | Core gRPC · 读 | `nico-admin-cli operating-system show` | id、name、type、status、is_active、ipxe_template_id、ipxe_template_parameters、ipxe_template_artifacts[].{name,url,cached_url} |
| 新建、修改和停用方案 | `CreateOperatingSystem / UpdateOperatingSystem / DeleteOperatingSystem` | Core gRPC · 写 | `nico-admin-cli operating-system create；nico-admin-cli operating-system set-cached-url` | — |
