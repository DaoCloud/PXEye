"use strict";
/* 机柜详情：登记机柜、开始上线、机柜维护进度、清单核对、设备（立面）、任务、健康与历史。由机柜列表、清单、健康等页面进入。
   这一页只放 NICo 在机柜对象上定义的东西，加上对成员设备的汇总。成员设备自己的地址、状态和单台操作在“设备管理”；装系统在“安装任务”。 */

/* 清单核对：规划与实物的差异。两类：规划里有、但还没有纳管的设备（登记机柜前就能看到）；
   NICo 读到的槽位和规划写的不同（上线之后才有，计算托盘和交换机有，供电框没有）。
   它帮人看清楚情况；NICo 的机柜维护不看它，只看就绪的交换机数量。 */
function rackCheck(r) {
  if (!r.trays.some((t) => t.declared)) return `<div class="live-card"><div class="live-empty"><strong>等待设备纳管</strong><br>规划里有 ${r.trays.length} 台设备（计算托盘 ${PROFILE_NEED.compute}、交换机 ${PROFILE_NEED.switch}、供电框 ${PROFILE_NEED.power_shelf}）。机柜接电后，设备的 BMC 出现在<a class="link-button" data-go="discovery">设备发现</a>里；获取设备信息并加入纳管之后，结果显示在这里。</div></div>`;
  const miss = DB.absent(r), swap = DB.misplaced(r), loose = r.trays.filter((t) => t.declared && !t.placed), got = (type) => { const list = r.trays.filter((t) => t.type === type); return `${list.filter((t) => t.declared).length}<small>/ ${list.length}</small>`; };
  const sw = r.up ? DB.ready(r, "switch") : r.trays.filter((t) => t.type === "switch" && t.declared).length;
  return `<div ${fp(5)}>${summary(r.up ? [["计算托盘就绪", readyCount(r, "compute")], ["交换机就绪", readyCount(r, "switch")], ["供电框就绪", readyCount(r, "power_shelf")], ["差异", miss.length + swap.length]] : [["计算托盘已纳管", got("compute")], ["交换机已纳管", got("switch")], ["供电框已纳管", got("power_shelf")], ["还没有一键匹配", loose.length], ["差异", miss.length + swap.length]])}</div>` +
    (loose.length ? note(`<b>${loose.length} 台已纳管的设备还没有“一键匹配”</b>，机柜和槽位还没有写进它们的设备配置，登记机柜时不会带上。到<a class="link-button" data-go="devices/compute">设备管理</a>里勾选它们，点“一键匹配”。`, "warning") : "") +
    (r.state === "Ready" ? "" : note(sw >= PROFILE_NEED.switch ? `交换机 ${sw} 台，达到机柜规格要求的 ${PROFILE_NEED.switch} 台。${r.up ? "交换机就绪后 NICo 自动开始机柜维护。" : "上线后，交换机就绪时 NICo 会自动开始机柜维护。"}` : `交换机 ${sw} 台，机柜规格要求 ${PROFILE_NEED.switch} 台。<b>交换机没到齐，NICo 不会开始机柜维护，机柜到不了就绪。</b>这个数量是最低门槛，写在机柜规格里；确实要以更少的交换机上线，由管理员在“站点设置”里调整这个规格的交换机数量。计算托盘和供电框缺件不影响，只留下成员数量不足的告警。`, sw >= PROFILE_NEED.switch ? "" : "warning")) +
    (miss.length + swap.length ? `<div ${fp(6)}>${table(["槽位", "设备", "差异", "规划", "实际", "对上线的影响", "操作"], miss.map((t) =>
      `<tr><td>${code(pad2(t.slot))}</td><td>${TYPE_LABEL[t.type]}</td><td><strong>未纳管</strong></td><td>${code(t.serial)}</td><td>${t.matched ? "已获取设备信息，还没有加入纳管" : "还没有设备读出这个序列号"}</td><td>${t.type === "switch" ? badge("交换机未到齐，机柜维护不会开始", "red") : badge("不影响上线", "amber")}</td><td>${button("去设备发现处理", "discovery-rack", false, `data-rack="${r.id}"`)}</td></tr>`).concat(swap.map((t) =>
      `<tr><td>${code(pad2(t.slot))}</td><td>${TYPE_LABEL[t.type]}</td><td><strong>槽位不一致</strong><span class="cell-sub">${code(t.serial)}</span></td><td>槽位 ${pad2(t.slot)}</td><td>槽位 ${pad2(t.seenSlot)}</td><td>${badge("不影响上线", "amber")}</td><td>${act("按实测更正规划", "slot-fix", { extra: `data-id="${t.id}"`, compact: true })}</td></tr>`)))}</div>` : note(r.up ? "规划里的设备都已经纳管，实测的槽位也和规划一致。" : "规划里的设备都已经纳管。槽位要到上线、NICo 接管设备之后才能核对。"));
}
/* 新机柜在机柜页上有两处要人点头，各一张卡片，做完就消失。在这之前，设备的纳管和一键匹配已经在设备发现和设备管理里做完。
   登记机柜：把机柜声明和成员关系写入 NICo。不上电、不装系统。
   开始上线：提交上线任务，上电并让 NICo 接管。设备会重启，可能清理磁盘。仍然不装系统，装系统在“安装任务”里。 */
