"use strict";
/* 接口契约：页面与 NICo 之间的约定。
   四张表，来源只有这一个文件：
   - NICO_RESOURCES：NICo 里的资源，以及它们之间的依赖。回答“这个页面要有数据，必须先有什么”。
   - NICO_CALLS：页面用到的 NICo 接口：属于哪一类接口、请求参数、用到的字段、对应的命令行、前置资源。
   - CONTRACT_GAPS：设计需要、但 NICo 没有直接提供的东西，以及待定的处理方式。
   - PAGE_CALLS：每个页面用到哪些接口和用途。
   这个文件只由实现参考版（internal.html）加载；对外版（index.html）不加载它。

   证据等级（evidence）：定义 = 只读过源码里的定义；模拟 = 在模拟环境里调用过；现场 = 在真实整机柜环境核对过。
   准备方式（prep）说明在没有真实整机柜时这个资源怎么得到。
   used = 现有产品（主线分支）已经调用过这个接口；没有这个标记的是整机柜方向新增的。 */

const CONTRACT_SOURCE = { repo: "dsx-ai-factory/infra-controller", commit: "856eb1665", version: "v2.5.0 之后", note: "接口、参数和字段取自这个提交的源码。换版本时逐项重新核对。" };
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
R("rms", "RMS", "Rack Management Service", "独立部署，在站点配置 [rms] 里填它的地址", ["rack-profiles"], "config",
  { prepNote: "没有硬件时接 RMS 模拟服务", note: "任一后端选了 rms，启动时就要求机柜规格配置里有产品系列和厂商", source: "docs/configuration/rms.md:243" });
R("component-manager", "组件管理器", "[component_manager]", "站点配置里为计算托盘、交换机、供电框各选一个后端，默认都是 rms", ["rms"], "config",
  { note: "没有这段配置时，设备电源、复位、固件接口返回未实现。当前生效的后端没有读取接口", source: "crates/api-core/src/handlers/component_manager.rs:130" });
R("rest-auth", "REST 身份认证", "JWT 签发方与声明映射", "REST 的部署配置：外部签发方或内置 Keycloak，二选一；从声明映射出组织名和角色", [], "config",
  { source: "rest-api/openapi/auth.md:43" });
R("rest-site", "REST 站点", "Infrastructure Provider、Site、站点代理", "部署 Temporal 并建好命名空间；调用一次 GET /infrastructure-provider/current；POST /site；再把站点注册信息写进站点代理", ["core", "rest-auth"], "direct",
  { note: "机柜、托盘、域和任务接口都要带 siteId。站点代理上线后回报是否启用了 Flow", source: "rest-api/INSTALLATION.md:773" });
R("flow", "Flow", "nico-flow", "独立部署；站点代理里配置 Flow 地址；Core 的权限表给 Flow 身份放行设备电源和固件接口", ["rest-site", "component-manager"], "config",
  { note: "REST 经 Temporal 和站点代理转发到 Flow。直接访问 Flow 要用双向证书，并且身份在允许名单里", source: "docs/architecture/flow.md:3" });
R("operation-rule", "操作规则", "OperationRule", "默认规则写在 Flow 的代码里；自定义规则用 POST /task/rule 创建，只有电源和固件两类", ["flow"], "derived",
  { note: "选用顺序：请求里指定的规则、机柜关联的规则、该类操作的全局默认、内置规则", source: "docs/operations/flow/operation-rules.md:553" });
R("nmxc", "NMX-C 接入", "NvlinkNmxcEndpoint", "CreateNvlinkNmxcEndpoint：机箱序列号和 NMX-C 地址", ["core"], "direct",
  { prepNote: "没有硬件时接 NMX-C 模拟服务", note: "没有专门的状态接口，只能从机柜健康报告里的 NmxcUnreachable 判断", source: "crates/rpc/proto/forge.proto:1116" });

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
R("vpc", "租户与 VPC", "Tenant、Vpc", "CreateTenant、CreateVpc。计算托盘的 DPU 处于 DPU 模式时用 FNN 或 ETHERNET_VIRTUALIZER，网卡模式或没有 DPU 时用 FLAT", ["core"], "direct",
  { note: "Core 的权限表只允许站点代理（以及模拟器）调用这两个创建接口，管理端证书不能调用", source: "crates/api-core/src/auth/internal_rbac_rules.rs:75" });
R("instance-type", "实例类型与配额", "InstanceType、ComputeAllocation", "CreateInstanceType，把计算托盘关联到实例类型，再给租户建配额", ["machine", "vpc"], "direct",
  { note: "只在“交给上层平台”时需要。Core 默认对超配额只告警不拒绝；REST 一侧强制检查", source: "crates/api-core/src/instance/mod.rs:2077" });
