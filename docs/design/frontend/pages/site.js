"use strict";
/* 站点设置：平台自身是否可用。合并现有的“站点设置”和“NICo 集群”。子网与 DHCP 在 network.js（网络规划）。 */

const SITE_COMPONENTS = () => [
  ["NICo Core", "库存、状态机、健康、实例", "nico-api", "3 / 3", true, "v2.5"],
  ["NICo REST 与 Flow", "机柜级操作的编排与任务", "nico-rest · flow", "2 / 2", S.flow, "v2.5"],
  ["RMS", "托盘、交换机、供电框的电源与固件", "rms-api-server", S.rms ? "1 / 1" : "0 / 1", S.rms, "1.4"],
  ["NMX-C", "NVLink 域的形成与分区", "nmx-controller", "1 / 1", true, "—"],
  ["Temporal", "工作流引擎", "temporal-frontend", "3 / 3", true, "—"],
  ["PostgreSQL", "状态存储", "nico-postgres", "3 / 3", true, "15"],
  ["DHCP / PXE", "地址分配与网络引导", "nico-dhcp · nico-pxe", "2 / 2", true, "v2.5"],
  ["BMS 泄漏事件", "设施侧泄漏事件接入", "dsx-exchange-consumer", "1 / 1", true, "—"],
];
const siteReady = () => S.rms && S.flow;
/* 组件未就绪时哪些操作不可用。站点概况只回答“能不能用、缺了什么会怎样”，部署细节在控制面页签。 */
const SITE_IMPACT = { "NICo Core": "全部页面无法读取和操作", "NICo REST 与 Flow": "机柜级电源、固件更新和任务不可用", RMS: "设备与机柜的电源、复位和固件操作不可用；NICo 的机柜上线会停在 Error", "NMX-C": "NVLink 域显示为未形成，分区不可用", Temporal: "机柜级任务和装机编排不可用", PostgreSQL: "控制面不可用", "DHCP / PXE": "新设备无法被发现，装机不可用", "BMS 泄漏事件": "只显示设备自带传感器的泄漏" };