const doList = (yes, no) => `<div class="live-grid" style="margin-top:4px"><div><p class="live-small" style="margin:0 0 4px"><b>会做</b></p><ul class="live-small" style="margin:0;padding-left:18px">${yes.map((x) => `<li>${x}</li>`).join("")}</ul></div><div><p class="live-small" style="margin:0 0 4px"><b>不会做</b></p><ul class="live-small" style="margin:0;padding-left:18px">${no.map((x) => `<li>${x}</li>`).join("")}</ul></div></div>`;
const ADMIT_DO = ["写入这个机柜的机柜声明：机柜编号和机柜规格", "把本柜已纳管的交换机和供电框同步为 NICo 声明：MAC、凭据、机柜和槽位。NICo 随后登录它们的 BMC，把口令换成站点凭据", "计算托盘的声明在纳管时已经写入，这里补上机柜和槽位；声明仍带暂停标记，NICo 不给它上电，也不接管"];
const ADMIT_NOT = ["不给任何设备上电或重启", "不改 BIOS，不动磁盘，不刷固件", "不改地址：BMC 仍用接电时拿到的地址；按规划改址在设备管理里另外做", "不装操作系统"];
const UP_DO = ["按顺序上电：供电框 → 计算托盘 → 交换机", "放行计算托盘：NICo 设置 BIOS 和启动顺序，从网络启动发现程序读硬件，核对硬件，锁定 BIOS", "计算托盘的固件与期望版本不同时更新，然后重启", "交换机就绪后 NICo 自动做机柜维护：固件、NVOS、上电顺序、NMX-C 集群、校验"];
const UP_NOT = ["不装操作系统：装系统在“安装任务”里逐台确认", "不建实例"];
function rackAdmit(r) {
  if (r.admit) return "";
  const done = r.trays.filter((t) => t.declared).length, n = DB.placed(r).length;
  return `<section class="live-card" ${fp(11)}><div class="live-heading" style="margin-bottom:12px"><div><h2 style="margin:0">第 1 步　登记机柜</h2><p>${done ? `本柜已纳管 ${done} / ${r.trays.length} 台，其中 ${n} 台已经一键匹配。` : "设备纳管并一键匹配之后，在这里登记机柜。"}设备的纳管在“设备发现”里做，规划在“设备管理”里一键匹配；这一步把机柜和成员关系写入 NICo，不上电、不装系统。</p></div><div class="live-tools">${act("登记机柜", "rack-admit", { primary: true, gate: n ? "" : done ? "已纳管的设备还没有一键匹配：先到设备管理里匹配" : "本柜还没有已纳管的设备：先到设备发现里纳管", extra: `data-id="${r.id}"` })}</div></div>
    ${doList(ADMIT_DO, ADMIT_NOT)}</section>`;
}
function rackUp(r) {
  if (!r.admit || r.up) return "";
  const n = DB.placed(r).length, sw = DB.placed(r).filter((t) => t.type === "switch").length;
  return `<section class="live-card" ${fp(12)}><div class="live-heading" style="margin-bottom:12px"><div><h2 style="margin:0">第 2 步　开始上线</h2><p>机柜已登记，成员 ${n} / ${r.trays.length} 台，其中交换机 ${sw} / ${PROFILE_NEED.switch}。设备还没有上电。上线会给设备上电并让 NICo 接管，<b>设备会重启，按站点策略可能清理全部磁盘</b>。</p></div><div class="live-tools">${act("开始上线", "rack-bringup", { primary: true, gate: rackGate(r, "bringup"), extra: `data-id="${r.id}"` })}</div></div>
    ${doList(UP_DO, UP_NOT)}${sw < PROFILE_NEED.switch ? `<p class="live-small" style="margin-top:10px"><b>登记的交换机只有 ${sw} 台，不到 ${PROFILE_NEED.switch} 台。</b>上线任务可以提交，但 NICo 的机柜维护要等交换机到齐才开始。</p>` : ""}</section>`;
}
function rackTrays(r) {
  const cls = (t) => `${t.health} ${t.type}`;
  return `<div class="rack-elevation-layout"><div ${fp(7)}><div class="rack-elevation"><h3>机柜立面</h3>${[...r.trays].reverse().map((t) => `<button class="elevation-slot" data-live="tray-detail" data-id="${t.id}" title="${TYPE_LABEL[t.type]} ${t.serial}">${pad2(t.slot)}<i class="${cls(t)}"></i></button>`).join("")}</div>
      <p class="elevation-legend">槽位来自设备规划。<br>绿色正常　黄色告警　红色严重　斜纹未上线<br>左侧蓝条交换机，棕条供电框。</p></div>
    <div ${fp(8)}>${table(["槽位", "类型", "设备 / 序列号", "BMC 地址", "运行状态", "健康", "电源", "固件", "操作"], [...r.trays].reverse().map((t) =>
      `<tr><td>${code(pad2(t.slot))}</td><td>${TYPE_LABEL[t.type]}</td><td><a class="link-button" data-live="tray-detail" data-id="${t.id}">${code(t.serial)}</a>${t.maintenance ? `<span class="cell-sub">维护：${esc(t.maintenance)}</span>` : ""}</td><td>${t.bmcIp ? code(t.bmcIp) : "—"}</td><td>${stateBadge(t.state)}</td><td>${healthBadge(t.health)}</td><td>${t.state ? powerText(t.power) : "—"}</td><td>${t.type === "power_shelf" || !t.baseline ? "—" : DB.drift(t) ? badge("与基线不同", "amber") : badge("与基线相同", "green")}</td><td><div class="inline-actions">${button("运行状态", "tray-detail", false, `data-id="${t.id}"`)}${act("操作", "tray-op", { gate: t.state ? "" : "NICo 尚未建立设备对象，不能操作。", extra: `data-id="${t.id}"` })}</div></td></tr>`))}</div></div>`;
}
const stageText = { done: "完成", run: "进行中…", wait: "等待", fail: "失败" };
function rackTasks(r) {
  if (!r.tasks.length) return `<div class="live-card"><div class="live-empty">还没有任务。上线、电源和固件操作提交后在这里跟踪步骤和结果。NICo 自动进行的机柜维护不是任务，进度在页面上方。</div></div>`;
  return r.tasks.map((t, i) => `<section class="live-card" ${i === 0 ? fp(9) : ""}><div class="live-heading" style="margin-bottom:14px"><div><h2 style="margin:0">${esc(t.label)}　${code(t.id)}</h2><p>${esc(t.target)} · ${t.at}${t.end ? " 至 " + t.end.slice(11) : ""} · ${t.by}${t.reason ? " · " + esc(t.reason) : ""}</p></div><div class="live-tools">${taskStatus(t)}${t.status === "执行中" ? act("取消任务", "task-cancel", { extra: `data-id="${r.id}"`, compact: true }) : ""}</div></div>
    <div class="task-stages">${t.stages.map((s, n) => `<div class="task-stage ${{ done: "done", run: "run", fail: "fail" }[s.s] || ""}"><b>${n + 1}. ${esc(s.n)}</b>${s.s === "fail" && t.status === "已终止" ? "已终止" : stageText[s.s]}</div>`).join("")}</div>
    ${t.status === "已终止" ? `<p class="live-small" style="margin-top:12px">已请求终止：还没开始的步骤不再执行。已经交给硬件后端的动作（例如正在刷写的固件）不会停，以设备读回的状态为准。</p>` : ""}</section>`).join("");
}
function rackHistory(r) {
  const alerts = DB.alerts().filter((a) => a.rack === r.id);
  return `<h2 class="section-title" style="margin-top:0">当前健康告警</h2>${table(["告警", "对象", "说明", "开始时间"], alerts.map((a) => `<tr><td>${code(a.id)}${alertClass(a)}</td><td>${esc(a.obj)}</td><td>${esc(a.msg)}</td><td>${code(a.since)}</td></tr>`), "当前没有健康告警。")}
    <h2 class="section-title">状态历史</h2><div ${fp(10)}>${table(["状态", "进入时间"], [...r.history].reverse().map((h, i) => `<tr><td>${stateBadge(h[1])}${i === 0 ? " " + badge("当前", "amber") : ""}</td><td>${code(h[0])}</td></tr>`), "NICo 里还没有这个机柜的对象。")}</div>`;
}
/* 机柜维护进度：上线任务让交换机就绪之后，NICo 的机柜状态机自己走的阶段。不是任务，顺序不能调整。
   进行中可以终止，终止后机柜进入 Error；失败或终止后停在 Error，要人重新发起一次机柜维护。 */