R("instance", "实例", "Instance", "AllocateInstances：计算托盘 ID 和实例配置（租户、系统、网络）", ["machine", "os-definition", "vpc"], "simulator",
  { note: "托盘必须是 Ready，没有维护标记、阻止分配的告警、待处理的实例或退役。机柜的健康报告会并入柜内每台主机的健康，所以机柜上阻止分配的告警会挡住整柜", source: "crates/api-model/src/machine/mod.rs:543" });

/* ---- 健康 ---- */
R("health-report", "健康报告", "HealthReport", "硬件健康服务、DPU 代理、站点发现和设施事件消费者写入；也可以用 Insert…HealthReport 手工写入一条", ["machine"], "direct",
  { prepNote: "设备对象存在后，可以手工写入报告来验证页面：nico-admin-cli machine health-report add", source: "crates/api-core/src/handlers/health.rs:98" });
R("facility-events", "设施事件接入", "nico-dsx-exchange-consumer", "部署事件消费者并连到楼宇管理系统的消息总线；泄漏事件被写成机柜的健康报告", ["rack"], "config",
  { note: "消费者是否连上没有读取接口，只有它自己的指标和存活探针", source: "crates/dsx-exchange-consumer/src/health_updater.rs:184" });

/* ================= 接口：站点与依赖 ================= */
C("core.version", "站点与依赖", "Core gRPC", "Version", { cli: "nico-admin-cli version --show-runtime-config", request: "display_config 为真时带回运行配置", fields: ["build_version", "git_sha", "capabilities[]", "runtime_config.dhcp_servers", "runtime_config.networks", "runtime_config.initial_domain_name", "runtime_config.attestation_enabled"], requires: ["core"], note: "运行配置里没有时间服务器、组件管理器后端和配额执行方式", source: "forge.proto:36" });
C("rms.status", "站点与依赖", "Core gRPC", "GetRmsVersion", { cli: "nico-admin-cli backend rms status", fields: ["version"], requires: ["rms"], executedBy: "Core → RMS", note: "没有配置 RMS 时返回 UNAVAILABLE；30 秒超时。命令行只有在连通时退出码才是 0", source: "crates/api-core/src/handlers/rms.rs:75" });
C("rest.site", "站点与依赖", "REST", "GET /site、GET /site/{id}", { cli: "nicocli site list", fields: ["id", "status（Pending、Registered、Error）", "isOnline", "siteAgentVersion", "siteControllerVersion", "capabilities.flow", "machineStats"], requires: ["rest-site"], executedBy: "REST", note: "Flow 是否可用只能从这里的 capabilities.flow 看，Core 没有对应接口", source: "spec.yaml:946" });
C("credential.readiness", "站点与依赖", "Core gRPC", "GetSiteCredentialReadiness", { fields: ["configured[]", "missing[]", "requires_recovery[]"], requires: ["core"], source: "forge.proto:589" });
C("credential.write", "站点与依赖", "Core gRPC", "InitializeSiteCredentials / CreateCredential", { write: true, cli: "nico-admin-cli credential add-bmc；nico-admin-cli credential add-uefi", request: "generate_missing，或逐项给 BMC、主机 UEFI、DPU UEFI 口令", requires: ["core"], note: "口令经标准输入或安全文件传入，不出现在命令行和日志里", source: "forge.proto:586" });
C("explorer.last-run", "站点与依赖", "Core gRPC", "GetSiteExplorerLastRun", { fields: ["started_at", "finished_at", "success", "error", "endpoint_explorations", "endpoint_explorations_success", "endpoint_explorations_failed", "failure_category", "last_successful_finished_at"], requires: ["core"], source: "site_explorer.proto:112" });
C("explorer.config", "站点与依赖", "Core gRPC", "SetDynamicConfig", { write: true, request: "SITE_EXPLORER_ENABLED、CREATE_MACHINES", requires: ["core"], note: "创建交换机和供电框的开关只在配置文件里，不能在运行时改", source: "forge.proto:502" });
C("rack-profile.list", "站点与依赖", "Core gRPC", "ListRackProfiles / GetRackProfile", { cli: "nico-admin-cli rack profile list；nico-admin-cli rack profile show <RACK_ID>", fields: ["rack_profile_id", "profile.rack_hardware_topology", "profile.capabilities.{compute,switch,power_shelf}.count", "profile.product_family"], requires: ["rack-profiles"], note: "从运行配置读出；只允许管理端证书调用", source: "crates/api-core/src/handlers/rack.rs:511" });
C("rule.list", "站点与依赖", "REST", "GET /task/rule", { cli: "nicocli rule list --site-id <SITE>", request: "siteId 必填；operationType 可选（PowerControl、FirmwareControl）", fields: ["id", "name", "operationType", "operationCode", "isDefault", "ruleDefinition.steps[]"], requires: ["operation-rule"], executedBy: "Flow", note: "只返回存进数据库的规则", source: "spec.yaml:14592" });
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
C("expected-machine.list", "设备清单", "Core gRPC", "GetAllExpectedMachines / GetAllExpectedMachinesLinked", { cli: "nico-admin-cli expected-machine show", fields: ["chassis_serial_number", "bmc_mac_address", "rack_id", "bmc_ip_address", "host_nics[]", "metadata.labels", "linked: interface_id、explored_endpoint_address、machine_id"], requires: ["expected-devices"], note: "带关联的读取一次给出每条声明走到了哪一步：有没有接口、有没有探测结果、有没有设备对象", source: "forge.proto:646" });
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
C("tray.rest", "机柜与 NVLink 域", "REST", "GET /tray、GET /tray/{id}", { cli: "nicocli tray list --site-id <SITE> --rack-id <RACK>", request: "siteId 必填；rackId 或 rackName、type、slotId 可选", fields: ["id", "type（Compute、NVSwitch、PowerShelf）", "position.{slotId,trayIdx,hostId}", "firmwareVersion", "powerState", "operationStatus", "leakStatus", "bmcs", "rackId", "nvLinkDomainId", "taskStats", "health"], requires: ["flow-inventory"], executedBy: "Flow", note: "机柜立面要的槽位在这里；Core 的供电框对象没有位置字段", source: "spec.yaml:14412" });
C("domain.list", "机柜与 NVLink 域", "REST", "GET /domain/nvlink、GET /domain/nvlink/{id}", { cli: "nicocli domain list --site-id <SITE>", request: "siteId 必填；includeComponents 可选", fields: ["id（等于机柜组编号）", "name", "nmxcClusterId", "topology", "operationStatus", "components"], requires: ["nvlink-domain"], executedBy: "Flow", note: "nicocli 的子命令名由接口规范生成，这里的写法没有实际运行核对", source: "spec.yaml:13335" });

