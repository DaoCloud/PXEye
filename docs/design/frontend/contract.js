"use strict";
/* 接口契约：页面与 NICo 之间的约定。
   五张表，来源只有这一个文件：
   - NICO_RESOURCES：NICo 里的资源，以及它们之间的依赖。回答“这个页面要有数据，必须先有什么”。
   - NICO_CALLS：页面用到的 NICo 接口：属于哪一类接口、请求参数、用到的字段、对应的命令行、前置资源。
   - CONTRACT_GAPS：设计需要、但 NICo 没有直接提供的东西，以及待定的处理方式。
   - PAGE_CALLS：每个页面用到哪些接口和用途。
   - NICO_COMPONENTS：要部署的组件。每个组件提供什么、哪些接口和页面离不开它、缺了它会怎样。
   这个文件只由实现参考版（internal.html）加载；对外版（index.html）不加载它。

   证据等级（evidence）：定义 = 只读过源码里的定义；调用 = 在没有整机柜硬件的 NICo 环境里实际调用过；
   模拟 = 在模拟整机柜的环境里调用过；现场 = 在真实整机柜环境核对过。调用过的接口用 observed 写明看到了什么。
   准备方式（prep）说明在没有真实整机柜时这个资源怎么得到。
   used = 现有产品（主线分支）已经调用过这个接口；没有这个标记的是整机柜方向新增的。 */

const CONTRACT_SOURCE = { repo: "dsx-ai-factory/infra-controller", commit: "856eb1665", version: "v2.5.0 之后", note: "接口、参数和字段取自这个提交的源码。换版本时逐项重新核对。", tested: "实际调用所用的环境运行的是提交 28e4e9824，比上面的提交早 2 个，在同一条线上。" };
const PREP_LABEL = { config: "部署时配置", direct: "可直接创建", derived: "NICo 自动生成", simulator: "需要模拟器或真实硬件", hardware: "只有真实硬件才有" };

const NICO_RESOURCES = [];
const NICO_CALLS = [];
const CONTRACT_GAPS = [];

/* 录入用的简写。出处是 NICo 源码里的相对路径和行号。 */
const R = (id, name, object, createdBy, requires, prep, extra = {}) => NICO_RESOURCES.push({ id, name, object, createdBy, requires, prep, ...extra });
const C = (id, area, surface, name, o = {}) => NICO_CALLS.push({ id, area, surface, name, evidence: "定义", ...o });
const G = (need, pages, finding, options, source) => CONTRACT_GAPS.push({ need, pages, finding, options, source });

/* ================= 资源 =================
   按“先有什么才能有什么”连成一张图。分五段：部署与配置、接入、编排、交付、健康。 */

/* ---- 部署与配置 ---- */
R("core", "NICo Core", "nico-api", "部署 NICo Core 及其数据库和密钥库；平台用客户端证书访问", [], "config",
  { note: "Core 按证书里的服务身份做权限判断，每个接口允许哪些身份写在权限表里", source: "crates/api-core/src/auth/internal_rbac_rules.rs:30" });
R("dns-domain", "正向 DNS 域", "Domain", "站点配置 initial_domain_name（只在域表为空时生效），或 CreateDomain", ["core"], "config",
  { note: "配置里的子网只有在恰好存在一个正向域时才会创建；子网没有子域时，设备拿不到 DHCP 记录", source: "crates/api-core/src/db_init.rs:46" });
R("resource-pools", "VLAN 与 VNI 资源池", "resource pool", "站点配置；nico-admin-cli resource-pool list / grow", ["core"], "config",
  { note: "带外管理以外的子网类型，创建时要从这两个池里各取一个值", source: "crates/api-core/src/handlers/network_segment.rs:773" });
R("rack-profiles", "机柜规格配置", "[rack_profiles]", "写在 nico-api 的站点配置里，随部署下发；接口和命令行都不能新增", ["core"], "config",
  { note: "规格名由机柜组的拓扑和成员厂商推导，推导出的名字必须在这里配置过", source: "crates/api-core/src/cfg/file.rs:857" });
R("firmware-object", "机柜固件清单", "[rack_profiles.<规格>.firmware_object]", "站点配置里给每个机柜规格填一个固件清单的地址和访问凭据", ["rack-profiles"], "config",
  { note: "固件操作不带版本时使用它。NICo 里没有可以命名、可以列出的“固件基线”对象", source: "docs/configuration/rms.md:183" });
R("site-credentials", "站点默认凭据", "SiteWideBmcRoot、主机 UEFI、DPU UEFI", "InitializeSiteCredentials，或逐项 CreateCredential", ["core"], "direct",
  { note: "三项都配置后，站点发现才会去探测设备", source: "crates/site-explorer/src/credentials.rs:113" });
R("dhcp-service", "DHCP 与引导服务", "nico-dhcp、nico-pxe", "随 NICo 部署；域名服务器、时间服务器和引导服务器地址写在 DHCP 服务的部署参数里", ["core"], "config",
  { note: "这些参数没有读取接口，只能从部署配置里看", source: "helm/charts/nico-dhcp/values.yaml:149" });
R("cluster-issuer", "集群级证书签发者", "ClusterIssuer vault-nico-issuer", "在 Vault 里建一个签发角色并让 cert-manager 用它签发；RMS、Flow、站点代理和编排用数据库的证书都由它签，和 Core 的证书出自同一个站点 CA", ["core"], "direct",
  { note: "官方 Chart 申请的是椭圆曲线证书，签发角色要接受这种密钥。证书最长 30 天，自动续期，但 RMS 和数据库不会自动重新加载", source: "helm-prereqs/templates/vault-nico-issuer.yaml:8" });
R("orchestration-db", "编排用数据库", "nico-pg-cluster", "单独的 PostgreSQL，按官方的名称、账号和凭据密钥提供 REST、Flow、Temporal、Keycloak、RMS 各自的库", ["cluster-issuer"], "direct",
  { note: "不和 Core 的数据库共用。REST 的库要有 pg_trgm 扩展；REST 和 Flow 的账号是超级用户，Temporal 的账号可建库", source: "helm-prereqs/templates/postgresql.yaml:46" });
R("temporal", "Temporal", "temporal", "官方 Chart 安装后，用它的管理工具建逻辑命名空间 cloud、site、flow，以及每个站点一个以站点 UUID 命名的", ["orchestration-db"], "direct",
  { note: "Flow 启动时要求 flow 这个逻辑命名空间已经存在。Temporal 自己的证书由 REST 的 CA 签发，不是站点 CA", source: "helm-prereqs/setup.sh:2406" });
R("rms", "RMS", "Rack Management Service", "官方 Chart rack-manager，发布名 rack，命名空间固定为 rack-manager；镜像要从公开源码自己构建。Core 配置里的 RMS 地址默认就指向它，装好后 Core 不用重启", ["rack-profiles", "cluster-issuer", "orchestration-db"], "config",
  { prepNote: "RMS 本身可以在没有硬件时部署并连通；要让它有设备可管，需要 RMS 模拟服务或真实机柜", note: "任一后端选了 rms，启动时就要求机柜规格配置里有产品系列和厂商", source: "docs/configuration/rms.md:243" });
R("component-manager", "组件管理器", "[component_manager]", "站点配置里为计算托盘、交换机、供电框各选一个后端，默认都是 rms", ["rms"], "config",
  { note: "没有这段配置时，设备电源、复位、固件接口返回未实现。当前生效的后端没有读取接口", source: "crates/api-core/src/handlers/component_manager.rs:130" });
R("rest-auth", "REST 身份认证", "JWT 签发方与声明映射", "REST 的部署配置：外部签发方或内置 Keycloak，二选一；从声明映射出组织名和角色", [], "config",
  { source: "rest-api/openapi/auth.md:43" });
R("rest-site", "REST 站点", "Infrastructure Provider、Site、站点代理", "官方 Chart nico-rest 和 nico-rest-site-agent，命名空间 nico-rest。在 REST 的库里登记站点，站点代理安装时向站点管理服务换取一次性口令完成握手；之后清单上报，站点由 Pending 变为 Registered", ["core", "rest-auth", "temporal", "cluster-issuer"], "direct",
  { note: "机柜、托盘、域和任务接口都要带 siteId。站点代理上线后回报是否启用了 Flow", source: "rest-api/INSTALLATION.md:773" });
R("flow", "Flow", "nico-flow", "官方 Chart nico-flow，发布名 flow，命名空间固定为 flow；镜像要自己构建，并且和 Core 出自同一个源码提交。站点代理打开 Flow 开关后经它转发", ["rest-site", "component-manager", "temporal"], "config",
  { note: "REST 经 Temporal 和站点代理转发到 Flow。直接访问 Flow 要用双向证书，并且身份在允许名单里", source: "docs/architecture/flow.md:3" });
R("operation-rule", "操作规则", "OperationRule", "默认规则写在 Flow 的代码里；自定义规则用 POST /task/rule 创建，只有电源和固件两类", ["flow"], "derived",
  { note: "选用顺序：请求里指定的规则、机柜关联的规则、该类操作的全局默认、内置规则", source: "docs/operations/flow/operation-rules.md:553" });
R("nmxc", "NMX-C 接入", "NvlinkNmxcEndpoint", "机柜里的设备不需要登记：Core 取机柜里第一台就绪且 Fabric Manager 已配置的交换机的 NVOS 地址，端口 9370。只有不属于任何机柜的设备才用 CreateNvlinkNmxcEndpoint 登记（机箱序列号和地址）", ["core"], "direct",
  { prepNote: "NMX-C 运行在交换机上，由 RMS 配置；没有交换机时只能接 NMX-C 模拟服务", note: "没有专门的状态接口，只能从机柜健康报告里的 NmxcUnreachable 判断。交换机要先由 RMS 配好，Core 才找得到 NMX-C", source: "crates/nvlink-manager/src/nmx_c_endpoint.rs:102" });

/* ---- 接入：子网、设备声明、发现 ---- */
R("network-segment", "子网", "NetworkSegment", "站点配置 [networks.<名称>] 在启动时创建并直接就绪；或 CreateNetworkSegment，创建后由控制器从 Provisioning 转为 Ready", ["dns-domain", "resource-pools"], "direct",
  { note: "没有修改接口。创建后只能给带外管理子网补另一个地址族、改 IPv4 的 DHCP 地址池、改 VPC 挂接；配置文件后续的修改不会更新已创建的子网", source: "crates/rpc/proto/forge.proto:129" });
R("rack-group", "机柜组声明", "ExpectedRackGroup", "AddExpectedRackGroup：拓扑、协议、每个机柜及其成员的类型和厂商", ["core"], "direct",
  { note: "成员只是（类型、厂商、编号）三元组，只用于推导机柜规格，不与设备声明关联", source: "crates/rpc/proto/forge.proto:3528" });
R("expected-rack", "机柜声明", "ExpectedRack", "AddExpectedRack：只需机柜 ID；规格和所属机柜组由 NICo 推导", ["rack-group", "rack-profiles"], "direct",
  { note: "要求恰好一个机柜组包含这个机柜 ID，且该机柜至少有一个计算成员和一个交换机成员", source: "crates/api-core/src/handlers/expected_rack.rs:29" });
R("expected-devices", "设备声明", "ExpectedMachine / ExpectedSwitch / ExpectedPowerShelf", "逐条新增或批量新增：BMC MAC、序列号、机柜 ID、出厂凭据；交换机另需 NVOS 管理口", ["core"], "direct",
  { note: "新增时不校验机柜、子网和凭据是否存在；机柜 ID 是自由文本", source: "crates/api-core/src/handlers/expected_machine.rs:77" });
R("expected-nvlink-domain", "NVLink 域声明", "ExpectedNvLinkDomain", "CreateExpectedNvLinkDomain：机柜组 ID 和成员的 BMC MAC；创建后不可修改，只能删除重建", ["rack-group", "expected-devices"], "direct",
  { note: "每个 MAC 必须对应机柜组内某个机柜里的计算托盘或交换机声明，且至少各有一个", source: "crates/api-db/src/expected_nvlink_domain.rs:19" });
R("dhcp-relay", "现场 DHCP 中继", "—", "现场网络设备把各管理网段的 DHCP 请求中继到 NICo 的 DHCP 服务", ["network-segment", "dhcp-service"], "hardware",
  { prepNote: "模拟器直接带着中继地址调用 Core，不经过真实网络", note: "NICo 按中继地址落在哪个子网前缀里来选子网，不看网关", source: "crates/api-core/src/dhcp/discover.rs:563" });
R("machine-interface", "设备接口与地址", "MachineInterface", "设备发出 DHCP 请求时由 Core 创建；声明了固定地址的接口由站点发现预先创建", ["dhcp-relay"], "simulator",
  { note: "没有声明的设备也会拿到地址，留下一条没有归属的接口记录", source: "crates/api-core/src/dhcp/discover.rs:716" });
