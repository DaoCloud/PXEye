# 整机柜运维接口契约

[设计稿说明](README.zh-CN.md) · [页面功能说明](page-spec.zh-CN.md) · [设计文档](../README.zh-CN.md)

本文件由 `tools/build-spec.mjs` 从 `contract.js` 生成，不要直接修改。它是内部实现参考，不用于对外展示；可点击的版本是 `internal.html`。

每个页面调用 NICo 的哪些接口、对应什么命令行、用到哪些字段，以及要让页面有数据必须先准备好哪些资源。接口、参数和字段取自 NICo 源码 `dsx-ai-factory/infra-controller` 的提交 `856eb1665`（v2.5.0 之后）。接口、参数和字段取自这个提交的源码。换版本时逐项重新核对。

证据等级：**定义** = 只读过源码里的定义；**模拟** = 在模拟环境里调用过；**现场** = 在真实整机柜环境核对过。共 36 个资源、80 个接口（其中写操作 35 个，现有产品已调用 43 个）、18 个缺口。

## 各页面的接口数与前置资源

| 页面 | 读 | 写 | 前置资源（按准备顺序） |
| --- | --- | --- | --- |
| 运维 › 机柜管理 | 5 | 0 | NICo Core → 正向 DNS 域 → VLAN 与 VNI 资源池 → 机柜规格配置 → 站点默认凭据 → DHCP 与引导服务 → RMS → 组件管理器 → REST 身份认证 → REST 站点 → Flow → 子网 → 机柜组声明 → 机柜声明 → 设备声明 → 现场 DHCP 中继 → 设备接口与地址 → 探测结果 → 交换机对象 → 机柜对象 → Flow 的机柜与托盘清单 → 任务 |
| 运维 › 机柜管理 › 机柜详情 | 14 | 8 | NICo Core → 正向 DNS 域 → VLAN 与 VNI 资源池 → 机柜规格配置 → 机柜固件清单 → 站点默认凭据 → DHCP 与引导服务 → RMS → 组件管理器 → REST 身份认证 → REST 站点 → Flow → 操作规则 → 子网 → 机柜组声明 → 机柜声明 → 设备声明 → 现场 DHCP 中继 → 设备接口与地址 → 探测结果 → 计算托盘对象 → 交换机对象 → 供电框对象 → 机柜对象 → Flow 的机柜与托盘清单 → 任务 → 健康报告 |
| 运维 › NVLink 域管理 | 5 | 3 | NICo Core → 正向 DNS 域 → VLAN 与 VNI 资源池 → 机柜规格配置 → 机柜固件清单 → 站点默认凭据 → DHCP 与引导服务 → RMS → 组件管理器 → REST 身份认证 → REST 站点 → Flow → 操作规则 → NMX-C 接入 → 子网 → 机柜组声明 → 机柜声明 → 设备声明 → 现场 DHCP 中继 → 设备接口与地址 → 探测结果 → 计算托盘对象 → 交换机对象 → 机柜对象 → Flow 的机柜与托盘清单 → 任务 → NVLink 域 → 健康报告 |
| 运维 › 设备管理 | 5 | 0 | NICo Core → 正向 DNS 域 → VLAN 与 VNI 资源池 → 机柜规格配置 → 站点默认凭据 → DHCP 与引导服务 → RMS → 组件管理器 → 子网 → 设备声明 → 现场 DHCP 中继 → 设备接口与地址 → 探测结果 → 计算托盘对象 → DPU 对象 → 交换机对象 → 供电框对象 |
| 运维 › 设备管理 › 计算托盘 | 7 | 8 | NICo Core → 正向 DNS 域 → VLAN 与 VNI 资源池 → 机柜规格配置 → 机柜固件清单 → 站点默认凭据 → DHCP 与引导服务 → RMS → 组件管理器 → REST 身份认证 → REST 站点 → Flow → 子网 → 机柜组声明 → 机柜声明 → 设备声明 → 现场 DHCP 中继 → 设备接口与地址 → 探测结果 → 计算托盘对象 → 交换机对象 → 机柜对象 → Flow 的机柜与托盘清单 → 任务 → 系统定义 → 租户与 VPC → 实例 |
| 运维 › 设备管理 › 交换机 | 5 | 5 | NICo Core → 正向 DNS 域 → VLAN 与 VNI 资源池 → 机柜规格配置 → 机柜固件清单 → 站点默认凭据 → DHCP 与引导服务 → RMS → 组件管理器 → REST 身份认证 → REST 站点 → Flow → 子网 → 机柜组声明 → 机柜声明 → 设备声明 → 现场 DHCP 中继 → 设备接口与地址 → 探测结果 → 计算托盘对象 → 交换机对象 → 机柜对象 → Flow 的机柜与托盘清单 → 任务 |
| 运维 › 设备管理 › 供电框 | 7 | 3 | NICo Core → 正向 DNS 域 → VLAN 与 VNI 资源池 → 机柜规格配置 → 站点默认凭据 → DHCP 与引导服务 → RMS → 组件管理器 → REST 身份认证 → REST 站点 → Flow → 子网 → 机柜组声明 → 机柜声明 → 设备声明 → 现场 DHCP 中继 → 设备接口与地址 → 探测结果 → 计算托盘对象 → 交换机对象 → 供电框对象 → 机柜对象 → Flow 的机柜与托盘清单 → 任务 |
| 运维 › 设备管理 › DPU | 2 | 0 | NICo Core → 正向 DNS 域 → VLAN 与 VNI 资源池 → 站点默认凭据 → DHCP 与引导服务 → 子网 → 设备声明 → 现场 DHCP 中继 → 设备接口与地址 → 探测结果 → 计算托盘对象 → DPU 对象 |
| 运维 › 健康告警 | 6 | 0 | NICo Core → 正向 DNS 域 → VLAN 与 VNI 资源池 → 机柜规格配置 → 站点默认凭据 → DHCP 与引导服务 → RMS → 组件管理器 → 子网 → 机柜组声明 → 机柜声明 → 设备声明 → 现场 DHCP 中继 → 设备接口与地址 → 探测结果 → 计算托盘对象 → 交换机对象 → 供电框对象 → 机柜对象 → 健康报告 |
| 运维 › 运维任务 | 1 | 1 | NICo Core → 正向 DNS 域 → VLAN 与 VNI 资源池 → 机柜规格配置 → 站点默认凭据 → DHCP 与引导服务 → RMS → 组件管理器 → REST 身份认证 → REST 站点 → Flow → 子网 → 机柜组声明 → 机柜声明 → 设备声明 → 现场 DHCP 中继 → 设备接口与地址 → 探测结果 → 交换机对象 → 机柜对象 → Flow 的机柜与托盘清单 → 任务 |
| 运维 › 操作审计 | 0 | 0 | 不调用 NICo，数据由平台自己保存 |
| 交付 › 机柜交付 | 6 | 2 | NICo Core → 正向 DNS 域 → VLAN 与 VNI 资源池 → 机柜规格配置 → 站点默认凭据 → DHCP 与引导服务 → RMS → 组件管理器 → 子网 → 机柜组声明 → 机柜声明 → 设备声明 → 现场 DHCP 中继 → 设备接口与地址 → 探测结果 → 计算托盘对象 → 交换机对象 → 机柜对象 → 系统定义 → 租户与 VPC → 实例 → 健康报告 |
| 交付 › 安装任务 | 2 | 0 | NICo Core → 正向 DNS 域 → VLAN 与 VNI 资源池 → 站点默认凭据 → DHCP 与引导服务 → 子网 → 设备声明 → 现场 DHCP 中继 → 设备接口与地址 → 探测结果 → 计算托盘对象 → 系统定义 → 租户与 VPC → 实例 |
| 交付 › 实例管理 | 2 | 1 | NICo Core → 正向 DNS 域 → VLAN 与 VNI 资源池 → 站点默认凭据 → DHCP 与引导服务 → 子网 → 设备声明 → 现场 DHCP 中继 → 设备接口与地址 → 探测结果 → 计算托盘对象 → 系统定义 → 租户与 VPC → 实例 |
| 接入 › 网络规划 › 子网 | 5 | 3 | NICo Core → 正向 DNS 域 → VLAN 与 VNI 资源池 → 子网 → 设备声明 |
| 接入 › 网络规划 › DHCP 服务 | 5 | 0 | NICo Core → 正向 DNS 域 → VLAN 与 VNI 资源池 → DHCP 与引导服务 → 子网 → 现场 DHCP 中继 → 设备接口与地址 |
| 接入 › 网络规划 › 地址分配 | 2 | 0 | NICo Core → 正向 DNS 域 → VLAN 与 VNI 资源池 → DHCP 与引导服务 → 子网 → 现场 DHCP 中继 → 设备接口与地址 |
| 接入 › 设备清单 › 期望清单 | 7 | 6 | NICo Core → 正向 DNS 域 → VLAN 与 VNI 资源池 → 机柜规格配置 → 子网 → 机柜组声明 → 机柜声明 → 设备声明 |
| 接入 › 设备清单 › 版本记录 | 0 | 0 | 不调用 NICo，数据由平台自己保存 |
| 接入 › 设备发现 | 12 | 0 | NICo Core → 正向 DNS 域 → VLAN 与 VNI 资源池 → 机柜规格配置 → 站点默认凭据 → DHCP 与引导服务 → RMS → 组件管理器 → 子网 → 设备声明 → 现场 DHCP 中继 → 设备接口与地址 → 探测结果 → 计算托盘对象 → 交换机对象 → 供电框对象 |
| 配置 › 站点设置 › 站点概况 | 8 | 2 | NICo Core → 机柜规格配置 → RMS → 组件管理器 → REST 身份认证 → REST 站点 → Flow → 操作规则 → NMX-C 接入 |
| 配置 › 站点设置 › 控制面 | 3 | 0 | NICo Core → 机柜规格配置 → RMS → REST 身份认证 → REST 站点 |
| 配置 › 固件基线 | 3 | 0 | NICo Core → 正向 DNS 域 → VLAN 与 VNI 资源池 → 机柜规格配置 → 站点默认凭据 → DHCP 与引导服务 → RMS → 组件管理器 → 子网 → 设备声明 → 现场 DHCP 中继 → 设备接口与地址 → 探测结果 |
| 配置 › 安装方案 | 1 | 1 | NICo Core → 系统定义 |

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
| 8 | RMS | `Rack Management Service` | 独立部署，在站点配置 [rms] 里填它的地址 | 机柜规格配置 | 部署时配置：没有硬件时接 RMS 模拟服务 | 任一后端选了 rms，启动时就要求机柜规格配置里有产品系列和厂商 | `docs/configuration/rms.md:243` |
| 9 | 组件管理器 | `[component_manager]` | 站点配置里为计算托盘、交换机、供电框各选一个后端，默认都是 rms | RMS | 部署时配置 | 没有这段配置时，设备电源、复位、固件接口返回未实现。当前生效的后端没有读取接口 | `crates/api-core/src/handlers/component_manager.rs:130` |
| 10 | REST 身份认证 | `JWT 签发方与声明映射` | REST 的部署配置：外部签发方或内置 Keycloak，二选一；从声明映射出组织名和角色 | — | 部署时配置 |  | `rest-api/openapi/auth.md:43` |
| 11 | REST 站点 | `Infrastructure Provider、Site、站点代理` | 部署 Temporal 并建好命名空间；调用一次 GET /infrastructure-provider/current；POST /site；再把站点注册信息写进站点代理 | NICo Core、REST 身份认证 | 可直接创建 | 机柜、托盘、域和任务接口都要带 siteId。站点代理上线后回报是否启用了 Flow | `rest-api/INSTALLATION.md:773` |
| 12 | Flow | `nico-flow` | 独立部署；站点代理里配置 Flow 地址；Core 的权限表给 Flow 身份放行设备电源和固件接口 | REST 站点、组件管理器 | 部署时配置 | REST 经 Temporal 和站点代理转发到 Flow。直接访问 Flow 要用双向证书，并且身份在允许名单里 | `docs/architecture/flow.md:3` |
| 13 | 操作规则 | `OperationRule` | 默认规则写在 Flow 的代码里；自定义规则用 POST /task/rule 创建，只有电源和固件两类 | Flow | NICo 自动生成 | 选用顺序：请求里指定的规则、机柜关联的规则、该类操作的全局默认、内置规则 | `docs/operations/flow/operation-rules.md:553` |
| 14 | NMX-C 接入 | `NvlinkNmxcEndpoint` | CreateNvlinkNmxcEndpoint：机箱序列号和 NMX-C 地址 | NICo Core | 可直接创建：没有硬件时接 NMX-C 模拟服务 | 没有专门的状态接口，只能从机柜健康报告里的 NmxcUnreachable 判断 | `crates/rpc/proto/forge.proto:1116` |
| 15 | 子网 | `NetworkSegment` | 站点配置 [networks.<名称>] 在启动时创建并直接就绪；或 CreateNetworkSegment，创建后由控制器从 Provisioning 转为 Ready | 正向 DNS 域、VLAN 与 VNI 资源池 | 可直接创建 | 没有修改接口。创建后只能给带外管理子网补另一个地址族、改 IPv4 的 DHCP 地址池、改 VPC 挂接；配置文件后续的修改不会更新已创建的子网 | `crates/rpc/proto/forge.proto:129` |
| 16 | 机柜组声明 | `ExpectedRackGroup` | AddExpectedRackGroup：拓扑、协议、每个机柜及其成员的类型和厂商 | NICo Core | 可直接创建 | 成员只是（类型、厂商、编号）三元组，只用于推导机柜规格，不与设备声明关联 | `crates/rpc/proto/forge.proto:3528` |
| 17 | 机柜声明 | `ExpectedRack` | AddExpectedRack：只需机柜 ID；规格和所属机柜组由 NICo 推导 | 机柜组声明、机柜规格配置 | 可直接创建 | 要求恰好一个机柜组包含这个机柜 ID，且该机柜至少有一个计算成员和一个交换机成员 | `crates/api-core/src/handlers/expected_rack.rs:29` |
| 18 | 设备声明 | `ExpectedMachine / ExpectedSwitch / ExpectedPowerShelf` | 逐条新增或批量新增：BMC MAC、序列号、机柜 ID、出厂凭据；交换机另需 NVOS 管理口 | NICo Core | 可直接创建 | 新增时不校验机柜、子网和凭据是否存在；机柜 ID 是自由文本 | `crates/api-core/src/handlers/expected_machine.rs:77` |
| 19 | NVLink 域声明 | `ExpectedNvLinkDomain` | CreateExpectedNvLinkDomain：机柜组 ID 和成员的 BMC MAC；创建后不可修改，只能删除重建 | 机柜组声明、设备声明 | 可直接创建 | 每个 MAC 必须对应机柜组内某个机柜里的计算托盘或交换机声明，且至少各有一个 | `crates/api-db/src/expected_nvlink_domain.rs:19` |
| 20 | 现场 DHCP 中继 | `—` | 现场网络设备把各管理网段的 DHCP 请求中继到 NICo 的 DHCP 服务 | 子网、DHCP 与引导服务 | 只有真实硬件才有：模拟器直接带着中继地址调用 Core，不经过真实网络 | NICo 按中继地址落在哪个子网前缀里来选子网，不看网关 | `crates/api-core/src/dhcp/discover.rs:563` |
| 21 | 设备接口与地址 | `MachineInterface` | 设备发出 DHCP 请求时由 Core 创建；声明了固定地址的接口由站点发现预先创建 | 现场 DHCP 中继 | 需要模拟器或真实硬件 | 没有声明的设备也会拿到地址，留下一条没有归属的接口记录 | `crates/api-core/src/dhcp/discover.rs:716` |
| 22 | 探测结果 | `ExploredEndpoint` | 站点发现按周期用 Redfish 探测带外管理子网上的接口 | 设备接口与地址、站点默认凭据、设备声明 | 需要模拟器或真实硬件 | 主机 BMC 要用设备声明里的出厂凭据，没有声明就报缺少凭据；一次认证失败后停止重试，直到清除错误 | `crates/site-explorer/src/bmc_endpoint_explorer.rs:445` |
| 23 | 计算托盘对象 | `Machine（主机）` | 站点发现在预检完成、主机与 DPU 配对成功后创建，随后由状态机推进到 Ready | 探测结果 | 需要模拟器或真实硬件 | 设备声明带暂停标记时要先放行；开启度量启动时还要人工批准 | `crates/site-explorer/src/lib.rs:3234` |
| 24 | DPU 对象 | `Machine（类型 DPU）` | DPU 的 BMC 被探测到并与主机配对后，随主机一起创建 | 探测结果 | 需要模拟器或真实硬件 | DPU 不需要设备声明，用出厂凭据探测；与主机按序列号配对 | `crates/site-explorer/src/lib.rs:1196` |
| 25 | 交换机对象 | `Switch` | 站点发现探测到与交换机声明匹配的 BMC 后创建 | 探测结果、组件管理器 | 需要模拟器或真实硬件 | 需要声明里的 NVOS 管理口 MAC 和主口，且该管理口已拿到地址，否则状态机进入 Error；随后的证书和口令配置经过硬件后端 | `crates/switch-controller/src/initializing.rs:48` |
| 26 | 供电框对象 | `PowerShelf` | 站点发现探测到与供电框声明匹配的 PMC 后创建 | 探测结果 | 需要模拟器或真实硬件 |  | `crates/site-explorer/src/inventory_creator/power_shelf_creator.rs:121` |
| 27 | 机柜对象 | `Rack` | 某个成员设备被接管时，如果它的机柜声明存在，由站点发现创建；没有创建接口 | 机柜声明、交换机对象 | NICo 自动生成 | 状态机只看交换机数量：发现的交换机数达到规格要求进入 Discovering，就绪的交换机数达到要求进入 Maintenance。计算托盘和供电框的数量不是条件 | `docs/architecture/state_machines/rackstatemachine.md:142` |
| 28 | Flow 的机柜与托盘清单 | `Rack / Tray（REST）` | Flow 从 Core 同步机柜、设备和设备声明 | Flow、机柜对象 | NICo 自动生成 | REST 的机柜、托盘、域读的是这份清单，不是直接读 Core。单个机柜的操作按外部 ID 定位，批量操作按机柜名定位 | `rest-api/api/pkg/api/handler/rack.go:154` |
| 29 | 任务 | `Task` | 机柜、托盘、域的每个写操作都返回任务编号，每个机柜一个任务 | Flow 的机柜与托盘清单 | NICo 自动生成 | REST 的返回只表示任务已创建。要轮询任务直到成功、失败或终止 | `rest-api/openapi/spec.yaml:28731` |
| 30 | NVLink 域 | `NVLinkDomain（REST）、nvlink_domain_uuid（Core）` | REST 的域编号就是机柜组编号；Core 一侧在机柜上线配置好 NMX-C 集群后，在交换机和计算托盘上回报域 UUID | 机柜组声明、Flow 的机柜与托盘清单、NMX-C 接入 | 需要模拟器或真实硬件 |  | `rest-api/openapi/spec.yaml:27724` |
| 31 | 系统定义 | `OperatingSystem` | CreateOperatingSystem：直接给 iPXE 脚本，或选一个内置 iPXE 模板并填参数和制品地址 | NICo Core | 可直接创建 | 脚本方式创建后立即可用。模板方式里标为“只用缓存”的制品，要由外部程序下载后回填缓存地址，系统定义才变为可用；NICo 不下载制品 | `docs/configuration/templated-ipxe-operating-systems.md:263` |
| 32 | 租户与 VPC | `Tenant、Vpc` | CreateTenant、CreateVpc。计算托盘的 DPU 处于 DPU 模式时用 FNN 或 ETHERNET_VIRTUALIZER，网卡模式或没有 DPU 时用 FLAT | NICo Core | 可直接创建 | Core 的权限表只允许站点代理（以及模拟器）调用这两个创建接口，管理端证书不能调用 | `crates/api-core/src/auth/internal_rbac_rules.rs:75` |
| 33 | 实例类型与配额 | `InstanceType、ComputeAllocation` | CreateInstanceType，把计算托盘关联到实例类型，再给租户建配额 | 计算托盘对象、租户与 VPC | 可直接创建 | 只在“交给上层平台”时需要。Core 默认对超配额只告警不拒绝；REST 一侧强制检查 | `crates/api-core/src/instance/mod.rs:2077` |
| 34 | 实例 | `Instance` | AllocateInstances：计算托盘 ID 和实例配置（租户、系统、网络） | 计算托盘对象、系统定义、租户与 VPC | 需要模拟器或真实硬件 | 托盘必须是 Ready，没有维护标记、阻止分配的告警、待处理的实例或退役。机柜的健康报告会并入柜内每台主机的健康，所以机柜上阻止分配的告警会挡住整柜 | `crates/api-model/src/machine/mod.rs:543` |
| 35 | 健康报告 | `HealthReport` | 硬件健康服务、DPU 代理、站点发现和设施事件消费者写入；也可以用 Insert…HealthReport 手工写入一条 | 计算托盘对象 | 可直接创建：设备对象存在后，可以手工写入报告来验证页面：nico-admin-cli machine health-report add |  | `crates/api-core/src/handlers/health.rs:98` |
| 36 | 设施事件接入 | `nico-dsx-exchange-consumer` | 部署事件消费者并连到楼宇管理系统的消息总线；泄漏事件被写成机柜的健康报告 | 机柜对象 | 部署时配置 | 消费者是否连上没有读取接口，只有它自己的指标和存活探针 | `crates/dsx-exchange-consumer/src/health_updater.rs:184` |