/* ================= 接口：设备读取 ================= */
C("machine.list", "设备读取", "Core gRPC", "FindMachineIds → FindMachinesByIds", { cli: "nico-admin-cli machine show [--hosts]", request: "筛选：rack_id、include_dpus、exclude_hosts、only_maintenance、only_quarantine、only_with_health_alert；include_history 带回状态事件", fields: ["id", "rack_id", "placement_in_rack.{slot_number,tray_index}", "state", "state_reason.{outcome,outcome_msg}", "state_sla.time_in_state_above_sla", "status.health.alerts[]", "bmc.{ip,mac}", "status.bmc_status.firmware_version", "status.discovery_info.dmi_data.chassis_serial", "status.associated_dpu_machine_ids", "config.maintenance_reference", "status.quarantine", "status.nvlink_info.domain_uuid", "status.lldp_neighbors[]", "inventory.components[]"], requires: ["machine"], note: "没有电源状态和实例字段，这两项另读。一次按编号读取的数量有上限", source: "forge.proto:5137" });
C("host.states", "设备读取", "Core gRPC", "FindHostStatesByIds", { request: "host_ids", fields: ["state", "state_reason", "rack_id", "nvlink_domain_id", "bmc_ip", "dpu_ids", "health_alerts", "quarantine", "allocation.{allocatable,blocking_reason,blocking_detail}", "explored.{bmc_version,uefi_version}"], requires: ["machine"], note: "一次给出“能不能分配，被什么挡住”。只允许管理端证书调用；命令行没有对应命令", source: "forge.proto:13734" });
C("dpu.list", "设备读取", "Core gRPC", "FindMachineIds（include_dpus、exclude_hosts）→ FindMachinesByIds", { cli: "nico-admin-cli dpu status；nico-admin-cli dpu versions", fields: ["id", "state", "status.associated_host_machine_id", "status.discovery_info.dpu_info.firmware_version", "status.bmc_status.firmware_version", "status.dpu_agent_version", "status.health"], requires: ["dpu"], note: "DPU 的工作模式不在这里：策略在设备声明的 dpu_mode，实测值在探测到的网卡设备上", source: "forge.proto:5021" });
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
C("domain.power", "机柜级任务", "REST", "PATCH /domain/nvlink/{id}/power", { write: true, request: "siteId、state 必填；ruleId、overrideReadinessCheck 可选", fields: ["taskIds[]"], requires: ["nvlink-domain", "operation-rule"], executedBy: "Flow → Core → 硬件后端", note: "按域展开成每个机柜一个任务", source: "spec.yaml:15956" });
C("domain.firmware", "机柜级任务", "REST", "PATCH /domain/nvlink/{id}/firmware", { write: true, request: "siteId 必填；version 省略表示用机柜固件清单；ruleId、overrideVersionCheck、overrideReadinessCheck 可选", fields: ["taskIds[]"], requires: ["nvlink-domain", "firmware-object", "operation-rule"], executedBy: "Flow → Core → 硬件后端", source: "spec.yaml:16014" });
C("task-run", "机柜级任务", "REST", "POST /task/run、GET /task/run、GET /task/run/{id}/target、POST /task/run/{id}/pause|resume|advance|cancel", { write: true, request: "siteId、name、options.maxConcurrentTargets、operation.firmware.version 必填；selector.percentage、options.phasePolicy、options.safetyPolicy 可选", fields: ["id", "status", "statusReason", "totalPhases", "targets[].{rackId,phaseIndex,taskId,status}"], requires: ["flow-inventory", "firmware-object"], executedBy: "Flow", note: "分阶段发布只支持固件。目标是“所有符合条件的机柜”，上限 100 个，不能传入机柜列表", source: "spec.yaml:15201" });
C("task.list", "机柜级任务", "REST", "GET /task、GET /rack/{id}/task、GET /tray/{id}/task、GET /task/{id}", { cli: "nicocli rack task get --site-id <SITE> <RACK_ID>", request: "siteId 必填；activeOnly、includeReport、分页可选", fields: ["id", "status（Pending、Running、Succeeded、Failed、Terminated）", "description", "message", "ruleId", "started", "finished", "report"], requires: ["flow-task"], executedBy: "Flow", note: "任务里没有操作者和原因，这两项由平台的审计记录", source: "spec.yaml:14768" });
C("task.cancel", "机柜级任务", "REST", "POST /task/{id}/cancel", { write: true, cli: "nicocli task cancel --site-id <SITE> <TASK_ID>", request: "siteId 必填", fields: ["status"], requires: ["flow-task"], executedBy: "Flow", note: "已经成功或失败的任务返回 412；已终止的任务重复取消不报错", source: "spec.yaml:14913" });
C("rack.maintenance", "机柜级任务", "Core gRPC", "OnDemandRackMaintenance / TerminateRackMaintenance", { write: true, cli: "nico-admin-cli rack maintenance start --rack <ID> --activities <firmware-upgrade,nvos-update,power-sequence,configure-nmx-cluster>；nico-admin-cli rack maintenance terminate --rack <ID>", request: "rack_id 必填；scope 可选（设备范围和活动）", requires: ["rack", "rms"], executedBy: "机柜状态机 → RMS", note: "机柜要在 Ready 或 Error。NVOS 更新和 NMX-C 集群配置只有这条路径提供，REST 和 Flow 都没有", source: "forge.proto:977" });