R("explored-endpoint", "探测结果", "ExploredEndpoint", "站点发现按周期用 Redfish 探测带外管理子网上的接口", ["machine-interface", "site-credentials", "expected-devices"], "simulator",
  { note: "主机 BMC 要用设备声明里的出厂凭据，没有声明就报缺少凭据；一次认证失败后停止重试，直到清除错误", source: "crates/site-explorer/src/bmc_endpoint_explorer.rs:445" });
R("machine", "计算托盘对象", "Machine（主机）", "站点发现在预检完成、主机与 DPU 配对成功后创建，随后由状态机推进到 Ready", ["explored-endpoint"], "simulator",
  { note: "设备声明带暂停标记时要先放行；开启度量启动时还要人工批准", source: "crates/site-explorer/src/lib.rs:3234" });
R("dpu", "DPU 对象", "Machine（类型 DPU）", "DPU 的 BMC 被探测到并与主机配对后，随主机一起创建", ["explored-endpoint"], "simulator",
  { note: "DPU 不需要设备声明，用出厂凭据探测；与主机按序列号配对", source: "crates/site-explorer/src/lib.rs:1196" });
R("switch", "交换机对象", "Switch", "站点发现探测到与交换机声明匹配的 BMC 后创建", ["explored-endpoint", "component-manager"], "simulator",
  { note: "需要声明里的 NVOS 管理口 MAC 和主口，且该管理口已拿到地址，否则状态机进入 Error；随后的证书和口令配置经过硬件后端", source: "crates/switch-controller/src/initializing.rs:48" });
R("power-shelf", "供电框对象", "PowerShelf", "站点发现探测到与供电框声明匹配的 PMC 后创建", ["explored-endpoint"], "simulator",
  { source: "crates/site-explorer/src/inventory_creator/power_shelf_creator.rs:121" });
R("rack", "机柜对象", "Rack", "某个成员设备被接管时，如果它的机柜声明存在，由站点发现创建；没有创建接口", ["expected-rack", "switch"], "derived",
  { note: "状态机只看交换机数量：发现的交换机数达到规格要求进入 Discovering，就绪的交换机数达到要求进入 Maintenance。计算托盘和供电框的数量不是条件", source: "docs/architecture/state_machines/rackstatemachine.md:142" });

/* ---- 编排：Flow 的清单、任务和 NVLink 域 ---- */
R("flow-inventory", "Flow 的机柜与托盘清单", "Rack / Tray（REST）", "Flow 从 Core 同步机柜、设备和设备声明", ["flow", "rack"], "derived",
  { note: "REST 的机柜、托盘、域读的是这份清单，不是直接读 Core。单个机柜的操作按外部 ID 定位，批量操作按机柜名定位", source: "rest-api/api/pkg/api/handler/rack.go:154" });
R("flow-task", "任务", "Task", "机柜、托盘、域的每个写操作都返回任务编号，每个机柜一个任务", ["flow-inventory"], "derived",
  { note: "REST 的返回只表示任务已创建。要轮询任务直到成功、失败或终止", source: "rest-api/openapi/spec.yaml:28731" });
R("nvlink-domain", "NVLink 域", "NVLinkDomain（REST）、nvlink_domain_uuid（Core）", "REST 的域编号就是机柜组编号；Core 一侧在机柜上线配置好 NMX-C 集群后，在交换机和计算托盘上回报域 UUID", ["rack-group", "flow-inventory", "nmxc"], "simulator",
  { source: "rest-api/openapi/spec.yaml:27724" });

/* ---- 交付 ---- */
R("os-definition", "系统定义", "OperatingSystem", "CreateOperatingSystem：直接给 iPXE 脚本，或选一个内置 iPXE 模板并填参数和制品地址", ["core"], "direct",
  { note: "脚本方式创建后立即可用。模板方式里标为“只用缓存”的制品，要由外部程序下载后回填缓存地址，系统定义才变为可用；NICo 不下载制品", source: "docs/configuration/templated-ipxe-operating-systems.md:263" });
R("vpc", "默认租户与 VPC", "Tenant、Vpc", "平台只用一个默认租户。CreateTenant、CreateVpc。计算托盘的 DPU 处于 DPU 模式时用 FNN 或 ETHERNET_VIRTUALIZER，网卡模式或没有 DPU 时用 FLAT", ["core"], "direct",
  { note: "Core 的权限表只允许站点代理（以及模拟器）调用这两个创建接口，管理端证书不能调用", source: "crates/api-core/src/auth/internal_rbac_rules.rs:75" });
R("instance", "实例", "Instance", "AllocateInstances：每个实例一个机器 ID，加实例配置（默认租户和主机名、系统、网络）", ["machine", "os-definition", "vpc"], "simulator",
  { note: "托盘必须是 Ready，没有维护标记、阻止分配的告警、待处理的实例或退役。机柜的健康报告会并入柜内每台主机的健康，所以机柜上阻止分配的告警会挡住整柜", source: "crates/api-model/src/machine/mod.rs:543" });

/* ---- 健康 ---- */
R("health-report", "健康报告", "HealthReport", "硬件健康服务、DPU 代理、站点发现和设施事件消费者写入；也可以用 Insert…HealthReport 手工写入一条", ["machine"], "direct",
  { prepNote: "设备对象存在后，可以手工写入报告来验证页面：nico-admin-cli machine health-report add", source: "crates/api-core/src/handlers/health.rs:98" });
R("facility-events", "设施事件接入", "nico-dsx-exchange-consumer", "部署事件消费者并连到楼宇管理系统的消息总线；泄漏事件被写成机柜的健康报告", ["rack"], "config",
  { note: "消费者是否连上没有读取接口，只有它自己的指标和存活探针", source: "crates/dsx-exchange-consumer/src/health_updater.rs:184" });

/* ================= 接口：站点与依赖 ================= */
C("core.version", "站点与依赖", "Core gRPC", "Version", { cli: "nico-admin-cli version --show-runtime-config", request: "display_config 为真时带回运行配置", fields: ["build_version", "git_sha", "capabilities[]", "runtime_config.dhcp_servers", "runtime_config.networks", "runtime_config.initial_domain_name", "runtime_config.attestation_enabled"], requires: ["core"], note: "运行配置里没有时间服务器、组件管理器后端和配额执行方式", source: "forge.proto:36" });
C("rms.status", "站点与依赖", "Core gRPC", "GetRmsVersion", { cli: "nico-admin-cli backend rms status", fields: ["status", "message", "version"], requires: ["rms"], executedBy: "Core → RMS", note: "没有配置 RMS 时返回 UNAVAILABLE；30 秒超时。命令行只有在连通时退出码才是 0", source: "crates/api-core/src/handlers/rms.rs:75" });
C("rest.site", "站点与依赖", "REST", "GET /site、GET /site/{id}", { cli: "nicocli site list", fields: ["id", "status（Pending、Registered、Error）", "isOnline", "siteAgentVersion", "siteControllerVersion", "capabilities.flow", "machineStats"], requires: ["rest-site"], executedBy: "REST", note: "Flow 是否可用只能从这里的 capabilities.flow 看，Core 没有对应接口", source: "spec.yaml:946" });
C("credential.readiness", "站点与依赖", "Core gRPC", "GetSiteCredentialReadiness", { fields: ["configured[]", "missing[]", "requires_recovery[]"], requires: ["core"], source: "forge.proto:589" });
C("credential.write", "站点与依赖", "Core gRPC", "InitializeSiteCredentials / CreateCredential", { write: true, cli: "nico-admin-cli credential add-bmc；nico-admin-cli credential add-uefi", request: "generate_missing，或逐项给 BMC、主机 UEFI、DPU UEFI 口令", requires: ["core"], note: "口令经标准输入或安全文件传入，不出现在命令行和日志里", source: "forge.proto:586" });
C("explorer.last-run", "站点与依赖", "Core gRPC", "GetSiteExplorerLastRun", { fields: ["started_at", "finished_at", "success", "error", "endpoint_explorations", "endpoint_explorations_success", "endpoint_explorations_failed", "failure_category", "last_successful_finished_at"], requires: ["core"], source: "site_explorer.proto:112" });
C("explorer.config", "站点与依赖", "Core gRPC", "SetDynamicConfig", { write: true, request: "SITE_EXPLORER_ENABLED、CREATE_MACHINES", requires: ["core"], note: "创建交换机和供电框的开关只在配置文件里，不能在运行时改", source: "forge.proto:502" });
C("rack-profile.list", "站点与依赖", "Core gRPC", "ListRackProfiles / GetRackProfile", { cli: "nico-admin-cli rack profile list；nico-admin-cli rack profile show <RACK_ID>", fields: ["rack_profile_id", "profile.rack_hardware_topology", "profile.capabilities.{compute,switch,power_shelf}.count", "profile.product_family"], requires: ["rack-profiles"], note: "从运行配置读出；只允许管理端证书调用", source: "crates/api-core/src/handlers/rack.rs:511" });
C("rule.list", "站点与依赖", "REST", "GET /task/rule", { cli: "nicocli rule list --site-id <SITE>", request: "siteId 必填；operationType 可选（PowerControl、FirmwareControl）", fields: ["id", "name", "operationType", "operationCode", "isDefault", "ruleDefinition.steps[]"], requires: ["operation-rule"], executedBy: "Flow", note: "只返回存进数据库的规则；内置的默认规则不在列表里", source: "spec.yaml:14592" });
C("nmxc.endpoints", "站点与依赖", "Core gRPC", "ListNvlinkNmxcEndpoints", { cli: "nico-admin-cli nvlink-nmxc-endpoints", fields: ["chassis_serial", "endpoint"], requires: ["nmxc"], source: "forge.proto:1116" });

/* ================= 接口：网络与地址 ================= */
C("segment.list", "网络与地址", "Core gRPC", "FindNetworkSegmentIds → FindNetworkSegmentsByIds", { cli: "nico-admin-cli network-segment show", request: "include_num_free_ips 为真才返回空闲地址数", fields: ["id", "metadata.name", "config.segment_type", "config.mtu", "config.subdomain_id", "config.prefixes[].{prefix,gateway,reserve_first,free_ip_count_v2}", "status.lifecycle.state"], requires: ["network-segment"], note: "类型：TENANT、ADMIN、UNDERLAY、HOST_INBAND", source: "forge.proto:129" });
C("segment.create", "网络与地址", "Core gRPC", "CreateNetworkSegment / CreateNetworkSegmentWithDhcpRange", { write: true, cli: "nico-admin-cli network-segment create --name --segment-type --prefix --gateway --reserve-first --mtu --subdomain-id", request: "prefixes 必填（每个地址族至多一个，各含 prefix、gateway、reserve_first）、segment_type 必填；name、mtu、subdomain_id 可选。带地址池的接口另需 range{start,end}", requires: ["dns-domain", "resource-pools"], note: "前缀不能与已有子网重叠。接口不强制子域，但没有子域的子网发不出 DHCP 记录，平台要自己把它当必填", source: "crates/rpc/src/model/network_segment.rs:78" });
C("segment.delete", "网络与地址", "Core gRPC", "DeleteNetworkSegment", { write: true, cli: "nico-admin-cli network-segment delete", request: "id", requires: ["network-segment"], note: "进入 Deleting，先等已分配的地址清空再删除", source: "crates/api-core/src/handlers/network_segment.rs:523" });
C("segment.dhcp-range", "网络与地址", "Core gRPC", "FindNetworkSegmentDhcpRanges", { request: "子网 ID 列表", fields: ["segment_id", "prefix", "range.{start,end}", "revision"], requires: ["network-segment"], note: "命令行没有对应命令", source: "forge.proto:148" });
C("segment.dhcp-range.write", "网络与地址", "Core gRPC", "SetNetworkSegmentDhcpRange", { write: true, request: "segment_id 必填；range 省略表示清除；if_revision 填上次读到的修订号，0 表示还没有地址池", fields: ["range.{start,end}", "revision"], requires: ["network-segment"], note: "只对有且只有一个 IPv4 前缀的 ADMIN、UNDERLAY、HOST_INBAND 子网有效；已有动态地址落在新范围之外时拒绝。命令行没有对应命令", source: "forge.proto:149" });
C("interface.list", "网络与地址", "Core gRPC", "FindInterfaces", { cli: "nico-admin-cli machine-interfaces show", request: "id 或 ip；都不填返回全部", fields: ["id", "mac_address", "address[]", "segment_id", "hostname", "vendor", "last_dhcp", "machine_id", "switch_id", "power_shelf_id", "association_type", "interface_type", "primary_interface"], requires: ["machine-interface"], note: "没有租约到期时间。association_type 为 NONE 的就是拿到地址但没有归属的设备", source: "forge.proto:318" });
C("interface.addresses", "网络与地址", "Core gRPC", "FindInterfaceAddresses / FindIpAddress", { cli: "nico-admin-cli machine-interfaces show-addresses；nico-admin-cli ip find <IP>", fields: ["addresses[].{address,allocation_type}", "matches[].{ip_type,owner_id,message}"], requires: ["machine-interface"], note: "按地址反查归属：地址可能属于设备接口、BMC、实例、资源池或子网本身", source: "forge.proto:315" });
C("dhcp.metrics", "网络与地址", "指标", "carbide_dhcp_requests_total、carbide_dhcp_dropped_requests_total、carbide_dhcp_replies_sent_total、carbide_available_ips_count", { fields: ["message_type", "reason", "name", "type", "prefix"], requires: ["dhcp-service"], executedBy: "监控系统", note: "DHCP 的请求计数只按报文类型和丢弃原因分，不按子网或中继分；空闲地址数按子网前缀分", source: "crates/dhcp-server/src/metrics.rs:495" });

