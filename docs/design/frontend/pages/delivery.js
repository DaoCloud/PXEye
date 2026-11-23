"use strict";
/* 交付：把就绪的机器变成可用资源。合并现有的“安装任务”和“实例管理”，入口改为按机柜交付。 */

function deliveryGate(r) {
  const free = r.trays.filter((t) => t.type === "compute" && t.state === "Ready" && !t.maintenance && !t.quarantine).length;
  if (r.state !== "Ready") return "机柜未就绪";
  if (r.power !== "On") return "机柜未上电";
  if (DB.preventAlloc(r.id)) return "有阻止分配的告警";
  if (DB.busy(r)) return "机柜有进行中的任务";
  if (S.deliveries.some((d) => d.rack === r.id && d.done < d.total)) return "该机柜正在交付";
  if (!free) return "没有可交付的计算托盘";
  return "";
}
const freeTrays = (r) => r.trays.filter((t) => t.type === "compute" && t.state === "Ready" && !t.maintenance && !t.quarantine);

registerPage("delivery", {
  module: "delivery", title: "机柜交付",
  render() {
    const cond = (ok, text) => badge(text, ok ? "green" : "gray");
    return heading("机柜交付", "把就绪的计算托盘变成可用资源：按安装方案装机并验收，或交给租户和上层平台。默认按机柜批量。", button("刷新数据", "refresh")) +
      `<div ${fp(1)}>${table(["机柜", "NICo 状态", "交付条件", "可交付 / 计算托盘", "已交付实例", "操作"], S.racks.map((r) => { const g = deliveryGate(r), n = freeTrays(r).length; return `<tr><td><strong>${r.id}</strong><span class="cell-sub">NVLink 域 ${r.domain}</span></td><td>${stateBadge(r.state)}</td>
        <td ${fp(2)}>${cond(r.state === "Ready", "机柜就绪")} ${cond(r.state === "Ready" && r.power === "On", "NVLink 域健康")} ${DB.preventAlloc(r.id) ? badge("有阻止分配的告警", "red") : cond(r.state !== "Created", "无阻止分配的告警")}</td>
        <td>${r.state === "Ready" ? n : 0}<small class="muted"> / 18</small>${r.trays.some((t) => t.maintenance) ? `<span class="cell-sub">${r.trays.filter((t) => t.maintenance).length} 台带维护标记，不参与交付</span>` : ""}</td><td>${DB.rackInstances(r.id).length}</td>
        <td><span ${fp(3)}>${act("交付", "deliver-open", { primary: !g, gate: g, extra: `data-id="${r.id}"` })}</span>${g ? `<span class="cell-sub">${g}</span>` : ""}</td></tr>`; }))}</div>` +
      `<h2 class="section-title">交付批次</h2><div ${fp(4)}>${table(["批次", "机柜", "类型", "目标", "设备进度", "操作"], S.deliveries.map((d) => `<tr><td>${code(d.id)}<span class="cell-sub">${d.at}</span></td><td>${d.rack}</td><td>${d.how}</td><td>${esc(d.target)}</td><td>完成 ${d.done} / ${d.total}<div class="progress-meter"><i style="width:${(d.done / d.total) * 100}%"></i></div></td><td>${button("逐台查看", "noop", false, 'data-go="delivery/installs"')}</td></tr>`), "还没有交付批次。")}</div>` +
      note("交付门控沿用 NICo 的原生门控：机柜就绪、NVLink 域健康、没有阻止分配的告警。平台只显示原因，不提供绕过。");
  },
  spec: {
    calls: [["rack.list", "机柜是否就绪"], ["machine.list", "按机柜筛出计算托盘"], ["host.states", "可交付的托盘数和不可交付的原因"], ["health.reports", "机柜和域的告警"], ["instance.list", "已交付的实例数"], ["os.list", "可选的安装方案"], ["instance.allocate", "装机并验收"], ["instance-type.write", "交给上层平台"]],
    purpose: "交付是平台价值兑现的一步。入口是机柜而不是单台设备：选一个就绪的机柜，选一种交付方式。",
    entry: "交付 → 机柜交付", design: "5 整体操作运维流程（交付）；6.4 交付", existing: "安装任务的“新建安装任务”向导改为按机柜交付；“安装批次”表沿用",
    points: [
      { n: 1, name: "可交付的机柜", kind: "新增", desc: "每个机柜的状态、交付条件、可交付的计算托盘数和已交付实例数。" },
      { n: 2, name: "交付条件", kind: "新增", desc: "三个条件逐项显示：机柜就绪、NVLink 域健康、无阻止分配的告警。不满足的显示为灰色或红色。" },
      { n: 3, name: "交付", kind: "调整", desc: "打开两步向导。不可用时按钮禁用，下方写明原因。" },
      { n: 4, name: "交付批次", kind: "沿用", desc: "沿用安装任务页的“安装批次”表：批次、类型、设备进度、逐台查看。" },
    ],
    fields: [["可交付", "NICo Core", "状态为 Ready、没有维护标记和隔离、没有实例的计算托盘"], ["类型", "交付方式", "装机并验收 / 交给上层平台"]],
    rules: ["机柜未就绪、未上电、有阻止分配的告警、有进行中的任务时不能交付。", "带维护标记或已隔离的托盘不参与交付。"],
    dialogs: [{ name: "交付向导", desc: "步骤 1 选择方式，步骤 2 核对并确认。沿用安装向导的“步骤 N / 2”写法，去掉逐机筛选。",
      fields: [["交付方式", "是", "装机并验收 / 交给上层平台"], ["安装方案 或 租户", "是", "只能选择已发布的方案或已有租户"], ["原因", "是", ""], ["确认所选机柜、安装方案及系统盘", "是", "勾选；沿用安装向导的确认项"], ["允许安装及重启验证", "装机时", "勾选"]] }],
  },
});
registerAction("deliver-open", ({ id }) => {
  const r = DB.rack(id), n = freeTrays(r).length;
  modal(`交付 ${id}`, "步骤 1 / 2 · 选择方式",
    `<p class="live-small">对象：${id} 的 ${n} 个就绪计算托盘。</p><div class="choice-cards"><label><input type="radio" name="how" value="os" checked> <b>装机并验收</b><small>按安装方案安装，完成后自动验收</small></label><label><input type="radio" name="how" value="tenant"> <b>交给上层平台</b><small>把就绪的机器分配给租户或集群平台</small></label></div>
     <div class="live-form">${field("安装方案", `<select class="input" id="dl-os">${S.osTemplates.filter((o) => o.state === "已发布").map((o) => `<option>${o.id}</option>`).join("")}</select>`, "装机并验收时使用；只列出已发布的方案")}${field("租户", `<select class="input" id="dl-tenant">${S.tenants.map((t) => `<option>${t}</option>`).join("")}</select>`, "交给上层平台时使用")}</div>`,
    button("取消", "close") + button("下一步", "deliver-review", true, `data-id="${id}"`), { wide: false });
});
registerAction("deliver-review", ({ id }) => {
  const r = DB.rack(id), how = document.querySelector("[name=how]:checked").value, target = how === "os" ? $("#dl-os").value : $("#dl-tenant").value, n = freeTrays(r).length;
  modal(`交付 ${id}`, "步骤 2 / 2 · 核对并确认",
    defs([["对象", `<b>${id}</b> · ${n} 个计算托盘`], ["方式", how === "os" ? "装机并验收" : "交给上层平台"], [how === "os" ? "安装方案" : "租户", esc(target)], ["受影响的实例", "0 个"], ["并发", "按站点默认安装并发 5 台"], ["交付条件", badge("机柜就绪", "green") + " " + badge("NVLink 域健康", "green") + " " + badge("无阻止分配的告警", "green")]]) +
    `<div class="live-form" style="margin-top:16px">${field("原因", `<input class="input" id="dl-why" value="交付训练集群">`)}</div>
     <label class="live-check"><input type="checkbox" id="dl-c1"> 确认所选机柜、${how === "os" ? "安装方案及系统盘" : "租户"}。</label>${how === "os" ? `<label class="live-check"><input type="checkbox" id="dl-c2"> 允许安装及重启验证。</label>` : ""}`,
    button("重新选择", "deliver-open", false, `data-id="${id}"`) + button(how === "os" ? "确认并安装" : "确认并交付", "deliver-run", true, `data-id="${id}" data-how="${how}" data-target="${esc(target)}"`), { wide: false });
});
registerAction("deliver-run", ({ id, how, target }) => {
  const why = $("#dl-why").value.trim(); if (!why) return toast("请填写原因");
  if (!$("#dl-c1").checked || ($("#dl-c2") && !$("#dl-c2").checked)) return toast("请勾选确认项");
  const r = DB.rack(id), trays = freeTrays(r), d = { id: "batch-" + String(S.deliveries.length + 7).padStart(3, "0"), rack: id, how: how === "os" ? "装机并验收" : "交给上层平台", target, at: nowText(), done: 0, total: trays.length, trays: trays.map((t) => t.id) };
  S.deliveries.unshift(d); const rec = addAudit(id, "交付：" + d.how, why, d.id, "已提交"); closeModal(); S.guide = Math.max(S.guide, 7);
  const timer = setInterval(() => {
    trays.slice(d.done, d.done + 3).forEach((t) => { t.state = "Assigned/Ready"; t.instance = `inst-${id.slice(-3).toLowerCase()}-${pad2(t.slot)}`; S.instances.push({ id: t.instance, tray: t.id, rack: id, host: `node-${id.slice(-3).toLowerCase()}-${pad2(t.slot)}`, os: how === "os" ? target.split(" · ")[0] : "由上层平台安装", tenant: how === "os" ? "—" : target, state: "Ready", ip: t.hostIp, created: nowText() }); });
    d.done = Math.min(d.total, d.done + 3);
    if (d.done >= d.total) { clearInterval(timer); rec.res = `验收通过 ${d.total}/${d.total}`; toast(id + "：交付完成"); }
    render();
  }, 900);
  go("delivery");
});