function rackBringup(r) {
  if (!r.state || (r.state === "Ready" && !r.bring)) return "";
  const stages = r.bring ? r.bring.stages : STAGES.bringup.map((n) => ({ n, s: "wait" })), sw = DB.ready(r, "switch");
  const head = r.state === "Error" ? `<b>机柜维护停在 Error。</b>${esc(r.reason)}。原因消除后 NICo 不会自己恢复，需要重新执行机柜维护。` : r.state === "Ready" ? "机柜维护已完成，机柜就绪。" : r.bring ? "NICo 正在自动做机柜维护。阶段和顺序由 NICo 决定，不能调整；可以终止，终止后机柜停在 Error。" : DB.busy(r) ? "上线任务正在给设备上电。交换机上电并就绪后，NICo 自动开始机柜维护。" : `等待交换机到齐：就绪 ${sw} / ${PROFILE_NEED.switch}。到齐后 NICo 自动开始。`;
  return `<section class="live-card" ${fp(3)}><div class="live-heading" style="margin-bottom:14px"><div><h2 style="margin:0">机柜维护进度　<span class="live-small">NICo 自动</span></h2><p>${head}</p></div><div class="live-tools">${r.state === "Error" ? act("重新执行机柜维护", "rack-remaint", { primary: true, gate: rackGate(r, "remaint"), extra: `data-id="${r.id}"` }) : /^Maintenance|^Validating/.test(r.state) ? act("终止维护", "rack-terminate", { gate: rackGate(r, "terminate"), extra: `data-id="${r.id}"` }) : ""}</div></div>
    <div class="task-stages">${stages.map((s, n) => `<div class="task-stage ${{ done: "done", run: "run", fail: "fail" }[s.s] || ""}"><b>${n + 1}. ${esc(s.n)}</b>${stageText[s.s]}</div>`).join("")}</div>
    <p class="live-small" style="margin-top:12px">阶段由 NICo 的机柜状态机推进。NICo 没有为这个机柜规格配置固件清单时，“固件升级”和“NVOS 更新”会直接通过，不做任何事；“上电顺序”只在需要时执行。</p></section>`;
}