## 接口：站点与依赖

| 接口 | 类型 | 命令行 | 请求参数 | 用到的字段 | 前置资源 | 执行方 | 使用的页面 | 证据 | 说明 | 出处 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `Version` | Core gRPC · 读 | `nico-admin-cli version --show-runtime-config` | display_config 为真时带回运行配置 | build_version、git_sha、capabilities[]、runtime_config.dhcp_servers、runtime_config.networks、runtime_config.initial_domain_name、runtime_config.attestation_enabled | NICo Core | Core | 配置 › 站点设置 › 站点概况；配置 › 站点设置 › 控制面；接入 › 网络规划 › DHCP 服务 | 定义；现有产品已调用 | 运行配置里没有时间服务器、组件管理器后端和配额执行方式 | `forge.proto:36` |
| `GetRmsVersion` | Core gRPC · 读 | `nico-admin-cli backend rms status` | — | version | RMS | Core → RMS | 配置 › 站点设置 › 站点概况；配置 › 站点设置 › 控制面 | 定义；现有产品已调用 | 没有配置 RMS 时返回 UNAVAILABLE；30 秒超时。命令行只有在连通时退出码才是 0 | `crates/api-core/src/handlers/rms.rs:75` |
| `GET /site、GET /site/{id}` | REST · 读 | `nicocli site list` | — | id、status（Pending、Registered、Error）、isOnline、siteAgentVersion、siteControllerVersion、capabilities.flow、machineStats | REST 站点 | REST | 配置 › 站点设置 › 站点概况；配置 › 站点设置 › 控制面 | 定义 | Flow 是否可用只能从这里的 capabilities.flow 看，Core 没有对应接口 | `spec.yaml:946` |
| `GetSiteCredentialReadiness` | Core gRPC · 读 | — | — | configured[]、missing[]、requires_recovery[] | NICo Core | Core | 配置 › 站点设置 › 站点概况 | 定义；现有产品已调用 |  | `forge.proto:589` |
| `InitializeSiteCredentials / CreateCredential` | Core gRPC · 写 | `nico-admin-cli credential add-bmc；nico-admin-cli credential add-uefi` | generate_missing，或逐项给 BMC、主机 UEFI、DPU UEFI 口令 | — | NICo Core | Core | 配置 › 站点设置 › 站点概况 | 定义；现有产品已调用 | 口令经标准输入或安全文件传入，不出现在命令行和日志里 | `forge.proto:586` |
| `GetSiteExplorerLastRun` | Core gRPC · 读 | — | — | started_at、finished_at、success、error、endpoint_explorations、endpoint_explorations_success、endpoint_explorations_failed、failure_category、last_successful_finished_at | NICo Core | Core | 配置 › 站点设置 › 站点概况；接入 › 设备发现 | 定义；现有产品已调用 |  | `site_explorer.proto:112` |
| `SetDynamicConfig` | Core gRPC · 写 | — | SITE_EXPLORER_ENABLED、CREATE_MACHINES | — | NICo Core | Core | 配置 › 站点设置 › 站点概况 | 定义 | 创建交换机和供电框的开关只在配置文件里，不能在运行时改 | `forge.proto:502` |
| `ListRackProfiles / GetRackProfile` | Core gRPC · 读 | `nico-admin-cli rack profile list；nico-admin-cli rack profile show <RACK_ID>` | — | rack_profile_id、profile.rack_hardware_topology、profile.capabilities.{compute,switch,power_shelf}.count、profile.product_family | 机柜规格配置 | Core | 配置 › 站点设置 › 站点概况；接入 › 设备清单 › 期望清单；运维 › 机柜管理 › 机柜详情；配置 › 固件基线 | 定义 | 从运行配置读出；只允许管理端证书调用 | `crates/api-core/src/handlers/rack.rs:511` |
| `GET /task/rule` | REST · 读 | `nicocli rule list --site-id <SITE>` | siteId 必填；operationType 可选（PowerControl、FirmwareControl） | id、name、operationType、operationCode、isDefault、ruleDefinition.steps[] | 操作规则 | Flow | 配置 › 站点设置 › 站点概况 | 定义 | 只返回存进数据库的规则 | `spec.yaml:14592` |
| `ListNvlinkNmxcEndpoints` | Core gRPC · 读 | `nico-admin-cli nvlink-nmxc-endpoints` | — | chassis_serial、endpoint | NMX-C 接入 | Core | 配置 › 站点设置 › 站点概况 | 定义 |  | `forge.proto:1116` |

## 接口：网络与地址