/* ================= 接口：设备清单 ================= */
C("rack-group.list", "设备清单", "Core gRPC", "GetAllExpectedRackGroups", { cli: "nico-admin-cli expected-rack-group show", fields: ["rack_group_id", "topology", "protocol", "racks[].rack_id", "racks[].members[].{type,manufacturer,id}"], requires: ["rack-group"], source: "forge.proto:746" });
C("rack-group.write", "设备清单", "Core gRPC", "AddExpectedRackGroup / UpdateExpectedRackGroup / DeleteExpectedRackGroup", { write: true, cli: "nico-admin-cli expected-rack-group add [--rack <JSON>]... <RACK_GROUP_ID> <PROTOCOL> <TOPOLOGY>", request: "rack_group_id、topology 必填；protocol、racks、metadata 可选。更新是整条替换", requires: ["core"], note: "有 NVLink 域声明引用时，不能改 racks，也不能删除", source: "forge.proto:737" });
C("expected-rack.list", "设备清单", "Core gRPC", "GetAllExpectedRacks", { cli: "nico-admin-cli expected-rack show", fields: ["rack_id", "rack_profile_id", "rack_group_id", "metadata"], requires: ["expected-rack"], source: "forge.proto:719" });
C("expected-rack.write", "设备清单", "Core gRPC", "AddExpectedRack / UpdateExpectedRack / DeleteExpectedRack", { write: true, cli: "nico-admin-cli expected-rack add [--label K:V] <RACK_ID>", request: "rack_id 必填；metadata 可选。规格和机柜组是输出字段，写入时忽略", requires: ["rack-group", "rack-profiles"], note: "推导失败返回 INVALID_ARGUMENT 并说明原因：没有机柜组包含它、多个机柜组包含它、缺计算或交换机成员、规格未配置", source: "expected_rack.rs:29" });
C("expected-machine.list", "设备清单", "Core gRPC", "GetAllExpectedMachines / GetAllExpectedMachinesLinked", { cli: "nico-admin-cli expected-machine show", fields: ["chassis_serial_number", "bmc_mac_address", "rack_id", "bmc_ip_address", "host_nics[]", "metadata.labels", "linked: interface_id、explored_endpoint_address、machine_id"], requires: ["expected-devices"], note: "带关联的读取一次给出每条声明走到了哪一步：有没有接口、有没有探测结果、有没有设备对象。读取结果里带着 BMC 的用户名和口令，后端不能把它们传给前端，也不能写进日志", source: "forge.proto:646" });
C("expected-machine.write", "设备清单", "Core gRPC", "CreateExpectedMachines / UpdateExpectedMachines / PatchExpectedMachine / DeleteExpectedMachine", { write: true, cli: "nico-admin-cli expected-machine add -a <BMC_MAC> -u <BMC_USER> -p <BMC_PASS> -s <SERIAL> [--rack_id] [--bmc-ip-address] [--interfaces] [--label]", request: "bmc_mac_address、chassis_serial_number 必填（序列号 4–32 位字母数字下划线连字符）；rack_id、bmc_ip_address、host_nics、metadata 可选。批量接口带 accept_partial_results", requires: ["core"], note: "不要用 ReplaceAllExpectedMachines 做增量导入：它替换整张表", source: "forge.proto:8268" });
C("expected-switch.list", "设备清单", "Core gRPC", "GetAllExpectedSwitches / GetAllExpectedSwitchesLinked", { cli: "nico-admin-cli expected-switch show", fields: ["switch_serial_number", "bmc_mac_address", "nvos_interfaces[]", "rack_id", "linked: switch_id、explored_endpoint_address"], requires: ["expected-devices"], source: "forge.proto:701" });
C("expected-switch.write", "设备清单", "Core gRPC", "AddExpectedSwitch / PatchExpectedSwitch / DeleteExpectedSwitch", { write: true, cli: "nico-admin-cli expected-switch add -a <BMC_MAC> -u <USER> -p <PASS> -s <SERIAL> --nvos-interface <MAC[,primary]> [--rack_id]", request: "bmc_mac_address 必填；nvos_interfaces 至少一个，多于一个时恰好一个为主口；NVOS 用户名和口令要么都填要么都不填", requires: ["core"], source: "forge.proto:691" });
C("expected-shelf.list", "设备清单", "Core gRPC", "GetAllExpectedPowerShelves / GetAllExpectedPowerShelvesLinked", { cli: "nico-admin-cli expected-power-shelf show", fields: ["shelf_serial_number", "bmc_mac_address", "rack_id", "linked: power_shelf_id、explored_endpoint_address"], requires: ["expected-devices"], source: "forge.proto:681" });
C("expected-shelf.write", "设备清单", "Core gRPC", "AddExpectedPowerShelf / PatchExpectedPowerShelf / DeleteExpectedPowerShelf", { write: true, cli: "nico-admin-cli expected-power-shelf add -a <BMC_MAC> -u <USER> -p <PASS> -s <SERIAL> [--rack_id]", request: "bmc_mac_address 必填；序列号、rack_id、bmc_ip_address 可选", requires: ["core"], source: "forge.proto:671" });
C("expected-domain.write", "设备清单", "Core gRPC", "CreateExpectedNvLinkDomain / DeleteExpectedNvLinkDomain / FindExpectedNvLinkDomainIds", { write: true, cli: "nico-admin-cli expected-nvlink-domain create --member <MAC>... [--name] <RACK_GROUP_ID>", request: "rack_group_id、member_bmc_mac_addresses 必填", requires: ["rack-group", "expected-devices"], note: "REST 规范里没有对应的端点", source: "forge.proto:725" });

/* ================= 接口：设备发现 ================= */
C("explorer.endpoints", "设备发现", "Core gRPC", "FindExploredEndpointIds → FindExploredEndpointsByIds", { cli: "nico-admin-cli site-explorer get-report endpoint", fields: ["address", "report.endpoint_type", "report.vendor", "report.systems[].serial_number", "report.chassis[].serial_number", "report.last_exploration_error_schema.{error_code,mitigation,text}", "report.firmware_versions", "preingestion_state", "pause_remediation"], requires: ["explored-endpoint"], note: "探测结果的编号就是 BMC 的 IP 地址", source: "site_explorer.proto:53" });
C("explorer.managed-hosts", "设备发现", "Core gRPC", "FindExploredManagedHostIds → FindExploredManagedHostsByIds", { cli: "nico-admin-cli site-explorer get-report managed-host", fields: ["host_bmc_ip", "dpus[].{bmc_ip,host_pf_mac_address}"], requires: ["explored-endpoint"], note: "主机与 DPU 的配对结果", source: "site_explorer.proto:84" });
C("explorer.unexpected", "设备发现", "Core gRPC", "GetAllUnexpectedMachines", { fields: ["address", "bmc_mac_address", "machine_id"], requires: ["explored-endpoint"], note: "只列出探测成功、类型是主机 BMC、MAC 不在任何声明里的设备。探测失败的未声明设备不在这里；命令行没有对应命令", source: "crates/api-db/src/expected_machine.rs:283" });
C("explorer.retry", "设备发现", "Core gRPC", "ReExploreEndpoint / RefreshEndpointReport / ClearSiteExplorationError", { write: true, cli: "nico-admin-cli site-explorer re-explore；nico-admin-cli site-explorer refresh；nico-admin-cli site-explorer clear-error", request: "ip_address", requires: ["explored-endpoint"], note: "重新探测排到下一轮；刷新立即探测并保存；认证失败之后要先清除错误才会再试", source: "forge.proto:390" });
C("ingestion.state", "设备发现", "Core gRPC", "DetermineMachineIngestionState", { cli: "nico-admin-cli managed-host power-options get-machine-ingestion-state --mac-address <MAC>", request: "mac_address 必填", fields: ["NotDiscovered、WaitingForIngestion、IngestionMachineNotCreated、IngestionMachineCreated"], requires: ["expected-devices"], source: "crates/api-core/src/handlers/power_options.rs:143" });
C("ingestion.allow", "设备发现", "Core gRPC", "AllowIngestionAndPowerOn", { write: true, cli: "nico-admin-cli managed-host power-options allow-ingestion-and-power-on --mac-address <MAC>", request: "mac_address 必填", requires: ["explored-endpoint"], note: "只对设备声明里带暂停标记的主机有意义", source: "crates/api-core/src/handlers/power_options.rs:213" });

/* ================= 接口：机柜与 NVLink 域 ================= */
C("rack.list", "机柜与 NVLink 域", "Core gRPC", "FindRackIds → FindRacksByIds", { cli: "nico-admin-cli rack list；nico-admin-cli rack show <RACK_ID>", fields: ["id", "rack_group_id", "status.lifecycle.{state,state_reason}", "status.health", "status.health_sources", "metadata", "created", "updated"], requires: ["rack"], note: "机柜对象不带规格和成员列表：规格另读，成员按机柜 ID 去各类设备里筛", source: "forge.proto:9860" });
C("rack.history", "机柜与 NVLink 域", "Core gRPC", "FindRackStateHistories", { cli: "nico-admin-cli rack state-history <RACK_ID>", fields: ["histories[rack_id].records[].{state,version,time}"], requires: ["rack"], source: "forge.proto:331" });
C("rack.rest", "机柜与 NVLink 域", "REST", "GET /rack、GET /rack/{id}", { cli: "nicocli rack list --site-id <SITE>", request: "siteId 必填；includeComponents、name、分页可选", fields: ["id", "name", "operationStatus", "operationStatusDetails.trayCountsByType", "nvLinkDomainIds", "taskStats.{pendingTaskCount,activeTaskCount}", "health", "components[]"], requires: ["flow-inventory"], executedBy: "Flow", note: "站点没有启用 Flow 时返回 412", source: "spec.yaml:13522" });
C("rack.validation", "机柜与 NVLink 域", "REST", "GET /rack/{id}/validation、GET /rack/validation", { cli: "nicocli rack validate --site-id <SITE>", request: "siteId 必填", fields: ["diffs[].{type,id,macAddress,fieldDiffs}", "totalDiffs", "missingCount", "unexpectedCount", "mismatchCount", "matchCount"], requires: ["flow-inventory", "expected-devices"], executedBy: "Flow", note: "差异类型：Missing、Unexpected、Mismatch。按 BMC MAC 比对，不比对序列号", source: "spec.yaml:13745" });
C("tray.rest", "机柜与 NVLink 域", "REST", "GET /tray、GET /tray/{id}", { cli: "nicocli tray list --site-id <SITE> --rack-id <RACK>", request: "siteId 必填；rackId 或 rackName、type、slotId 可选", fields: ["id", "type（Compute、NVSwitch、PowerShelf）", "position.{slotId,trayIdx,hostId}", "firmwareVersion", "powerState", "operationStatus", "leakStatus", "bmcs", "rackId", "nvLinkDomainId", "taskStats", "health"], requires: ["flow-inventory"], executedBy: "Flow", note: "机柜立面要的槽位在这里；Core 的供电框对象没有位置字段。不属于任何机柜的普通服务器也在这个列表里", source: "spec.yaml:14412" });
C("domain.list", "机柜与 NVLink 域", "REST", "GET /domain/nvlink、GET /domain/nvlink/{id}", { cli: "nicocli domain list --site-id <SITE>", request: "siteId 必填；includeComponents 可选", fields: ["id（等于机柜组编号）", "name", "nmxcClusterId", "topology", "operationStatus", "components"], requires: ["nvlink-domain"], executedBy: "Flow", note: "nicocli 的子命令名由接口规范生成，这里的写法没有实际运行核对", source: "spec.yaml:13335" });

