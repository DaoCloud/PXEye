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

/* 站点准备：设备到货之前要配好的东西。它们都是 Core 的运行配置，平台只读出来核对，不在页面上改。 */
const SITE_PREP = () => [
  ["BlueField 的工作方式", "网卡模式", true, "这一版只支持网卡模式", "按 DPU 模式部署的站点，主机的地址来源、发现过程和交付网络都不一样，本平台的流程不适用"],
  ["交换机 NVOS 凭据入库", "已开启", true, "必须开启", "机柜上线走到“配置 NMX-C 集群”时找不到 NVOS 凭据，停在 Error"],
  ["机柜规格", PROFILE, true, "清单里用到的规格都已配置", "导入清单时报错"],
  ["固件清单", BASELINES[0].id, true, "要升级固件的机柜规格都有清单", "上线的“固件升级”和“NVOS 更新”直接通过，不做任何事，也没有提示"],
  ["DNS 子域", "3 个", true, "每个子网都要有子域", "子网发不出地址"],
  ["NVLink 分区", "已启用", true, "需要按租户划分 NVLink 时开启", "NVLink 域管理里没有分区"],
  ["机柜校验", "未开启", null, "可选", "上线的“机柜校验”直接通过"],
];
registerPage("site", {
  module: "site", tab: "站点概况", title: "站点设置",
  render() {
    const comps = SITE_COMPONENTS(), prep = SITE_PREP();
    return heading("站点设置", "查看平台和依赖组件是否可用，以及设备到货前站点要配好的各项是否齐备。", button("刷新数据", "refresh") + button("查看控制面", "noop", false, 'data-go="site/cluster"') + act("编辑站点", "site-edit", { primary: true, admin: true })) +
      `<div ${fp(1)}>${siteReady() ? note("全部依赖为就绪，可以导入清单和操作机柜。") : note(`<b>${[!S.rms && "RMS", !S.flow && "Flow"].filter(Boolean).join("、")} 未就绪。</b>依赖它的机柜级操作不可用；读取、清单核对和单设备的维护标记照常。`, "error")}</div>` +
      `<div ${fp(2)}>${table(["组件", "作用", "未就绪时的影响", "状态"], comps.map((c) => `<tr><td><strong>${c[0]}</strong></td><td>${c[1]}</td><td>${SITE_IMPACT[c[0]]}</td><td>${c[4] ? badge("已就绪", "green") : badge("需处理", "red")}</td></tr>`))}</div>` +
      `<h2 class="section-title">站点准备</h2><div ${fp(3)}>${table(["项目", "当前", "要求", "不满足时会怎样", "结果"], prep.map((c) => `<tr><td><strong>${c[0]}</strong></td><td>${code(c[1])}</td><td>${c[3]}</td><td>${c[4]}</td><td>${c[2] === null ? badge("可选", "gray") : c[2] ? badge("满足", "green") : badge("不满足", "red")}</td></tr>`))}<p class="live-small">这些都是 NICo 的站点配置，在部署时确定。平台读出来核对，不在这里修改。</p></div>` +
      `<div class="live-grid"><section class="live-card" ${fp(4)}><h2>站点发现</h2>${defs([["站点发现", badge("已启用", "green") + ` <span class="live-small">平台最近一次设置的值</span>`], ["自动建机", badge("已启用", "green") + ` <span class="live-small">平台最近一次设置的值</span>`], ["接管后的站点凭据", badge("已配置", "green")], ["最近扫描", "2026-11-24 08:00 · 完成"]])}</section>
       <section class="live-card" ${fp(5)}><h2>操作规则</h2>${defs([["电源：上电、下电、重启", "NICo 内置的默认规则"], ["固件更新", "NICo 内置的默认规则"], ["泄漏处理", "NICo 内置：整柜泄漏时强制下电整柜"]])}<p class="live-small">站点没有自定义规则时使用内置的默认规则。电源和固件任务的步骤、顺序和等待时间由规则决定，操作时不填写。</p></section></div>`;
  },
  spec: {
    purpose: "回答两件事：平台现在能不能用；设备到货之前，站点要配好的东西齐不齐。",
    entry: "配置 → 站点设置 → 站点概况", design: "6.1 站点；8.3 外部依赖缺失时的行为", existing: "站点设置（概览、站点发现）与 NICo 集群（服务状态）合并而来；网络部分移到“网络规划”",
    points: [
      { n: 1, name: "就绪结论", kind: "新增", desc: "一句话给出能否导入清单和操作机柜。有组件未就绪时写明哪些操作不可用、哪些照常。" },
      { n: 2, name: "依赖组件", kind: "新增", desc: "每个组件的作用、未就绪时哪些操作不可用、当前状态。工作负载、副本和端口不在这里重复，点“查看控制面”查看。" },
      { n: 3, name: "站点准备", kind: "新增", desc: "设备到货前要配好的各项：BlueField 的工作方式、交换机 NVOS 凭据入库、机柜规格、固件清单、DNS 子域、NVLink 分区、机柜校验。逐项给出当前值、要求和不满足时的后果。" },
      { n: 4, name: "站点发现", kind: "调整", desc: "沿用站点设置的站点发现、自动建机和最近扫描。两个开关显示的是平台最近一次设置的值。" },
      { n: 5, name: "操作规则", kind: "新增", desc: "电源、固件和泄漏处理当前用的是哪套规则。规则在这里只读。" },
    ],
    fields: [["未就绪时的影响", "设计约定", "与各页面按钮的禁用原因一致"], ["站点准备的各项", "NICo Core 的运行配置", "只读"], ["站点发现 / 自动建机", "平台", "NICo 只提供设置这两个开关的接口，没有读取的接口，所以显示平台最近一次设置的值"], ["依赖组件的状态", "NICo 的状态接口与所在集群", "NICo 不报告的组件（工作流引擎、数据库、DHCP 与引导服务）从集群读取"], ["操作规则", "NICo Flow", "站点自定义的规则，或内置的默认规则"]],
    rules: ["RMS 未就绪：电源与固件操作不可用；NICo 的机柜上线会停在 Error。", "Flow 未就绪：机柜级电源、固件更新和任务不可用。", "站点准备里有“不满足”的项目时，页面顶部给出提示；BlueField 不是网卡模式时不能导入清单。", "编辑站点需要管理角色。", "子网、DHCP 和引导服务地址在“网络规划”里维护。"],
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