| 接口 | 类型 | 命令行 | 请求参数 | 用到的字段 | 前置资源 | 执行方 | 使用的页面 | 证据 | 说明 | 出处 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `FindNetworkSegmentIds → FindNetworkSegmentsByIds` | Core gRPC · 读 | `nico-admin-cli network-segment show` | include_num_free_ips 为真才返回空闲地址数 | id、metadata.name、config.segment_type、config.mtu、config.subdomain_id、config.prefixes[].{prefix,gateway,reserve_first,free_ip_count_v2}、status.lifecycle.state | 子网 | Core | 接入 › 网络规划 › 子网；接入 › 网络规划 › DHCP 服务；接入 › 设备清单 › 期望清单 | 定义；现有产品已调用 | 类型：TENANT、ADMIN、UNDERLAY、HOST_INBAND | `forge.proto:129` |
| `CreateNetworkSegment / CreateNetworkSegmentWithDhcpRange` | Core gRPC · 写 | `nico-admin-cli network-segment create --name --segment-type --prefix --gateway --reserve-first --mtu --subdomain-id` | prefixes 必填（每个地址族至多一个，各含 prefix、gateway、reserve_first）、segment_type 必填；name、mtu、subdomain_id 可选。带地址池的接口另需 range{start,end} | — | 正向 DNS 域、VLAN 与 VNI 资源池 | Core | 接入 › 网络规划 › 子网 | 定义；现有产品已调用 | 前缀不能与已有子网重叠。接口不强制子域，但没有子域的子网发不出 DHCP 记录，平台要自己把它当必填 | `crates/rpc/src/model/network_segment.rs:78` |
| `DeleteNetworkSegment` | Core gRPC · 写 | `nico-admin-cli network-segment delete` | id | — | 子网 | Core | 接入 › 网络规划 › 子网 | 定义；现有产品已调用 | 进入 Deleting，先等已分配的地址清空再删除 | `crates/api-core/src/handlers/network_segment.rs:523` |
| `FindNetworkSegmentDhcpRanges` | Core gRPC · 读 | — | 子网 ID 列表 | segment_id、prefix、range.{start,end}、revision | 子网 | Core | 接入 › 网络规划 › 子网；接入 › 网络规划 › DHCP 服务 | 定义；现有产品已调用 | 命令行没有对应命令 | `forge.proto:148` |
| `SetNetworkSegmentDhcpRange` | Core gRPC · 写 | — | segment_id 必填；range 省略表示清除；if_revision 填上次读到的修订号，0 表示还没有地址池 | range.{start,end}、revision | 子网 | Core | 接入 › 网络规划 › 子网 | 定义；现有产品已调用 | 只对有且只有一个 IPv4 前缀的 ADMIN、UNDERLAY、HOST_INBAND 子网有效；已有动态地址落在新范围之外时拒绝。命令行没有对应命令 | `forge.proto:149` |
| `FindInterfaces` | Core gRPC · 读 | `nico-admin-cli machine-interfaces show` | id 或 ip；都不填返回全部 | id、mac_address、address[]、segment_id、hostname、vendor、last_dhcp、machine_id、switch_id、power_shelf_id、association_type、interface_type、primary_interface | 设备接口与地址 | Core | 接入 › 网络规划 › DHCP 服务；接入 › 网络规划 › 地址分配；接入 › 设备发现 | 定义；现有产品已调用 | 没有租约到期时间。association_type 为 NONE 的就是拿到地址但没有归属的设备 | `forge.proto:318` |
| `FindInterfaceAddresses / FindIpAddress` | Core gRPC · 读 | `nico-admin-cli machine-interfaces show-addresses；nico-admin-cli ip find <IP>` | — | addresses[].{address,allocation_type}、matches[].{ip_type,owner_id,message} | 设备接口与地址 | Core | 接入 › 网络规划 › 地址分配 | 定义；现有产品已调用 | 按地址反查归属：地址可能属于设备接口、BMC、实例、资源池或子网本身 | `forge.proto:315` |
| `carbide_dhcp_requests_total、carbide_dhcp_dropped_requests_total、carbide_dhcp_replies_sent_total、carbide_available_ips_count` | 指标 · 读 | — | — | message_type、reason、name、type、prefix | DHCP 与引导服务 | 监控系统 | 接入 › 网络规划 › DHCP 服务 | 定义 | DHCP 的请求计数只按报文类型和丢弃原因分，不按子网或中继分；空闲地址数按子网前缀分 | `crates/dhcp-server/src/metrics.rs:495` |

## 接口：设备清单

| 接口 | 类型 | 命令行 | 请求参数 | 用到的字段 | 前置资源 | 执行方 | 使用的页面 | 证据 | 说明 | 出处 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `GetAllExpectedRackGroups` | Core gRPC · 读 | `nico-admin-cli expected-rack-group show` | — | rack_group_id、topology、protocol、racks[].rack_id、racks[].members[].{type,manufacturer,id} | 机柜组声明 | Core | 接入 › 设备清单 › 期望清单 | 定义 |  | `forge.proto:746` |
| `AddExpectedRackGroup / UpdateExpectedRackGroup / DeleteExpectedRackGroup` | Core gRPC · 写 | `nico-admin-cli expected-rack-group add [--rack <JSON>]... <RACK_GROUP_ID> <PROTOCOL> <TOPOLOGY>` | rack_group_id、topology 必填；protocol、racks、metadata 可选。更新是整条替换 | — | NICo Core | Core | 接入 › 设备清单 › 期望清单 | 定义 | 有 NVLink 域声明引用时，不能改 racks，也不能删除 | `forge.proto:737` |
| `GetAllExpectedRacks` | Core gRPC · 读 | `nico-admin-cli expected-rack show` | — | rack_id、rack_profile_id、rack_group_id、metadata | 机柜声明 | Core | 接入 › 设备清单 › 期望清单；运维 › 机柜管理 | 定义；现有产品已调用 |  | `forge.proto:719` |
| `AddExpectedRack / UpdateExpectedRack / DeleteExpectedRack` | Core gRPC · 写 | `nico-admin-cli expected-rack add [--label K:V] <RACK_ID>` | rack_id 必填；metadata 可选。规格和机柜组是输出字段，写入时忽略 | — | 机柜组声明、机柜规格配置 | Core | 接入 › 设备清单 › 期望清单 | 定义 | 推导失败返回 INVALID_ARGUMENT 并说明原因：没有机柜组包含它、多个机柜组包含它、缺计算或交换机成员、规格未配置 | `expected_rack.rs:29` |
| `GetAllExpectedMachines / GetAllExpectedMachinesLinked` | Core gRPC · 读 | `nico-admin-cli expected-machine show` | — | chassis_serial_number、bmc_mac_address、rack_id、bmc_ip_address、host_nics[]、metadata.labels、linked: interface_id、explored_endpoint_address、machine_id | 设备声明 | Core | 接入 › 网络规划 › 子网；接入 › 设备清单 › 期望清单；接入 › 设备发现；运维 › 机柜管理 › 机柜详情 | 定义；现有产品已调用 | 带关联的读取一次给出每条声明走到了哪一步：有没有接口、有没有探测结果、有没有设备对象 | `forge.proto:646` |
| `CreateExpectedMachines / UpdateExpectedMachines / PatchExpectedMachine / DeleteExpectedMachine` | Core gRPC · 写 | `nico-admin-cli expected-machine add -a <BMC_MAC> -u <BMC_USER> -p <BMC_PASS> -s <SERIAL> [--rack_id] [--bmc-ip-address] [--interfaces] [--label]` | bmc_mac_address、chassis_serial_number 必填（序列号 4–32 位字母数字下划线连字符）；rack_id、bmc_ip_address、host_nics、metadata 可选。批量接口带 accept_partial_results | — | NICo Core | Core | 接入 › 设备清单 › 期望清单；运维 › 机柜管理 › 机柜详情 | 定义；现有产品已调用 | 不要用 ReplaceAllExpectedMachines 做增量导入：它替换整张表 | `forge.proto:8268` |
| `GetAllExpectedSwitches / GetAllExpectedSwitchesLinked` | Core gRPC · 读 | `nico-admin-cli expected-switch show` | — | switch_serial_number、bmc_mac_address、nvos_interfaces[]、rack_id、linked: switch_id、explored_endpoint_address | 设备声明 | Core | 接入 › 网络规划 › 子网；接入 › 设备清单 › 期望清单；接入 › 设备发现 | 定义；现有产品已调用 |  | `forge.proto:701` |
| `AddExpectedSwitch / PatchExpectedSwitch / DeleteExpectedSwitch` | Core gRPC · 写 | `nico-admin-cli expected-switch add -a <BMC_MAC> -u <USER> -p <PASS> -s <SERIAL> --nvos-interface <MAC[,primary]> [--rack_id]` | bmc_mac_address 必填；nvos_interfaces 至少一个，多于一个时恰好一个为主口；NVOS 用户名和口令要么都填要么都不填 | — | NICo Core | Core | 接入 › 设备清单 › 期望清单 | 定义 |  | `forge.proto:691` |
| `GetAllExpectedPowerShelves / GetAllExpectedPowerShelvesLinked` | Core gRPC · 读 | `nico-admin-cli expected-power-shelf show` | — | shelf_serial_number、bmc_mac_address、rack_id、linked: power_shelf_id、explored_endpoint_address | 设备声明 | Core | 接入 › 网络规划 › 子网；接入 › 设备清单 › 期望清单；接入 › 设备发现；运维 › 设备管理 › 供电框 | 定义；现有产品已调用 |  | `forge.proto:681` |
| `AddExpectedPowerShelf / PatchExpectedPowerShelf / DeleteExpectedPowerShelf` | Core gRPC · 写 | `nico-admin-cli expected-power-shelf add -a <BMC_MAC> -u <USER> -p <PASS> -s <SERIAL> [--rack_id]` | bmc_mac_address 必填；序列号、rack_id、bmc_ip_address 可选 | — | NICo Core | Core | 接入 › 设备清单 › 期望清单 | 定义 |  | `forge.proto:671` |
| `CreateExpectedNvLinkDomain / DeleteExpectedNvLinkDomain / FindExpectedNvLinkDomainIds` | Core gRPC · 写 | `nico-admin-cli expected-nvlink-domain create --member <MAC>... [--name] <RACK_GROUP_ID>` | rack_group_id、member_bmc_mac_addresses 必填 | — | 机柜组声明、设备声明 | Core | 接入 › 设备清单 › 期望清单 | 定义 | REST 规范里没有对应的端点 | `forge.proto:725` |

## 接口：设备发现

| 接口 | 类型 | 命令行 | 请求参数 | 用到的字段 | 前置资源 | 执行方 | 使用的页面 | 证据 | 说明 | 出处 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `FindExploredEndpointIds → FindExploredEndpointsByIds` | Core gRPC · 读 | `nico-admin-cli site-explorer get-report endpoint` | — | address、report.endpoint_type、report.vendor、report.systems[].serial_number、report.chassis[].serial_number、report.last_exploration_error_schema.{error_code,mitigation,text}、report.firmware_versions、preingestion_state、pause_remediation | 探测结果 | Core | 接入 › 设备发现；运维 › 机柜管理 › 机柜详情 | 定义；现有产品已调用 | 探测结果的编号就是 BMC 的 IP 地址 | `site_explorer.proto:53` |
| `FindExploredManagedHostIds → FindExploredManagedHostsByIds` | Core gRPC · 读 | `nico-admin-cli site-explorer get-report managed-host` | — | host_bmc_ip、dpus[].{bmc_ip,host_pf_mac_address} | 探测结果 | Core | 接入 › 设备发现 | 定义 | 主机与 DPU 的配对结果 | `site_explorer.proto:84` |
| `GetAllUnexpectedMachines` | Core gRPC · 读 | — | — | address、bmc_mac_address、machine_id | 探测结果 | Core | 接入 › 设备发现 | 定义 | 只列出探测成功、类型是主机 BMC、MAC 不在任何声明里的设备。探测失败的未声明设备不在这里；命令行没有对应命令 | `crates/api-db/src/expected_machine.rs:283` |
| `ReExploreEndpoint / RefreshEndpointReport / ClearSiteExplorationError` | Core gRPC · 写 | `nico-admin-cli site-explorer re-explore；nico-admin-cli site-explorer refresh；nico-admin-cli site-explorer clear-error` | ip_address | — | 探测结果 | Core | 运维 › 机柜管理 › 机柜详情 | 定义 | 重新探测排到下一轮；刷新立即探测并保存；认证失败之后要先清除错误才会再试 | `forge.proto:390` |
| `DetermineMachineIngestionState` | Core gRPC · 读 | `nico-admin-cli managed-host power-options get-machine-ingestion-state --mac-address <MAC>` | mac_address 必填 | NotDiscovered、WaitingForIngestion、IngestionMachineNotCreated、IngestionMachineCreated | 设备声明 | Core | 接入 › 设备发现 | 定义；现有产品已调用 |  | `crates/api-core/src/handlers/power_options.rs:143` |
| `AllowIngestionAndPowerOn` | Core gRPC · 写 | `nico-admin-cli managed-host power-options allow-ingestion-and-power-on --mac-address <MAC>` | mac_address 必填 | — | 探测结果 | Core | 运维 › 机柜管理 › 机柜详情 | 定义；现有产品已调用 | 只对设备声明里带暂停标记的主机有意义 | `crates/api-core/src/handlers/power_options.rs:213` |