/* ================= 接口：设备读取 ================= */
C("nvlink.domain-health", "机柜与 NVLink 域", "Core gRPC", "ListNVLinkDomainHealthReports", { fields: ["health_report_entries[]"], requires: ["nvlink-domain"], note: "按 NMX-C 的域编号记录，不是按机柜组编号", source: "forge.proto:262" });
C("nvlink.partitions", "机柜与 NVLink 域", "Core gRPC", "FindNVLinkPartitionIds → FindNVLinkPartitionsByIds", { fields: ["id", "name", "nmx_m_id", "domain_uuid", "logical_partition_id"], requires: ["nvlink-domain"], note: "要先在 Core 的配置里启用 NVLink 分区", source: "forge.proto:1294" });
C("nvlink.logical-partitions", "机柜与 NVLink 域", "Core gRPC", "FindNVLinkLogicalPartitionIds → FindNVLinkLogicalPartitionsByIds", { fields: ["id", "config.metadata.name", "config.tenant_organization_id", "status.state", "created"], requires: ["nvlink-domain"], note: "创建、修改、删除分区属于交付，这一页只读", source: "forge.proto:1300" });
C("machine.list", "设备读取", "Core gRPC", "FindMachineIds → FindMachinesByIds", { cli: "nico-admin-cli machine show [--hosts]", request: "筛选：rack_id、include_dpus、exclude_hosts、only_maintenance、only_quarantine、only_with_health_alert；include_history 带回状态事件", fields: ["id", "rack_id", "placement_in_rack.{slot_number,tray_index}", "state", "state_reason.{outcome,outcome_msg}", "state_sla.time_in_state_above_sla", "status.health.alerts[]", "bmc.{ip,mac}", "status.bmc_status.firmware_version", "status.discovery_info.dmi_data.chassis_serial", "status.associated_dpu_machine_ids", "config.maintenance_reference", "status.quarantine", "status.nvlink_info.domain_uuid", "status.lldp_neighbors[]", "inventory.components[]"], requires: ["machine"], note: "没有电源状态和实例字段，这两项另读。一次按编号读取的数量有上限", source: "forge.proto:5137" });
C("host.states", "设备读取", "Core gRPC", "FindHostStatesByIds", { request: "host_ids", fields: ["state", "state_reason", "rack_id", "nvlink_domain_id", "bmc_ip", "dpu_ids", "health_alerts", "quarantine", "allocation.{allocatable,blocking_reason,blocking_detail}", "explored.{bmc_version,uefi_version}"], requires: ["machine"], note: "一次给出“能不能分配，被什么挡住”。只允许管理端证书调用；命令行没有对应命令", source: "forge.proto:13734" });
C("switch.list", "设备读取", "Core gRPC", "FindSwitchIds → FindSwitchesByIds", { cli: "nico-admin-cli switch list；nico-admin-cli switch show <SWITCH_ID>", request: "筛选：rack_id、controller_state、bmc_mac、nvos_mac、only_with_health_alert", fields: ["id", "rack_id", "placement_in_rack", "nvlink_domain_uuid", "bmc_info.{ip,mac,firmware_version}", "status.serial_number", "status.power_state", "status.controller_state", "status.state_reason", "status.health", "status.fabric_manager_status_details", "status.nvos_ports[].{mac,addresses,is_primary}"], requires: ["switch"], source: "forge.proto:3332" });
C("shelf.list", "设备读取", "Core gRPC", "FindPowerShelfIds → FindPowerShelvesByIds", { cli: "nico-admin-cli power-shelf list；nico-admin-cli power-shelf show <ID>", request: "筛选：rack_id、controller_state、bmc_mac", fields: ["id", "rack_id", "bmc_info.{ip,mac,firmware_version}", "config.{capacity,voltage}", "status.power_state", "status.controller_state", "status.state_reason", "status.health"], requires: ["power-shelf"], note: "没有槽位字段，也没有序列号字段", source: "forge.proto:3087" });
C("device.history", "设备读取", "Core gRPC", "FindMachineStateHistories / FindSwitchStateHistories / FindPowerShelfStateHistories", { cli: "nico-admin-cli machine show <ID> -c <条数>", fields: ["histories[id].records[].{state 或 event,version,time}"], requires: ["machine"], source: "forge.proto:329" });
C("device.inventory", "设备读取", "Core gRPC", "GetComponentInventory", { request: "machine_ids、switch_ids、power_shelf_ids 三选一", fields: ["entries[].result.{component_id,status,error}", "entries[].report.firmware_versions", "entries[].report.systems[]", "entries[].report.chassis[]"], requires: ["explored-endpoint"], note: "读的是保存下来的探测报告，不经过硬件后端。命令行没有对应命令", source: "forge.proto:1373" });
C("device.power-state", "设备读取", "Core gRPC", "GetComponentPowerDetails / GetPowerOptions", { cli: "nico-admin-cli managed-host power-options show <MACHINE>", request: "machine_ids、switch_ids、power_shelf_ids 三选一，1–64 个", fields: ["entries[].actual.{state,source,observed_at}", "entries[].desired.state", "entries[].actions[].{status,operation,requested_at,initiator}"], requires: ["component-manager"], executedBy: "Core 或硬件后端", note: "整机柜里的主机、交换机和供电框经硬件后端读取；交换机和供电框对象上另有一个文本形式的 status.power_state", source: "forge.proto:11423" });
C("firmware.desired", "设备读取", "Core gRPC", "GetDesiredFirmwareVersions / ListComponentFirmwareVersions", { cli: "nico-admin-cli component-manager get-firmware-versions {compute-tray|switch|power-shelf|rack}", fields: ["entries[].{vendor,model,component_versions}", "devices[].versions[]", "devices[].compute_fw_versions[]"], requires: ["component-manager"], note: "前者是按厂商型号配置的主机期望版本；后者是硬件后端可用的固件包。以机柜为目标时返回未实现", source: "forge.proto:998" });
C("firmware.status", "设备读取", "Core gRPC", "GetComponentFirmwareStatus", { cli: "nico-admin-cli component-manager get-firmware-update-status {compute-tray|switch|power-shelf|rack}", fields: ["statuses[].state（QUEUED、IN_PROGRESS、VERIFYING、COMPLETED、FAILED、CANCELLED）", "statuses[].target_version", "statuses[].updated_at"], requires: ["component-manager"], executedBy: "Core 或硬件后端", source: "forge.proto:1375" });
C("machine.validation", "设备读取", "Core gRPC", "GetMachineValidationRuns / GetMachineValidationResults", { cli: "nico-admin-cli machine-validation runs show -m <MACHINE>", fields: ["runs[].{validation_id,status,start_time,end_time}", "results[].{name,exit_code,std_out,std_err}"], requires: ["machine"], source: "forge.proto:878" });
C("device.identify", "设备读取", "Core gRPC", "IdentifySerial / IdentifyMac / FindIpAddress", { cli: "nico-admin-cli ip find <IP>", request: "序列号、MAC 或 IP", fields: ["machine_id", "matches[].{ip_type,owner_id}"], requires: ["machine"], note: "跨类型搜索用。序列号只能反查主机；交换机和供电框要在各自的列表里按 BMC MAC 筛", source: "forge.proto:350" });

/* ================= 接口：设备操作 ================= */
C("tray.power", "设备操作", "REST", "PATCH /tray/{id}/power、PATCH /tray/power", { write: true, cli: "nicocli tray power --site-id <SITE> --data '{\"state\":\"Off\"}' <TRAY_ID>", request: "siteId、state 必填（On、Off、Cycle、ForceOff、ForceCycle、ACPowerCycle）；ruleId、overrideReadinessCheck 可选。批量接口的 filter 为空表示站点内全部托盘", fields: ["taskIds[]"], requires: ["flow-inventory"], executedBy: "Flow → Core → 硬件后端", note: "读回用 GET /tray/{id}/power，它分别给出实际状态、期望状态和进行中的动作", source: "spec.yaml:16691" });
C("tray.firmware", "设备操作", "REST", "PATCH /tray/{id}/firmware、PATCH /tray/firmware", { write: true, cli: "nicocli tray firmware --site-id <SITE> <TRAY_ID>", request: "siteId 必填；version 省略表示用机柜固件清单；targets 可选（bmc、cpld、bios、nvos、pmc、psu、dpu）；ruleId、overrideVersionCheck、overrideReadinessCheck 可选", fields: ["taskIds[]"], requires: ["flow-inventory", "firmware-object"], executedBy: "Flow → Core → 硬件后端", note: "内置的固件规则只覆盖计算托盘和交换机，不含供电框", source: "spec.yaml:16743" });
C("device.power-direct", "设备操作", "Core gRPC", "ComponentPowerControl", { write: true, cli: "nico-admin-cli component-manager component-power-control --action <on|graceful-shutdown|force-off|graceful-restart|force-restart|a-c-powercycle> {compute-tray|switch|power-shelf} --machine-id <ID>", request: "machine_ids、switch_ids、power_shelf_ids 三选一；action 必填", fields: ["results[].{component_id,status,error}"], requires: ["component-manager"], executedBy: "Core → 硬件后端", note: "Flow 的托盘电源最终也调这个接口。结果里的 OUTCOME_UNKNOWN 表示不确定是否执行，不能自动重发。读回用 GetComponentPowerDetails", source: "forge.proto:1347" });
C("shelf.power", "设备操作", "Core gRPC", "SetPowerShelfMaintenance", { write: true, cli: "nico-admin-cli power-shelf maintenance power-off --power-shelf-id <ID> [--reference] [--graceful]；… power-on", request: "power_shelf_ids、operation 必填（POWER_ON、POWER_OFF）；reference、graceful 可选", requires: ["power-shelf", "component-manager"], executedBy: "供电框状态机 → 硬件后端", note: "供电框在 Ready 或 Error 时才会被处理。读回看供电框状态从 Maintenance 回到 Ready", source: "crates/api-core/src/handlers/power_shelf.rs:330" });
C("machine.maintenance", "设备操作", "Core gRPC", "SetMaintenance", { write: true, cli: "nico-admin-cli managed-host maintenance on --host <ID> --reference <原因>；… off --host <ID>", request: "operation、host_id 必填；开启时 reference 必填，至少 5 个字符", requires: ["machine"], note: "实现方式是给主机写一条健康报告，带阻止分配。读回看 config.maintenance_reference 或按 only_maintenance 筛选", source: "crates/api-core/src/handlers/managed_host.rs:200" });
C("machine.quarantine", "设备操作", "Core gRPC", "SetManagedHostQuarantineState / ClearManagedHostQuarantineState", { write: true, cli: "nico-admin-cli managed-host quarantine on --host <ID> --reason <原因>；… off --host <ID>", request: "machine_id、quarantine_state.{mode,reason}", fields: ["prior_quarantine_state"], requires: ["machine"], note: "模式只有 BLOCK_ALL_TRAFFIC。读回看 status.quarantine", source: "crates/api-core/src/handlers/machine_quarantine.rs:28" });
C("machine.validate", "设备操作", "Core gRPC", "OnDemandMachineValidation", { write: true, cli: "nico-admin-cli machine-validation on-demand start -m <MACHINE>", request: "machine_id、action 必填（只有 Start 可用）", fields: ["validation_id"], requires: ["machine"], note: "主机要在 Ready 或 Failed 状态", source: "forge.proto:974" });
C("machine.sku", "设备操作", "Core gRPC", "VerifySkuForMachine", { write: true, cli: "nico-admin-cli sku verify <MACHINE_ID>", request: "machine_id", requires: ["machine"], note: "读回看 status.hw_sku.verify_request_time", source: "crates/api-core/src/handlers/sku.rs:186" });
C("device.bmc-reset", "设备操作", "Core gRPC", "AdminBmcReset", { write: true, cli: "nico-admin-cli bmc-machine bmc-reset [--machine <ID>|--switch <ID>|--power-shelf <ID>]", request: "device_id（machine_id、switch_id、power_shelf_id 之一）；reset_type 可选", requires: ["explored-endpoint"], executedBy: "Core（Redfish）", note: "没有读回接口：返回成功只表示 BMC 接受了请求", source: "crates/api-core/src/handlers/bmc_endpoint_explorer.rs:302" });
C("device.decommission", "设备操作", "Core gRPC", "DecommissionSwitch / DecommissionPowerShelf / DecommissionManagedHost", { write: true, cli: "nico-admin-cli managed-switch decommission <SWITCH_ID>；nico-admin-cli power-shelf decommission <ID>；nico-admin-cli managed-host decommission <ID>", request: "设备 ID", requires: ["switch", "component-manager"], executedBy: "设备状态机 → 硬件后端", note: "设备要在 Ready；交换机和供电框还要求所在机柜没有已分配的主机；交换机要求后端是 rms。退役后要强制删除并清掉 BMC 抑制记录，设备才能被重新发现", source: "crates/api-core/src/handlers/switch.rs:389" });

