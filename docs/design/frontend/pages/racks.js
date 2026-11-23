"use strict";
/* 机柜、NVLink 域两个列表页。设备页面在 trays.js，任务在 tasks.js，机柜详情在 rack.js。 */

const reconBadge = (r) => (r.state === "Created" ? badge("等待发现", "gray") : DB.blockers(r).length ? badge(DB.blockers(r).length + " 项阻塞", "red") : r.issues.some((i) => !i.done) ? badge("有差异 · 不阻塞", "amber") : badge("无阻塞项", "green"));
const members = (r) => `计算托盘 ${r.trays.filter((t) => t.type === "compute").length} · 交换机 ${r.trays.filter((t) => t.type === "switch").length} · 供电框 ${r.trays.filter((t) => t.type === "power_shelf").length}`;
const taskStatus = (t) => badge(t.status, t.status === "已完成" ? "green" : t.status === "已终止" ? "red" : "amber");
const taskStage = (t) => { const cur = t.stages.find((s) => s.s === "run" || s.s === "fail"); return cur ? cur.n : t.status === "已完成" ? "完成" : "等待执行"; };

registerPage("racks", {
  module: "racks", title: "机柜管理",
  render() {
    const trays = DB.trays();
    return heading("机柜管理", "查看 NICo 机柜对象的状态、健康和成员设备，并发起上线、电源和固件操作。", button("刷新数据", "refresh")) +
      `<div ${fp(1)}>${summary([["机柜", S.racks.length], ["就绪", S.racks.filter((r) => r.state === "Ready").length], ["需要处理", S.racks.filter(rackNeedsAttention).length], ["设备就绪", `${trays.filter((t) => /Ready$/.test(t.state)).length}<small>/ ${trays.length}</small>`], ["进行中的任务", S.racks.filter(DB.busy).length]])}</div>` +
      `<div ${fp(2)}>${table(["机柜", "NICo 状态", "健康", "机柜规格", "成员设备", "对账", "实例", "当前任务", "操作"], S.racks.map((r) =>
        `<tr class="row-link" data-go="rack/${r.id}"><td><strong>${r.id}</strong><span class="cell-sub">${esc(r.location)}</span></td><td ${fp(3)}>${stateBadge(r.state)}<span class="cell-sub">自 ${r.stateSince}</span></td><td>${healthBadge(rackHealth(r))}</td><td>${code(r.profile)}<span class="cell-sub">NVLink 域 ${r.domain}</span></td><td>${members(r)}<span class="cell-sub">就绪 ${r.trays.filter((t) => /Ready$/.test(t.state)).length} / 35</span></td><td ${fp(4)}>${reconBadge(r)}</td><td>${DB.rackInstances(r.id).length}</td><td ${fp(5)}>${DB.busy(r) ? badge(r.task.label + " · " + taskStage(r.task), "blue") : "—"}</td><td>${button("详情", "noop", false, `data-go="rack/${r.id}"`)}</td></tr>`))}</div>` +
      note("新机柜不在这里创建。在“设备清单”导入到货清单后，NICo 发现带相同机柜 ID 的设备时会建立机柜对象。");
  },
  spec: {
    calls: [["rack.list", "机柜状态与健康"], ["expected-rack.list", "机柜规格，以及还没有出现的机柜"], ["rack.rest", "托盘计数与任务计数"], ["rack.validation", "对账差异数"], ["task.list", "当前任务"]],
    purpose: "机柜是默认的操作单位。本页回答每个机柜处在流程的哪一步、有没有需要处理的问题。",
    entry: "运维 → 机柜管理（默认首页）", design: "5 整体操作运维流程；6.3 机柜与设备", existing: "设备管理 → 机柜（列与状态用词沿用）；机柜拓扑的统计条并入",
    points: [
      { n: 1, name: "统计条", kind: "调整", desc: "机柜数、就绪数、需要处理、设备就绪、进行中的任务。取代机柜拓扑页的设备数量统计。" },
      { n: 2, name: "机柜表", kind: "沿用", desc: "机柜、NICo 状态、健康、机柜规格、成员设备沿用现有机柜页；点击整行进入机柜详情。" },
      { n: 3, name: "NICo 状态", kind: "沿用", desc: "显示状态机的状态原文和进入时间，不翻译、不另起状态名。" },
      { n: 4, name: "对账", kind: "新增", desc: "等待发现、N 项阻塞、有差异不阻塞、无阻塞项。阻塞项清零前不能上线。" },
      { n: 5, name: "当前任务", kind: "新增", desc: "显示正在执行的 Flow 任务及其阶段。同一机柜同时只有一个任务。" },
    ],
    fields: [["NICo 状态", "NICo Core", "Created、Discovering、Maintenance、Validating、Ready、Error、Deleting"], ["机柜规格 / NVLink 域", "NICo Core", "规格由清单推导；NVLink 域对应 NICo 的机柜组"], ["成员设备", "期望清单 + NICo", "三类设备的数量与就绪数"], ["实例", "NICo Core", "机柜上已交付的实例数"]],
    rules: ["“需要处理”只用 NICo 的信号：对账阻塞、状态为 Error、有阻止分配的告警。", "没有期望清单的机柜不出现。"],
  },
});