## 接口：机柜与 NVLink 域

| 接口 | 类型 | 命令行 | 请求参数 | 用到的字段 | 前置资源 | 执行方 | 使用的页面 | 证据 | 说明 | 出处 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `FindRackIds → FindRacksByIds` | Core gRPC · 读 | `nico-admin-cli rack list；nico-admin-cli rack show <RACK_ID>` | — | id、rack_group_id、status.lifecycle.{state,state_reason}、status.health、status.health_sources、metadata、created、updated | 机柜对象 | Core | 运维 › 机柜管理；运维 › 机柜管理 › 机柜详情；运维 › 健康告警；交付 › 机柜交付 | 定义；现有产品已调用 | 机柜对象不带规格和成员列表：规格另读，成员按机柜 ID 去各类设备里筛 | `forge.proto:9860` |
| `FindRackStateHistories` | Core gRPC · 读 | `nico-admin-cli rack state-history <RACK_ID>` | — | histories[rack_id].records[].{state,version,time} | 机柜对象 | Core | 运维 › 机柜管理 › 机柜详情 | 定义；现有产品已调用 |  | `forge.proto:331` |
| `GET /rack、GET /rack/{id}` | REST · 读 | `nicocli rack list --site-id <SITE>` | siteId 必填；includeComponents、name、分页可选 | id、name、operationStatus、operationStatusDetails.trayCountsByType、nvLinkDomainIds、taskStats.{pendingTaskCount,activeTaskCount}、health、components[] | Flow 的机柜与托盘清单 | Flow | 运维 › 机柜管理；运维 › 机柜管理 › 机柜详情 | 定义 | 站点没有启用 Flow 时返回 412 | `spec.yaml:13522` |
| `GET /rack/{id}/validation、GET /rack/validation` | REST · 读 | `nicocli rack validate --site-id <SITE>` | siteId 必填 | diffs[].{type,id,macAddress,fieldDiffs}、totalDiffs、missingCount、unexpectedCount、mismatchCount、matchCount | Flow 的机柜与托盘清单、设备声明 | Flow | 运维 › 机柜管理；运维 › 机柜管理 › 机柜详情 | 定义 | 差异类型：Missing、Unexpected、Mismatch。按 BMC MAC 比对，不比对序列号 | `spec.yaml:13745` |
| `GET /tray、GET /tray/{id}` | REST · 读 | `nicocli tray list --site-id <SITE> --rack-id <RACK>` | siteId 必填；rackId 或 rackName、type、slotId 可选 | id、type（Compute、NVSwitch、PowerShelf）、position.{slotId,trayIdx,hostId}、firmwareVersion、powerState、operationStatus、leakStatus、bmcs、rackId、nvLinkDomainId、taskStats、health | Flow 的机柜与托盘清单 | Flow | 运维 › 机柜管理 › 机柜详情；运维 › 设备管理 › 供电框 | 定义 | 机柜立面要的槽位在这里；Core 的供电框对象没有位置字段 | `spec.yaml:14412` |
| `GET /domain/nvlink、GET /domain/nvlink/{id}` | REST · 读 | `nicocli domain list --site-id <SITE>` | siteId 必填；includeComponents 可选 | id（等于机柜组编号）、name、nmxcClusterId、topology、operationStatus、components | NVLink 域 | Flow | 运维 › NVLink 域管理 | 定义 | nicocli 的子命令名由接口规范生成，这里的写法没有实际运行核对 | `spec.yaml:13335` |

## 接口：设备读取

| 接口 | 类型 | 命令行 | 请求参数 | 用到的字段 | 前置资源 | 执行方 | 使用的页面 | 证据 | 说明 | 出处 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `FindMachineIds → FindMachinesByIds` | Core gRPC · 读 | `nico-admin-cli machine show [--hosts]` | 筛选：rack_id、include_dpus、exclude_hosts、only_maintenance、only_quarantine、only_with_health_alert；include_history 带回状态事件 | id、rack_id、placement_in_rack.{slot_number,tray_index}、state、state_reason.{outcome,outcome_msg}、state_sla.time_in_state_above_sla、status.health.alerts[]、bmc.{ip,mac}、status.bmc_status.firmware_version、status.discovery_info.dmi_data.chassis_serial、status.associated_dpu_machine_ids、config.maintenance_reference、status.quarantine、status.nvlink_info.domain_uuid、status.lldp_neighbors[]、inventory.components[] | 计算托盘对象 | Core | 接入 › 设备发现；运维 › 机柜管理 › 机柜详情；运维 › 设备管理 › 计算托盘；运维 › 设备管理；运维 › 设备管理 › DPU；运维 › 健康告警；交付 › 机柜交付；交付 › 安装任务；交付 › 实例管理 | 定义；现有产品已调用 | 没有电源状态和实例字段，这两项另读。一次按编号读取的数量有上限 | `forge.proto:5137` |
| `FindHostStatesByIds` | Core gRPC · 读 | — | host_ids | state、state_reason、rack_id、nvlink_domain_id、bmc_ip、dpu_ids、health_alerts、quarantine、allocation.{allocatable,blocking_reason,blocking_detail}、explored.{bmc_version,uefi_version} | 计算托盘对象 | Core | 交付 › 机柜交付 | 定义 | 一次给出“能不能分配，被什么挡住”。只允许管理端证书调用；命令行没有对应命令 | `forge.proto:13734` |
| `FindMachineIds（include_dpus、exclude_hosts）→ FindMachinesByIds` | Core gRPC · 读 | `nico-admin-cli dpu status；nico-admin-cli dpu versions` | — | id、state、status.associated_host_machine_id、status.discovery_info.dpu_info.firmware_version、status.bmc_status.firmware_version、status.dpu_agent_version、status.health | DPU 对象 | Core | 运维 › 设备管理；运维 › 设备管理 › DPU | 定义 | DPU 的工作模式不在这里：策略在设备声明的 dpu_mode，实测值在探测到的网卡设备上 | `forge.proto:5021` |
| `FindSwitchIds → FindSwitchesByIds` | Core gRPC · 读 | `nico-admin-cli switch list；nico-admin-cli switch show <SWITCH_ID>` | 筛选：rack_id、controller_state、bmc_mac、nvos_mac、only_with_health_alert | id、rack_id、placement_in_rack、nvlink_domain_uuid、bmc_info.{ip,mac,firmware_version}、status.serial_number、status.power_state、status.controller_state、status.state_reason、status.health、status.fabric_manager_status_details、status.nvos_ports[].{mac,addresses,is_primary} | 交换机对象 | Core | 接入 › 设备发现；运维 › NVLink 域管理；运维 › 机柜管理 › 机柜详情；运维 › 设备管理 › 交换机；运维 › 设备管理；运维 › 健康告警 | 定义；现有产品已调用 |  | `forge.proto:3332` |
| `FindPowerShelfIds → FindPowerShelvesByIds` | Core gRPC · 读 | `nico-admin-cli power-shelf list；nico-admin-cli power-shelf show <ID>` | 筛选：rack_id、controller_state、bmc_mac | id、rack_id、bmc_info.{ip,mac,firmware_version}、config.{capacity,voltage}、status.power_state、status.controller_state、status.state_reason、status.health | 供电框对象 | Core | 接入 › 设备发现；运维 › 机柜管理 › 机柜详情；运维 › 设备管理 › 供电框；运维 › 设备管理；运维 › 健康告警 | 定义；现有产品已调用 | 没有槽位字段，也没有序列号字段 | `forge.proto:3087` |
| `FindMachineStateHistories / FindSwitchStateHistories / FindPowerShelfStateHistories` | Core gRPC · 读 | `nico-admin-cli machine show <ID> -c <条数>` | — | histories[id].records[].{state 或 event,version,time} | 计算托盘对象 | Core | 运维 › 设备管理 › 计算托盘；运维 › 设备管理 › 交换机；运维 › 设备管理 › 供电框 | 定义；现有产品已调用 |  | `forge.proto:329` |
| `GetComponentInventory` | Core gRPC · 读 | — | machine_ids、switch_ids、power_shelf_ids 三选一 | entries[].result.{component_id,status,error}、entries[].report.firmware_versions、entries[].report.systems[]、entries[].report.chassis[] | 探测结果 | Core | 运维 › NVLink 域管理；运维 › 设备管理 › 计算托盘；运维 › 设备管理 › 交换机；运维 › 设备管理 › 供电框；配置 › 固件基线 | 定义；现有产品已调用 | 读的是保存下来的探测报告，不经过硬件后端。命令行没有对应命令 | `forge.proto:1373` |
| `GetComponentPowerDetails / GetPowerOptions` | Core gRPC · 读 | `nico-admin-cli managed-host power-options show <MACHINE>` | machine_ids、switch_ids、power_shelf_ids 三选一，1–64 个 | entries[].actual.{state,source,observed_at}、entries[].desired.state、entries[].actions[].{status,operation,requested_at,initiator} | 组件管理器 | Core 或硬件后端 | 运维 › 设备管理 › 计算托盘；运维 › 设备管理 › 交换机；运维 › 设备管理 › 供电框 | 定义；现有产品已调用 | 整机柜里的主机、交换机和供电框经硬件后端读取；交换机和供电框对象上另有一个文本形式的 status.power_state | `forge.proto:11423` |
| `GetDesiredFirmwareVersions / ListComponentFirmwareVersions` | Core gRPC · 读 | `nico-admin-cli component-manager get-firmware-versions {compute-tray\|switch\|power-shelf\|rack}` | — | entries[].{vendor,model,component_versions}、devices[].versions[]、devices[].compute_fw_versions[] | 组件管理器 | Core | 配置 › 固件基线 | 定义 | 前者是按厂商型号配置的主机期望版本；后者是硬件后端可用的固件包。以机柜为目标时返回未实现 | `forge.proto:998` |
| `GetComponentFirmwareStatus` | Core gRPC · 读 | `nico-admin-cli component-manager get-firmware-update-status {compute-tray\|switch\|power-shelf\|rack}` | — | statuses[].state（QUEUED、IN_PROGRESS、VERIFYING、COMPLETED、FAILED、CANCELLED）、statuses[].target_version、statuses[].updated_at | 组件管理器 | Core 或硬件后端 | 运维 › 机柜管理 › 机柜详情 | 定义 |  | `forge.proto:1375` |
| `GetMachineValidationRuns / GetMachineValidationResults` | Core gRPC · 读 | `nico-admin-cli machine-validation runs show -m <MACHINE>` | — | runs[].{validation_id,status,start_time,end_time}、results[].{name,exit_code,std_out,std_err} | 计算托盘对象 | Core | 运维 › 设备管理 › 计算托盘 | 定义；现有产品已调用 |  | `forge.proto:878` |
| `IdentifySerial / IdentifyMac / FindIpAddress` | Core gRPC · 读 | `nico-admin-cli ip find <IP>` | 序列号、MAC 或 IP | machine_id、matches[].{ip_type,owner_id} | 计算托盘对象 | Core | 运维 › 设备管理 | 定义 | 跨类型搜索用。序列号只能反查主机；交换机和供电框要在各自的列表里按 BMC MAC 筛 | `forge.proto:350` |

## 接口：设备操作