registerPage("rack", {
  module: "racks", title: "机柜详情", crumb: (id) => id,
  render(id) {
    const r = DB.rack(id); if (!r || r.pool) return heading("机柜管理", "没有这个机柜。", button("返回机柜管理", "noop", false, 'data-go="racks"'));
    const tab = view("rackTab:" + id, r.state === "Ready" ? "trays" : "check"), n = DB.rackInstances(id).length, done = r.trays.filter((t) => t.declared).length, got = DB.placed(r).length, diff = DB.absent(r).length + DB.misplaced(r).length;
    const phase = !r.admit ? 1 : r.state === "Ready" ? 3 : 2;
    const step = (i, title, text) => `<div class="flow-step ${phase > i ? "done" : phase === i ? "now" : ""}"><b>${title}</b>${text}</div>`;
    const ops = `<span ${fp(2)} style="display:inline-flex;gap:10px;flex-wrap:wrap">${act("电源", "rack-power", { gate: rackGate(r, "power"), extra: `data-id="${id}"` })}${act("固件更新", "rack-firmware", { gate: rackGate(r, "firmware"), extra: `data-id="${id}"` })}${act("期望与实际校验", "rack-validate", { gate: r.state ? "" : "NICo 里还没有这个机柜的对象", extra: `data-id="${id}"` })}${act("删除机柜", "rack-delete", { gate: r.state ? "" : "NICo 里还没有这个机柜的对象；要从规划里去掉它，重新导入规划", extra: `data-id="${id}"` })}</span>`;
    const gate = r.state && r.state !== "Ready" ? rackGate(r, "power") : DB.busy(r) ? rackGate(r, "power") : "";
    const tabs = [["check", "清单核对" + (diff ? ` · ${diff}` : "")], ["trays", "设备"], ["tasks", "任务" + (DB.busy(r) ? " · 执行中" : "")], ["history", "健康与历史"]];
    return heading(id, `${r.location} · NVLink 域 ${r.domain} · 机柜规格 ${r.profile}`, button("刷新数据", "refresh") + ops) +
      `<div ${fp(1)}>${summary([["NICo 状态", r.state ? stateBadge(r.state) : badge("尚未建立", "gray")], ["健康", healthBadge(rackHealth(r))], ["成员电源", DB.power(r).text], ["固件基线", r.baseline || "—"], ["实例", n]])}</div>` +
      `<div class="flow-steps">${step(1, "纳管与登记", r.admit ? `已登记 · 成员 ${got} / ${r.trays.length}` : `已纳管 ${done} / ${r.trays.length} · 已匹配 ${got} · 待登记机柜`)}${step(2, "上线", !r.admit ? "上电 · 接管 · 机柜维护" : !r.up ? "待开始上线" : r.state === "Ready" ? "机柜就绪" : "进行中")}${step(3, "装系统", r.state === "Ready" ? `逐台进行 · 已有实例 ${n} / ${PROFILE_NEED.compute}　<a class="link-button" data-live="install-new" data-rack="${id}" ${fp(13)}>新建安装任务</a>` : "机柜就绪后，在“安装任务”里逐台进行")}</div>` +
      (DB.leak(id) ? note(`<b>机柜级泄漏。</b>NICo 已自动对整柜全部设备强制下电，${n ? `<b>${n} 个实例已中断</b>，` : ""}并拒绝再次上电。断路器与冷却阀由设施侧控制。告警清除后设备不会自动开机，需要在这里提交上电。`, "error") : "") +
      (gate ? note("电源和固件操作暂不可用：" + esc(gate) + "。", "warning") : "") +
      rackAdmit(r) + rackUp(r) + rackBringup(r) +
      `<div class="live-tabs" role="tablist" ${fp(4)}>${tabs.map(([k, t]) => `<button class="button ${tab === k ? "primary" : ""}" role="tab" data-live="rack-tab" data-id="${id}" data-tab="${k}">${t}</button>`).join("")}</div>` +
      { check: rackCheck, trays: rackTrays, tasks: rackTasks, history: rackHistory }[tab](r);
  },
  spec: {
    purpose: "一个机柜的工作台：看它在流程的哪一步，登记机柜，开始上线，看机柜维护走到哪个阶段，发起机柜级操作并跟踪任务。这一页只放 NICo 在机柜对象上定义的操作，以及对成员设备的汇总；成员设备自己的事（纳管、一键匹配、地址、单台操作）在“设备发现”和“设备管理”，装系统在“安装任务”。",
    entry: "运维 → 机柜管理，点击整行；设备管理、设备清单、健康告警、NVLink 域管理、运维任务页里的机柜链接", design: "5 整体操作运维流程；6.3 机柜与设备；9 操作设计", existing: "设备管理 → 机柜的详情弹窗（状态、健康、成员、状态历史）扩展为页面；机柜拓扑并入“设备”页签",
    points: [
      { n: 1, name: "机柜概况", kind: "调整", desc: "NICo 状态、健康、成员电源、固件基线、实例数。机柜对象没有电源状态，所以显示成员里有几台开机。" },
      { n: 2, name: "机柜操作", kind: "调整", desc: "电源、固件更新、期望与实际校验、删除机柜。这四项加上开始上线、重新执行和终止机柜维护，就是 NICo 在机柜对象上定义的全部操作。不可用时按钮禁用并在提示里写明原因。" },
      { n: 3, name: "机柜维护进度", kind: "新增", desc: "上线任务让交换机就绪之后，NICo 自动做的五个阶段：固件升级、NVOS 更新、上电顺序、配置 NMX-C 集群、机柜校验。它是机柜状态机的进度，不是任务，顺序不能调整。进行中可以“终止维护”，终止后机柜进入 Error；停在 Error 时显示原因和“重新执行机柜维护”。" },
      { n: 4, name: "页签", kind: "新增", desc: "清单核对、设备、任务、健康与历史。已就绪的机柜默认打开设备，其余默认打开清单核对。" },
      { n: 5, name: "纳管与就绪统计", kind: "新增", desc: "上线前显示三类设备各纳管了几台、还有几台没有一键匹配，上线后显示各就绪几台，以及差异的数量。说明 NICo 开始机柜维护的条件：就绪的交换机数达到机柜规格里写的数量。" },
      { n: 6, name: "差异", kind: "调整", desc: "两类：规划里有、但还没有纳管的设备，登记机柜前就能看到，处理入口在“设备发现”；实测的槽位和规划不同，上线之后才有，可以按实测更正规划。每行写明对上线有没有影响。" },
      { n: 7, name: "机柜立面", kind: "调整", desc: "取代机柜拓扑的卡片视图：按槽位从上到下排列，颜色表示健康，点击打开设备的运行状态。" },
      { n: 8, name: "设备表", kind: "沿用", desc: "设备 / 序列号、BMC 地址、运行状态、健康、电源沿用服务器页；行操作“运行状态”“操作”不变。" },
      { n: 9, name: "任务卡", kind: "新增", desc: "电源和固件任务按步骤显示进度；执行中的任务可以取消。" },
      { n: 10, name: "状态历史", kind: "沿用", desc: "沿用机柜详情弹窗的状态历史和当前健康告警。" },
      { n: 11, name: "登记机柜", kind: "新增", desc: "新机柜在这一页的第 1 步，整柜新增。设备的纳管和一键匹配已经在设备发现和设备管理里做完；这一步把机柜声明和成员关系写入 NICo：写机柜声明，把本柜已纳管的交换机和供电框同步为 NICo 声明，给计算托盘的声明补上机柜和槽位。卡片显示本柜已纳管和已匹配的数量，并分两栏写明会做什么、不会做什么。登记后这张卡片消失。" },
      { n: 12, name: "开始上线", kind: "新增", desc: "新机柜的第 2 步，纳管之后出现。分两栏写明会做什么、不会做什么：按顺序上电、放行计算托盘的接管、必要时更新固件、交换机就绪后 NICo 自动做机柜维护；设备会重启，可能清理全部磁盘；不装系统。提交为一个任务。" },
      { n: 13, name: "新建安装任务", kind: "新增", desc: "机柜就绪后出现的快捷入口：打开“安装任务”的向导，并预先选中这个机柜里可以安装的计算托盘。装系统不是机柜的操作，所以它不在机柜操作那一排。" },
    ],
    fields: [["成员电源", "各成员设备的电源状态", "全部开机、全部关机，或“N / M 开机”"], ["NICo 上线进度", "NICo 机柜状态", "状态里带着所在的阶段"], ["实测槽位", "NICo 接管设备后向硬件后端 RMS 查询；RMS 读自托盘的 BMC", "计算托盘和交换机有，供电框没有。上线之后才有，和规划里写的槽位比对"], ["对上线的影响", "NICo 机柜规格", "交换机未到齐时上线不会开始；计算托盘和供电框缺件、槽位不一致都不影响"], ["固件", "设备实际版本对比推荐基线", "与基线相同 / 与基线不同；供电框没有可读的版本"]],
    rules: ["一个新机柜要人点头的地方依次是：设备发现里纳管（逐台或批量）、设备管理里一键匹配、这一页登记机柜、这一页开始上线、安装任务里装系统。前两步和现有产品一样，登记机柜和开始上线是整柜新增的。", "机柜页只放机柜对象上的操作。纳管是逐台设备的事，在设备发现里做；装系统和实例只在单台机器上。", "登记机柜只带上已纳管并且已经一键匹配的成员：没有匹配的设备，机柜和槽位还没有写进它的配置。之后才纳管、匹配的成员自动补进这个机柜。", "登记机柜之前，交换机和供电框只在平台本地纳管，NICo 不知道它们；计算托盘的声明在纳管时已写入 NICo，带暂停标记，NICo 不给它上电，也不接管。", "开始上线提交的是一个上线任务：供电框上电、计算托盘上电并放行接管、计算托盘固件、交换机上电、核对交换机固件、计算托盘重启。", "交换机就绪数达到机柜规格里写的数量后，NICo 的机柜状态机自动开始机柜维护。这一段没有“等人确认”的开关，阶段的顺序不能调整。进行中可以终止，终止后机柜进入 Error。", "交换机的数量门槛写在机柜规格里，由管理员在“站点设置”里调整。", "机柜进入 Error 后不会自己恢复；原因消除后要“重新执行机柜维护”。终止维护只在机柜处于维护阶段时可用。", "清单核对帮人在登记机柜前看清差异；登记之后它不拦截上线。", "同一机柜同时只有一个任务，执行期间其他机柜级操作禁用。", "有整柜泄漏的机柜：NICo 自动强制下电，并拒绝上电。", "删除机柜只删除机柜对象，不处理成员设备：要先删除实例，再把成员设备逐台退役，然后才能删除。删除前逐项显示这些前提是否满足。", "下电、重启、有实例时的固件更新、终止维护和删除机柜是高风险操作，要输入机柜 ID。", "待定：上线任务与 NICo 自动的机柜维护同时进行时如何衔接，要在模拟环境里实测后确定。"],
    dialogs: [
      { name: "登记机柜", desc: "显示带上的成员数量（三类设备各几台）、已纳管但还没有一键匹配的数量、规划里有但还没有纳管的数量，以及会做什么、不会做什么。", fields: [["原因", "是", "写入审计"]] },
      { name: "开始上线", desc: "显示已登记的成员数量、将经过的步骤、NICo 随后自动做的事，以及对设备的影响。", fields: [["原因", "是", "写入任务和审计"], ["输入机柜 ID", "是", "设备会上电和重启，可能清理磁盘"]] },
      { name: "操作确认（电源、固件更新、重新执行与终止机柜维护共用）", desc: "显示对象、动作、受影响的实例、将经过的步骤；电源和固件另外显示现在有几台主机不满足就绪条件、任务会等多久。", fields: [["固件基线", "仅固件更新", "只能选择基线"], ["原因", "是", "写入任务和审计"], ["输入机柜 ID", "高风险时", "下电、重启、有实例的固件更新、终止维护"]] },
      { name: "删除机柜", desc: "逐项显示删除前要满足的前提和现在是否满足：没有实例、成员设备都已退役、没有进行中的任务。前提没有全部满足时不能提交。", fields: [["原因", "是", "写入审计"], ["输入机柜 ID", "是", ""]] },
    ],
  },
});
registerAction("rack-tab", ({ id, tab }) => { S.view["rackTab:" + id] = tab; render(); });
