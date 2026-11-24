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

/* 操作规则：什么情况下 NICo 会怎么做。目的是透明：操作时不用填顺序和超时，但要能在这里看到实际会怎样执行。 */
const SITE_RULES = [
  ["新机柜上线", "机柜确认接入、交换机就绪后自动开始", "固件升级 → NVOS 更新 → 上电顺序（需要时）→ 配置 NMX-C 集群 → 机柜校验。任一阶段失败停在 Error，要人重新执行机柜维护"],
  ["机柜上电", "操作人提交", "供电框 → 交换机 → 计算托盘"],
  ["机柜下电", "操作人提交", "先等主机就绪（最多 30 分钟），再计算托盘 → 交换机 → 供电框"],
  ["机柜重启", "操作人提交", "先等主机就绪，再按下电顺序全部断电、按上电顺序全部上电，包括供电框"],
  ["固件更新", "操作人提交", "先等主机就绪，再计算托盘 → 交换机。刷写后不自动重启；供电框不在其中"],
  ["整柜泄漏", "NICo 检测到机柜级泄漏", "自动对整柜全部设备强制下电，并拒绝再次上电；告警清除后不自动开机"],
];
registerPage("site", {
  module: "site", tab: "站点概况", title: "站点设置",
  render() {
    const comps = SITE_COMPONENTS();
    return heading("站点设置", "查看平台和依赖组件是否可用。某个组件未就绪时，依赖它的操作显示为不可用。", button("刷新数据", "refresh") + button("查看控制面", "noop", false, 'data-go="site/cluster"') + act("编辑站点", "site-edit", { primary: true, admin: true })) +
      `<div ${fp(1)}>${siteReady() ? note("全部依赖为就绪，可以导入清单和操作机柜。") : note(`<b>${[!S.rms && "RMS", !S.flow && "Flow"].filter(Boolean).join("、")} 未就绪。</b>依赖它的机柜级操作不可用；读取、清单核对和单设备的维护标记照常。`, "error")}</div>` +
      `<div ${fp(2)}>${table(["组件", "作用", "未就绪时的影响", "状态"], comps.map((c) => `<tr><td><strong>${c[0]}</strong></td><td>${c[1]}</td><td>${SITE_IMPACT[c[0]]}</td><td>${c[4] ? badge("已就绪", "green") : badge("需处理", "red")}</td></tr>`))}</div>` +
      `<div class="live-grid"><section class="live-card" ${fp(3)}><h2>站点发现</h2>${defs([["站点发现", badge("已启用", "green")], ["自动建机", badge("已启用", "green")], ["接管凭据", badge("已配置", "green")], ["最近扫描", "2026-11-24 08:00 · 完成"]])}</section>
       <section class="live-card" ${fp(4)}><h2>机柜规格</h2>${defs([["支持的机柜规格", code("GB200_NVL72R1_C2G4_WIWYNN") + "　" + code("GB300_NVL72R1_C2G4_LENOVO")], ["DPU 的工作方式", "网卡模式"], ["当前固件基线", BASELINES[0].id]])}<p class="live-small">机柜规格是 NICo 的站点配置：每种规格写着应有几台计算托盘、交换机和供电框，以及用哪份固件清单。导入清单时选的机柜拓扑和厂商要能对上其中一个。</p></section></div>` +
      `<h2 class="section-title">操作规则</h2><div ${fp(5)}>${table(["情况", "什么时候发生", "NICo 怎么处理"], SITE_RULES.map((r) => `<tr><td><strong>${r[0]}</strong></td><td>${r[1]}</td><td>${r[2]}</td></tr>`))}<p class="live-small">现在用的是 NICo 内置的默认规则。操作时不填写顺序、等待时间和重试，实际怎么执行以这张表为准；规则在这里只读。</p></div>`;
  },
  spec: {
    purpose: "回答“平台现在能不能用”。把控制面、硬件后端和设施接入的就绪状态放在一页，并说明缺失时哪些操作受影响；同时把 NICo 在各种情况下会怎么做摆出来。",
    entry: "配置 → 站点设置 → 站点概况", design: "6.1 站点；8.3 外部依赖缺失时的行为", existing: "站点设置（概览、站点发现）与 NICo 集群（服务状态）合并而来；网络部分移到“网络规划”",
    points: [
      { n: 1, name: "就绪结论", kind: "新增", desc: "一句话给出能否导入清单和操作机柜。有组件未就绪时写明哪些操作不可用、哪些照常。" },
      { n: 2, name: "依赖组件", kind: "新增", desc: "每个组件的作用、未就绪时哪些操作不可用、当前状态。工作负载、副本和端口不在这里重复，点“查看控制面”查看。" },
      { n: 3, name: "站点发现", kind: "沿用", desc: "沿用站点设置的站点发现、自动建机、接管凭据和最近扫描。" },
      { n: 4, name: "机柜规格", kind: "新增", desc: "NICo 已配置的机柜规格、DPU 的工作方式和当前的固件基线。" },
      { n: 5, name: "操作规则", kind: "新增", desc: "一张表写明六种情况各自什么时候发生、NICo 怎么处理：新机柜上线、上电、下电、重启、固件更新、整柜泄漏。规则只读。" },
    ],
    fields: [["未就绪时的影响", "设计约定", "与各页面按钮的禁用原因一致"], ["支持的机柜规格", "NICo 的站点配置", "规格里有各类设备的数量和固件清单"], ["操作规则", "NICo Flow 的规则与机柜状态机", "站点没有自定义规则时是内置的默认规则"]],
    rules: ["RMS 未就绪：电源与固件操作不可用；正在上线的机柜会停在 Error。", "Flow 未就绪：机柜级电源、固件更新和任务不可用。", "编辑站点需要管理角色。", "子网、DHCP 和引导服务地址在“网络规划”里维护。"],
    dialogs: [{ name: "编辑站点", desc: "沿用现有弹窗。", fields: [["站点名称", "是", ""], ["Core HTTPS 地址", "是", ""], ["默认安装并发", "是", "交付时同时装机的台数"]] }],
  },
});
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