/* 自动化流程说明：有些事是系统自己做的，操作人看不到过程。这张表按场景写明系统会自动做什么、需要人做什么。 */
const SITE_FLOWS = [
  ["机柜接电", "现场给机柜接电", "设备的 BMC 申请到地址，出现在“设备发现”里。这时系统不知道它是哪台设备，也不会自己去读", "在设备发现里输入 BMC 用户名和密码获取设备信息，核对后加入纳管设备；再到设备管理里一键匹配，到机柜详情登记机柜"],
  ["新机柜上线", "你提交“开始上线”", "按顺序上电：供电框 → 计算托盘 → 交换机。接管计算托盘：设置 BIOS 和启动顺序、读取硬件、核对硬件。交换机就绪后做机柜维护：固件升级 → NVOS 更新 → 上电顺序 → 配置 NMX-C 集群 → 机柜校验", "等它完成。中途停在 Error 时，先排除原因，再点“重新执行机柜维护”，它不会自己恢复"],
  ["机柜上电", "你提交", "供电框 → 交换机 → 计算托盘，每一步确认电源状态后再做下一步", "不需要"],
  ["机柜下电、重启", "你提交", "先等机柜里的主机可以操作，最多等 30 分钟。下电：计算托盘 → 交换机 → 供电框。重启：全部断电后再按上电顺序上电，供电框也会断电", "机柜上有实例时先释放实例，否则任务会一直等到超时后失败"],
  ["固件更新", "你提交，并选一个固件基线", "先等主机可以操作。然后计算托盘 → 交换机；版本已经相同的设备跳过。刷完不自动重启", "需要重启才生效时，另外提交机柜重启"],
  ["整柜泄漏", "设施侧或设备报告机柜级泄漏", "立刻对整柜全部设备强制下电，不等人确认；之后拒绝上电", "通知设施侧处理。告警清除后设备不会自己开机，要在机柜详情提交上电"],
];
/* 固件什么时候会被更新：只有两种时候，其余时间不会在后台自动刷。 */
const FIRMWARE_WHEN = [
  ["新机柜上线", "机柜规格配了固件清单时，上线过程中按清单更新；没有配清单就跳过，不刷", "不想在上线时刷：不给这个机柜规格配固件清单"],
  ["你提交固件更新", "只更新你选的机柜或设备；版本已经与所选基线相同的跳过", "不提交就不会更新"],
  ["平时", "不会自动更新。设备版本与基线不同只是在页面上标出来", "—"],
];
registerPage("site", {
  module: "site", tab: "站点概况", title: "站点设置",
  render() {
    const comps = SITE_COMPONENTS();
    return heading("站点设置", "查看平台和依赖组件是否可用。某个组件未就绪时，依赖它的操作显示为不可用。", button("刷新数据", "refresh") + button("查看控制面", "noop", false, 'data-go="site/cluster"') + act("编辑站点", "site-edit", { primary: true, admin: true })) +
      `<div ${fp(1)}>${siteReady() ? note("全部依赖为就绪，可以导入清单和操作机柜。") : note(`<b>${[!S.rms && "RMS", !S.flow && "Flow"].filter(Boolean).join("、")} 未就绪。</b>依赖它的机柜级操作不可用；读取、清单核对和单设备的维护标记照常。`, "error")}</div>` +
      `<div ${fp(2)}>${table(["组件", "作用", "未就绪时的影响", "状态"], comps.map((c) => `<tr><td><strong>${c[0]}</strong></td><td>${c[1]}</td><td>${SITE_IMPACT[c[0]]}</td><td>${c[4] ? badge("已就绪", "green") : badge("需处理", "red")}</td></tr>`))}</div>` +
      `<div class="live-grid"><section class="live-card" ${fp(3)}><h2>站点发现</h2>${defs([["站点发现", badge("已启用", "green")], ["自动建机", badge("已启用", "green")], ["接管凭据", badge("已配置", "green")], ["最近扫描", "2026-11-24 08:00 · 完成"]])}</section>
       <section class="live-card" ${fp(4)}><div class="live-heading" style="margin-bottom:10px"><div><h2 style="margin:0">机柜规格</h2></div><div class="live-tools">${act("调整机柜规格", "profile-edit", { admin: true, compact: true })}</div></div>${table(["规格", "计算托盘", "交换机", "供电框", "固件清单"], [[PROFILE, 18, 9, 8, BASELINES[0].id], ["GB300_NVL72R1_C2G4_LENOVO", 18, 9, 6, "未配置"]].map((p) => `<tr><td>${code(p[0])}</td><td>${p[1]}</td><td>${p[2]}</td><td>${p[3]}</td><td>${p[4] === "未配置" ? badge("未配置", "gray") : esc(p[4])}</td></tr>`))}<p class="live-small">每种规格写着这种机柜应有几台设备、用哪份固件清单。交换机的数量是机柜维护开始的最低门槛。DPU 的工作方式：网卡模式。</p></section></div>` +
      `<h2 class="section-title">自动化流程说明</h2><div ${fp(5)}>${table(["场景", "什么时候开始", "系统会自动做什么", "需要你做什么"], SITE_FLOWS.map((r) => `<tr><td><strong>${r[0]}</strong></td><td>${r[1]}</td><td>${r[2]}</td><td>${r[3]}</td></tr>`))}<p class="live-small">这些流程的顺序、等待时间和重试是预先定好的，操作时不用填，也不能在页面上改。</p></div>` +
      `<h2 class="section-title">固件什么时候会被更新</h2><div ${fp(6)}>${table(["时候", "会发生什么", "怎么控制"], FIRMWARE_WHEN.map((r) => `<tr><td><strong>${r[0]}</strong></td><td>${r[1]}</td><td>${r[2]}</td></tr>`))}</div>`;
  },
  spec: {
    purpose: "回答“平台现在能不能用”，并把系统会自动做的事摆出来：哪些场景下系统自己会做什么、需要人做什么、固件什么时候会被更新。",
    entry: "配置 → 站点设置 → 站点概况", design: "6.1 站点；8.3 外部依赖缺失时的行为", existing: "站点设置（概览、站点发现）与 NICo 集群（服务状态）合并而来；网络部分移到“网络规划”",
    points: [
      { n: 1, name: "就绪结论", kind: "新增", desc: "一句话给出能否导入清单和操作机柜。有组件未就绪时写明哪些操作不可用、哪些照常。" },
      { n: 2, name: "依赖组件", kind: "新增", desc: "每个组件的作用、未就绪时哪些操作不可用、当前状态。工作负载、副本和端口不在这里重复，点“查看控制面”查看。" },
      { n: 3, name: "站点发现", kind: "沿用", desc: "沿用站点设置的站点发现、自动建机、接管凭据和最近扫描。" },
      { n: 4, name: "机柜规格", kind: "新增", desc: "每种规格应有几台计算托盘、交换机和供电框，用哪份固件清单。管理角色可以调整。" },
      { n: 5, name: "自动化流程说明", kind: "新增", desc: "按场景写明什么时候开始、系统会自动做什么、需要人做什么：机柜接电、新机柜上线、上电、下电与重启、固件更新、整柜泄漏。只读。" },
      { n: 6, name: "固件什么时候会被更新", kind: "新增", desc: "只有两种时候：新机柜上线（规格配了固件清单时）和人提交固件更新。平时不会自动更新。每种时候写明怎么控制。" },
    ],
    fields: [["未就绪时的影响", "设计约定", "与各页面按钮的禁用原因一致"], ["机柜规格", "NICo 的站点配置", "各类设备的数量和固件清单"], ["自动化流程说明", "NICo 的内置规则与机柜状态机", "站点没有自定义规则时的默认行为"]],
    rules: ["RMS 未就绪：电源与固件操作不可用；正在做机柜维护的机柜会停在 Error。", "Flow 未就绪：上线、机柜级电源、固件更新和任务不可用。", "编辑站点、调整机柜规格需要管理角色。", "调整机柜规格会更新 NICo 的站点配置并滚动重启 NICo，对所有使用这个规格的机柜生效。", "平时不会在后台自动更新固件：设备版本与基线不同只标出来。", "子网、DHCP 和引导服务地址在“网络规划”里维护。"],
    dialogs: [{ name: "编辑站点", desc: "沿用现有弹窗。", fields: [["站点名称", "是", ""], ["Core HTTPS 地址", "是", ""], ["默认安装并发", "是", "安装任务同时装机的台数"]] },
      { name: "调整机柜规格", desc: "改一种规格的设备数量或固件清单。保存后平台更新 NICo 的站点配置并滚动重启 NICo。", fields: [["规格", "是", "从已有规格里选"], ["计算托盘、交换机、供电框的数量", "是", "交换机的数量是机柜维护开始的最低门槛"], ["固件清单", "否", "选一个固件基线；不选表示上线时不更新固件"], ["原因", "是", "写入审计"]] }],
  },
});
registerAction("profile-edit", () => modal("调整机柜规格", "对所有使用这个规格的机柜生效",
  `<div class="live-form">${field("规格", `<select class="input"><option>${PROFILE}</option><option>GB300_NVL72R1_C2G4_LENOVO</option></select>`)}${field("计算托盘", `<input class="input" type="number" value="18">`)}${field("交换机", `<input class="input" type="number" value="9">`, "机柜维护开始的最低门槛：就绪的交换机不少于这个数才开始")}${field("供电框", `<input class="input" type="number" value="8">`)}${field("固件清单", `<select class="input"><option>${BASELINES[0].id}</option><option>${BASELINES[1].id}</option><option>不配置：上线时不更新固件</option></select>`)}${field("原因", `<input class="input" placeholder="工单号或原因">`)}</div>
   ${note("保存后平台更新 NICo 的站点配置并滚动重启 NICo，重启期间页面只读。进行中的任务不受影响。", "warning")}`,
  button("取消", "close") + button("保存并应用", "profile-save", true), { wide: false }));