/* ================= 接口：机柜级任务 ================= */
C("rack.bringup", "机柜级任务", "REST", "POST /rack/{id}/bringup", { write: true, cli: "nicocli rack bringup --site-id <SITE> <RACK_ID>", request: "siteId 必填；description、ruleId、overrideReadinessCheck 可选", fields: ["taskIds[]"], requires: ["flow-inventory", "firmware-object", "operation-rule"], executedBy: "Flow → Core → 硬件后端", note: "默认规则的阶段：供电框上电、计算托盘上电、计算托盘固件、交换机上电、交换机固件一致性核对、计算托盘重新上电。完成后还要看 Core 的机柜状态走到 Ready", source: "spec.yaml:14357" });
C("rack.power", "机柜级任务", "REST", "PATCH /rack/{id}/power", { write: true, cli: "nicocli rack power --site-id <SITE> --data '{\"state\":\"On\"}' <RACK_ID>", request: "siteId、state 必填（On、Off、Cycle、ForceOff、ForceCycle、ACPowerCycle）；ruleId、overrideReadinessCheck 可选", fields: ["taskIds[]"], requires: ["flow-inventory", "operation-rule"], executedBy: "Flow → Core → 硬件后端", note: "机柜级上下电只有 Flow 提供，Core 的设备电源接口没有机柜这个目标。相同的进行中请求会合并成同一个任务", source: "spec.yaml:14125" });
C("rack.firmware", "机柜级任务", "REST", "PATCH /rack/{id}/firmware", { write: true, cli: "nicocli rack firmware --site-id <SITE> <RACK_ID>", request: "siteId 必填；version 省略表示用机柜固件清单；ruleId、overrideVersionCheck、overrideReadinessCheck 可选", fields: ["taskIds[]"], requires: ["flow-inventory", "firmware-object", "operation-rule"], executedBy: "Flow → Core → 硬件后端", note: "走硬件后端时 version 是一整份固件清单文本，不是版本号。机柜接口不转发 targets", source: "spec.yaml:14245" });
C("task.list", "机柜级任务", "REST", "GET /task、GET /rack/{id}/task、GET /tray/{id}/task、GET /task/{id}", { cli: "nicocli rack task get --site-id <SITE> <RACK_ID>", request: "siteId 必填；activeOnly、includeReport、分页可选", fields: ["id", "status（Pending、Running、Succeeded、Failed、Terminated）", "description", "message", "ruleId", "started", "finished", "report"], requires: ["flow-task"], executedBy: "Flow", note: "任务里没有操作者和原因，这两项由平台的审计记录", source: "spec.yaml:14768" });
C("task.cancel", "机柜级任务", "REST", "POST /task/{id}/cancel", { write: true, cli: "nicocli task cancel --site-id <SITE> <TASK_ID>", request: "siteId 必填", fields: ["status"], requires: ["flow-task"], executedBy: "Flow", note: "已经成功或失败的任务返回 412；已终止的任务重复取消不报错", source: "spec.yaml:14913" });
C("rack.maintenance", "机柜级任务", "Core gRPC", "OnDemandRackMaintenance / TerminateRackMaintenance", { write: true, cli: "nico-admin-cli rack maintenance start --rack <ID> --activities <firmware-upgrade,nvos-update,power-sequence,configure-nmx-cluster>；nico-admin-cli rack maintenance terminate --rack <ID>", request: "rack_id 必填；scope 可选（设备范围和活动）", requires: ["rack", "rms"], executedBy: "机柜状态机 → RMS", note: "发起：机柜要在 Ready 或 Error。终止：只在机柜处于 Maintenance 时接受，终止后机柜进入 Error，已发给设备的请求和当前阶段的状态会被清理；重复终止不报错。NVOS 更新和 NMX-C 集群配置只有这条路径提供，REST 和 Flow 都没有", source: "forge.proto:977" });
C("rack.delete", "机柜级任务", "Core gRPC", "DeleteRack / AdminForceDeleteRack", { write: true, cli: "nico-admin-cli rack delete <RACK_ID>；nico-admin-cli rack force-delete", request: "机柜 ID", requires: ["rack"], note: "DeleteRack 只把机柜标记为删除；AdminForceDeleteRack 立即删除并保留状态历史。两个接口都不检查机柜里还有没有设备，也不处理成员设备。配套还要 DeleteExpectedRack 删掉机柜声明", source: "crates/api-core/src/handlers/rack.rs:201" });

/* ================= 接口：交付与实例 ================= */
C("os.list", "交付与实例", "Core gRPC", "FindOperatingSystemIds → FindOperatingSystemsByIds", { cli: "nico-admin-cli operating-system show", fields: ["id", "name", "type", "status", "is_active", "ipxe_template_id", "ipxe_template_parameters", "ipxe_template_artifacts[].{name,url,cached_url}"], requires: ["os-definition"], source: "forge.proto:1380" });
C("os.write", "交付与实例", "Core gRPC", "CreateOperatingSystem / UpdateOperatingSystem / DeleteOperatingSystem", { write: true, cli: "nico-admin-cli operating-system create；nico-admin-cli operating-system set-cached-url", request: "name 必填；ipxe_script，或 ipxe_template_id 加参数和制品，二选一；is_active、user_data 可选", requires: ["core"], note: "删除时 Core 不检查是否还有实例在引用，平台要自己检查", source: "crates/api-core/src/handlers/operating_system.rs:196" });
C("instance.allocate", "交付与实例", "Core gRPC", "AllocateInstances / AllocateInstance", { write: true, cli: "nico-admin-cli instance allocate --machine-id <ID>... --transactional --os <OS_ID> [--flat-vpc-id|--vpc-prefix-id]", request: "每个实例：machine_id、config 必填（config.tenant、config.os、config.network）；instance_type_id、metadata、allow_unhealthy_machine 可选", fields: ["instances[].{id,machine_id,status}"], requires: ["machine", "os-definition", "vpc"], note: "批量接口在一个事务里，全部成功或全部失败。不满足条件时的错误带有 nico-error-code、nico-error-text、nico-error-mitigation 三个附加信息", source: "crates/api-core/src/instance/mod.rs:2009" });
C("instance.list", "交付与实例", "Core gRPC", "FindInstanceIds → FindInstancesByIds / FindInstanceByMachineID", { cli: "nico-admin-cli instance show", fields: ["id", "machine_id", "config.tenant.{tenant_organization_id,hostname}", "config.os", "status.tenant.state", "status.network", "metadata"], requires: ["instance"], note: "状态：PROVISIONING、READY、CONFIGURING、UPDATING、TERMINATING、TERMINATED、FAILED、REPAIRING", source: "forge.proto:230" });
C("instance.release", "交付与实例", "Core gRPC", "ReleaseInstance / ReleaseInstances", { write: true, cli: "nico-admin-cli instance release --instance <ID>", request: "id 必填", fields: ["results[].{id,status,error}"], requires: ["instance"], note: "重复调用不报错。主机健康带“阻止删除实例”时拒绝。回收是异步的：读回看实例消失，以及主机状态回到 Ready 且可分配", source: "crates/api-core/src/handlers/instance.rs:822" });

/* ================= 接口：健康 ================= */
C("health.reports", "健康", "Core gRPC", "ListMachineHealthReports / ListSwitchHealthReports / ListPowerShelfHealthReports / ListRackHealthReports / ListNVLinkDomainHealthReports", { cli: "nico-admin-cli machine health-report show <ID>；nico-admin-cli nvl-domain health-report show", request: "设备、机柜或域的 ID", fields: ["health_report_entries[].mode", "report.source", "report.alerts[].{id,target,in_alert_since,message,classifications[]}"], requires: ["health-report"], note: "一条告警是否阻止分配，看 classifications 里有没有 PreventAllocations。泄漏告警的编号：BmsLeakDetectRack、BmsLeakSensorFaultRack、BmcLeakDetection", source: "forge.proto:238" });
C("health.history", "健康", "Core gRPC", "FindMachineHealthHistories / FindSwitchHealthHistories / FindPowerShelfHealthHistories / FindRackHealthHistories", { cli: "nico-admin-cli machine health-history <ID>；nico-admin-cli rack health-history <RACK_ID>", request: "ids 必填；start_time、end_time 可选", fields: ["histories[id].records[].{health,time}"], requires: ["health-report"], source: "forge.proto:330" });

/* 现有产品已经调用过的接口（主线分支的 Core 客户端里有同名调用）。其余是整机柜方向新增的。 */
["core.version", "rms.status", "credential.readiness", "credential.write", "explorer.last-run", "segment.list", "segment.create", "segment.delete", "segment.dhcp-range", "segment.dhcp-range.write", "interface.list", "interface.addresses",
  "expected-rack.list", "expected-machine.list", "expected-machine.write", "expected-switch.list", "expected-shelf.list", "explorer.endpoints", "ingestion.state", "ingestion.allow",
  "rack.list", "rack.history", "machine.list", "switch.list", "shelf.list", "device.history", "device.inventory", "device.power-state", "machine.validation",
  "device.power-direct", "shelf.power", "machine.maintenance", "machine.quarantine", "machine.validate", "machine.sku", "device.bmc-reset", "device.decommission", "rack.maintenance",
  "os.list", "os.write", "instance.allocate", "instance.list", "instance.release"].forEach((id) => { const c = NICO_CALLS.find((x) => x.id === id); if (c) c.used = true; });

/* 实测结果。在一套没有整机柜硬件的 NICo 环境里实际调用过的接口：证据升为“调用”，observed 写明看到了什么、没看到什么。
   “调用”只说明接口存在、认证和权限通过、返回与这里写的不矛盾。返回空列表的接口没法核对字段。
   核对方式：只记录退出码、状态码和返回里的字段名，不保存数据内容。 */
const OBSERVED = {
  // 站点与依赖
  "core.version": "返回 build_version（形如 0.0.0-main-<提交号>）、build_date、git_sha、rust_version、capabilities 和 runtime_config。运行配置里有 dhcp_servers、networks、initial_domain_name、site_fabric_prefixes、attestation_enabled",
  "rms.status": "RMS 部署之前 Core 的配置就指向它；部署后返回 status: connected 和 RMS 的版本号，Core 没有重启。命令行的输出是 status、message、version 三项",
  "rest.site": "返回 200。字段与这里一致：id、name、org、status、isOnline、siteAgentVersion、siteControllerVersion、machineStats，以及 capabilities 下的 flow 等七项。站点登记后先是 Pending，站点代理上报清单后约 5 分钟变为 Registered",
  "rule.list": "新装的环境返回 200 和空列表，内置的默认规则确实不在里面",
  "rack-profile.list": "返回 14 个机柜规格。每个有 rack_profile_id 和 profile 下的 rack_hardware_type、rack_hardware_topology、rack_hardware_class、capabilities、product_family",
  // 网络与地址
  "segment.list": "返回 2 个子网。每个有 id、config、status、metadata 和创建、更新、删除时间。config 和 status 里面的字段没有逐项核对",
  "interface.list": "返回 8 个接口。字段与这里一致，另外还有 is_bmc、attached_dpu_machine_id、domain_id、created",
  // 设备清单
  "rack-group.list": "调用成功，没有机柜组，字段没法核对",
  "expected-rack.list": "调用成功，没有机柜声明，字段没法核对",
  "expected-machine.list": "返回 1 条声明。这个版本里网口列表的字段名是 interfaces，不是 host_nics；另有 sku_id、dpu_mode、bmc_ip_allocation、server_name、default_pause_ingestion_and_poweron 等。读取结果里带着 bmc_username 和 bmc_password。带关联关系的读取没有核对",
  "expected-switch.list": "调用成功，没有交换机声明，字段没法核对",
  "expected-shelf.list": "调用成功，没有供电框声明，字段没法核对",
  // 设备发现
  "explorer.endpoints": "返回 6 个探测结果。字段与这里一致：address、report（endpoint_type、vendor、systems、chassis、firmware_versions、last_exploration_error_schema 等）、preingestion_state、pause_remediation",
  "explorer.managed-hosts": "返回 1 组配对。字段是 host_bmc_ip、dpu_bmc_ip、host_pf_mac_address、dpus",
  // 机柜与 NVLink 域
  "rack.list": "调用成功，没有机柜。没有数据时命令行即使指定 JSON 格式也只输出一行文字，后端解析时要单独处理",
  "rack.rest": "返回 200 和空列表（环境里没有机柜），字段没法核对",
  "rack.validation": "返回 200，结构是 diffs、totalDiffs、missingCount、unexpectedCount、mismatchCount、matchCount，与这里一致。没有机柜时各计数都是 0",
  "tray.rest": "返回 200，列表和单个都调用过。字段与这里完全一致，包括 position 下的 slotId、trayIdx、hostId，以及 bmcs、nvosPorts、rackId、nvLinkDomainId、taskStats、health、leakHandlingStatus。列表里有一台不属于任何机柜的普通服务器，类型是 Compute",
  "domain.list": "返回 200 和空列表，字段没法核对",
  // 设备读取
  "machine.list": "返回 1 台主机。顶层字段与这里一致：id、state、state_reason、state_sla、rack_id、placement_in_rack、bmc、config、status、inventory、metadata、version。config 和 status 里面的字段没有逐项核对",
  "switch.list": "调用成功，没有交换机。没有数据时命令行只输出一行文字，不是 JSON",
  "shelf.list": "调用成功，没有供电框。没有数据时命令行只输出一行文字，不是 JSON",
  "device.power-state": "只调用了 GetPowerOptions 这一半：返回 desired_state、actual_state 和各自的更新时间、host_id、off_counter 等。GetComponentPowerDetails 没有命令行，没有调用",
  // 机柜级任务
  "task.list": "返回 200 和空列表（没有提交过任务），按站点和按托盘两种都调用过，字段没法核对",
  // 交付与实例
  "os.list": "返回 1 个系统定义。字段与这里一致，制品另有 sha、auth_type、cache_strategy",
  "instance.list": "返回 1 个实例。顶层字段是 id、machine_id、instance_type_id、config、status、metadata 和各配置的版本号。config 和 status 里面的字段没有逐项核对",
};
/* 只调用过其中读取那一半的写接口：证据仍是“定义”，但把看到的记下来。 */
const OBSERVED_PARTIAL = {
  "tray.power": "只调用过读回用的 GET /tray/{id}/power：返回 actual（state、source、observed、error）、desired（status、state、error）和 operations（actions、tasks 及各自的错误）。写操作没有调用",
};
Object.entries(OBSERVED).forEach(([id, text]) => { const c = NICO_CALLS.find((x) => x.id === id); if (c) { c.evidence = "调用"; c.observed = text; } });
Object.entries(OBSERVED_PARTIAL).forEach(([id, text]) => { const c = NICO_CALLS.find((x) => x.id === id); if (c) c.observed = text; });

