"use strict";
/* 机柜详情：对账、托盘（立面）、任务、历史。由机柜列表、清单、健康等页面进入。 */

function rackRecon(r) {
  if (r.state === "Created") return `<div class="live-card"><div class="live-empty"><strong>等待通电与发现</strong><br>期望 35 台设备（计算托盘 18、交换机 9、供电框 8）。通电后 NICo 通过 DHCP 自动发现并接管，不需要在这里操作。</div></div>`;
  const open = r.issues.filter((i) => !i.done);
  return `<div ${fp(5)}>${summary([["计算托盘就绪", readyCount(r, "compute")], ["交换机 就绪", readyCount(r, "switch")], ["供电框就绪", readyCount(r, "power_shelf")], ["阻塞项", DB.blockers(r).length]])}</div>` +
    (open.length ? "" : note(`期望清单、实测信息和状态机一致，对账无阻塞项${r.state === "Discovering" ? "，可以开始上线" : ""}。`)) +
    (r.issues.length ? `<div ${fp(6)}>${table(["槽位", "设备", "问题", "期望", "实测", "影响", "操作"], r.issues.map((i) =>
      `<tr><td>${code(pad2(i.slot))}</td><td>${TYPE_LABEL[i.type]}</td><td><strong>${i.title}</strong><span class="cell-sub">${esc(i.detail)}</span></td><td>${code(i.expect)}</td><td>${code(i.actual)}</td><td>${i.done ? badge("已处理", "green") : i.block ? badge("阻塞上线", "red") : badge("不阻塞", "amber")}</td><td>${i.done ? "" : act(i.action, "issue-fix", { extra: `data-id="${r.id}" data-issue="${i.k}"`, compact: true })}</td></tr>`))}</div>` : "");
}
function rackTrays(r) {
  const cls = (t) => `${t.health} ${t.type}`;
  return `<div class="rack-elevation-layout"><div ${fp(7)}><div class="rack-elevation"><h3>机柜立面</h3>${[...r.trays].reverse().map((t) => `<button class="elevation-slot" data-live="tray-detail" data-id="${t.id}" title="${TYPE_LABEL[t.type]} ${t.serial}">${pad2(t.slot)}<i class="${cls(t)}"></i></button>`).join("")}</div>
      <p class="elevation-legend">槽位来自期望清单。<br>绿色正常　黄色告警　红色严重　斜纹未发现<br>左侧蓝条交换机，棕条供电框。</p></div>
    <div ${fp(8)}>${table(["槽位", "类型", "设备 / 序列号", "BMC 地址", "运行状态", "健康", "电源", "固件", "操作"], [...r.trays].reverse().map((t) =>
      `<tr><td>${code(pad2(t.slot))}</td><td>${TYPE_LABEL[t.type]}</td><td><a class="link-button" data-live="tray-detail" data-id="${t.id}">${code(t.serial)}</a>${t.maintenance ? `<span class="cell-sub">维护：${esc(t.maintenance)}</span>` : ""}</td><td>${t.state ? code(t.bmcIp) : "—"}</td><td>${stateBadge(t.state)}</td><td>${healthBadge(t.health)}</td><td>${t.state ? powerText(t.power) : "—"}</td><td>${t.baseline ? (DB.drift(t) ? badge("偏差", "amber") : badge("符合基线", "green")) : "—"}</td><td><div class="inline-actions">${button("运行状态", "tray-detail", false, `data-id="${t.id}"`)}${act("操作", "tray-op", { gate: t.state ? "" : "NICo 尚未建立设备对象，不能操作。", extra: `data-id="${t.id}"` })}</div></td></tr>`))}</div></div>`;
}
function rackTasks(r) {
  if (!r.tasks.length) return `<div class="live-card"><div class="live-empty">还没有任务。机柜级操作提交后在这里跟踪阶段和结果。</div></div>`;
  return r.tasks.map((t, i) => `<section class="live-card" ${i === 0 ? fp(9) : ""}><div class="live-heading" style="margin-bottom:14px"><div><h2 style="margin:0">${esc(t.label)}　${code(t.id)}</h2><p>${esc(t.target)} · ${t.at} · ${t.by}${t.reason ? " · " + esc(t.reason) : ""}</p></div><div class="live-tools">${taskStatus(t)}${t.status === "执行中" ? act("取消任务", "task-cancel", { extra: `data-id="${r.id}"`, compact: true }) : ""}</div></div>
    <div class="task-stages">${t.stages.map((s, n) => `<div class="task-stage ${{ done: "done", run: "run", fail: "fail" }[s.s] || ""}"><b>${n + 1}. ${esc(s.n)}</b>${{ done: "完成", run: "进行中…", wait: "等待", fail: "已终止" }[s.s]}</div>`).join("")}</div>
    ${t.status === "已终止" ? `<p class="live-small" style="margin-top:12px">任务在该阶段停止，已完成的硬件动作不会撤销。重新提交后机柜可离开 Error。</p>` : ""}</section>`).join("");
}
function rackHistory(r) {
  const alerts = DB.alerts().filter((a) => a.rack === r.id);
  return `<h2 class="section-title" style="margin-top:0">当前健康告警</h2>${table(["告警", "对象", "说明", "开始时间"], alerts.map((a) => `<tr><td>${code(a.id)}${a.block ? " " + badge("阻止分配", "red") : ""}</td><td>${esc(a.obj)}</td><td>${esc(a.msg)}</td><td>${code(a.since)}</td></tr>`), "当前没有健康告警。")}
    <h2 class="section-title">状态历史</h2><div ${fp(10)}>${table(["状态", "进入时间", "停留"], [...r.history].reverse().map((h, i) => `<tr><td>${stateBadge(h[1])}${i === 0 ? " " + badge("当前", "amber") : ""}</td><td>${code(h[0])}</td><td>${i === 0 ? "至今" : "—"}</td></tr>`))}</div>`;
}