| 接口 | 类型 | 命令行 | 请求参数 | 用到的字段 | 前置资源 | 执行方 | 使用的页面 | 证据 | 说明 | 出处 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `PATCH /tray/{id}/power、PATCH /tray/power` | REST · 写 | `nicocli tray power --site-id <SITE> --data '{"state":"Off"}' <TRAY_ID>` | siteId、state 必填（On、Off、Cycle、ForceOff、ForceCycle、ACPowerCycle）；ruleId、overrideReadinessCheck 可选。批量接口的 filter 为空表示站点内全部托盘 | taskIds[] | Flow 的机柜与托盘清单 | Flow → Core → 硬件后端 | 运维 › 设备管理 › 计算托盘；运维 › 设备管理 › 交换机；运维 › 设备管理 › 供电框 | 定义 | 读回用 GET /tray/{id}/power，它分别给出实际状态、期望状态和进行中的动作 | `spec.yaml:16691` |
| `PATCH /tray/{id}/firmware、PATCH /tray/firmware` | REST · 写 | `nicocli tray firmware --site-id <SITE> <TRAY_ID>` | siteId 必填；version 省略表示用机柜固件清单；targets 可选（bmc、cpld、bios、nvos、pmc、psu、dpu）；ruleId、overrideVersionCheck、overrideReadinessCheck 可选 | taskIds[] | Flow 的机柜与托盘清单、机柜固件清单 | Flow → Core → 硬件后端 | 运维 › 设备管理 › 计算托盘；运维 › 设备管理 › 交换机 | 定义 | 内置的固件规则只覆盖计算托盘和交换机，不含供电框 | `spec.yaml:16743` |
| `ComponentPowerControl` | Core gRPC · 写 | `nico-admin-cli component-manager component-power-control --action <on\|graceful-shutdown\|force-off\|graceful-restart\|force-restart\|a-c-powercycle> {compute-tray\|switch\|power-shelf} --machine-id <ID>` | machine_ids、switch_ids、power_shelf_ids 三选一；action 必填 | results[].{component_id,status,error} | 组件管理器 | Core → 硬件后端 | 运维 › 设备管理 › 计算托盘；运维 › 设备管理 › 交换机 | 定义；现有产品已调用 | Flow 的托盘电源最终也调这个接口。结果里的 OUTCOME_UNKNOWN 表示不确定是否执行，不能自动重发。读回用 GetComponentPowerDetails | `forge.proto:1347` |
| `SetPowerShelfMaintenance` | Core gRPC · 写 | `nico-admin-cli power-shelf maintenance power-off --power-shelf-id <ID> [--reference] [--graceful]；… power-on` | power_shelf_ids、operation 必填（POWER_ON、POWER_OFF）；reference、graceful 可选 | — | 供电框对象、组件管理器 | 供电框状态机 → 硬件后端 | 运维 › 设备管理 › 供电框 | 定义；现有产品已调用 | 供电框在 Ready 或 Error 时才会被处理。读回看供电框状态从 Maintenance 回到 Ready | `crates/api-core/src/handlers/power_shelf.rs:330` |
| `SetMaintenance` | Core gRPC · 写 | `nico-admin-cli managed-host maintenance on --host <ID> --reference <原因>；… off --host <ID>` | operation、host_id 必填；开启时 reference 必填，至少 5 个字符 | — | 计算托盘对象 | Core | 运维 › 设备管理 › 计算托盘 | 定义；现有产品已调用 | 实现方式是给主机写一条健康报告，带阻止分配。读回看 config.maintenance_reference 或按 only_maintenance 筛选 | `crates/api-core/src/handlers/managed_host.rs:200` |
| `SetManagedHostQuarantineState / ClearManagedHostQuarantineState` | Core gRPC · 写 | `nico-admin-cli managed-host quarantine on --host <ID> --reason <原因>；… off --host <ID>` | machine_id、quarantine_state.{mode,reason} | prior_quarantine_state | 计算托盘对象 | Core | 运维 › 设备管理 › 计算托盘 | 定义；现有产品已调用 | 模式只有 BLOCK_ALL_TRAFFIC。读回看 status.quarantine | `crates/api-core/src/handlers/machine_quarantine.rs:28` |
| `OnDemandMachineValidation` | Core gRPC · 写 | `nico-admin-cli machine-validation on-demand start -m <MACHINE>` | machine_id、action 必填（只有 Start 可用） | validation_id | 计算托盘对象 | Core | 运维 › 设备管理 › 计算托盘 | 定义；现有产品已调用 | 主机要在 Ready 或 Failed 状态 | `forge.proto:974` |
| `VerifySkuForMachine` | Core gRPC · 写 | `nico-admin-cli sku verify <MACHINE_ID>` | machine_id | — | 计算托盘对象 | Core | 运维 › 设备管理 › 计算托盘 | 定义；现有产品已调用 | 读回看 status.hw_sku.verify_request_time | `crates/api-core/src/handlers/sku.rs:186` |
| `AdminBmcReset` | Core gRPC · 写 | `nico-admin-cli bmc-machine bmc-reset [--machine <ID>\|--switch <ID>\|--power-shelf <ID>]` | device_id（machine_id、switch_id、power_shelf_id 之一）；reset_type 可选 | — | 探测结果 | Core（Redfish） | 运维 › 设备管理 › 计算托盘；运维 › 设备管理 › 交换机 | 定义；现有产品已调用 | 没有读回接口：返回成功只表示 BMC 接受了请求 | `crates/api-core/src/handlers/bmc_endpoint_explorer.rs:302` |
| `DecommissionSwitch / DecommissionPowerShelf / DecommissionManagedHost` | Core gRPC · 写 | `nico-admin-cli managed-switch decommission <SWITCH_ID>；nico-admin-cli power-shelf decommission <ID>；nico-admin-cli managed-host decommission <ID>` | 设备 ID | — | 交换机对象、组件管理器 | 设备状态机 → 硬件后端 | 运维 › 设备管理 › 交换机；运维 › 设备管理 › 供电框 | 定义；现有产品已调用 | 设备要在 Ready；交换机和供电框还要求所在机柜没有已分配的主机；交换机要求后端是 rms。退役后要强制删除并清掉 BMC 抑制记录，设备才能被重新发现 | `crates/api-core/src/handlers/switch.rs:389` |

## 接口：机柜级任务

| 接口 | 类型 | 命令行 | 请求参数 | 用到的字段 | 前置资源 | 执行方 | 使用的页面 | 证据 | 说明 | 出处 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `POST /rack/{id}/bringup` | REST · 写 | `nicocli rack bringup --site-id <SITE> <RACK_ID>` | siteId 必填；description、ruleId、overrideReadinessCheck 可选 | taskIds[] | Flow 的机柜与托盘清单、机柜固件清单、操作规则 | Flow → Core → 硬件后端 | 运维 › 机柜管理 › 机柜详情 | 定义 | 默认规则的阶段：供电框上电、计算托盘上电、计算托盘固件、交换机上电、交换机固件一致性核对、计算托盘重新上电。完成后还要看 Core 的机柜状态走到 Ready | `spec.yaml:14357` |
| `PATCH /rack/{id}/power` | REST · 写 | `nicocli rack power --site-id <SITE> --data '{"state":"On"}' <RACK_ID>` | siteId、state 必填（On、Off、Cycle、ForceOff、ForceCycle、ACPowerCycle）；ruleId、overrideReadinessCheck 可选 | taskIds[] | Flow 的机柜与托盘清单、操作规则 | Flow → Core → 硬件后端 | 运维 › 机柜管理 › 机柜详情 | 定义 | 机柜级上下电只有 Flow 提供，Core 的设备电源接口没有机柜这个目标。相同的进行中请求会合并成同一个任务 | `spec.yaml:14125` |
| `PATCH /rack/{id}/firmware` | REST · 写 | `nicocli rack firmware --site-id <SITE> <RACK_ID>` | siteId 必填；version 省略表示用机柜固件清单；ruleId、overrideVersionCheck、overrideReadinessCheck 可选 | taskIds[] | Flow 的机柜与托盘清单、机柜固件清单、操作规则 | Flow → Core → 硬件后端 | 运维 › 机柜管理 › 机柜详情 | 定义 | 走硬件后端时 version 是一整份固件清单文本，不是版本号。机柜接口不转发 targets | `spec.yaml:14245` |
| `PATCH /domain/nvlink/{id}/power` | REST · 写 | — | siteId、state 必填；ruleId、overrideReadinessCheck 可选 | taskIds[] | NVLink 域、操作规则 | Flow → Core → 硬件后端 | 运维 › NVLink 域管理 | 定义 | 按域展开成每个机柜一个任务 | `spec.yaml:15956` |
| `PATCH /domain/nvlink/{id}/firmware` | REST · 写 | — | siteId 必填；version 省略表示用机柜固件清单；ruleId、overrideVersionCheck、overrideReadinessCheck 可选 | taskIds[] | NVLink 域、机柜固件清单、操作规则 | Flow → Core → 硬件后端 | 运维 › NVLink 域管理 | 定义 |  | `spec.yaml:16014` |
| `POST /task/run、GET /task/run、GET /task/run/{id}/target、POST /task/run/{id}/pause\|resume\|advance\|cancel` | REST · 写 | — | siteId、name、options.maxConcurrentTargets、operation.firmware.version 必填；selector.percentage、options.phasePolicy、options.safetyPolicy 可选 | id、status、statusReason、totalPhases、targets[].{rackId,phaseIndex,taskId,status} | Flow 的机柜与托盘清单、机柜固件清单 | Flow | 运维 › NVLink 域管理 | 定义 | 分阶段发布只支持固件。目标是“所有符合条件的机柜”，上限 100 个，不能传入机柜列表 | `spec.yaml:15201` |
| `GET /task、GET /rack/{id}/task、GET /tray/{id}/task、GET /task/{id}` | REST · 读 | `nicocli rack task get --site-id <SITE> <RACK_ID>` | siteId 必填；activeOnly、includeReport、分页可选 | id、status（Pending、Running、Succeeded、Failed、Terminated）、description、message、ruleId、started、finished、report | 任务 | Flow | 运维 › 机柜管理；运维 › NVLink 域管理；运维 › 机柜管理 › 机柜详情；运维 › 设备管理 › 计算托盘；运维 › 设备管理 › 交换机；运维 › 设备管理 › 供电框；运维 › 运维任务 | 定义 | 任务里没有操作者和原因，这两项由平台的审计记录 | `spec.yaml:14768` |
| `POST /task/{id}/cancel` | REST · 写 | `nicocli task cancel --site-id <SITE> <TASK_ID>` | siteId 必填 | status | 任务 | Flow | 运维 › 机柜管理 › 机柜详情；运维 › 运维任务 | 定义 | 已经成功或失败的任务返回 412；已终止的任务重复取消不报错 | `spec.yaml:14913` |
| `OnDemandRackMaintenance / TerminateRackMaintenance` | Core gRPC · 写 | `nico-admin-cli rack maintenance start --rack <ID> --activities <firmware-upgrade,nvos-update,power-sequence,configure-nmx-cluster>；nico-admin-cli rack maintenance terminate --rack <ID>` | rack_id 必填；scope 可选（设备范围和活动） | — | 机柜对象、RMS | 机柜状态机 → RMS | 运维 › 机柜管理 › 机柜详情 | 定义；现有产品已调用 | 机柜要在 Ready 或 Error。NVOS 更新和 NMX-C 集群配置只有这条路径提供，REST 和 Flow 都没有 | `forge.proto:977` |

## 接口：交付与实例

| 接口 | 类型 | 命令行 | 请求参数 | 用到的字段 | 前置资源 | 执行方 | 使用的页面 | 证据 | 说明 | 出处 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `FindOperatingSystemIds → FindOperatingSystemsByIds` | Core gRPC · 读 | `nico-admin-cli operating-system show` | — | id、name、type、status、is_active、ipxe_template_id、ipxe_template_parameters、ipxe_template_artifacts[].{name,url,cached_url} | 系统定义 | Core | 交付 › 机柜交付；配置 › 安装方案 | 定义；现有产品已调用 |  | `forge.proto:1380` |
| `CreateOperatingSystem / UpdateOperatingSystem / DeleteOperatingSystem` | Core gRPC · 写 | `nico-admin-cli operating-system create；nico-admin-cli operating-system set-cached-url` | name 必填；ipxe_script，或 ipxe_template_id 加参数和制品，二选一；is_active、user_data 可选 | — | NICo Core | Core | 配置 › 安装方案 | 定义；现有产品已调用 | 删除时 Core 不检查是否还有实例在引用，平台要自己检查 | `crates/api-core/src/handlers/operating_system.rs:196` |
| `AllocateInstances / AllocateInstance` | Core gRPC · 写 | `nico-admin-cli instance allocate --machine-id <ID>... --transactional --os <OS_ID> [--flat-vpc-id\|--vpc-prefix-id]` | 每个实例：machine_id、config 必填（config.tenant、config.os、config.network）；instance_type_id、metadata、allow_unhealthy_machine 可选 | instances[].{id,machine_id,status} | 计算托盘对象、系统定义、租户与 VPC | Core | 交付 › 机柜交付 | 定义；现有产品已调用 | 批量接口在一个事务里，全部成功或全部失败。不满足条件时的错误带有 nico-error-code、nico-error-text、nico-error-mitigation 三个附加信息 | `crates/api-core/src/instance/mod.rs:2009` |
| `FindInstanceIds → FindInstancesByIds / FindInstanceByMachineID` | Core gRPC · 读 | `nico-admin-cli instance show` | — | id、machine_id、config.tenant.{tenant_organization_id,hostname}、config.os、status.tenant.state、status.network、metadata | 实例 | Core | 运维 › 设备管理 › 计算托盘；交付 › 机柜交付；交付 › 安装任务；交付 › 实例管理 | 定义；现有产品已调用 | 状态：PROVISIONING、READY、CONFIGURING、UPDATING、TERMINATING、TERMINATED、FAILED、REPAIRING | `forge.proto:230` |
| `ReleaseInstance / ReleaseInstances` | Core gRPC · 写 | `nico-admin-cli instance release --instance <ID>` | id 必填 | results[].{id,status,error} | 实例 | Core | 交付 › 实例管理 | 定义；现有产品已调用 | 重复调用不报错。主机健康带“阻止删除实例”时拒绝。回收是异步的：读回看实例消失，以及主机状态回到 Ready 且可分配 | `crates/api-core/src/handlers/instance.rs:822` |
| `CreateInstanceType / AssociateMachinesWithInstanceType / CreateComputeAllocation` | Core gRPC · 写 | `nico-admin-cli instance-type create；nico-admin-cli instance-type associate；nico-admin-cli compute-allocation create` | 实例类型：名称和能力；关联：instance_type_id、machine_ids；配额：tenant_organization_id、instance_type_id、count | — | 计算托盘对象、租户与 VPC | Core | 交付 › 机柜交付 | 定义 | REST 一侧的等价流程是：邀请租户、建实例类型并关联设备、建配额，之后由租户自己建实例 | `forge.proto:761` |

## 接口：健康