/* ================= 缺口 =================
   分三类：NICo 没有的（要由平台补或者改设计）、两条路径要选一条的、源码里对不上要实测的。 */
G("到货清单里的槽位写入 NICo 的期望清单", ["设备清单"], "Core 的设备声明没有槽位字段。REST 的设备声明有 slotId、trayIdx、hostId，存在 REST 自己的数据库里，并以 slot_id、tray_idx、host_id 三个标签写进 Core 的 metadata。实际位置来自 RMS 或 BMC 的探测报告，不来自声明", "走 Core 时把槽位写成同样的三个 metadata 标签，与 REST 保持一致；或者设备声明改走 REST", "rest-api/db/pkg/db/model/common.go:100");
G("到货清单没有 MAC：设备的身份由平台读取", ["设备发现", "设备清单"], "NICo 的设备声明以 BMC 的 MAC 为键，没有 MAC 就写不进去；NICo 也不会去读一个没有声明的地址背后是什么设备。Core 的站点发现在设备有声明之后才比对序列号，结果只是一个计数指标和一条 SerialNumberMismatch 告警", "平台自己做：对拿到地址但没有归属的接口，用清单里的凭据读设备 BMC 的 Redfish，得到设备类型、序列号和型号，按序列号匹配清单后再写声明。现有产品已有这套读取（discovery.py、device_identity.py），但没有在 GB200/GB300 的计算托盘、NVLink 交换机和供电框上验证过分类是否正确。清单里的口令按批还是按台、每台不同时如何避免触发登录锁定，待确认", "crates/site-explorer/src/lib.rs:1046");
G("交换机 NVOS 管理口的 MAC 从哪来", ["设备发现"], "交换机声明至少要一个 NVOS 管理口的 MAC，多于一个时要标主口。NVOS 管理口自己也会申请地址，但 NICo 不知道哪个 NVOS 口属于哪台交换机", "设计按“从交换机的 BMC 读出 NVOS 管理口的 MAC”写，读不到时人工关联。这个读取现有代码里没有，要在模拟环境或真实设备上验证", "crates/api-db/src/expected_switch.rs");
G("对账里的“未声明的设备”", ["设备发现", "机柜详情"], "没有一个接口能列全。GetAllUnexpectedMachines 只含探测成功的主机 BMC；探测失败的、交换机和供电框都不在里面。未声明的主机 BMC 因为没有凭据，通常就是探测失败", "用设备接口列表里没有归属的记录，加上探测结果，由平台与声明对比得出", "crates/api-db/src/expected_machine.rs:292");
G("“没有收到 DHCP 请求”按子网定位", ["网络规划", "设备发现"], "NICo 不记录每个子网或每个中继最近一次收到请求的时间和次数。DHCP 的指标只按报文类型和丢弃原因分；接口上只有该设备最近一次请求的时间", "DHCP 服务页的“最近请求”改成从设备接口的 last_dhcp 按子网汇总得出：只能反映拿到过地址的设备。完全没有请求到达的情况，页面只能提示去看中继配置和 DHCP 的丢弃计数", "crates/dhcp-server/src/metrics.rs:496");
G("引导服务地址和时间服务器的展示", ["网络规划"], "域名服务器、时间服务器、引导服务器地址在 DHCP 服务的部署参数里，没有接口可读；运行配置里只有 DHCP 服务器地址", "从平台自己保存的部署配置读，并标明来源是部署配置而不是 NICo 的回报", "helm/charts/nico-dhcp/values.yaml:199");
G("固件基线", ["固件基线", "机柜详情", "设备管理"], "NICo 里没有可命名的固件基线对象。期望版本有两处：每个机柜规格的固件清单地址，和按厂商型号配置的主机期望版本。固件操作要么不带版本（用机柜规格的清单），要么带一整份清单文本", "固件基线做成平台自己的档案：一条基线对应一份清单文件。操作时把清单内容作为 version 传入，或者只允许选择与机柜规格配置一致的那一份。“低于基线”由平台对比探测到的版本和清单得出", "docs/configuration/rms.md:183");
G("站点概况里的硬件后端和设施接入状态", ["站点设置"], "当前生效的组件管理器后端没有读取接口；设施事件消费者是否连上也没有接口，只有它自己的指标。NMX-C 没有状态接口", "RMS 用版本接口判断；NMX-C 从机柜健康报告里的 NmxcUnreachable 判断；设施接入读消费者的指标，读不到就显示未知，不显示正常", "crates/api-core/src/cfg/README.md:140");
G("平台访问 REST 接口的身份", ["机柜管理", "机柜详情", "运维任务", "NVLink 域管理"], "REST 接口用的是身份系统签发的令牌，按组织和角色授权，和 Core 的客户端证书是两套。平台现在只有访问 Core 的证书，没有访问 REST 的身份。令牌必须从集群内的地址获取，否则签发者地址对不上", "给平台建一个服务账号，用客户端凭据方式取令牌并缓存、到期前刷新；组织名作为站点配置的一项。身份系统用官方的 Keycloak 还是现场已有的，按站点决定", "rest-api/openapi/auth.md:43");
G("依赖组件的证书到期", ["站点设置"], "RMS、Flow、站点代理和编排用数据库的证书最长 30 天，会自动续期，但 RMS 和数据库不会自动重新加载，过期后 Core 就连不上 RMS。NICo 没有接口报告这些证书的到期时间", "站点概况的依赖组件里显示各证书的到期时间，数据从集群里的证书对象读；临近到期而组件还没重启时给出提示", "docs/configuration/rms.md:82");
G("任务里的操作者和原因", ["运维任务", "操作审计"], "Flow 的任务只有描述、规则和阶段报告，没有操作者和原因字段。REST 有自己的审计接口，记录的是调用它的账号", "操作者和原因由平台审计保存，用任务编号关联；提交时把原因写进任务的 description", "rest-api/openapi/spec.yaml:28731");
G("单台设备电源走任务还是直接执行", ["设备管理"], "两条路径都能用：REST 的托盘电源提交为 Flow 任务，可取消、有阶段；Core 的设备电源接口立即执行。供电框在 Core 里另有一个走状态机的专用接口。现有产品用的是 Core 的直接接口", "设计稿目前写的是走任务。建议保持：有 Flow 时走任务，电源动作因此受“同一机柜只有一个任务”的约束；Flow 不可用时这些操作不可用，不悄悄改走直接接口", "crates/api-core/src/handlers/component_manager.rs:3244");
G("设备声明和机柜读取走 Core 还是走 REST", ["设备清单", "机柜管理", "机柜详情"], "REST 和 Core 是两套存储，靠工作流和定时任务同步；REST 的资源编号是它自己的 UUID。机柜的状态机状态只在 Core，任务计数、槽位和对账只在 REST", "写入只走 Core。读取分工：状态、健康、历史读 Core；槽位、对账、任务读 REST。两边用机柜 ID 和 BMC MAC 关联，页面上不显示 REST 的编号", "rest-api/api/pkg/api/handler/expectedrack.go:161");
G("新机柜的纳管、上线和机柜维护怎么衔接", ["机柜详情"], "三件事已经分清。纳管：现有产品写设备声明时带暂停标记（discovery.py:269），NICo 不上电也不接管，首次安装时才放行（onboarding.py:640）。上线：Flow 有内置的上线规则，六步，其中计算托盘上电这一步会打开 NICo 的上电闸门（AllowIngestionAndPowerOn）。机柜维护：Core 的机柜状态机在就绪的交换机数不少于机柜规格里的数量时自动开始，没有等人确认的开关，顺序是固件升级、NVOS 更新、上电顺序（需要时）、配置 NMX-C 集群、校验。没有核实的是这两条线同时进行时的衔接：Flow 上线里的计算托盘固件走状态机路径时要求机柜已经在 Ready 或 Error；交换机没有上电时能否被 NICo 建立对象；计算托盘带暂停标记时机柜能否走到 Ready", "设计按“人确认纳管 → 人开始上线（Flow 上线任务）→ NICo 自动机柜维护”来画，各阶段的定义、对设备的影响和人工确认点写在说明书 5.4 至 5.6，设计前提写在 5.9。衔接问题要在现场版本的模拟环境里把 Flow 上线任务和机柜状态机一起跑一遍才能定；旧版本模拟环境只测过机柜状态机这一半", "rest-api/flow/internal/task/operationrules/resolver_defaults.go:775；crates/rack-controller/src/discovering.rs:65；crates/rack-controller/src/maintenance.rs:1496");
G("更换设备后机柜重新发现", ["机柜详情"], "文档说更换托盘会让机柜因 topology_changed 回到 Discovering，但源码里没有找到设置这个标志的非测试代码。更换的实际步骤是：打上待更换标记并等 NVLink 隔离完成、强制删除旧设备、改设备声明、等新设备被发现", "更换设备做成平台编排的分步流程，每步读回；机柜状态是否变化以实测为准，页面不预先承诺", "crates/rack-controller/src/ready.rs:50");
G("删除机柜", ["机柜详情"], "DeleteRack 只把机柜标记为删除，不检查机柜里还有没有设备，状态机进入 Deleting 后一直等待；真正删除只有强制删除，同样不处理成员设备。命令行的说明写着“机柜不应再有关联的计算托盘、交换机和供电框”，但接口不做这项检查。Flow 有退役任务，但只在 Flow 自己的接口上，REST 没有端点", "机柜页只提供“删除机柜”，不提供“机柜退役”。删除的前提由平台检查并逐项显示：没有实例、成员设备都已逐台退役、没有进行中的任务。满足后平台删除机柜声明，再强制删除机柜对象。成员设备的退役是逐台设备的操作，在设备管理里做，机柜操作不代做", "crates/api-core/src/handlers/rack.rs:201");
G("跨机柜的固件分阶段发布", ["固件基线"], "一个 NVL72 机柜就是一个 NVLink 域，所以没有“域内按机柜分批”。Flow 的分阶段发布目标是站点内所有符合条件的机柜，按百分比抽取，不能传入机柜列表；只调用过它的列表接口，返回空", "这一版不设计：域级电源、域级固件和分阶段发布都已从设计稿里去掉。以后作为站点级功能单独设计", "docs/operations/flow/operation-runs.md:123");
G("装系统前的“机柜就绪”和“无整柜泄漏”", ["安装任务"], "NICo 建实例时只看主机自己：状态、维护标记和阻止分配的告警。机柜的健康报告会并入主机，所以泄漏会挡住整柜；但机柜状态不是 Ready、域的健康报告有告警，都不会让建实例失败", "机柜里的设备，平台在选择设备时另外检查机柜是否就绪、有没有整柜泄漏、有没有进行中的任务，并在每一行写明原因；页面上标明这是平台的规则。“可以装系统”的判断用主机状态接口里的 allocatable，与 NICo 保持一致", "crates/api-model/src/machine/mod.rs:543");
G("实例用的租户和 VPC", ["安装任务"], "NICo 里每个实例都要属于一个租户、接入一个网络。Core 的创建租户和创建 VPC 接口只对站点代理放行，管理端证书调不了。现有产品用一个固定的默认租户（site_network_context.py:40），只读取已有的 VPC", "平台不做多租户：所有实例建在站点的默认租户下，页面上不显示也不让选。默认租户和 VPC 是部署前提，由部署步骤建好。实例类型和配额是 NICo 向多个租户分发机器时用的，平台不使用", "crates/api-core/src/auth/internal_rbac_rules.rs:75");
G("一次给多台机器建实例", ["安装任务"], "实例是逐台机器的：建实例的请求里每个实例带一个机器 ID。REST 的批量建实例按实例类型和数量挑设备，不能指定设备列表。Core 的批量接口可以传入明确的设备列表，并且是一个事务。机柜上没有建实例或装系统的接口", "走 Core：向导里选了几台就提交几个实例，每个实例明确给出机器 ID、主机名和系统，一次提交在一个事务里。机柜只是选择设备时的筛选条件，不是装系统的对象", "crates/api-core/src/instance/mod.rs:2009");
G("安装条件检查由谁做", ["安装任务"], "NICo 建实例时只检查主机状态。现有产品在提交前自己做一组检查（execution.py:387、onboarding.py:960、onboarding.py:1120）：设备规划与地址占用、引导方式、既有实例与目标盘基线、BMC 认证与序列号、管理地址与安装网络配置、安装材料的 HTTP 可达与长度。还没有接入的设备把“就绪”和“目标盘”推迟到执行前。页面把这些归成三组显示：设备身份、安装配置、操作系统材料", "整机柜方向照搬这组检查和页面。其中 BMC 认证是平台直接读设备的 BMC，不经 NICo；材料检查是平台对自己的材料服务的请求；主机状态、实例和地址占用读 NICo。选盘规则解析不出唯一的系统盘时，检查不通过，在向导里逐台指定", "crates/api-model/src/machine/mod.rs:543");
G("主机名在哪里确定", ["安装任务", "实例管理"], "实例配置的租户部分有一个主机名字段；实例名称合法时，NICo 把它作为 cloud-init 的 local-hostname 传给系统。机器在 NICo 里自己的 DNS 名由站点的命名策略决定（默认按地址生成），那不是系统里的主机名。现有产品在建实例时逐台传主机名（executor.py:2022）", "主机名在新建安装任务时逐台确定，同时用作实例名称。它是设备系统配置里的一项：没有填时平台按管理地址生成（node-加上把点换成连字符的地址），可以逐台改；平台在提交前检查写法和重名。站点的命名策略不动", "crates/api-core/src/handlers/client_resolution.rs:512");
G("主机的网络配置在哪里确定", ["安装任务"], "NICo 给主机管理口分配地址，分配方式有动态、固定、保留三种，接口已有分配后再改声明不会改地址。现有产品在设备的系统配置里逐台保存：启动网卡 MAC、管理 IP、管理子网，以及其他网口各自的 IP、子网和网关；装机时把这些写进系统的网络配置，不含 Bond、VLAN 和 IPv6（现有产品的设备管理使用指南第 6 节）", "照搬字段，放在设备管理的“系统配置”里，新建安装任务只引用和核对。管理地址在设备规划时和启动网口的 MAC 对应（到货清单可带 management_ip 一列），一般不改；其他网口可各配一个固定地址。规划的管理地址如何落到 NICo 的地址分配上（改声明还是固定租约），沿用现有产品的做法，没有在整机柜环境里核对", "docs/provisioning/expected-machine-interfaces.md");
G("不属于机柜的服务器", ["设备管理", "设备清单", "设备发现", "安装任务"], "设备声明里的机柜编号是可选的，机器、交换机、供电框通过各自的机柜编号指向机柜，机柜对象里不存成员。Flow 的上线任务按机柜提交，没有机柜的服务器走不了这条路。现有产品写声明时带暂停标记（discovery.py:269），首次安装时才放行（onboarding.py:640）", "设备是基础对象，机柜是叠在上面的一层。不属于机柜的服务器进同一份清单，机柜和槽位留空；在设备发现里逐台确认纳管；没有上线这一步，安装任务的第一步放行，由 NICo 上电接管。机柜里的设备由上线任务放行。这是从两边的定义推出来的设计，没有在同一个环境里把两种设备一起跑过", "crates/rpc/proto/forge.proto:8191");
G("供电框的槽位和序列号", ["设备管理", "机柜详情"], "Core 的供电框对象没有位置字段，也没有序列号字段；交换机的序列号取自探测报告", "供电框的槽位读 REST 的托盘，序列号读设备声明或探测报告", "crates/rpc/proto/forge.proto:3087");