registerPage("delivery/installs", {
  module: "installs", title: "安装任务",
  render() {
    const rows = S.deliveries.filter((d) => d.how === "装机并验收").flatMap((d) => d.trays.map((tid, i) => { const t = DB.tray(tid), done = i < d.done, run = !done && i < d.done + 3;
      return `<tr><td><a class="link-button" data-live="install-detail" data-id="${tid}">${code(`${d.id}-${pad2(i + 1)}`)}</a><span class="cell-sub">${d.at}</span></td><td>${code(t.serial)}<span class="cell-sub live-code">${t.hostIp}</span></td><td>${code(`node-${d.rack.slice(-3).toLowerCase()}-${pad2(t.slot)}`)}</td><td>${done ? "完成" : run ? "安装系统" : "等待执行"}<span class="cell-sub">${done ? badge("已完成", "green") : run ? badge("执行中", "amber") : badge("待执行", "amber")}</span></td><td><a class="link-button">https://${t.bmcIp} ↗</a></td><td>${button("实时日志 / 记录", "install-detail", false, `data-id="${tid}"`)}</td></tr>`; }));
    return heading("安装任务", "查看装机进度、日志和验收结果。任务由“机柜交付”创建。", button("刷新数据", "refresh") + button("前往机柜交付", "noop", true, 'data-go="delivery"')) +
      `<div ${fp(1)}>${table(["任务 / 创建时间", "设备 / 管理地址", "目标主机名", "阶段 / 状态", "BMC 控制台", "操作"], rows, "暂无记录。在“机柜交付”里选择“装机并验收”后，任务出现在这里。")}</div>` +
      `<div ${fp(2)}>${note("每个任务保留安装进度、BMC 串口日志和安装验收（安装器成功、主机配置、系统盘与 EFI 分区验证、网络配置、SSH 连通、GPU 环境检查、重启验收）。详情沿用现有的“物理机安装记录”。")}</div>`;
  },
  spec: {
    calls: [["instance.list", "实例状态"], ["machine.list", "主机状态"]],
    purpose: "逐台查看装机的阶段、日志和验收证据。这一页是现有产品的主线页面，结构不变，只是入口改为由交付创建。",
    entry: "交付 → 安装任务；交付批次的“逐台查看”", design: "6.4 交付", existing: "安装任务页。表头、阶段和状态用词、任务详情全部沿用；去掉“新建安装任务”按钮",
    points: [
      { n: 1, name: "任务表", kind: "沿用", desc: "任务 / 创建时间、设备 / 管理地址、目标主机名、阶段 / 状态、BMC 控制台、操作，与现有页面一致。" },
      { n: 2, name: "任务详情", kind: "沿用", desc: "点击任务编号或“实时日志 / 记录”打开现有的“物理机安装记录”：状态、安装进度、实时日志、执行与恢复记录、安装验收。" },
    ],
    rules: ["阶段用词：等待执行、准备设备、安装前检查、安装系统、启动系统盘、安装验收、GPU 环境检查、重启验收、完成。", "状态用词：待执行、执行中、已完成、需处理、已终止。", "失败的设备暂停等待处理，不影响同批其他设备。"],
  },
});
registerAction("install-detail", ({ id }) => { const t = DB.tray(id); modal("物理机安装记录", t.serial, defs([["设备 / 主机名", code(t.serial)], ["本次安装目标地址", code(t.hostIp)], ["BMC 控制台", `https://${t.bmcIp} ↗`], ["Instance", t.instance ? code(t.instance) : "分配中"], ["目标盘", "唯一匹配的 NVMe"]]) + `<h3 class="section-title">安装验收</h3>` + table(["检查项", "结果"], ["安装器成功", "主机配置", "系统盘与 EFI 分区验证", "网络配置", "SSH 连通", "GPU 环境检查", "重启验收"].map((c) => `<tr><td>${c}</td><td>${t.instance ? badge("通过", "green") : badge("待执行", "gray")}</td></tr>`)), button("下载验收报告", "noop") + button("关闭", "close", true)); });