| 接口 | 类型 | 命令行 | 请求参数 | 用到的字段 | 前置资源 | 执行方 | 使用的页面 | 证据 | 说明 | 出处 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `ListMachineHealthReports / ListSwitchHealthReports / ListPowerShelfHealthReports / ListRackHealthReports / ListNVLinkDomainHealthReports` | Core gRPC · 读 | `nico-admin-cli machine health-report show <ID>；nico-admin-cli nvl-domain health-report show` | 设备、机柜或域的 ID | health_report_entries[].mode、report.source、report.alerts[].{id,target,in_alert_since,message,classifications[]} | 健康报告 | Core | 运维 › NVLink 域管理；运维 › 机柜管理 › 机柜详情；运维 › 健康告警；交付 › 机柜交付 | 定义 | 一条告警是否阻止分配，看 classifications 里有没有 PreventAllocations。泄漏告警的编号：BmsLeakDetectRack、BmsLeakSensorFaultRack、BmcLeakDetection | `forge.proto:238` |
| `FindMachineHealthHistories / FindSwitchHealthHistories / FindPowerShelfHealthHistories / FindRackHealthHistories` | Core gRPC · 读 | `nico-admin-cli machine health-history <ID>；nico-admin-cli rack health-history <RACK_ID>` | ids 必填；start_time、end_time 可选 | histories[id].records[].{health,time} | 健康报告 | Core | 运维 › 健康告警 | 定义 |  | `forge.proto:330` |

## 缺口：设计需要、NICo 没有直接提供

| 设计需要 | 涉及页面 | 源码里的情况 | 可选的处理 | 出处 |
| --- | --- | --- | --- | --- |
| 到货清单里的槽位写入 NICo 的期望清单 | 设备清单 | Core 的设备声明没有槽位字段。REST 的设备声明有 slotId、trayIdx、hostId，存在 REST 自己的数据库里，并以 slot_id、tray_idx、host_id 三个标签写进 Core 的 metadata。实际位置来自 RMS 或 BMC 的探测报告，不来自声明 | 走 Core 时把槽位写成同样的三个 metadata 标签，与 REST 保持一致；或者设备声明改走 REST | `rest-api/db/pkg/db/model/common.go:100` |
| 对账里的“序列号不符” | 机柜详情、设备发现 | REST 的期望与实际校验按 BMC MAC 比对存在性，只对计算托盘比对槽位、托盘号和主机号，不比对序列号。Core 的站点发现会比对序列号，但结果只是一个计数指标，以及设备对象建好之后的一条 SerialNumberMismatch 告警，不拦截接管 | 由平台判断：对比设备声明的序列号和探测结果里的序列号。设备对象建好后再用 SerialNumberMismatch 告警交叉核对 | `crates/site-explorer/src/lib.rs:1046` |
| 对账里的“未声明的设备” | 设备发现、机柜详情 | 没有一个接口能列全。GetAllUnexpectedMachines 只含探测成功的主机 BMC；探测失败的、交换机和供电框都不在里面。未声明的主机 BMC 因为没有凭据，通常就是探测失败 | 用设备接口列表里没有归属的记录，加上探测结果，由平台与声明对比得出 | `crates/api-db/src/expected_machine.rs:292` |
| “没有收到 DHCP 请求”按子网定位 | 网络规划、设备发现 | NICo 不记录每个子网或每个中继最近一次收到请求的时间和次数。DHCP 的指标只按报文类型和丢弃原因分；接口上只有该设备最近一次请求的时间 | DHCP 服务页的“最近请求”改成从设备接口的 last_dhcp 按子网汇总得出：只能反映拿到过地址的设备。完全没有请求到达的情况，页面只能提示去看中继配置和 DHCP 的丢弃计数 | `crates/dhcp-server/src/metrics.rs:496` |
| 引导服务地址和时间服务器的展示 | 网络规划 | 域名服务器、时间服务器、引导服务器地址在 DHCP 服务的部署参数里，没有接口可读；运行配置里只有 DHCP 服务器地址 | 从平台自己保存的部署配置读，并标明来源是部署配置而不是 NICo 的回报 | `helm/charts/nico-dhcp/values.yaml:199` |
| 固件基线 | 固件基线、机柜详情、NVLink 域管理、设备管理 | NICo 里没有可命名的固件基线对象。期望版本有两处：每个机柜规格的固件清单地址，和按厂商型号配置的主机期望版本。固件操作要么不带版本（用机柜规格的清单），要么带一整份清单文本 | 固件基线做成平台自己的档案：一条基线对应一份清单文件。操作时把清单内容作为 version 传入，或者只允许选择与机柜规格配置一致的那一份。“低于基线”由平台对比探测到的版本和清单得出 | `docs/configuration/rms.md:183` |
| 站点概况里的硬件后端和设施接入状态 | 站点设置 | 当前生效的组件管理器后端没有读取接口；设施事件消费者是否连上也没有接口，只有它自己的指标。NMX-C 没有状态接口 | RMS 用版本接口判断；NMX-C 从机柜健康报告里的 NmxcUnreachable 判断；设施接入读消费者的指标，读不到就显示未知，不显示正常 | `crates/api-core/src/cfg/README.md:140` |
| 任务里的操作者和原因 | 运维任务、操作审计 | Flow 的任务只有描述、规则和阶段报告，没有操作者和原因字段。REST 有自己的审计接口，记录的是调用它的账号 | 操作者和原因由平台审计保存，用任务编号关联；提交时把原因写进任务的 description | `rest-api/openapi/spec.yaml:28731` |
| 单台设备电源走任务还是直接执行 | 设备管理 | 两条路径都能用：REST 的托盘电源提交为 Flow 任务，可取消、有阶段；Core 的设备电源接口立即执行。供电框在 Core 里另有一个走状态机的专用接口。现有产品用的是 Core 的直接接口 | 设计稿目前写的是走任务。建议保持：有 Flow 时走任务，电源动作因此受“同一机柜只有一个任务”的约束；Flow 不可用时这些操作不可用，不悄悄改走直接接口 | `crates/api-core/src/handlers/component_manager.rs:3244` |
| 设备声明和机柜读取走 Core 还是走 REST | 设备清单、机柜管理、机柜详情 | REST 和 Core 是两套存储，靠工作流和定时任务同步；REST 的资源编号是它自己的 UUID。机柜的状态机状态只在 Core，任务计数、槽位和对账只在 REST | 写入只走 Core。读取分工：状态、健康、历史读 Core；槽位、对账、任务读 REST。两边用机柜 ID 和 BMC MAC 关联，页面上不显示 REST 的编号 | `rest-api/api/pkg/api/handler/expectedrack.go:161` |
| 机柜上线由谁推进 | 机柜详情 | 有两套机制：Core 的机柜状态机在交换机就绪后自动进入 Maintenance，依次做固件、NVOS、上电顺序和 NMX-C 配置；Flow 的上线任务按规则做上电、固件和核对。两者的阶段不同，也没有找到它们之间的协调：Flow 上线里的计算托盘固件走状态机路径时，要求机柜已经在 Ready 或 Error | 先在模拟环境里把两条路径各跑一遍，确定“开始上线”按钮对应哪一个、阶段条显示哪一套阶段，再定稿。在此之前，机柜详情的阶段只作示意 | `docs/architecture/state_machines/rackstatemachine.md:142` |
| 更换设备后机柜重新发现 | 机柜详情 | 文档说更换托盘会让机柜因 topology_changed 回到 Discovering，但源码里没有找到设置这个标志的非测试代码。更换的实际步骤是：打上待更换标记并等 NVLink 隔离完成、强制删除旧设备、改设备声明、等新设备被发现 | 更换设备做成平台编排的分步流程，每步读回；机柜状态是否变化以实测为准，页面不预先承诺 | `crates/rack-controller/src/ready.rs:50` |
| 机柜退役 | 机柜详情 | DeleteRack 只把机柜标记为删除，状态机进入 Deleting 后一直等待；真正删除只有强制删除，而且不处理成员设备。Flow 有退役任务，但只在 Flow 自己的接口上，REST 没有端点 | 退役拆成明确的几步由平台编排：确认无实例、成员设备逐个退役并强制删除、删除设备声明和机柜声明、最后强制删除机柜；或者本阶段不提供机柜退役 | `crates/api-core/src/handlers/rack.rs:201` |
| NVLink 域的分阶段发布 | NVLink 域管理 | 分阶段发布的目标是站点内所有符合条件的机柜，按百分比抽取，不能限定为某个域，也不能传入机柜列表 | 域级固件用域的固件接口一次提交；分阶段发布作为站点级功能单独呈现，不挂在某个域下面 | `docs/operations/flow/operation-runs.md:123` |
| 交付条件里的“机柜就绪”和“NVLink 域健康” | 机柜交付 | NICo 分配实例时只看主机自己：状态、维护标记和阻止分配的告警。机柜的健康报告会并入主机，所以泄漏会挡住整柜；但机柜状态不是 Ready、域的健康报告有告警，都不会让分配失败 | 这两个条件由平台在交付前检查并拦截，页面上标明是平台的规则。“可交付的托盘数”用主机状态接口里的 allocatable 得出，与 NICo 的判断保持一致 | `crates/api-model/src/machine/mod.rs:543` |
| 交付用的租户和 VPC 由谁创建 | 机柜交付 | Core 的创建租户和创建 VPC 接口只对站点代理放行，管理端证书调不了。现有产品只读取已有的 VPC | 租户和 VPC 作为部署前提，由 REST 一侧或部署步骤建好；平台只读取并在交付时选择。计算托盘的 DPU 模式决定 VPC 类型，交付向导里要按它筛选 | `crates/api-core/src/auth/internal_rbac_rules.rs:75` |
| 按机柜整柜交付 | 机柜交付 | REST 的批量建实例按实例类型和数量挑设备，优先同一个 NVLink 域，不能指定机柜或设备列表。Core 的批量接口可以传入明确的设备列表，并且是一个事务 | 按机柜交付走 Core：按机柜 ID 筛出主机，读可分配状态，再一次提交。“交给上层平台”则是建实例类型、关联设备和配额，不建实例 | `crates/api-core/src/instance/mod.rs:2009` |
| 供电框的槽位和序列号 | 设备管理、机柜详情 | Core 的供电框对象没有位置字段，也没有序列号字段；交换机的序列号取自探测报告 | 供电框的槽位读 REST 的托盘，序列号读设备声明或探测报告 | `crates/rpc/proto/forge.proto:3087` |

## 各页面用到的接口

### 运维 › 机柜管理

| 用途 | 接口 | 类型 | 命令行 | 用到的字段 |
| --- | --- | --- | --- | --- |
| 机柜状态与健康 | `FindRackIds → FindRacksByIds` | Core gRPC · 读 | `nico-admin-cli rack list；nico-admin-cli rack show <RACK_ID>` | id、rack_group_id、status.lifecycle.{state,state_reason}、status.health、status.health_sources、metadata、created、updated |
| 机柜规格，以及还没有出现的机柜 | `GetAllExpectedRacks` | Core gRPC · 读 | `nico-admin-cli expected-rack show` | rack_id、rack_profile_id、rack_group_id、metadata |
| 托盘计数与任务计数 | `GET /rack、GET /rack/{id}` | REST · 读 | `nicocli rack list --site-id <SITE>` | id、name、operationStatus、operationStatusDetails.trayCountsByType、nvLinkDomainIds、taskStats.{pendingTaskCount,activeTaskCount}、health、components[] |
| 对账差异数 | `GET /rack/{id}/validation、GET /rack/validation` | REST · 读 | `nicocli rack validate --site-id <SITE>` | diffs[].{type,id,macAddress,fieldDiffs}、totalDiffs、missingCount、unexpectedCount、mismatchCount、matchCount |
| 当前任务 | `GET /task、GET /rack/{id}/task、GET /tray/{id}/task、GET /task/{id}` | REST · 读 | `nicocli rack task get --site-id <SITE> <RACK_ID>` | id、status（Pending、Running、Succeeded、Failed、Terminated）、description、message、ruleId、started、finished、report |

### 运维 › 机柜管理 › 机柜详情