/* ================= 接口：交付与实例 ================= */
C("os.list", "交付与实例", "Core gRPC", "FindOperatingSystemIds → FindOperatingSystemsByIds", { cli: "nico-admin-cli operating-system show", fields: ["id", "name", "type", "status", "is_active", "ipxe_template_id", "ipxe_template_parameters", "ipxe_template_artifacts[].{name,url,cached_url}"], requires: ["os-definition"], source: "forge.proto:1380" });
C("os.write", "交付与实例", "Core gRPC", "CreateOperatingSystem / UpdateOperatingSystem / DeleteOperatingSystem", { write: true, cli: "nico-admin-cli operating-system create；nico-admin-cli operating-system set-cached-url", request: "name 必填；ipxe_script，或 ipxe_template_id 加参数和制品，二选一；is_active、user_data 可选", requires: ["core"], note: "删除时 Core 不检查是否还有实例在引用，平台要自己检查", source: "crates/api-core/src/handlers/operating_system.rs:196" });
C("instance.allocate", "交付与实例", "Core gRPC", "AllocateInstances / AllocateInstance", { write: true, cli: "nico-admin-cli instance allocate --machine-id <ID>... --transactional --os <OS_ID> [--flat-vpc-id|--vpc-prefix-id]", request: "每个实例：machine_id、config 必填（config.tenant、config.os、config.network）；instance_type_id、metadata、allow_unhealthy_machine 可选", fields: ["instances[].{id,machine_id,status}"], requires: ["machine", "os-definition", "vpc"], note: "批量接口在一个事务里，全部成功或全部失败。不满足条件时的错误带有 nico-error-code、nico-error-text、nico-error-mitigation 三个附加信息", source: "crates/api-core/src/instance/mod.rs:2009" });
C("instance.list", "交付与实例", "Core gRPC", "FindInstanceIds → FindInstancesByIds / FindInstanceByMachineID", { cli: "nico-admin-cli instance show", fields: ["id", "machine_id", "config.tenant.{tenant_organization_id,hostname}", "config.os", "status.tenant.state", "status.network", "metadata"], requires: ["instance"], note: "状态：PROVISIONING、READY、CONFIGURING、UPDATING、TERMINATING、TERMINATED、FAILED、REPAIRING", source: "forge.proto:230" });
C("instance.release", "交付与实例", "Core gRPC", "ReleaseInstance / ReleaseInstances", { write: true, cli: "nico-admin-cli instance release --instance <ID>", request: "id 必填", fields: ["results[].{id,status,error}"], requires: ["instance"], note: "重复调用不报错。主机健康带“阻止删除实例”时拒绝。回收是异步的：读回看实例消失，以及主机状态回到 Ready 且可分配", source: "crates/api-core/src/handlers/instance.rs:822" });
C("instance-type.write", "交付与实例", "Core gRPC", "CreateInstanceType / AssociateMachinesWithInstanceType / CreateComputeAllocation", { write: true, cli: "nico-admin-cli instance-type create；nico-admin-cli instance-type associate；nico-admin-cli compute-allocation create", request: "实例类型：名称和能力；关联：instance_type_id、machine_ids；配额：tenant_organization_id、instance_type_id、count", requires: ["machine", "vpc"], note: "REST 一侧的等价流程是：邀请租户、建实例类型并关联设备、建配额，之后由租户自己建实例", source: "forge.proto:761" });

