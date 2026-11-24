"use strict";
/* 机柜详情：NICo 上线进度、清单核对、设备（立面）、任务、健康与历史。由机柜列表、清单、健康等页面进入。 */

/* 清单核对：清单里有、但还没有设备读出这个序列号的行。只是提示，NICo 的上线不看它。 */
function rackCheck(r) {
  if (!r.trays.some((t) => t.declared)) return `<div class="live-card"><div class="live-empty"><strong>等待通电</strong><br>清单里有 ${r.trays.length} 台设备（计算托盘 ${PROFILE_NEED.compute}、交换机 ${PROFILE_NEED.switch}、供电框 ${PROFILE_NEED.power_shelf}）。通电后平台按序列号自动匹配并写进 NICo，不需要在这里操作。</div></div>`;
  const miss = DB.absent(r), sw = DB.ready(r, "switch");
  return `<div ${fp(5)}>${summary([["计算托盘就绪", readyCount(r, "compute")], ["交换机就绪", readyCount(r, "switch")], ["供电框就绪", readyCount(r, "power_shelf")], ["清单里未出现", miss.length]])}</div>` +
    (r.state === "Discovering" ? note(sw >= PROFILE_NEED.switch ? `就绪的交换机 ${sw} 台，已达到机柜规格要求的 ${PROFILE_NEED.switch} 台。NICo 会自动开始上线，不需要人触发。` : `就绪的交换机 ${sw} 台，机柜规格要求 ${PROFILE_NEED.switch} 台。<b>交换机到齐之前 NICo 不会开始上线。</b>计算托盘和供电框缺件不影响上线，只会留下成员缺失的告警。`, sw >= PROFILE_NEED.switch ? "" : "warning") : "") +
    (miss.length ? `<div ${fp(6)}>${table(["槽位", "设备", "清单里的序列号", "对上线的影响", "操作"], miss.map((t) =>
      `<tr><td>${code(pad2(t.slot))}</td><td>${TYPE_LABEL[t.type]}</td><td>${code(t.serial)}</td><td>${t.type === "switch" ? badge("交换机未到齐，上线不会开始", "red") : badge("不影响上线", "amber")}</td><td>${button("去设备发现处理", "discovery-rack", false, `data-rack="${r.id}"`)}</td></tr>`))}</div>` : note("清单里的设备都已经出现并写进 NICo。"));
}
function rackTrays(r) {
  const cls = (t) => `${t.health} ${t.type}`;
  return `<div class="rack-elevation-layout"><div ${fp(7)}><div class="rack-elevation"><h3>机柜立面</h3>${[...r.trays].reverse().map((t) => `<button class="elevation-slot" data-live="tray-detail" data-id="${t.id}" title="${TYPE_LABEL[t.type]} ${t.serial}">${pad2(t.slot)}<i class="${cls(t)}"></i></button>`).join("")}</div>
      <p class="elevation-legend">槽位来自到货清单。<br>绿色正常　黄色告警　红色严重　斜纹未出现<br>左侧蓝条交换机，棕条供电框。</p></div>
    <div ${fp(8)}>${table(["槽位", "类型", "设备 / 序列号", "BMC 地址", "运行状态", "健康", "电源", "固件", "操作"], [...r.trays].reverse().map((t) =>
      `<tr><td>${code(pad2(t.slot))}</td><td>${TYPE_LABEL[t.type]}</td><td><a class="link-button" data-live="tray-detail" data-id="${t.id}">${code(t.serial)}</a>${t.maintenance ? `<span class="cell-sub">维护：${esc(t.maintenance)}</span>` : ""}</td><td>${t.bmcIp ? code(t.bmcIp) : "—"}</td><td>${stateBadge(t.state)}</td><td>${healthBadge(t.health)}</td><td>${t.state ? powerText(t.power) : "—"}</td><td>${t.type === "power_shelf" || !t.baseline ? "—" : DB.drift(t) ? badge("与基线不同", "amber") : badge("与基线相同", "green")}</td><td><div class="inline-actions">${button("运行状态", "tray-detail", false, `data-id="${t.id}"`)}${act("操作", "tray-op", { gate: t.state ? "" : "NICo 尚未建立设备对象，不能操作。", extra: `data-id="${t.id}"` })}</div></td></tr>`))}</div></div>`;
}
const stageText = { done: "完成", run: "进行中…", wait: "等待", fail: "失败" };
function rackTasks(r) {
  if (!r.tasks.length) return `<div class="live-card"><div class="live-empty">还没有任务。机柜级的电源和固件操作提交后在这里跟踪步骤和结果。NICo 自动进行的上线不是任务，进度在页面上方。</div></div>`;
  return r.tasks.map((t, i) => `<section class="live-card" ${i === 0 ? fp(9) : ""}><div class="live-heading" style="margin-bottom:14px"><div><h2 style="margin:0">${esc(t.label)}　${code(t.id)}</h2><p>${esc(t.target)} · ${t.at}${t.end ? " 至 " + t.end.slice(11) : ""} · ${t.by}${t.reason ? " · " + esc(t.reason) : ""}</p></div><div class="live-tools">${taskStatus(t)}${t.status === "执行中" ? act("取消任务", "task-cancel", { extra: `data-id="${r.id}"`, compact: true }) : ""}</div></div>
    <div class="task-stages">${t.stages.map((s, n) => `<div class="task-stage ${{ done: "done", run: "run", fail: "fail" }[s.s] || ""}"><b>${n + 1}. ${esc(s.n)}</b>${s.s === "fail" && t.status === "已终止" ? "已终止" : stageText[s.s]}</div>`).join("")}</div>
    ${t.status === "已终止" ? `<p class="live-small" style="margin-top:12px">已请求终止：还没开始的步骤不再执行。已经交给硬件后端的动作（例如正在刷写的固件）不会停，以设备读回的状态为准。</p>` : ""}</section>`).join("");
}
function rackHistory(r) {
  const alerts = DB.alerts().filter((a) => a.rack === r.id);
  return `<h2 class="section-title" style="margin-top:0">当前健康告警</h2>${table(["告警", "对象", "说明", "开始时间"], alerts.map((a) => `<tr><td>${code(a.id)}${alertClass(a)}</td><td>${esc(a.obj)}</td><td>${esc(a.msg)}</td><td>${code(a.since)}</td></tr>`), "当前没有健康告警。")}
    <h2 class="section-title">状态历史</h2><div ${fp(10)}>${table(["状态", "进入时间"], [...r.history].reverse().map((h, i) => `<tr><td>${stateBadge(h[1])}${i === 0 ? " " + badge("当前", "amber") : ""}</td><td>${code(h[0])}</td></tr>`), "NICo 里还没有这个机柜的对象。")}</div>`;
}
/* NICo 上线进度：机柜状态机自己走的阶段。不是任务，不能取消；失败后停在 Error，要人重新发起一次机柜维护。 */
function rackBringup(r) {
  if (!r.state || (r.state === "Ready" && !r.bring)) return "";
  const stages = r.bring ? r.bring.stages : STAGES.bringup.map((n) => ({ n, s: "wait" })), sw = DB.ready(r, "switch");
  const head = r.state === "Error" ? `<b>上线停在 Error。</b>${esc(r.reason)}。原因消除后 NICo 不会自己恢复，需要重新执行机柜维护。` : r.state === "Ready" ? "NICo 已完成上线。" : r.bring ? "NICo 正在自动上线，不需要人触发。" : `等待交换机到齐：就绪 ${sw} / ${PROFILE_NEED.switch}。到齐后 NICo 自动开始。`;
  return `<section class="live-card" ${fp(3)}><div class="live-heading" style="margin-bottom:14px"><div><h2 style="margin:0">NICo 上线进度</h2><p>${head}</p></div><div class="live-tools">${r.state === "Error" ? act("重新执行机柜维护", "rack-remaint", { primary: true, gate: rackGate(r, "remaint"), extra: `data-id="${r.id}"` }) : ""}</div></div>
    <div class="task-stages">${stages.map((s, n) => `<div class="task-stage ${{ done: "done", run: "run", fail: "fail" }[s.s] || ""}"><b>${n + 1}. ${esc(s.n)}</b>${stageText[s.s]}</div>`).join("")}</div>
    <p class="live-small" style="margin-top:12px">阶段由 NICo 的机柜状态机推进。站点没有为这个机柜规格配置固件清单时，“固件升级”和“NVOS 更新”会直接通过，不做任何事。</p></section>`;
}