| 用途 | 接口 | 类型 | 命令行 | 用到的字段 |
| --- | --- | --- | --- | --- |
| 状态、原因与健康 | `FindRackIds → FindRacksByIds` | Core gRPC · 读 | `nico-admin-cli rack list；nico-admin-cli rack show <RACK_ID>` | id、rack_group_id、status.lifecycle.{state,state_reason}、status.health、status.health_sources、metadata、created、updated |
| 机柜规格 | `ListRackProfiles / GetRackProfile` | Core gRPC · 读 | `nico-admin-cli rack profile list；nico-admin-cli rack profile show <RACK_ID>` | rack_profile_id、profile.rack_hardware_topology、profile.capabilities.{compute,switch,power_shelf}.count、profile.product_family |
| 状态历史 | `FindRackStateHistories` | Core gRPC · 读 | `nico-admin-cli rack state-history <RACK_ID>` | histories[rack_id].records[].{state,version,time} |
| 任务计数与所属域 | `GET /rack、GET /rack/{id}` | REST · 读 | `nicocli rack list --site-id <SITE>` | id、name、operationStatus、operationStatusDetails.trayCountsByType、nvLinkDomainIds、taskStats.{pendingTaskCount,activeTaskCount}、health、components[] |
| 对账统计与差异 | `GET /rack/{id}/validation、GET /rack/validation` | REST · 读 | `nicocli rack validate --site-id <SITE>` | diffs[].{type,id,macAddress,fieldDiffs}、totalDiffs、missingCount、unexpectedCount、mismatchCount、matchCount |
| 机柜立面的槽位 | `GET /tray、GET /tray/{id}` | REST · 读 | `nicocli tray list --site-id <SITE> --rack-id <RACK>` | id、type（Compute、NVSwitch、PowerShelf）、position.{slotId,trayIdx,hostId}、firmwareVersion、powerState、operationStatus、leakStatus、bmcs、rackId、nvLinkDomainId、taskStats、health |
| 设备表：计算托盘 | `FindMachineIds → FindMachinesByIds` | Core gRPC · 读 | `nico-admin-cli machine show [--hosts]` | id、rack_id、placement_in_rack.{slot_number,tray_index}、state、state_reason.{outcome,outcome_msg}、state_sla.time_in_state_above_sla、status.health.alerts[]、bmc.{ip,mac}、status.bmc_status.firmware_version、status.discovery_info.dmi_data.chassis_serial、status.associated_dpu_machine_ids、config.maintenance_reference、status.quarantine、status.nvlink_info.domain_uuid、status.lldp_neighbors[]、inventory.components[] |
| 设备表：交换机 | `FindSwitchIds → FindSwitchesByIds` | Core gRPC · 读 | `nico-admin-cli switch list；nico-admin-cli switch show <SWITCH_ID>` | id、rack_id、placement_in_rack、nvlink_domain_uuid、bmc_info.{ip,mac,firmware_version}、status.serial_number、status.power_state、status.controller_state、status.state_reason、status.health、status.fabric_manager_status_details、status.nvos_ports[].{mac,addresses,is_primary} |
| 设备表：供电框 | `FindPowerShelfIds → FindPowerShelvesByIds` | Core gRPC · 读 | `nico-admin-cli power-shelf list；nico-admin-cli power-shelf show <ID>` | id、rack_id、bmc_info.{ip,mac,firmware_version}、config.{capacity,voltage}、status.power_state、status.controller_state、status.state_reason、status.health |
| 对账：声明的序列号 | `GetAllExpectedMachines / GetAllExpectedMachinesLinked` | Core gRPC · 读 | `nico-admin-cli expected-machine show` | chassis_serial_number、bmc_mac_address、rack_id、bmc_ip_address、host_nics[]、metadata.labels、linked: interface_id、explored_endpoint_address、machine_id |
| 对账：实测序列号和探测失败原因 | `FindExploredEndpointIds → FindExploredEndpointsByIds` | Core gRPC · 读 | `nico-admin-cli site-explorer get-report endpoint` | address、report.endpoint_type、report.vendor、report.systems[].serial_number、report.chassis[].serial_number、report.last_exploration_error_schema.{error_code,mitigation,text}、report.firmware_versions、preingestion_state、pause_remediation |
| 重新发现、重新探测 | `ReExploreEndpoint / RefreshEndpointReport / ClearSiteExplorationError` | Core gRPC · 写 | `nico-admin-cli site-explorer re-explore；nico-admin-cli site-explorer refresh；nico-admin-cli site-explorer clear-error` | — |
| 放行等待中的主机 | `AllowIngestionAndPowerOn` | Core gRPC · 写 | `nico-admin-cli managed-host power-options allow-ingestion-and-power-on --mac-address <MAC>` | — |
| 更换设备：更新声明 | `CreateExpectedMachines / UpdateExpectedMachines / PatchExpectedMachine / DeleteExpectedMachine` | Core gRPC · 写 | `nico-admin-cli expected-machine add -a <BMC_MAC> -u <BMC_USER> -p <BMC_PASS> -s <SERIAL> [--rack_id] [--bmc-ip-address] [--interfaces] [--label]` | — |
| 开始上线 | `POST /rack/{id}/bringup` | REST · 写 | `nicocli rack bringup --site-id <SITE> <RACK_ID>` | taskIds[] |
| 机柜电源 | `PATCH /rack/{id}/power` | REST · 写 | `nicocli rack power --site-id <SITE> --data '{"state":"On"}' <RACK_ID>` | taskIds[] |
| 固件更新 | `PATCH /rack/{id}/firmware` | REST · 写 | `nicocli rack firmware --site-id <SITE> <RACK_ID>` | taskIds[] |
| 固件阶段的逐台进度 | `GetComponentFirmwareStatus` | Core gRPC · 读 | `nico-admin-cli component-manager get-firmware-update-status {compute-tray\|switch\|power-shelf\|rack}` | statuses[].state（QUEUED、IN_PROGRESS、VERIFYING、COMPLETED、FAILED、CANCELLED）、statuses[].target_version、statuses[].updated_at |
| 任务卡与阶段 | `GET /task、GET /rack/{id}/task、GET /tray/{id}/task、GET /task/{id}` | REST · 读 | `nicocli rack task get --site-id <SITE> <RACK_ID>` | id、status（Pending、Running、Succeeded、Failed、Terminated）、description、message、ruleId、started、finished、report |
| 取消任务 | `POST /task/{id}/cancel` | REST · 写 | `nicocli task cancel --site-id <SITE> <TASK_ID>` | status |
| NVOS 更新与 NMX-C 配置（见缺口：机柜上线由谁推进） | `OnDemandRackMaintenance / TerminateRackMaintenance` | Core gRPC · 写 | `nico-admin-cli rack maintenance start --rack <ID> --activities <firmware-upgrade,nvos-update,power-sequence,configure-nmx-cluster>；nico-admin-cli rack maintenance terminate --rack <ID>` | — |
| 机柜健康与泄漏告警 | `ListMachineHealthReports / ListSwitchHealthReports / ListPowerShelfHealthReports / ListRackHealthReports / ListNVLinkDomainHealthReports` | Core gRPC · 读 | `nico-admin-cli machine health-report show <ID>；nico-admin-cli nvl-domain health-report show` | health_report_entries[].mode、report.source、report.alerts[].{id,target,in_alert_since,message,classifications[]} |

### 运维 › NVLink 域管理

| 用途 | 接口 | 类型 | 命令行 | 用到的字段 |
| --- | --- | --- | --- | --- |
| 域、成员机柜和 NMX-C 集群 | `GET /domain/nvlink、GET /domain/nvlink/{id}` | REST · 读 | `nicocli domain list --site-id <SITE>` | id（等于机柜组编号）、name、nmxcClusterId、topology、operationStatus、components |
| 交换机回报的域编号 | `FindSwitchIds → FindSwitchesByIds` | Core gRPC · 读 | `nico-admin-cli switch list；nico-admin-cli switch show <SWITCH_ID>` | id、rack_id、placement_in_rack、nvlink_domain_uuid、bmc_info.{ip,mac,firmware_version}、status.serial_number、status.power_state、status.controller_state、status.state_reason、status.health、status.fabric_manager_status_details、status.nvos_ports[].{mac,addresses,is_primary} |
| 域内各设备的固件版本 | `GetComponentInventory` | Core gRPC · 读 | — | entries[].result.{component_id,status,error}、entries[].report.firmware_versions、entries[].report.systems[]、entries[].report.chassis[] |
| 域的健康报告 | `ListMachineHealthReports / ListSwitchHealthReports / ListPowerShelfHealthReports / ListRackHealthReports / ListNVLinkDomainHealthReports` | Core gRPC · 读 | `nico-admin-cli machine health-report show <ID>；nico-admin-cli nvl-domain health-report show` | health_report_entries[].mode、report.source、report.alerts[].{id,target,in_alert_since,message,classifications[]} |
| 域级电源 | `PATCH /domain/nvlink/{id}/power` | REST · 写 | — | taskIds[] |
| 域级固件更新 | `PATCH /domain/nvlink/{id}/firmware` | REST · 写 | — | taskIds[] |
| 分阶段发布 | `POST /task/run、GET /task/run、GET /task/run/{id}/target、POST /task/run/{id}/pause\|resume\|advance\|cancel` | REST · 写 | — | id、status、statusReason、totalPhases、targets[].{rackId,phaseIndex,taskId,status} |
| 域级任务的进度 | `GET /task、GET /rack/{id}/task、GET /tray/{id}/task、GET /task/{id}` | REST · 读 | `nicocli rack task get --site-id <SITE> <RACK_ID>` | id、status（Pending、Running、Succeeded、Failed、Terminated）、description、message、ruleId、started、finished、report |

### 运维 › 设备管理

| 用途 | 接口 | 类型 | 命令行 | 用到的字段 |
| --- | --- | --- | --- | --- |
| 计算托盘的数量和需要处理的设备 | `FindMachineIds → FindMachinesByIds` | Core gRPC · 读 | `nico-admin-cli machine show [--hosts]` | id、rack_id、placement_in_rack.{slot_number,tray_index}、state、state_reason.{outcome,outcome_msg}、state_sla.time_in_state_above_sla、status.health.alerts[]、bmc.{ip,mac}、status.bmc_status.firmware_version、status.discovery_info.dmi_data.chassis_serial、status.associated_dpu_machine_ids、config.maintenance_reference、status.quarantine、status.nvlink_info.domain_uuid、status.lldp_neighbors[]、inventory.components[] |
| 交换机的数量和需要处理的设备 | `FindSwitchIds → FindSwitchesByIds` | Core gRPC · 读 | `nico-admin-cli switch list；nico-admin-cli switch show <SWITCH_ID>` | id、rack_id、placement_in_rack、nvlink_domain_uuid、bmc_info.{ip,mac,firmware_version}、status.serial_number、status.power_state、status.controller_state、status.state_reason、status.health、status.fabric_manager_status_details、status.nvos_ports[].{mac,addresses,is_primary} |
| 供电框的数量和需要处理的设备 | `FindPowerShelfIds → FindPowerShelvesByIds` | Core gRPC · 读 | `nico-admin-cli power-shelf list；nico-admin-cli power-shelf show <ID>` | id、rack_id、bmc_info.{ip,mac,firmware_version}、config.{capacity,voltage}、status.power_state、status.controller_state、status.state_reason、status.health |
| DPU 的数量和需要处理的设备 | `FindMachineIds（include_dpus、exclude_hosts）→ FindMachinesByIds` | Core gRPC · 读 | `nico-admin-cli dpu status；nico-admin-cli dpu versions` | id、state、status.associated_host_machine_id、status.discovery_info.dpu_info.firmware_version、status.bmc_status.firmware_version、status.dpu_agent_version、status.health |
| 按序列号、MAC、地址搜索 | `IdentifySerial / IdentifyMac / FindIpAddress` | Core gRPC · 读 | `nico-admin-cli ip find <IP>` | machine_id、matches[].{ip_type,owner_id} |

### 运维 › 设备管理 › 计算托盘

| 用途 | 接口 | 类型 | 命令行 | 用到的字段 |
| --- | --- | --- | --- | --- |
| 列表、状态、健康和地址 | `FindMachineIds → FindMachinesByIds` | Core gRPC · 读 | `nico-admin-cli machine show [--hosts]` | id、rack_id、placement_in_rack.{slot_number,tray_index}、state、state_reason.{outcome,outcome_msg}、state_sla.time_in_state_above_sla、status.health.alerts[]、bmc.{ip,mac}、status.bmc_status.firmware_version、status.discovery_info.dmi_data.chassis_serial、status.associated_dpu_machine_ids、config.maintenance_reference、status.quarantine、status.nvlink_info.domain_uuid、status.lldp_neighbors[]、inventory.components[] |
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
| 电源的直接执行路径（见缺口） | `ComponentPowerControl` | Core gRPC · 写 | `nico-admin-cli component-manager component-power-control --action <on\|graceful-shutdown\|force-off\|graceful-restart\|force-restart\|a-c-powercycle> {compute-tray\|switch\|power-shelf} --machine-id <ID>` | results[].{component_id,status,error} |

### 运维 › 设备管理 › 交换机

| 用途 | 接口 | 类型 | 命令行 | 用到的字段 |
| --- | --- | --- | --- | --- |
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
| DPU 列表、状态和固件 | `FindMachineIds（include_dpus、exclude_hosts）→ FindMachinesByIds` | Core gRPC · 读 | `nico-admin-cli dpu status；nico-admin-cli dpu versions` | id、state、status.associated_host_machine_id、status.discovery_info.dpu_info.firmware_version、status.bmc_status.firmware_version、status.dpu_agent_version、status.health |
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

### 交付 › 机柜交付