/* ================= 页面与接口的对照 =================
   每个页面用到哪些接口、做什么用：[接口编号, 用途]。键是页面编号（与地址栏 # 后面的路径一致）。
   页面脚本里不写接口，全部在这里，所以对外版的设计稿不带任何接口内容。 */
const PAGE_CALLS = {
  "site": [
    ["core.version", "Core 版本与运行配置"],
    ["rms.status", "RMS 是否就绪"],
    ["rest.site", "Flow 与站点代理是否在线"],
    ["nmxc.endpoints", "NMX-C 接入"],
    ["explorer.last-run", "站点发现最近一次扫描"],
    ["explorer.config", "开关站点发现和自动建机"],
    ["credential.readiness", "接管凭据是否齐备"],
    ["credential.write", "补齐接管凭据"],
    ["rack-profile.list", "支持的机柜规格"],
    ["rule.list", "生效的电源和固件规则"],
  ],
  "site/cluster": [
    ["core.version", "Core 版本"],
    ["rms.status", "RMS 版本"],
    ["rest.site", "站点代理与 Flow 的版本和在线状态"],
  ],
  "network": [
    ["segment.list", "子网、状态和空闲地址"],
    ["segment.create", "新增子网"],
    ["segment.dhcp-range", "读取 DHCP 地址池"],
    ["segment.dhcp-range.write", "修改 DHCP 地址池"],
    ["segment.delete", "删除子网"],
    ["expected-machine.list", "规划检查：计算托盘接口的数量"],
    ["expected-switch.list", "规划检查：交换机接口的数量"],
    ["expected-shelf.list", "规划检查：供电框接口的数量"],
  ],
  "network/dhcp": [
    ["core.version", "DHCP 服务器地址"],
    ["segment.list", "各子网的地址余量"],
    ["segment.dhcp-range", "各子网的地址池范围"],
    ["interface.list", "各子网最近一次请求"],
    ["dhcp.metrics", "请求、应答和丢弃计数"],
  ],
  "network/leases": [
    ["interface.list", "地址、MAC、归属和最近请求"],
    ["interface.addresses", "分配方式，按地址反查归属"],
  ],
  "inventory": [
    ["rack-profile.list", "核对清单里的机柜拓扑和厂商能推导出已配置的机柜规格"],
    ["rack-group.list", "哪些机柜组已经写入"],
    ["expected-rack.list", "哪些机柜的声明已经写入"],
    ["expected-machine.list", "哪些计算托盘已经写入 NICo"],
    ["expected-switch.list", "哪些交换机已经写入 NICo"],
    ["expected-shelf.list", "哪些供电框已经写入 NICo"],
    ["segment.list", "导入预览：各用途的地址够不够"],
  ],
  "discovery": [
    ["interface.list", "拿到了地址、但还没有归属的接口，以及最近一次申请地址的时间"],
    ["expected-machine.write", "机柜已确认纳管时，新匹配上的计算托盘直接写入：MAC、凭据、序列号、机柜、槽位和 DPU 策略。不属于机柜的服务器逐台确认纳管时写入，不带机柜，带暂停标记"],
    ["expected-switch.write", "机柜已确认纳管时，新匹配上的交换机直接写入：BMC 与 NVOS 管理口的 MAC、两组凭据"],
    ["expected-shelf.write", "机柜已确认纳管时，新匹配上的供电框直接写入"],
    ["expected-domain.write", "机柜的声明齐了之后写入 NVLink 域声明"],
    ["expected-machine.list", "计算托盘声明走到了哪一步"],
    ["expected-switch.list", "交换机声明走到了哪一步"],
    ["expected-shelf.list", "供电框声明走到了哪一步"],
    ["explorer.endpoints", "NICo 的探测结果和失败原因"],
    ["explorer.managed-hosts", "主机的接管进度"],
    ["explorer.unexpected", "NICo 探测到、但没有声明的主机"],
    ["explorer.retry", "重新探测、清除探测错误"],
    ["ingestion.state", "是否在等待放行"],
    ["ingestion.allow", "放行等待中的主机"],
    ["machine.list", "计算托盘的状态"],
    ["switch.list", "交换机的状态"],
    ["shelf.list", "供电框的状态"],
    ["explorer.last-run", "最近一次扫描"],
  ],
  "racks": [
    ["rack.list", "机柜状态（含上线所在的阶段）与健康"],
    ["expected-rack.list", "机柜规格"],
    ["rack.rest", "托盘计数与任务计数"],
    ["task.list", "当前任务"],
  ],
  "rack": [
    ["rack.list", "状态、所在阶段、原因与健康"],
    ["rack-profile.list", "机柜规格和它要求的各类设备数量"],
    ["rack.history", "状态历史"],
    ["rack-group.write", "确认纳管：写入机柜组"],
    ["expected-rack.write", "确认纳管：写入机柜声明；删除机柜时删掉机柜声明"],
    ["expected-machine.write", "确认纳管：写入已匹配的计算托盘，带暂停标记（default_pause_ingestion_and_poweron），不上电、不接管"],
    ["expected-switch.write", "确认纳管：写入已匹配的交换机"],
    ["expected-shelf.write", "确认纳管：写入已匹配的供电框"],
    ["rack.maintenance", "重新执行机柜维护；终止进行中的机柜维护"],
    ["rack.delete", "删除机柜"],
    ["rack.bringup", "开始上线：提交上线任务。内置规则六步：供电框上电、计算托盘上电并放行接管、计算托盘固件、交换机上电、核对交换机固件、计算托盘重启"],
    ["rack.rest", "任务计数与所属域"],
    ["rack.validation", "期望与实际校验"],
    ["tray.rest", "实测槽位（与清单比对）；电源和固件确认页上各主机现在能否被操作"],
    ["machine.list", "设备表：计算托盘"],
    ["switch.list", "设备表：交换机"],
    ["shelf.list", "设备表：供电框"],
    ["device.power-state", "成员电源"],
    ["rack.power", "机柜电源"],
    ["rack.firmware", "固件更新"],
    ["firmware.status", "固件步骤的逐台进度"],
    ["task.list", "任务卡与步骤"],
    ["task.cancel", "取消任务"],
    ["health.reports", "机柜健康与整柜泄漏"],
  ],
  "domains": [
    ["domain.list", "域（机柜组编号）、拓扑和 NMX-C 集群"],
    ["switch.list", "交换机回报的 NMX-C 域编号和 Fabric Manager 状态"],
    ["health.reports", "机柜健康里的 NMX-C 不可达"],
    ["nvlink.domain-health", "域的健康报告"],
    ["nvlink.partitions", "NMX 分区"],
    ["nvlink.logical-partitions", "逻辑分区和状态"],
  ],
  "devices": [
    ["machine.list", "计算托盘的数量和需要处理的设备"],
    ["switch.list", "交换机的数量和需要处理的设备"],
    ["shelf.list", "供电框的数量和需要处理的设备"],
    ["device.identify", "按序列号、MAC、地址搜索"],
    ["explorer.endpoints", "DPU 卡片上 BlueField 卡的数量和工作方式"],
  ],
  "devices/dpu": [
    ["explorer.endpoints", "BlueField 卡的部件号、序列号、网卡固件、工作方式和 BMC 地址（命令行 site-explorer mlx-devices 列的是同一批数据）"],
    ["expected-machine.list", "每台主机声明的 DPU 策略"],
    ["machine.list", "所属主机"],
  ],
  "devices/compute": [
    ["machine.list", "列表、状态、健康和地址；机柜编号为空的是不属于机柜的服务器"],
    ["device.power-state", "电源状态"],
    ["device.inventory", "固件版本"],
    ["instance.list", "所属实例"],
    ["device.history", "运行状态里的状态历史"],
    ["machine.validation", "硬件校验结果"],
    ["tray.power", "上电、关机、重启"],
    ["tray.firmware", "固件更新"],
    ["task.list", "任务进度"],
    ["machine.maintenance", "设置和清除维护标记"],
    ["machine.quarantine", "隔离和解除隔离"],
    ["machine.validate", "按需硬件校验"],
    ["machine.sku", "核对 SKU"],
    ["device.bmc-reset", "重启 BMC"],
    ["device.decommission", "退役"],
    ["device.power-direct", "电源的直接执行路径（见缺口）"],
    ["interface.list", "系统配置：这台机器上的主机网口和 NICo 引导时用的网口"],
    ["interface.addresses", "系统配置：管理地址有没有被占用"],
    ["segment.list", "系统配置：管理子网的范围和网关"],
    ["os.list", "系统配置：这种架构已发布的安装方案"],
  ],
  "devices/switch": [
    ["switch.list", "列表、状态、健康、地址和 Fabric Manager"],
    ["device.power-state", "电源状态"],
    ["device.inventory", "固件与 NVOS 版本"],
    ["device.history", "运行状态里的状态历史"],
    ["tray.power", "上电、关机、重启"],
    ["tray.firmware", "固件更新"],
    ["task.list", "任务进度"],
    ["device.bmc-reset", "重启 BMC"],
    ["device.decommission", "退役"],
    ["device.power-direct", "电源的直接执行路径（见缺口）"],
  ],
  "devices/power-shelf": [
    ["shelf.list", "列表、状态、健康、地址和供电规格"],
    ["tray.rest", "槽位"],
    ["expected-shelf.list", "序列号"],
    ["device.power-state", "电源状态"],
    ["device.inventory", "固件版本"],
    ["device.history", "运行状态里的状态历史"],
    ["tray.power", "上电、关机"],
    ["task.list", "任务进度"],
    ["device.decommission", "退役"],
    ["shelf.power", "电源的直接执行路径（见缺口）"],
  ],
  "health": [
    ["health.reports", "各对象当前的告警与分类"],
    ["health.history", "告警历史"],
    ["rack.list", "机柜级告警"],
    ["machine.list", "有告警的计算托盘"],
    ["switch.list", "有告警的交换机"],
    ["shelf.list", "有告警的供电框"],
  ],
  "tasks": [
    ["task.list", "任务、阶段和状态"],
    ["task.cancel", "取消任务"],
  ],
  "delivery/installs": [
    ["machine.list", "可选的服务器：机柜里的计算托盘和不属于机柜的服务器"],
    ["host.states", "“安装条件”一列：每台能不能装系统，被什么挡住"],
    ["rack.list", "机柜里的设备：所在机柜是否就绪"],
    ["health.reports", "整柜泄漏和阻止分配的告警"],
    ["os.list", "已发布的安装方案，按架构列出"],
    ["instance.list", "已有的实例名称（主机名查重）和实例状态；安装条件检查：机器没有实例"],
    ["interface.addresses", "安装条件检查：管理地址与地址占用"],
    ["interface.list", "核对配置：启动网口的 MAC"],
    ["device.inventory", "安装条件检查：读硬件里的磁盘，按安装方案的规则解析系统盘"],
    ["ingestion.state", "不属于机柜的服务器是否还在等待放行"],
    ["ingestion.allow", "不属于机柜的服务器第一次装系统时放行，由 NICo 上电接管"],
    ["instance.allocate", "逐台建实例：机器 ID、主机名和系统；一次提交在一个事务里"],
  ],
  "delivery/instances": [
    ["instance.list", "实例名称、系统和状态"],
    ["machine.list", "机器状态与回收进度"],
    ["instance.release", "删除（退租回收）"],
  ],
  "baselines": [
    ["rack-profile.list", "机柜规格"],
    ["firmware.desired", "NICo 里配置的期望版本和可用固件包"],
    ["device.inventory", "偏差统计：探测到的版本"],
  ],
  "os-templates": [
    ["os.list", "方案列表与状态"],
    ["os.write", "新建、修改和停用方案"],
  ],
};