/* ================= 接口：健康 ================= */
C("health.reports", "健康", "Core gRPC", "ListMachineHealthReports / ListSwitchHealthReports / ListPowerShelfHealthReports / ListRackHealthReports / ListNVLinkDomainHealthReports", { cli: "nico-admin-cli machine health-report show <ID>；nico-admin-cli nvl-domain health-report show", request: "设备、机柜或域的 ID", fields: ["health_report_entries[].mode", "report.source", "report.alerts[].{id,target,in_alert_since,message,classifications[]}"], requires: ["health-report"], note: "一条告警是否阻止分配，看 classifications 里有没有 PreventAllocations。泄漏告警的编号：BmsLeakDetectRack、BmsLeakSensorFaultRack、BmcLeakDetection", source: "forge.proto:238" });
C("health.history", "健康", "Core gRPC", "FindMachineHealthHistories / FindSwitchHealthHistories / FindPowerShelfHealthHistories / FindRackHealthHistories", { cli: "nico-admin-cli machine health-history <ID>；nico-admin-cli rack health-history <RACK_ID>", request: "ids 必填；start_time、end_time 可选", fields: ["histories[id].records[].{health,time}"], requires: ["health-report"], source: "forge.proto:330" });

/* 现有产品已经调用过的接口（主线分支的 Core 客户端里有同名调用）。其余是整机柜方向新增的。 */
["core.version", "rms.status", "credential.readiness", "credential.write", "explorer.last-run", "segment.list", "segment.create", "segment.delete", "segment.dhcp-range", "segment.dhcp-range.write", "interface.list", "interface.addresses",
  "expected-rack.list", "expected-machine.list", "expected-machine.write", "expected-switch.list", "expected-shelf.list", "explorer.endpoints", "ingestion.state", "ingestion.allow",
  "rack.list", "rack.history", "machine.list", "switch.list", "shelf.list", "device.history", "device.inventory", "device.power-state", "machine.validation",
  "device.power-direct", "shelf.power", "machine.maintenance", "machine.quarantine", "machine.validate", "machine.sku", "device.bmc-reset", "device.decommission", "rack.maintenance",
  "os.list", "os.write", "instance.allocate", "instance.list", "instance.release"].forEach((id) => { const c = NICO_CALLS.find((x) => x.id === id); if (c) c.used = true; });

/* ================= 缺口 =================
   分三类：NICo 没有的（要由平台补或者改设计）、两条路径要选一条的、源码里对不上要实测的。 */