registerPage("delivery/instances", {
  module: "instances", title: "实例管理",
  render() {
    const f = { rack: view("instRack", ""), q: view("instQ", "").toLowerCase() };
    const list = S.instances.filter((i) => (!f.rack || i.rack === f.rack) && (!f.q || [i.id, i.host, i.ip, DB.tray(i.tray).serial, i.tenant].join(" ").toLowerCase().includes(f.q)));
    return heading("实例管理", "查看实例分配，删除实例并回收设备。", button("刷新数据", "refresh")) +
      `<div class="filter-bar" ${fp(1)}>${selectField("instRack", "机柜", [["", "全部机柜"], ...S.racks.map((r) => [r.id, r.id])], f.rack)}${searchField("instQ", "搜索实例", view("instQ", ""), "名称、编号、序列号、主机名、IP")}<span class="live-small">${list.length} 个当前实例</span></div>` +
      `<div ${fp(2)}>${table(["实例名称 / ID", "设备序列号 / 主机名", "实例地址 / 操作系统", "机柜 / 租户", "机器状态 / 回收进度", "操作"], list.map((i) => { const t = DB.tray(i.tray); return `<tr><td><strong>${i.host}</strong><span class="cell-sub live-code">${i.id}</span></td><td>${code(t.serial)}<span class="cell-sub">${i.host}</span></td><td>${code(i.ip)}<span class="cell-sub">${esc(i.os)}</span></td><td><a class="link-button" data-go="rack/${i.rack}">${i.rack}</a><span class="cell-sub">${esc(i.tenant)}</span></td><td>${stateBadge(i.releasing ? "回收中" : t.state)}${i.releasing ? `<span class="cell-sub">实例已移除，设备准备中</span>` : ""}</td><td><div class="inline-actions">${button("详情", "tray-detail", false, `data-id="${t.id}"`)}<span ${fp(3)}>${act("删除（退租回收）", "inst-release", { gate: i.releasing ? "正在回收" : "", extra: `data-id="${i.id}"`, compact: true })}</span></div></td></tr>`; }), "未找到匹配的实例。")}</div>` +
      note("删除实例会发起 NICo 回收：清理磁盘并重新校验。清理完成前，这台设备不显示为可交付。");
  },
  spec: {
    calls: [["instance.list", "实例、租户和系统"], ["machine.list", "机器状态与回收进度"], ["instance.release", "删除（退租回收）"]],
    purpose: "查看已交付的实例，并在租户退租时回收设备。", entry: "交付 → 实例管理", design: "6.4 交付（释放与复用）", existing: "实例管理页。表头、回收用词和确认弹窗沿用，增加机柜和租户",
    points: [
      { n: 1, name: "筛选", kind: "调整", desc: "沿用搜索；增加按机柜筛选。" },
      { n: 2, name: "实例表", kind: "调整", desc: "实例名称 / ID、设备序列号 / 主机名、实例地址 / 操作系统、机器状态 / 回收进度沿用；增加“机柜 / 租户”。" },
      { n: 3, name: "删除（退租回收）", kind: "沿用", desc: "按钮名称、输入设备序列号确认、清理全部磁盘的勾选项都与现有页面一致。" },
    ],
    rules: ["回收完成并重新校验通过前，设备不计入“可交付”。", "回收用词：回收请求已接受、实例已移除设备准备中、回收完成、设备回收失败需处理。"],
    dialogs: [{ name: "删除（退租回收）", desc: "沿用现有弹窗。", fields: [["输入设备序列号确认范围", "是", ""], ["允许清理本机全部磁盘并回收实例资源。", "是", "勾选"]] }],
  },
});
registerAction("inst-release", ({ id }) => {
  const i = S.instances.find((x) => x.id === id), t = DB.tray(i.tray);
  modal("删除（退租回收）", i.host, defs([["实例名称 / ID", `${i.host} · ${code(i.id)}`], ["设备序列号", code(t.serial)], ["机柜", `${i.rack} 槽位 ${pad2(t.slot)}`], ["影响", "实例被删除；NICo 清理本机全部磁盘并重新校验"]]) +
    `<div class="live-form" style="margin-top:16px">${field("输入设备序列号确认范围", `<input class="input live-code" id="rl-sn" autocomplete="off" placeholder="${t.serial}">`)}</div><label class="live-check"><input type="checkbox" id="rl-ok"> 允许清理本机全部磁盘并回收实例资源。</label>`,
    button("取消", "close") + `<button class="button danger" data-live="inst-release-run" data-id="${id}">确认删除并回收</button>`, { wide: false });
});
registerAction("inst-release-run", ({ id }) => {
  const i = S.instances.find((x) => x.id === id), t = DB.tray(i.tray);
  if ($("#rl-sn").value.trim() !== t.serial) return toast("输入的序列号与设备不一致");
  if (!$("#rl-ok").checked) return toast("请勾选确认项");
  closeModal(); i.releasing = true; const rec = addAudit(`${i.rack} / 槽位 ${pad2(t.slot)}`, "删除（退租回收）", "租户退租", "—", "回收请求已接受"); render();
  setTimeout(() => { S.instances = S.instances.filter((x) => x.id !== id); t.instance = ""; t.state = "Ready"; rec.res = "回收完成，重新校验通过"; toast(`${t.serial}：回收完成，可再次交付`); render(); }, 2600);
});