| 用途 | 接口 | 类型 | 命令行 | 用到的字段 |
| --- | --- | --- | --- | --- |
| 机柜是否就绪 | `FindRackIds → FindRacksByIds` | Core gRPC · 读 | `nico-admin-cli rack list；nico-admin-cli rack show <RACK_ID>` | id、rack_group_id、status.lifecycle.{state,state_reason}、status.health、status.health_sources、metadata、created、updated |
| 按机柜筛出计算托盘 | `FindMachineIds → FindMachinesByIds` | Core gRPC · 读 | `nico-admin-cli machine show [--hosts]` | id、rack_id、placement_in_rack.{slot_number,tray_index}、state、state_reason.{outcome,outcome_msg}、state_sla.time_in_state_above_sla、status.health.alerts[]、bmc.{ip,mac}、status.bmc_status.firmware_version、status.discovery_info.dmi_data.chassis_serial、status.associated_dpu_machine_ids、config.maintenance_reference、status.quarantine、status.nvlink_info.domain_uuid、status.lldp_neighbors[]、inventory.components[] |
| 可交付的托盘数和不可交付的原因 | `FindHostStatesByIds` | Core gRPC · 读 | — | state、state_reason、rack_id、nvlink_domain_id、bmc_ip、dpu_ids、health_alerts、quarantine、allocation.{allocatable,blocking_reason,blocking_detail}、explored.{bmc_version,uefi_version} |
| 机柜和域的告警 | `ListMachineHealthReports / ListSwitchHealthReports / ListPowerShelfHealthReports / ListRackHealthReports / ListNVLinkDomainHealthReports` | Core gRPC · 读 | `nico-admin-cli machine health-report show <ID>；nico-admin-cli nvl-domain health-report show` | health_report_entries[].mode、report.source、report.alerts[].{id,target,in_alert_since,message,classifications[]} |
| 已交付的实例数 | `FindInstanceIds → FindInstancesByIds / FindInstanceByMachineID` | Core gRPC · 读 | `nico-admin-cli instance show` | id、machine_id、config.tenant.{tenant_organization_id,hostname}、config.os、status.tenant.state、status.network、metadata |
| 可选的安装方案 | `FindOperatingSystemIds → FindOperatingSystemsByIds` | Core gRPC · 读 | `nico-admin-cli operating-system show` | id、name、type、status、is_active、ipxe_template_id、ipxe_template_parameters、ipxe_template_artifacts[].{name,url,cached_url} |
| 装机并验收 | `AllocateInstances / AllocateInstance` | Core gRPC · 写 | `nico-admin-cli instance allocate --machine-id <ID>... --transactional --os <OS_ID> [--flat-vpc-id\|--vpc-prefix-id]` | instances[].{id,machine_id,status} |
| 交给上层平台 | `CreateInstanceType / AssociateMachinesWithInstanceType / CreateComputeAllocation` | Core gRPC · 写 | `nico-admin-cli instance-type create；nico-admin-cli instance-type associate；nico-admin-cli compute-allocation create` | — |

### 交付 › 安装任务

| 用途 | 接口 | 类型 | 命令行 | 用到的字段 |
| --- | --- | --- | --- | --- |
| 实例状态 | `FindInstanceIds → FindInstancesByIds / FindInstanceByMachineID` | Core gRPC · 读 | `nico-admin-cli instance show` | id、machine_id、config.tenant.{tenant_organization_id,hostname}、config.os、status.tenant.state、status.network、metadata |
| 主机状态 | `FindMachineIds → FindMachinesByIds` | Core gRPC · 读 | `nico-admin-cli machine show [--hosts]` | id、rack_id、placement_in_rack.{slot_number,tray_index}、state、state_reason.{outcome,outcome_msg}、state_sla.time_in_state_above_sla、status.health.alerts[]、bmc.{ip,mac}、status.bmc_status.firmware_version、status.discovery_info.dmi_data.chassis_serial、status.associated_dpu_machine_ids、config.maintenance_reference、status.quarantine、status.nvlink_info.domain_uuid、status.lldp_neighbors[]、inventory.components[] |

### 交付 › 实例管理

| 用途 | 接口 | 类型 | 命令行 | 用到的字段 |
| --- | --- | --- | --- | --- |
| 实例、租户和系统 | `FindInstanceIds → FindInstancesByIds / FindInstanceByMachineID` | Core gRPC · 读 | `nico-admin-cli instance show` | id、machine_id、config.tenant.{tenant_organization_id,hostname}、config.os、status.tenant.state、status.network、metadata |
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

### 接入 › 设备清单 › 期望清单

| 用途 | 接口 | 类型 | 命令行 | 用到的字段 |
| --- | --- | --- | --- | --- |
| 核对机柜规格是否受支持 | `ListRackProfiles / GetRackProfile` | Core gRPC · 读 | `nico-admin-cli rack profile list；nico-admin-cli rack profile show <RACK_ID>` | rack_profile_id、profile.rack_hardware_topology、profile.capabilities.{compute,switch,power_shelf}.count、profile.product_family |
| 核对固定地址落在已有子网内 | `FindNetworkSegmentIds → FindNetworkSegmentsByIds` | Core gRPC · 读 | `nico-admin-cli network-segment show` | id、metadata.name、config.segment_type、config.mtu、config.subdomain_id、config.prefixes[].{prefix,gateway,reserve_first,free_ip_count_v2}、status.lifecycle.state |
| 读取机柜组 | `GetAllExpectedRackGroups` | Core gRPC · 读 | `nico-admin-cli expected-rack-group show` | rack_group_id、topology、protocol、racks[].rack_id、racks[].members[].{type,manufacturer,id} |
| 写入机柜组 | `AddExpectedRackGroup / UpdateExpectedRackGroup / DeleteExpectedRackGroup` | Core gRPC · 写 | `nico-admin-cli expected-rack-group add [--rack <JSON>]... <RACK_GROUP_ID> <PROTOCOL> <TOPOLOGY>` | — |
| 读取机柜声明和推导出的规格 | `GetAllExpectedRacks` | Core gRPC · 读 | `nico-admin-cli expected-rack show` | rack_id、rack_profile_id、rack_group_id、metadata |
| 写入机柜声明 | `AddExpectedRack / UpdateExpectedRack / DeleteExpectedRack` | Core gRPC · 写 | `nico-admin-cli expected-rack add [--label K:V] <RACK_ID>` | — |
| 读取计算托盘声明 | `GetAllExpectedMachines / GetAllExpectedMachinesLinked` | Core gRPC · 读 | `nico-admin-cli expected-machine show` | chassis_serial_number、bmc_mac_address、rack_id、bmc_ip_address、host_nics[]、metadata.labels、linked: interface_id、explored_endpoint_address、machine_id |
| 写入计算托盘声明 | `CreateExpectedMachines / UpdateExpectedMachines / PatchExpectedMachine / DeleteExpectedMachine` | Core gRPC · 写 | `nico-admin-cli expected-machine add -a <BMC_MAC> -u <BMC_USER> -p <BMC_PASS> -s <SERIAL> [--rack_id] [--bmc-ip-address] [--interfaces] [--label]` | — |
| 读取交换机声明 | `GetAllExpectedSwitches / GetAllExpectedSwitchesLinked` | Core gRPC · 读 | `nico-admin-cli expected-switch show` | switch_serial_number、bmc_mac_address、nvos_interfaces[]、rack_id、linked: switch_id、explored_endpoint_address |
| 写入交换机声明 | `AddExpectedSwitch / PatchExpectedSwitch / DeleteExpectedSwitch` | Core gRPC · 写 | `nico-admin-cli expected-switch add -a <BMC_MAC> -u <USER> -p <PASS> -s <SERIAL> --nvos-interface <MAC[,primary]> [--rack_id]` | — |
| 读取供电框声明 | `GetAllExpectedPowerShelves / GetAllExpectedPowerShelvesLinked` | Core gRPC · 读 | `nico-admin-cli expected-power-shelf show` | shelf_serial_number、bmc_mac_address、rack_id、linked: power_shelf_id、explored_endpoint_address |
| 写入供电框声明 | `AddExpectedPowerShelf / PatchExpectedPowerShelf / DeleteExpectedPowerShelf` | Core gRPC · 写 | `nico-admin-cli expected-power-shelf add -a <BMC_MAC> -u <USER> -p <PASS> -s <SERIAL> [--rack_id]` | — |
| 写入 NVLink 域声明 | `CreateExpectedNvLinkDomain / DeleteExpectedNvLinkDomain / FindExpectedNvLinkDomainIds` | Core gRPC · 写 | `nico-admin-cli expected-nvlink-domain create --member <MAC>... [--name] <RACK_GROUP_ID>` | — |

### 接入 › 设备清单 › 版本记录

不调用 NICo，数据由平台自己保存。

### 接入 › 设备发现

| 用途 | 接口 | 类型 | 命令行 | 用到的字段 |
| --- | --- | --- | --- | --- |
| 计算托盘声明走到了哪一步 | `GetAllExpectedMachines / GetAllExpectedMachinesLinked` | Core gRPC · 读 | `nico-admin-cli expected-machine show` | chassis_serial_number、bmc_mac_address、rack_id、bmc_ip_address、host_nics[]、metadata.labels、linked: interface_id、explored_endpoint_address、machine_id |
| 交换机声明走到了哪一步 | `GetAllExpectedSwitches / GetAllExpectedSwitchesLinked` | Core gRPC · 读 | `nico-admin-cli expected-switch show` | switch_serial_number、bmc_mac_address、nvos_interfaces[]、rack_id、linked: switch_id、explored_endpoint_address |
| 供电框声明走到了哪一步 | `GetAllExpectedPowerShelves / GetAllExpectedPowerShelvesLinked` | Core gRPC · 读 | `nico-admin-cli expected-power-shelf show` | shelf_serial_number、bmc_mac_address、rack_id、linked: power_shelf_id、explored_endpoint_address |
| 有没有收到 DHCP 请求 | `FindInterfaces` | Core gRPC · 读 | `nico-admin-cli machine-interfaces show` | id、mac_address、address[]、segment_id、hostname、vendor、last_dhcp、machine_id、switch_id、power_shelf_id、association_type、interface_type、primary_interface |
| 探测结果和失败原因 | `FindExploredEndpointIds → FindExploredEndpointsByIds` | Core gRPC · 读 | `nico-admin-cli site-explorer get-report endpoint` | address、report.endpoint_type、report.vendor、report.systems[].serial_number、report.chassis[].serial_number、report.last_exploration_error_schema.{error_code,mitigation,text}、report.firmware_versions、preingestion_state、pause_remediation |
| 主机与 DPU 的配对 | `FindExploredManagedHostIds → FindExploredManagedHostsByIds` | Core gRPC · 读 | `nico-admin-cli site-explorer get-report managed-host` | host_bmc_ip、dpus[].{bmc_ip,host_pf_mac_address} |
| 未声明的主机 | `GetAllUnexpectedMachines` | Core gRPC · 读 | — | address、bmc_mac_address、machine_id |
| 是否在等待放行 | `DetermineMachineIngestionState` | Core gRPC · 读 | `nico-admin-cli managed-host power-options get-machine-ingestion-state --mac-address <MAC>` | NotDiscovered、WaitingForIngestion、IngestionMachineNotCreated、IngestionMachineCreated |
| 计算托盘的状态机阶段 | `FindMachineIds → FindMachinesByIds` | Core gRPC · 读 | `nico-admin-cli machine show [--hosts]` | id、rack_id、placement_in_rack.{slot_number,tray_index}、state、state_reason.{outcome,outcome_msg}、state_sla.time_in_state_above_sla、status.health.alerts[]、bmc.{ip,mac}、status.bmc_status.firmware_version、status.discovery_info.dmi_data.chassis_serial、status.associated_dpu_machine_ids、config.maintenance_reference、status.quarantine、status.nvlink_info.domain_uuid、status.lldp_neighbors[]、inventory.components[] |
| 交换机的状态机阶段 | `FindSwitchIds → FindSwitchesByIds` | Core gRPC · 读 | `nico-admin-cli switch list；nico-admin-cli switch show <SWITCH_ID>` | id、rack_id、placement_in_rack、nvlink_domain_uuid、bmc_info.{ip,mac,firmware_version}、status.serial_number、status.power_state、status.controller_state、status.state_reason、status.health、status.fabric_manager_status_details、status.nvos_ports[].{mac,addresses,is_primary} |
| 供电框的状态机阶段 | `FindPowerShelfIds → FindPowerShelvesByIds` | Core gRPC · 读 | `nico-admin-cli power-shelf list；nico-admin-cli power-shelf show <ID>` | id、rack_id、bmc_info.{ip,mac,firmware_version}、config.{capacity,voltage}、status.power_state、status.controller_state、status.state_reason、status.health |
| 最近一次扫描 | `GetSiteExplorerLastRun` | Core gRPC · 读 | — | started_at、finished_at、success、error、endpoint_explorations、endpoint_explorations_success、endpoint_explorations_failed、failure_category、last_successful_finished_at |

### 配置 › 站点设置 › 站点概况

| 用途 | 接口 | 类型 | 命令行 | 用到的字段 |
| --- | --- | --- | --- | --- |
| Core 版本与运行配置 | `Version` | Core gRPC · 读 | `nico-admin-cli version --show-runtime-config` | build_version、git_sha、capabilities[]、runtime_config.dhcp_servers、runtime_config.networks、runtime_config.initial_domain_name、runtime_config.attestation_enabled |
| RMS 是否就绪 | `GetRmsVersion` | Core gRPC · 读 | `nico-admin-cli backend rms status` | version |
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
| RMS 版本 | `GetRmsVersion` | Core gRPC · 读 | `nico-admin-cli backend rms status` | version |
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