registerPage("rack", {
  module: "racks", title: "机柜详情", crumb: (id) => id,
  render(id) {
    const r = DB.rack(id); if (!r) return heading("机柜管理", "没有这个机柜。", button("返回机柜管理", "noop", false, 'data-go="racks"'));
    const tab = view("rackTab:" + id, r.state === "Ready" ? "trays" : "recon"), n = DB.rackInstances(id).length;
    const phase = { Created: 1, Discovering: 1, Maintenance: 2, Validating: 2, Error: 2, Ready: 3 }[r.state];
    const step = (i, title, text) => `<div class="flow-step ${phase > i ? "done" : phase === i ? "now" : ""}"><b>${title}</b>${text}</div>`;
    const ops = `<span ${fp(2)} style="display:inline-flex;gap:10px;flex-wrap:wrap">${r.state === "Ready" ? "" : act("开始上线", "rack-bringup", { primary: true, gate: rackGate(r, "bringup"), extra: `data-id="${id}"` })}${act("电源", "rack-power", { gate: rackGate(r, "power"), extra: `data-id="${id}"` })}${act("固件更新", "rack-firmware", { gate: rackGate(r, "firmware"), extra: `data-id="${id}"` })}${act("期望与实际校验", "rack-validate", { gate: r.state === "Created" ? "等待通电与发现" : "", extra: `data-id="${id}"` })}${act("退役", "rack-decommission", { gate: rackGate(r, "decommission"), extra: `data-id="${id}"` })}</span>`;
    const firstGate = r.state !== "Ready" && !DB.busy(r) ? rackGate(r, "bringup") : DB.busy(r) ? rackGate(r, "power") : "";
    const tabs = [["recon", "对账" + (DB.blockers(r).length ? ` · ${DB.blockers(r).length}` : "")], ["trays", "设备"], ["tasks", "任务" + (DB.busy(r) ? " · 执行中" : "")], ["history", "健康与历史"]];
    return heading(id, `${r.location} · NVLink 域 ${r.domain} · 机柜规格 ${r.profile}`, button("刷新数据", "refresh") + ops) +
      `<div ${fp(1)}>${summary([["NICo 状态", stateBadge(r.state)], ["健康", healthBadge(rackHealth(r))], ["电源", powerText(r.power)], ["固件基线", r.baseline || "—"], ["实例", n]])}</div>` +
      `<div class="flow-steps" ${fp(3)}>${step(1, "接入与对账", r.state === "Created" ? "等待通电与发现" : DB.blockers(r).length ? DB.blockers(r).length + " 项阻塞" : "无阻塞项")}${step(2, "机柜上线", "固件 · NVOS · NMX-C · 机柜校验")}${step(3, "可交付", r.state === "Ready" ? `已交付实例 ${n}` : "机柜就绪后")}</div>` +
      (firstGate ? note("部分操作暂不可用：" + esc(firstGate) + "。", "warning") : "") +
      (S.leak && DB.preventAlloc(id) ? note(`<b>泄漏告警。</b>该机柜有阻止分配的泄漏告警，上电与交付会被拒绝。断路器与冷却阀由设施侧 BMS 控制。`, "error") : "") +
      `<div class="live-tabs" role="tablist" ${fp(4)}>${tabs.map(([k, t]) => `<button class="button ${tab === k ? "primary" : ""}" role="tab" data-live="rack-tab" data-id="${id}" data-tab="${k}">${t}</button>`).join("")}</div>` +
      { recon: rackRecon, trays: rackTrays, tasks: rackTasks, history: rackHistory }[tab](r);
  },
  spec: {
    purpose: "一个机柜的工作台：看它在流程的哪一步，处理对账问题，发起机柜级操作并跟踪任务。",
    entry: "运维 → 机柜管理，点击整行；设备管理、设备清单、健康告警、NVLink 域管理、运维任务页里的机柜链接", design: "5 整体操作运维流程；6.3 机柜与设备；9 操作设计", existing: "设备管理 → 机柜的详情弹窗（状态、健康、成员、状态历史）扩展为页面；发现诊断、布线并入“对账”；机柜拓扑并入“设备”页签",
    points: [
      { n: 1, name: "机柜概况", kind: "调整", desc: "NICo 状态、健康、电源、固件基线、实例数。沿用机柜详情弹窗的字段。" },
      { n: 2, name: "机柜操作", kind: "调整", desc: "上线、电源、固件更新、期望与实际校验、退役。不可用时按钮禁用并在提示里写明原因；机柜就绪后不再显示“开始上线”。现有的“机柜维护”弹窗被拆成这几个单一动作。" },
      { n: 3, name: "流程位置", kind: "新增", desc: "接入与对账、机柜上线、可交付三步，标出当前位置和每步的完成情况。" },
      { n: 4, name: "页签", kind: "新增", desc: "对账、设备、任务、健康与历史。已就绪的机柜默认打开设备，其余默认打开对账。" },
      { n: 5, name: "对账统计", kind: "新增", desc: "三类设备的就绪数和阻塞项数。交换机就绪数达到机柜规格要求才能上线。" },
      { n: 6, name: "对账问题", kind: "调整", desc: "把发现诊断（探测失败、错误码、处理建议）、布线（接线不符）和清单比对（序列号不符、未发现）合成一张表，每行一个处理入口。" },
      { n: 7, name: "机柜立面", kind: "调整", desc: "取代机柜拓扑的卡片视图：按槽位从上到下排列，颜色表示健康，点击打开设备的运行状态。" },
      { n: 8, name: "设备表", kind: "沿用", desc: "设备 / 序列号、BMC 地址、运行状态、健康、电源沿用服务器页；行操作“运行状态”“操作”不变。" },
      { n: 9, name: "任务卡", kind: "新增", desc: "按阶段显示 Flow 任务的进度和每个阶段的结果；执行中的任务可以取消。" },
      { n: 10, name: "状态历史", kind: "沿用", desc: "沿用机柜详情弹窗的状态历史（状态、进入时间、停留）和当前健康告警。" },
    ],
    fields: [["对账问题 · 影响", "NICo 机柜规格", "阻塞上线：序列号不符、交换机未发现；不阻塞：供电框或计算托盘缺失、接线不符"], ["固件", "托盘实际版本对比推荐基线", "符合基线 / 偏差"], ["电源", "NICo 读回", "On / Off / 未报告"]],
    rules: ["“上线”对应 NICo 的 bringup：固件、NVOS、NMX-C 配置和机柜校验。", "同一机柜同时只有一个任务，执行期间其他机柜级操作禁用。", "对账有阻塞项、机柜未发现或已 Ready 时不能开始上线。", "有泄漏告警的机柜拒绝上电。", "机柜上还有实例时不能退役。", "下电、重启和有实例时的固件更新是高风险操作，要输入机柜 ID。"],
    dialogs: [
      { name: "操作确认（上线、电源、固件更新、退役共用）", desc: "只显示对象、动作、受影响的实例、将经过的阶段。", fields: [["固件基线", "仅固件更新", "只能选择基线"], ["原因", "是", "写入任务和审计"], ["输入机柜 ID", "高风险时", "下电、重启、有实例的固件更新、退役"]] },
      { name: "更换设备", desc: "从“序列号不符”的对账问题进入，按实物更新期望清单。", fields: [["新序列号", "是", "默认带入实测值"], ["新 BMC MAC", "是", ""], ["原因", "是", ""]] },
    ],
  },
});
registerAction("rack-tab", ({ id, tab }) => { S.view["rackTab:" + id] = tab; render(); });