registerAction("profile-save", () => { addAudit("站点", "调整机柜规格 " + PROFILE, "—", "—", "已应用，NICo 已重启"); closeModal(); toast("机柜规格已更新"); render(); });
registerAction("site-edit", () => modal("编辑站点", "演示站点", `<div class="live-form">${field("站点名称", `<input class="input" value="演示站点">`)}${field("Core HTTPS 地址", `<input class="input live-code" value="https://nico-api.example.internal:1079">`)}${field("默认安装并发", `<input class="input" type="number" value="5">`)}</div>`, button("取消", "close") + button("验证并保存", "close", true), { wide: false }));

registerPage("site/cluster", {
  module: "site", tab: "控制面", title: "控制面",
  render() {
    return heading("控制面", "在当前 Kubernetes 集群部署 NICo 及其依赖，查看服务运行状态。", button("刷新状态", "refresh") + button("站点概况", "noop", false, 'data-go="site"')) +
      `<div ${fp(1)}>${summary([["必需服务", `${SITE_COMPONENTS().filter((c) => c[4]).length}<small>/ ${SITE_COMPONENTS().length}</small>`], ["部署阶段", badge("已连接站点", "green")], ["初始化与存储", badge("已就绪", "green")], ["引导材料", badge("已就绪", "green")]])}</div>` +
      `<div class="live-tabs">${button("服务总览", "noop", true)}${button("部署配置", "cluster-config")}</div>` +
      `<div ${fp(2)}>${table(["服务 / 作用", "工作负载", "就绪副本", "服务端口", "状态"], SITE_COMPONENTS().map((c, i) => `<tr><td><strong>${c[0]}</strong><span class="cell-sub">${c[1]}</span></td><td>${code(c[2])}</td><td>${c[3]}</td><td>${code(["1079", "8388", "8801", "9370", "7233", "5432", "67 / 8080", "—"][i])}</td><td>${c[4] ? badge("已就绪", "green") : badge("需处理", "red")}</td></tr>`))}</div>` +
      `<div ${fp(3)}>${note("部署清单是固定的：NICo、Flow、RMS、Temporal 及基础服务作为一个带版本锁的离线包安装。这里不提供逐项组件参数。")}</div>`;
  },
  spec: {
    purpose: "部署和查看控制面。整机柜方向要求 Flow 和 RMS 与 NICo 一起部署。",
    entry: "配置 → 站点设置 → 控制面", design: "4.3 依赖组件；6.1 站点", existing: "NICo 集群页，指标与服务表不变",
    points: [
      { n: 1, name: "部署指标", kind: "沿用", desc: "必需服务、部署阶段、初始化与存储、引导材料四项，状态用词不变。" },
      { n: 2, name: "服务表", kind: "调整", desc: "在现有服务分组里加入 REST 与工作流（Flow、Temporal）和硬件后端（RMS）。" },
      { n: 3, name: "固定部署清单", kind: "新增", desc: "说明部署内容是带版本锁的固定清单，不逐项填写组件参数。" },
    ],
    rules: ["部署配置页签沿用现有的在线 / 离线部署表单。"],
  },
});
registerAction("cluster-config", () => toast("沿用现有的部署配置表单"));
registerAction("noop", () => {});
