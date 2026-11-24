"use strict";
/* 机柜详情：确认接入、NICo 上线进度、清单核对、设备（立面）、任务、健康与历史。由机柜列表、清单、健康等页面进入。 */

/* 清单核对：清单与实物的差异。两类：清单里有、但还没有设备读出这个序列号；设备读到的槽位和清单写的不同。
   它帮人在确认接入前看清楚情况；NICo 的上线不看它，只看就绪的交换机数量。 */
function rackCheck(r) {
  if (!r.trays.some((t) => t.matched)) return `<div class="live-card"><div class="live-empty"><strong>等待通电</strong><br>清单里有 ${r.trays.length} 台设备（计算托盘 ${PROFILE_NEED.compute}、交换机 ${PROFILE_NEED.switch}、供电框 ${PROFILE_NEED.power_shelf}）。通电后平台按序列号自动匹配，匹配结果会显示在这里。</div></div>`;
  const miss = DB.absent(r), swap = DB.misplaced(r), got = (type) => { const list = r.trays.filter((t) => t.type === type); return `${list.filter((t) => t.matched).length}<small>/ ${list.length}</small>`; };
  const sw = r.admit ? DB.ready(r, "switch") : r.trays.filter((t) => t.type === "switch" && t.matched).length;
  return `<div ${fp(5)}>${summary(r.admit ? [["计算托盘就绪", readyCount(r, "compute")], ["交换机就绪", readyCount(r, "switch")], ["供电框就绪", readyCount(r, "power_shelf")], ["差异", miss.length + swap.length]] : [["计算托盘已匹配", got("compute")], ["交换机已匹配", got("switch")], ["供电框已匹配", got("power_shelf")], ["差异", miss.length + swap.length]])}</div>` +
    (r.state === "Ready" ? "" : note(sw >= PROFILE_NEED.switch ? `交换机 ${sw} 台，达到机柜规格要求的 ${PROFILE_NEED.switch} 台。${r.admit ? "NICo 会自动开始上线。" : "确认接入后，NICo 会在交换机就绪时自动开始上线。"}` : `交换机 ${sw} 台，机柜规格要求 ${PROFILE_NEED.switch} 台。<b>交换机没到齐，NICo 不会开始上线。</b>这个数量写在 NICo 的机柜规格里，是开始上线的最低门槛；确实要以更少的交换机上线，只能由管理员修改 NICo 站点配置里这个规格的交换机数量。计算托盘和供电框缺件不影响上线，只留下成员数量不足的告警。`, sw >= PROFILE_NEED.switch ? "" : "warning")) +
    (miss.length + swap.length ? `<div ${fp(6)}>${table(["槽位", "设备", "差异", "清单", "实测", "对上线的影响", "操作"], miss.map((t) =>
      `<tr><td>${code(pad2(t.slot))}</td><td>${TYPE_LABEL[t.type]}</td><td><strong>未出现</strong></td><td>${code(t.serial)}</td><td>没有设备读出这个序列号</td><td>${t.type === "switch" ? badge("交换机未到齐，上线不会开始", "red") : badge("不影响上线", "amber")}</td><td>${button("去设备发现处理", "discovery-rack", false, `data-rack="${r.id}"`)}</td></tr>`).concat(swap.map((t) =>
      `<tr><td>${code(pad2(t.slot))}</td><td>${TYPE_LABEL[t.type]}</td><td><strong>槽位不一致</strong><span class="cell-sub">${code(t.serial)}</span></td><td>槽位 ${pad2(t.slot)}</td><td>槽位 ${pad2(t.seenSlot)}</td><td>${badge("不影响上线", "amber")}</td><td>${act("按实测更正清单", "slot-fix", { extra: `data-id="${t.id}"`, compact: true })}</td></tr>`)))}</div>` : note("清单里的设备都已经出现，槽位也和清单一致。"));
}
/* 确认接入：这个机柜唯一需要人点头的地方。确认之前平台只读设备、不写 NICo；确认之后 NICo 接管设备并自动上线。 */
function rackAdmit(r) {
  if (r.admit) return "";
  const n = r.trays.filter((t) => t.matched).length, eps = S.endpoints.length;
  return `<section class="live-card" ${fp(11)}><div class="live-heading" style="margin-bottom:${n ? 12 : 0}px"><div><h2 style="margin:0">确认接入</h2><p>${n ? `已有 ${n} / ${r.trays.length} 台设备匹配上清单，还没有写进 NICo。看过下面的清单核对后确认接入。` : "设备通电并匹配上清单后，在这里确认接入。确认之前平台只读设备，不写 NICo。"}</p></div><div class="live-tools">${act("确认接入", "rack-admit", { primary: true, gate: n ? "" : "还没有设备匹配上清单", extra: `data-id="${r.id}"` })}</div></div>
    ${n ? `<p class="live-small">确认后：平台把已匹配的设备写进 NICo → NICo 探测并接管，轮换设备口令 → 交换机就绪后 NICo 自动开始上线（固件升级、NVOS 更新、上电顺序、配置 NMX-C 集群、机柜校验）。<b>确认后不能撤回，上线开始后不能取消。</b>${eps ? `另有 ${eps} 个端点还没匹配上，可以先处理，也可以确认后再处理。` : ""}</p>` : ""}</section>`;
}
function rackTrays(r) {
  const cls = (t) => `${t.health} ${t.type}`;
  return `<div class="rack-elevation-layout"><div ${fp(7)}><div class="rack-elevation"><h3>机柜立面</h3>${[...r.trays].reverse().map((t) => `<button class="elevation-slot" data-live="tray-detail" data-id="${t.id}" title="${TYPE_LABEL[t.type]} ${t.serial}">${pad2(t.slot)}<i class="${cls(t)}"></i></button>`).join("")}</div>
      <p class="elevation-legend">槽位来自到货清单。<br>绿色正常　黄色告警　红色严重　斜纹未写入 NICo<br>左侧蓝条交换机，棕条供电框。</p></div>
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
  const head = r.state === "Error" ? `<b>上线停在 Error。</b>${esc(r.reason)}。原因消除后 NICo 不会自己恢复，需要重新执行机柜维护。` : r.state === "Ready" ? "NICo 已完成上线。" : r.bring ? "NICo 正在自动上线。阶段和顺序由 NICo 决定，不能调整，也不能取消。" : `等待交换机到齐：就绪 ${sw} / ${PROFILE_NEED.switch}。到齐后 NICo 自动开始。`;
  return `<section class="live-card" ${fp(3)}><div class="live-heading" style="margin-bottom:14px"><div><h2 style="margin:0">NICo 上线进度</h2><p>${head}</p></div><div class="live-tools">${r.state === "Error" ? act("重新执行机柜维护", "rack-remaint", { primary: true, gate: rackGate(r, "remaint"), extra: `data-id="${r.id}"` }) : ""}</div></div>
    <div class="task-stages">${stages.map((s, n) => `<div class="task-stage ${{ done: "done", run: "run", fail: "fail" }[s.s] || ""}"><b>${n + 1}. ${esc(s.n)}</b>${stageText[s.s]}</div>`).join("")}</div>
    <p class="live-small" style="margin-top:12px">阶段由 NICo 的机柜状态机推进。NICo 没有为这个机柜规格配置固件清单时，“固件升级”和“NVOS 更新”会直接通过，不做任何事；“上电顺序”只在需要时执行。</p></section>`;
}

registerPage("rack", {
  module: "racks", title: "机柜详情", crumb: (id) => id,
  render(id) {
    const r = DB.rack(id); if (!r) return heading("机柜管理", "没有这个机柜。", button("返回机柜管理", "noop", false, 'data-go="racks"'));
    const tab = view("rackTab:" + id, r.state === "Ready" ? "trays" : "check"), n = DB.rackInstances(id).length, done = r.trays.filter((t) => t.declared).length, got = r.trays.filter((t) => t.matched).length, diff = DB.absent(r).length + DB.misplaced(r).length;
    const phase = !r.state || r.state === "Discovering" ? 1 : r.state === "Ready" ? 3 : 2;
    const step = (i, title, text) => `<div class="flow-step ${phase > i ? "done" : phase === i ? "now" : ""}"><b>${title}</b>${text}</div>`;
    const ops = `<span ${fp(2)} style="display:inline-flex;gap:10px;flex-wrap:wrap">${act("电源", "rack-power", { gate: rackGate(r, "power"), extra: `data-id="${id}"` })}${act("固件更新", "rack-firmware", { gate: rackGate(r, "firmware"), extra: `data-id="${id}"` })}${act("期望与实际校验", "rack-validate", { gate: r.state ? "" : "NICo 里还没有这个机柜的对象", extra: `data-id="${id}"` })}${act("退役", "rack-decommission", { gate: rackGate(r, "decommission"), extra: `data-id="${id}"` })}</span>`;
    const gate = r.state && r.state !== "Ready" ? rackGate(r, "power") : DB.busy(r) ? rackGate(r, "power") : "";
    const tabs = [["check", "清单核对" + (diff ? ` · ${diff}` : "")], ["trays", "设备"], ["tasks", "任务" + (DB.busy(r) ? " · 执行中" : "")], ["history", "健康与历史"]];
    return heading(id, `${r.location} · NVLink 域 ${r.domain} · 机柜规格 ${r.profile}`, button("刷新数据", "refresh") + ops) +
      `<div ${fp(1)}>${summary([["NICo 状态", r.state ? stateBadge(r.state) : badge("尚未建立", "gray")], ["健康", healthBadge(rackHealth(r))], ["成员电源", DB.power(r).text], ["固件基线", r.baseline || "—"], ["实例", n]])}</div>` +
      `<div class="flow-steps">${step(1, "接入", r.admit ? `已写入 NICo ${done} / ${r.trays.length}` : `已匹配 ${got} / ${r.trays.length} · 待确认接入`)}${step(2, "NICo 上线", "固件 · NVOS · 上电顺序 · NMX-C 集群 · 校验")}${step(3, "可交付", r.state === "Ready" ? `已交付实例 ${n}` : "机柜就绪后")}</div>` +
      (DB.leak(id) ? note(`<b>机柜级泄漏。</b>NICo 已自动对整柜全部设备强制下电，${n ? `<b>${n} 个实例已中断</b>，` : ""}并拒绝再次上电。断路器与冷却阀由设施侧控制。告警清除后设备不会自动开机，需要在这里提交上电。`, "error") : "") +
      (gate ? note("电源和固件操作暂不可用：" + esc(gate) + "。", "warning") : "") +
      rackAdmit(r) + rackBringup(r) +
      `<div class="live-tabs" role="tablist" ${fp(4)}>${tabs.map(([k, t]) => `<button class="button ${tab === k ? "primary" : ""}" role="tab" data-live="rack-tab" data-id="${id}" data-tab="${k}">${t}</button>`).join("")}</div>` +
      { check: rackCheck, trays: rackTrays, tasks: rackTasks, history: rackHistory }[tab](r);
  },
  spec: {
    purpose: "一个机柜的工作台：看它在流程的哪一步，确认接入，看 NICo 上线走到哪个阶段，发起机柜级操作并跟踪任务。",
    entry: "运维 → 机柜管理，点击整行；设备管理、设备清单、健康告警、NVLink 域管理、运维任务页里的机柜链接", design: "5 整体操作运维流程；6.3 机柜与设备；9 操作设计", existing: "设备管理 → 机柜的详情弹窗（状态、健康、成员、状态历史）扩展为页面；机柜拓扑并入“设备”页签",
    points: [
      { n: 1, name: "机柜概况", kind: "调整", desc: "NICo 状态、健康、成员电源、固件基线、实例数。机柜对象没有电源状态，所以显示成员里有几台开机。" },
      { n: 2, name: "机柜操作", kind: "调整", desc: "电源、固件更新、期望与实际校验、退役。不可用时按钮禁用并在提示里写明原因。没有“开始上线”：上线在确认接入之后由 NICo 自动进行。" },
      { n: 3, name: "NICo 上线进度", kind: "新增", desc: "固件升级、NVOS 更新、上电顺序、配置 NMX-C 集群、机柜校验五个阶段。它是机柜状态机的进度，不是任务，顺序不能调整。停在 Error 时显示原因和“重新执行机柜维护”。" },
      { n: 4, name: "页签", kind: "新增", desc: "清单核对、设备、任务、健康与历史。已就绪的机柜默认打开设备，其余默认打开清单核对。" },
      { n: 5, name: "匹配与就绪统计", kind: "新增", desc: "确认接入前显示三类设备各匹配上几台，确认后显示各就绪几台，以及差异的数量。说明 NICo 开始上线的条件：就绪的交换机数达到机柜规格里写的数量。" },
      { n: 6, name: "差异", kind: "调整", desc: "两类：清单里有、但还没有设备读出这个序列号（处理入口在“设备发现”）；设备实测的槽位和清单不同（可以按实测更正清单）。每行写明对上线有没有影响。" },
      { n: 7, name: "机柜立面", kind: "调整", desc: "取代机柜拓扑的卡片视图：按槽位从上到下排列，颜色表示健康，点击打开设备的运行状态。" },
      { n: 8, name: "设备表", kind: "沿用", desc: "设备 / 序列号、BMC 地址、运行状态、健康、电源沿用服务器页；行操作“运行状态”“操作”不变。" },
      { n: 9, name: "任务卡", kind: "新增", desc: "电源和固件任务按步骤显示进度；执行中的任务可以取消。" },
      { n: 10, name: "状态历史", kind: "沿用", desc: "沿用机柜详情弹窗的状态历史和当前健康告警。" },
      { n: 11, name: "确认接入", kind: "新增", desc: "新机柜唯一需要人点头的一步。显示已有多少设备匹配上清单，并写明确认后会发生什么：写入 NICo、NICo 接管并轮换口令、交换机就绪后自动上线。确认后这张卡片消失。" },
    ],
    fields: [["成员电源", "各成员设备的电源状态", "全部开机、全部关机，或“N / M 开机”"], ["NICo 上线进度", "NICo 机柜状态", "状态里带着所在的阶段"], ["实测槽位", "NICo，经硬件后端从设备读到", "和清单里写的槽位比对"], ["对上线的影响", "NICo 机柜规格", "交换机未到齐时上线不会开始；计算托盘和供电框缺件、槽位不一致都不影响"], ["固件", "设备实际版本对比推荐基线", "与基线相同 / 与基线不同；供电框没有可读的版本"]],
    rules: ["确认接入之前，平台只读设备，不写 NICo；NICo 不会接管这个机柜的任何设备，也就不会开始上线。", "确认接入之后，上线由 NICo 的机柜状态机自动进行：就绪的交换机数达到机柜规格里写的数量后开始。NICo 没有“等人确认再开始”的开关，阶段的顺序也不能调整，开始后不能在页面上取消。", "交换机的数量门槛写在 NICo 的机柜规格里，只有管理员修改站点配置才能改。", "机柜进入 Error 后不会自己恢复；原因消除后要“重新执行机柜维护”。", "清单核对帮人在确认接入前看清差异；确认接入之后它不拦截上线。", "同一机柜同时只有一个任务，执行期间其他机柜级操作禁用。", "有整柜泄漏的机柜：NICo 自动强制下电，并拒绝上电。", "机柜上还有实例时不能退役。", "下电、重启和有实例时的固件更新是高风险操作，要输入机柜 ID。", "待定：上线期间计算托盘是否需要由平台放行，实测后确定。"],
    dialogs: [
      { name: "确认接入", desc: "显示已匹配的数量、差异和待处理的端点，以及确认后依次会发生什么。", fields: [["原因", "是", "写入审计"]] },
      { name: "操作确认（电源、固件更新、退役、重新执行机柜维护共用）", desc: "显示对象、动作、受影响的实例、将经过的步骤；电源和固件另外显示现在有几台主机不满足就绪条件、任务会等多久。", fields: [["固件基线", "仅固件更新", "只能选择基线"], ["原因", "是", "写入任务和审计"], ["输入机柜 ID", "高风险时", "下电、重启、有实例的固件更新、退役"]] },
    ],
  },
});
registerAction("rack-tab", ({ id, tab }) => { S.view["rackTab:" + id] = tab; render(); });