G("到货清单里的槽位写入 NICo 的期望清单", ["设备清单"], "Core 的设备声明没有槽位字段。REST 的设备声明有 slotId、trayIdx、hostId，存在 REST 自己的数据库里，并以 slot_id、tray_idx、host_id 三个标签写进 Core 的 metadata。实际位置来自 RMS 或 BMC 的探测报告，不来自声明", "走 Core 时把槽位写成同样的三个 metadata 标签，与 REST 保持一致；或者设备声明改走 REST", "rest-api/db/pkg/db/model/common.go:100");
G("对账里的“序列号不符”", ["机柜详情", "设备发现"], "REST 的期望与实际校验按 BMC MAC 比对存在性，只对计算托盘比对槽位、托盘号和主机号，不比对序列号。Core 的站点发现会比对序列号，但结果只是一个计数指标，以及设备对象建好之后的一条 SerialNumberMismatch 告警，不拦截接管", "由平台判断：对比设备声明的序列号和探测结果里的序列号。设备对象建好后再用 SerialNumberMismatch 告警交叉核对", "crates/site-explorer/src/lib.rs:1046");
G("对账里的“未声明的设备”", ["设备发现", "机柜详情"], "没有一个接口能列全。GetAllUnexpectedMachines 只含探测成功的主机 BMC；探测失败的、交换机和供电框都不在里面。未声明的主机 BMC 因为没有凭据，通常就是探测失败", "用设备接口列表里没有归属的记录，加上探测结果，由平台与声明对比得出", "crates/api-db/src/expected_machine.rs:292");
G("“没有收到 DHCP 请求”按子网定位", ["网络规划", "设备发现"], "NICo 不记录每个子网或每个中继最近一次收到请求的时间和次数。DHCP 的指标只按报文类型和丢弃原因分；接口上只有该设备最近一次请求的时间", "DHCP 服务页的“最近请求”改成从设备接口的 last_dhcp 按子网汇总得出：只能反映拿到过地址的设备。完全没有请求到达的情况，页面只能提示去看中继配置和 DHCP 的丢弃计数", "crates/dhcp-server/src/metrics.rs:496");
G("引导服务地址和时间服务器的展示", ["网络规划"], "域名服务器、时间服务器、引导服务器地址在 DHCP 服务的部署参数里，没有接口可读；运行配置里只有 DHCP 服务器地址", "从平台自己保存的部署配置读，并标明来源是部署配置而不是 NICo 的回报", "helm/charts/nico-dhcp/values.yaml:199");
G("固件基线", ["固件基线", "机柜详情", "NVLink 域管理", "设备管理"], "NICo 里没有可命名的固件基线对象。期望版本有两处：每个机柜规格的固件清单地址，和按厂商型号配置的主机期望版本。固件操作要么不带版本（用机柜规格的清单），要么带一整份清单文本", "固件基线做成平台自己的档案：一条基线对应一份清单文件。操作时把清单内容作为 version 传入，或者只允许选择与机柜规格配置一致的那一份。“低于基线”由平台对比探测到的版本和清单得出", "docs/configuration/rms.md:183");
G("站点概况里的硬件后端和设施接入状态", ["站点设置"], "当前生效的组件管理器后端没有读取接口；设施事件消费者是否连上也没有接口，只有它自己的指标。NMX-C 没有状态接口", "RMS 用版本接口判断；NMX-C 从机柜健康报告里的 NmxcUnreachable 判断；设施接入读消费者的指标，读不到就显示未知，不显示正常", "crates/api-core/src/cfg/README.md:140");
G("任务里的操作者和原因", ["运维任务", "操作审计"], "Flow 的任务只有描述、规则和阶段报告，没有操作者和原因字段。REST 有自己的审计接口，记录的是调用它的账号", "操作者和原因由平台审计保存，用任务编号关联；提交时把原因写进任务的 description", "rest-api/openapi/spec.yaml:28731");
G("单台设备电源走任务还是直接执行", ["设备管理"], "两条路径都能用：REST 的托盘电源提交为 Flow 任务，可取消、有阶段；Core 的设备电源接口立即执行。供电框在 Core 里另有一个走状态机的专用接口。现有产品用的是 Core 的直接接口", "设计稿目前写的是走任务。建议保持：有 Flow 时走任务，电源动作因此受“同一机柜只有一个任务”的约束；Flow 不可用时这些操作不可用，不悄悄改走直接接口", "crates/api-core/src/handlers/component_manager.rs:3244");
G("设备声明和机柜读取走 Core 还是走 REST", ["设备清单", "机柜管理", "机柜详情"], "REST 和 Core 是两套存储，靠工作流和定时任务同步；REST 的资源编号是它自己的 UUID。机柜的状态机状态只在 Core，任务计数、槽位和对账只在 REST", "写入只走 Core。读取分工：状态、健康、历史读 Core；槽位、对账、任务读 REST。两边用机柜 ID 和 BMC MAC 关联，页面上不显示 REST 的编号", "rest-api/api/pkg/api/handler/expectedrack.go:161");
G("机柜上线由谁推进", ["机柜详情"], "有两套机制：Core 的机柜状态机在交换机就绪后自动进入 Maintenance，依次做固件、NVOS、上电顺序和 NMX-C 配置；Flow 的上线任务按规则做上电、固件和核对。两者的阶段不同，也没有找到它们之间的协调：Flow 上线里的计算托盘固件走状态机路径时，要求机柜已经在 Ready 或 Error", "先在模拟环境里把两条路径各跑一遍，确定“开始上线”按钮对应哪一个、阶段条显示哪一套阶段，再定稿。在此之前，机柜详情的阶段只作示意", "docs/architecture/state_machines/rackstatemachine.md:142");
G("更换设备后机柜重新发现", ["机柜详情"], "文档说更换托盘会让机柜因 topology_changed 回到 Discovering，但源码里没有找到设置这个标志的非测试代码。更换的实际步骤是：打上待更换标记并等 NVLink 隔离完成、强制删除旧设备、改设备声明、等新设备被发现", "更换设备做成平台编排的分步流程，每步读回；机柜状态是否变化以实测为准，页面不预先承诺", "crates/rack-controller/src/ready.rs:50");
G("机柜退役", ["机柜详情"], "DeleteRack 只把机柜标记为删除，状态机进入 Deleting 后一直等待；真正删除只有强制删除，而且不处理成员设备。Flow 有退役任务，但只在 Flow 自己的接口上，REST 没有端点", "退役拆成明确的几步由平台编排：确认无实例、成员设备逐个退役并强制删除、删除设备声明和机柜声明、最后强制删除机柜；或者本阶段不提供机柜退役", "crates/api-core/src/handlers/rack.rs:201");
G("NVLink 域的分阶段发布", ["NVLink 域管理"], "分阶段发布的目标是站点内所有符合条件的机柜，按百分比抽取，不能限定为某个域，也不能传入机柜列表", "域级固件用域的固件接口一次提交；分阶段发布作为站点级功能单独呈现，不挂在某个域下面", "docs/operations/flow/operation-runs.md:123");
G("交付条件里的“机柜就绪”和“NVLink 域健康”", ["机柜交付"], "NICo 分配实例时只看主机自己：状态、维护标记和阻止分配的告警。机柜的健康报告会并入主机，所以泄漏会挡住整柜；但机柜状态不是 Ready、域的健康报告有告警，都不会让分配失败", "这两个条件由平台在交付前检查并拦截，页面上标明是平台的规则。“可交付的托盘数”用主机状态接口里的 allocatable 得出，与 NICo 的判断保持一致", "crates/api-model/src/machine/mod.rs:543");
G("交付用的租户和 VPC 由谁创建", ["机柜交付"], "Core 的创建租户和创建 VPC 接口只对站点代理放行，管理端证书调不了。现有产品只读取已有的 VPC", "租户和 VPC 作为部署前提，由 REST 一侧或部署步骤建好；平台只读取并在交付时选择。计算托盘的 DPU 模式决定 VPC 类型，交付向导里要按它筛选", "crates/api-core/src/auth/internal_rbac_rules.rs:75");
G("按机柜整柜交付", ["机柜交付"], "REST 的批量建实例按实例类型和数量挑设备，优先同一个 NVLink 域，不能指定机柜或设备列表。Core 的批量接口可以传入明确的设备列表，并且是一个事务", "按机柜交付走 Core：按机柜 ID 筛出主机，读可分配状态，再一次提交。“交给上层平台”则是建实例类型、关联设备和配额，不建实例", "crates/api-core/src/instance/mod.rs:2009");
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
    ["rack-profile.list", "核对机柜规格是否受支持"],
    ["segment.list", "核对固定地址落在已有子网内"],
    ["rack-group.list", "读取机柜组"],
    ["rack-group.write", "写入机柜组"],
    ["expected-rack.list", "读取机柜声明和推导出的规格"],
    ["expected-rack.write", "写入机柜声明"],
    ["expected-machine.list", "读取计算托盘声明"],
    ["expected-machine.write", "写入计算托盘声明"],
    ["expected-switch.list", "读取交换机声明"],
    ["expected-switch.write", "写入交换机声明"],
    ["expected-shelf.list", "读取供电框声明"],
    ["expected-shelf.write", "写入供电框声明"],
    ["expected-domain.write", "写入 NVLink 域声明"],
  ],
  "discovery": [
    ["expected-machine.list", "计算托盘声明走到了哪一步"],
    ["expected-switch.list", "交换机声明走到了哪一步"],
    ["expected-shelf.list", "供电框声明走到了哪一步"],
    ["interface.list", "有没有收到 DHCP 请求"],
    ["explorer.endpoints", "探测结果和失败原因"],
    ["explorer.managed-hosts", "主机与 DPU 的配对"],
    ["explorer.unexpected", "未声明的主机"],
    ["ingestion.state", "是否在等待放行"],
    ["machine.list", "计算托盘的状态机阶段"],
    ["switch.list", "交换机的状态机阶段"],
    ["shelf.list", "供电框的状态机阶段"],
    ["explorer.last-run", "最近一次扫描"],
  ],
  "racks": [
    ["rack.list", "机柜状态与健康"],
    ["expected-rack.list", "机柜规格，以及还没有出现的机柜"],
    ["rack.rest", "托盘计数与任务计数"],
    ["rack.validation", "对账差异数"],
    ["task.list", "当前任务"],
  ],
  "rack": [
    ["rack.list", "状态、原因与健康"],
    ["rack-profile.list", "机柜规格"],
    ["rack.history", "状态历史"],
    ["rack.rest", "任务计数与所属域"],
    ["rack.validation", "对账统计与差异"],
    ["tray.rest", "机柜立面的槽位"],
    ["machine.list", "设备表：计算托盘"],
    ["switch.list", "设备表：交换机"],
    ["shelf.list", "设备表：供电框"],
    ["expected-machine.list", "对账：声明的序列号"],
    ["explorer.endpoints", "对账：实测序列号和探测失败原因"],
    ["explorer.retry", "重新发现、重新探测"],
    ["ingestion.allow", "放行等待中的主机"],
    ["expected-machine.write", "更换设备：更新声明"],
    ["rack.bringup", "开始上线"],
    ["rack.power", "机柜电源"],
    ["rack.firmware", "固件更新"],
    ["firmware.status", "固件阶段的逐台进度"],
    ["task.list", "任务卡与阶段"],
    ["task.cancel", "取消任务"],
    ["rack.maintenance", "NVOS 更新与 NMX-C 配置（见缺口：机柜上线由谁推进）"],
    ["health.reports", "机柜健康与泄漏告警"],
  ],
  "domains": [
    ["domain.list", "域、成员机柜和 NMX-C 集群"],
    ["switch.list", "交换机回报的域编号"],
    ["device.inventory", "域内各设备的固件版本"],
    ["health.reports", "域的健康报告"],
    ["domain.power", "域级电源"],
    ["domain.firmware", "域级固件更新"],
    ["task-run", "分阶段发布"],
    ["task.list", "域级任务的进度"],
  ],
  "devices": [
    ["machine.list", "计算托盘的数量和需要处理的设备"],
    ["switch.list", "交换机的数量和需要处理的设备"],
    ["shelf.list", "供电框的数量和需要处理的设备"],
    ["dpu.list", "DPU 的数量和需要处理的设备"],
    ["device.identify", "按序列号、MAC、地址搜索"],
  ],
  "devices/compute": [
    ["machine.list", "列表、状态、健康和地址"],
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
    ["device.power-direct", "电源的直接执行路径（见缺口）"],
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
  "devices/dpu": [
    ["dpu.list", "DPU 列表、状态和固件"],
    ["machine.list", "所属主机"],
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
  "delivery": [
    ["rack.list", "机柜是否就绪"],
    ["machine.list", "按机柜筛出计算托盘"],
    ["host.states", "可交付的托盘数和不可交付的原因"],
    ["health.reports", "机柜和域的告警"],
    ["instance.list", "已交付的实例数"],
    ["os.list", "可选的安装方案"],
    ["instance.allocate", "装机并验收"],
    ["instance-type.write", "交给上层平台"],
  ],
  "delivery/installs": [
    ["instance.list", "实例状态"],
    ["machine.list", "主机状态"],
  ],
  "delivery/instances": [
    ["instance.list", "实例、租户和系统"],
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
  NICO_CALLS.forEach((c) => { if (!callUsers(c.id).length) out.push(`接口 ${c.id} 没有页面使用`); });
  return out;
}