registerPage("domains", {
  module: "domains", title: "NVLink 域管理",
  render() {
    const rows = S.domains.map((d) => {
      const racks = d.racks.map(DB.rack), bases = [...new Set(racks.map((r) => r.baseline).filter(Boolean))], ready = racks.every((r) => r.state === "Ready");
      const gate = racks.map((r) => rackGate(r, "firmware")).find(Boolean) || "";
      return `<tr><td><strong>${d.id}</strong><span class="cell-sub live-code">${d.topology}</span></td><td>${d.racks.map((r) => `<a class="link-button" data-go="rack/${r}">${r}</a>`).join("　")}</td><td>${ready ? badge("已形成", "green") : badge("未报告", "gray")}</td><td>${ready ? healthBadge(racks.some((r) => rackHealth(r) === "bad") ? "bad" : racks.some((r) => rackHealth(r) === "warn") ? "warn" : "ok") : healthBadge("none")}</td>
        <td ${fp(2)}>${bases.length > 1 ? badge("不一致", "red") + `<span class="cell-sub">${bases.join(" / ")}</span>` : bases.length ? badge("一致", "green") + `<span class="cell-sub">${bases[0]}</span>` : "—"}</td><td>${racks.reduce((n, r) => n + DB.rackInstances(r.id).length, 0)}</td>
        <td><div class="inline-actions" ${fp(3)}>${act("域级固件更新", "domain-firmware", { gate, extra: `data-id="${d.id}"`, compact: true })}${act("域级电源", "domain-power", { gate: racks.map((r) => rackGate(r, "power")).find(Boolean) || "", extra: `data-id="${d.id}"`, compact: true })}</div></td></tr>`;
    });
    return heading("NVLink 域管理", "按 NVLink 域查看机柜、域健康和固件一致性，并发起域级操作。", button("刷新数据", "refresh")) +
      `<div ${fp(1)}>${table(["NVLink 域 / 拓扑", "机柜", "域状态", "健康", "固件基线", "实例", "操作"], rows)}</div>` +
      `<h2 class="section-title">分阶段发布记录</h2><div ${fp(4)}>${table(["发布", "NVLink 域", "固件基线", "批次", "状态", "操作者 / 时间"], S.rollouts.map((ro) => `<tr><td>${code(ro.id)}</td><td>${ro.domain}</td><td>${ro.baseline}</td><td>${ro.phases.map((p, i) => `第 ${i + 1} 批 ${p.rack} ${badge(p.status, p.status === "已完成" ? "green" : p.status === "执行中" ? "amber" : "gray")}`).join("　")}</td><td>${taskStatus(ro)}</td><td>${ro.by}<span class="cell-sub">${ro.at}</span></td></tr>`), "还没有分阶段发布。")}</div>` +
      note("同一个 NVLink 域内的固件版本不一致会影响域的形成。固件更新的推荐单位是域；域级更新按机柜分批，每批并发一个机柜，失败后停止后续批次。");
  },
  spec: {
    calls: [["domain.list", "域、成员机柜和 NMX-C 集群"], ["switch.list", "交换机回报的域编号"], ["device.inventory", "域内各设备的固件版本"], ["health.reports", "域的健康报告"], ["domain.power", "域级电源"], ["domain.firmware", "域级固件更新"], ["task-run", "分阶段发布"], ["task.list", "域级任务的进度"]],
    purpose: "NVLink 域是固件一致性和交付门控的单位。本页用来发现域内版本不一致，并以域为单位发起更新。",
    entry: "运维 → NVLink 域管理", design: "6.3 机柜与设备；10 非功能设计（固件一致性、分阶段发布）", existing: "新增页面。现有交换机详情里的“NVLink 域”字段是它的来源",
    points: [
      { n: 1, name: "域列表", kind: "新增", desc: "域、拓扑、成员机柜、域状态、健康和实例数。机柜可点击进入详情。" },
      { n: 2, name: "固件基线一致性", kind: "新增", desc: "域内各机柜的固件基线是否一致。不一致时列出各基线。" },
      { n: 3, name: "域级操作", kind: "新增", desc: "域级固件更新和域级电源。域内任一机柜不满足门控时不可用，并说明原因。" },
      { n: 4, name: "分阶段发布记录", kind: "新增", desc: "每次域级固件更新的批次和状态。对应 Flow 的分阶段发布。" },
    ],
    fields: [["域状态", "NICo + NMX-C", "已形成 / 未报告"], ["固件基线", "各机柜实际基线的汇总", "一致 / 不一致"], ["批次", "Flow 分阶段发布", "每批一个机柜，前一批成功后才开始下一批"]],
    rules: ["域级固件更新是高风险操作，要输入域 ID 确认，并显示域内全部实例数。", "任一批失败后停止后续批次，已完成的机柜不回滚。"],
    dialogs: [{ name: "域级固件更新", desc: "确认页显示对象、动作、受影响实例数和批次。", fields: [["固件基线", "是", "只能选择基线"], ["原因", "是", ""], ["输入域 ID", "是", "高风险确认"]] }, { name: "域级电源", desc: "选择下电或上电，按机柜逐个提交任务；前一个机柜完成后才开始下一个。", fields: [["动作", "是", "下电 / 上电；域内有机柜未上电时默认上电"], ["原因", "是", ""], ["输入域 ID", "下电时", "高风险确认"]] }],
  },
});