registerPage("rack", {
  module: "racks", title: "机柜详情", crumb: (id) => id,
  render(id) {
    const r = DB.rack(id); if (!r) return heading("机柜管理", "没有这个机柜。", button("返回机柜管理", "noop", false, 'data-go="racks"'));
    const tab = view("rackTab:" + id, r.state === "Ready" ? "trays" : "check"), n = DB.rackInstances(id).length, done = r.trays.filter((t) => t.declared).length;
    const phase = !r.state || r.state === "Discovering" ? 1 : r.state === "Ready" ? 3 : 2;
    const step = (i, title, text) => `<div class="flow-step ${phase > i ? "done" : phase === i ? "now" : ""}"><b>${title}</b>${text}</div>`;
    const ops = `<span ${fp(2)} style="display:inline-flex;gap:10px;flex-wrap:wrap">${act("电源", "rack-power", { gate: rackGate(r, "power"), extra: `data-id="${id}"` })}${act("固件更新", "rack-firmware", { gate: rackGate(r, "firmware"), extra: `data-id="${id}"` })}${act("期望与实际校验", "rack-validate", { gate: r.state ? "" : "NICo 里还没有这个机柜的对象", extra: `data-id="${id}"` })}${act("退役", "rack-decommission", { gate: rackGate(r, "decommission"), extra: `data-id="${id}"` })}</span>`;
    const gate = r.state && r.state !== "Ready" ? rackGate(r, "power") : DB.busy(r) ? rackGate(r, "power") : "";
    const tabs = [["check", "清单核对" + (DB.absent(r).length ? ` · ${DB.absent(r).length}` : "")], ["trays", "设备"], ["tasks", "任务" + (DB.busy(r) ? " · 执行中" : "")], ["history", "健康与历史"]];
    return heading(id, `${r.location} · NVLink 域 ${r.domain} · 机柜规格 ${r.profile}`, button("刷新数据", "refresh") + ops) +
      `<div ${fp(1)}>${summary([["NICo 状态", r.state ? stateBadge(r.state) : badge("尚未建立", "gray")], ["健康", healthBadge(rackHealth(r))], ["成员电源", DB.power(r).text], ["固件基线", r.baseline || "—"], ["实例", n]])}</div>` +
      `<div class="flow-steps">${step(1, "接入", `已写入 NICo ${done} / ${r.trays.length}`)}${step(2, "NICo 上线", "固件 · NVOS · NMX-C 集群 · 上电顺序 · 校验")}${step(3, "可交付", r.state === "Ready" ? `已交付实例 ${n}` : "机柜就绪后")}</div>` +
      (DB.leak(id) ? note(`<b>机柜级泄漏。</b>NICo 已自动对整柜全部设备强制下电，${n ? `<b>${n} 个实例已中断</b>，` : ""}并拒绝再次上电。断路器与冷却阀由设施侧控制。告警清除后设备不会自动开机，需要在这里提交上电。`, "error") : "") +
      (gate ? note("电源和固件操作暂不可用：" + esc(gate) + "。", "warning") : "") +
      rackBringup(r) +
      `<div class="live-tabs" role="tablist" ${fp(4)}>${tabs.map(([k, t]) => `<button class="button ${tab === k ? "primary" : ""}" role="tab" data-live="rack-tab" data-id="${id}" data-tab="${k}">${t}</button>`).join("")}</div>` +
      { check: rackCheck, trays: rackTrays, tasks: rackTasks, history: rackHistory }[tab](r);
  },
  spec: {
    purpose: "一个机柜的工作台：看它在流程的哪一步，看 NICo 上线走到哪个阶段，发起机柜级操作并跟踪任务。",
    entry: "运维 → 机柜管理，点击整行；设备管理、设备清单、健康告警、NVLink 域管理、运维任务页里的机柜链接", design: "5 整体操作运维流程；6.3 机柜与设备；9 操作设计", existing: "设备管理 → 机柜的详情弹窗（状态、健康、成员、状态历史）扩展为页面；机柜拓扑并入“设备”页签",
    points: [
      { n: 1, name: "机柜概况", kind: "调整", desc: "NICo 状态、健康、成员电源、固件基线、实例数。机柜对象没有电源状态，所以显示成员里有几台开机。" },
      { n: 2, name: "机柜操作", kind: "调整", desc: "电源、固件更新、期望与实际校验、退役。不可用时按钮禁用并在提示里写明原因。没有“开始上线”：上线由 NICo 自动进行。" },
      { n: 3, name: "NICo 上线进度", kind: "新增", desc: "固件升级、NVOS 更新、配置 NMX-C 集群、上电顺序、机柜校验五个阶段。它是机柜状态机的进度，不是任务。停在 Error 时显示原因和“重新执行机柜维护”。" },
      { n: 4, name: "页签", kind: "新增", desc: "清单核对、设备、任务、健康与历史。已就绪的机柜默认打开设备，其余默认打开清单核对。" },
      { n: 5, name: "就绪统计", kind: "新增", desc: "三类设备的就绪数，以及清单里还没有出现的台数。说明 NICo 开始上线的唯一条件：就绪的交换机数达到机柜规格要求。" },
      { n: 6, name: "未出现的设备", kind: "调整", desc: "清单里有、但还没有设备读出这个序列号的行，以及它对上线有没有影响。处理入口在“设备发现”。" },
      { n: 7, name: "机柜立面", kind: "调整", desc: "取代机柜拓扑的卡片视图：按槽位从上到下排列，颜色表示健康，点击打开设备的运行状态。" },
      { n: 8, name: "设备表", kind: "沿用", desc: "设备 / 序列号、BMC 地址、运行状态、健康、电源沿用服务器页；行操作“运行状态”“操作”不变。" },
      { n: 9, name: "任务卡", kind: "新增", desc: "电源和固件任务按步骤显示进度；执行中的任务可以取消。" },
      { n: 10, name: "状态历史", kind: "沿用", desc: "沿用机柜详情弹窗的状态历史和当前健康告警。" },
    ],
    fields: [["成员电源", "各成员设备的电源状态", "全部开机、全部关机，或“N / M 开机”"], ["NICo 上线进度", "NICo 机柜状态", "状态里带着所在的阶段"], ["对上线的影响", "NICo 机柜规格", "交换机未到齐时上线不会开始；计算托盘和供电框缺件不影响"], ["固件", "设备实际版本对比推荐基线", "与基线相同 / 与基线不同；供电框没有可读的版本"]],
    rules: ["上线由 NICo 的机柜状态机自动进行：就绪的交换机数达到机柜规格要求后开始，不需要人触发，也不能在页面上取消。", "机柜进入 Error 后不会自己恢复；原因消除后要“重新执行机柜维护”。", "清单核对只是提示，不拦截上线。", "同一机柜同时只有一个任务，执行期间其他机柜级操作禁用。", "有整柜泄漏的机柜：NICo 自动强制下电，并拒绝上电。", "机柜上还有实例时不能退役。", "下电、重启和有实例时的固件更新是高风险操作，要输入机柜 ID。", "待定：上线期间计算托盘是否需要由平台放行，实测后确定。"],
    dialogs: [
      { name: "操作确认（电源、固件更新、退役、重新执行机柜维护共用）", desc: "只显示对象、动作、受影响的实例、将经过的步骤。", fields: [["固件基线", "仅固件更新", "只能选择基线"], ["原因", "是", "写入任务和审计"], ["输入机柜 ID", "高风险时", "下电、重启、有实例的固件更新、退役"]] },
    ],
  },
});
registerAction("rack-tab", ({ id, tab }) => { S.view["rackTab:" + id] = tab; render(); });