/* ================= 组件 =================
   回答“这个功能需要部署什么”。一个接口需要某个组件，按三条规则判断，三条都由接口自己的记录推出，不另外维护对照：
   - 接口的类型（surface）是这个组件对外提供的；
   - 接口的执行方（executedBy）经过这个组件；
   - 接口的前置资源（requires）里有这个组件负责的资源。
   level：必需 = 任何功能都需要；整机柜 = 机柜级功能需要；可选 = 缺了只影响一部分信息。 */
const NICO_COMPONENTS = [
  { id: "core", deploy: "随产品的 Chart 安装", name: "NICo Core", workload: "nico-api（含站点发现和各状态机）、数据库、密钥库", level: "必需", provides: "全部 Core gRPC：子网、设备声明、发现、设备读取与单设备操作、实例、健康报告",
    missing: "平台不可用", surfaces: ["Core gRPC", "REST"], source: "helm/charts/nico-api" },
  { id: "dhcp", deploy: "随 Core 的 Chart 安装", name: "DHCP 服务", workload: "nico-dhcp", level: "必需", provides: "给各管理网段的设备分配地址，并在 Core 里留下设备接口；设备发现从这里开始",
    missing: "新设备拿不到地址，不会被发现；已发现的设备不受影响", resources: ["dhcp-service", "dhcp-relay", "machine-interface"], surfaces: [], source: "helm/charts/nico-dhcp" },
  { id: "boot", deploy: "随 Core 的 Chart 安装", name: "引导服务", workload: "nico-pxe、nico-dns、nico-ntp", level: "必需", provides: "iPXE 引导、装机材料、名称解析和时间",
    missing: "不能装机；新主机走不完接管流程", calls: ["instance.allocate", "os.write"], surfaces: [], source: "helm/charts/nico-pxe" },
  { id: "health", deploy: "随 Core 的 Chart 安装", name: "硬件健康服务", workload: "nico-hardware-health", level: "必需", provides: "采集 BMC 传感器和托盘泄漏检测，写成设备的健康报告",
    missing: "健康告警页只剩站点发现和手工写入的报告；托盘泄漏不会阻止分配", resources: ["health-report"], surfaces: [], source: "helm/charts/nico-hardware-health" },
  { id: "rms", deploy: "官方 Chart rack-manager；镜像从公开源码自己构建。已在没有整机柜硬件的环境里部署，Core 探测结果为已连通", name: "RMS", workload: "Rack Management Service", level: "整机柜", provides: "整机柜里计算托盘、交换机、供电框的电源和固件；交换机的证书与口令配置、复位、退役；设备的槽位信息",
    missing: "设备和机柜的电源、固件操作不可用；交换机过不了配置阶段，机柜走不到就绪", resources: ["rms", "component-manager"], executors: ["硬件后端", "RMS"], surfaces: [], source: "docs/configuration/rms.md" },
  { id: "rest", deploy: "官方 Chart nico-rest、nico-rest-site-agent、temporal；镜像自己构建，要和 Core 同一个源码提交。已部署，接口实际调用通过", name: "REST 接口", workload: "REST API、工作流、站点管理、站点代理、Temporal", level: "整机柜", provides: "机柜、托盘、NVLink 域和任务的 REST 接口；期望与实际的对账",
    missing: "机柜对账、机柜立面的槽位、任务列表不可用；机柜级任务无法提交", resources: ["rest-site", "rest-auth", "temporal"], surfaces: ["REST"], source: "rest-api/INSTALLATION.md" },
  { id: "flow", deploy: "官方 Chart nico-flow；镜像自己构建，要和 Core 同一个源码提交。已部署，已从 Core 同步到清单", name: "Flow", workload: "nico-flow", level: "整机柜", provides: "机柜级任务的编排：上线、电源、固件、分阶段发布；机柜与托盘的清单和任务记录",
    missing: "机柜级电源与固件、运维任务不可用，整柜泄漏时也不会自动下电；机柜上线由 Core 的状态机进行，不受影响；单设备的状态类操作照常", resources: ["flow", "flow-inventory", "flow-task", "operation-rule"], executors: ["Flow"], surfaces: [], source: "docs/architecture/flow.md" },
  { id: "nmxc", deploy: "不在集群里部署：它运行在交换机上，由 RMS 配置，Core 通过交换机的管理地址访问", name: "NMX-C", workload: "交换机上的 NMX-C", level: "整机柜", provides: "NVLink 域的集群配置和域编号",
    missing: "NVLink 域管理没有数据；机柜上线里的 NMX-C 配置阶段无法完成", resources: ["nmxc", "nvlink-domain"], surfaces: [], source: "docs/development/machine-a-tron-nmxc-mock.md" },
  { id: "facility", deploy: "Core Chart 里的一个开关；另外需要现场楼宇系统的消息总线。未部署", name: "设施事件接入", workload: "nico-dsx-exchange-consumer、消息总线", level: "可选", provides: "把楼宇管理系统的泄漏事件写成机柜的健康报告",
    missing: "机柜级泄漏不会进入 NICo，不会自动阻止分配；安全联锁本来就不依赖它", resources: ["facility-events"], pages: ["health", "rack"], surfaces: [], source: "docs/operations/leak-detection-handling.md" },
  { id: "metrics", deploy: "现场已有的监控系统", name: "监控系统", workload: "Prometheus", level: "可选", provides: "DHCP 的请求、应答和丢弃计数；各子网的空闲地址数",
    missing: "DHCP 服务页没有请求计数，其余不受影响", surfaces: ["指标"], source: "docs/observability/core_metrics.md" },
];
const componentById = (id) => NICO_COMPONENTS.find((c) => c.id === id);
/* 一个接口需要哪些组件。REST 接口最终落到 Core，所以也算 Core。 */
const callNeeds = (k, c) => (k.surfaces || []).includes(c.surface) || (k.calls || []).includes(c.id) ||
  (k.executors || []).some((e) => (c.executedBy || "").includes(e)) || (c.requires || []).some((r) => (k.resources || []).includes(r));
const componentCalls = (k) => NICO_CALLS.filter((c) => callNeeds(k, c));
const callComponents = (c) => NICO_COMPONENTS.filter((k) => callNeeds(k, c));
/* 一个页面需要哪些组件：它用到的接口需要的，加上组件里直接点名的页面。 */
const pageComponents = (page) => NICO_COMPONENTS.filter((k) => (k.pages || []).includes(page.id) || pageCalls(page).some((x) => x.call && callNeeds(k, x.call)));
const componentPages = (k) => PAGE_ORDER.map((p) => PAGES[p]).filter((p) => p.spec && pageComponents(p).includes(k));

const resourceById = (id) => NICO_RESOURCES.find((r) => r.id === id);
const callById = (id) => NICO_CALLS.find((c) => c.id === id);
/* 一组资源连同它们的全部前置，按“先准备的在前”排序。顺序取自整张资源表的排序，所以各页面看到的先后一致。 */
function resourceChain(ids) {
  const need = new Set(), seen = new Set(), order = [];
  const want = (id) => { const r = resourceById(id); if (!r || need.has(id)) return; need.add(id); (r.requires || []).forEach(want); };
  const place = (r) => { if (seen.has(r.id)) return; seen.add(r.id); (r.requires || []).map(resourceById).filter(Boolean).forEach(place); order.push(r); };
  ids.forEach(want); NICO_RESOURCES.forEach(place);
  return order.filter((r) => need.has(r.id));
}
/* 页面用到的接口，连同接口定义。对照里写了契约里没有的接口时保留下来并标出，方便发现漏项。 */
const pageCalls = (page) => (PAGE_CALLS[page.id] || []).map(([id, use]) => ({ id, use, call: callById(id) }));
const pageResources = (page) => resourceChain(pageCalls(page).flatMap((x) => (x.call ? x.call.requires || [] : [])));
const callUsers = (id) => PAGE_ORDER.map((p) => PAGES[p]).filter((p) => pageCalls(p).some((x) => x.id === id));
/* 契约自检：对照里的页面不存在、页面引用了不存在的接口、接口引用了不存在的资源、定义了却没有页面使用的接口。 */
function contractProblems() {
  const out = [];
  PAGE_ORDER.map((p) => PAGES[p]).forEach((p) => pageCalls(p).forEach((x) => { if (!x.call) out.push(`页面 ${p.id} 引用了未定义的接口 ${x.id}`); }));
  Object.keys(PAGE_CALLS).forEach((id) => { if (!PAGES[id]) out.push(`对照里的页面 ${id} 不存在`); });
  NICO_CALLS.forEach((c) => (c.requires || []).forEach((r) => { if (!resourceById(r)) out.push(`接口 ${c.id} 引用了未定义的资源 ${r}`); }));
  NICO_RESOURCES.forEach((r) => (r.requires || []).forEach((x) => { if (!resourceById(x)) out.push(`资源 ${r.id} 引用了未定义的资源 ${x}`); }));
  NICO_COMPONENTS.forEach((k) => [...(k.resources || []).filter((r) => !resourceById(r)).map((r) => `资源 ${r}`), ...(k.calls || []).filter((c) => !callById(c)).map((c) => `接口 ${c}`), ...(k.pages || []).filter((p) => !PAGES[p]).map((p) => `页面 ${p}`)].forEach((x) => out.push(`组件 ${k.id} 引用了未定义的${x}`)));
  Object.keys({ ...OBSERVED, ...OBSERVED_PARTIAL }).forEach((id) => { if (!callById(id)) out.push(`实测结果里的接口 ${id} 不存在`); });
  NICO_CALLS.forEach((c) => { if (!callComponents(c).length) out.push(`接口 ${c.id} 没有对应的组件`); });
  NICO_CALLS.forEach((c) => { if (!callUsers(c.id).length) out.push(`接口 ${c.id} 没有页面使用`); });
  return out;
}
