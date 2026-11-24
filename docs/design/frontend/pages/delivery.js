"use strict";
/* 交付：给就绪的机器装系统，并管理装好的实例。
   装系统是逐台机器的事：NICo 里一台机器建一个实例，实例名称就是装好之后系统里的主机名。机柜上没有“装系统”这个操作。
   所以入口是“安装任务”：选设备，逐台确定主机名、安装方案和系统盘，核对后提交，每台一个实例。
   机柜详情、服务器列表和设备发现里的“新建安装任务”打开的是同一个向导，只是预先选好了设备。
   平台不做多租户：所有实例建在站点的默认租户下，页面上不出现租户。 */

/* 一台服务器现在能不能装系统：返回不能装的原因，空字符串表示可以。
   NICo 建实例时只看这台机器自己（状态、维护标记、阻止分配的告警）；机柜未就绪、整柜泄漏、机柜有任务是平台加的检查。 */
function installGate(t) {
  if (t.type !== "compute") return "只有服务器能装系统";
  if (t.instance) return "已有实例";
  if (DB.installing(t)) return "有进行中的安装任务";
  if (t.quarantine) return "已隔离";
  if (t.maintenance) return "带维护标记";
  if (DB.blocked(t)) return "有阻止分配的告警";
  if (t.rack) {
    const r = DB.rack(t.rack);
    if (r.state !== "Ready") return r.state ? "所在机柜还没有就绪" : "所在机柜还没有上线";
    if (DB.leak(r.id)) return "所在机柜有整柜泄漏告警";
    if (DB.busy(r)) return "所在机柜有进行中的任务";
    return t.state === "Ready" ? "" : "设备未就绪";
  }
  if (!t.declared) return "还没有纳管";
  /* 不属于机柜的服务器：纳管后还没有被接管的也可以装，安装任务的第一步就是让 NICo 上电接管它。 */
  return !t.state || t.state === "Ready" ? "" : "设备未就绪";
}
const servers = () => DB.trays().filter((t) => t.type === "compute");
const osReady = (arch) => S.osTemplates.filter((o) => o.state === "已发布" && o.arch === arch);
/* 主机名同时是 NICo 里的实例名称，所以要符合主机名的写法，并且不能和已有的实例重名。 */
const HOST_RE = /^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$/;
const hostTaken = (h) => S.instances.some((i) => i.host === h) || S.installs.some((b) => b.items.some((i) => i.s !== "done" && i.host === h));
const hostProblem = (h, all) => (!h ? "请填写主机名" : !HOST_RE.test(h) ? "只能用小写字母、数字和连字符，不能以连字符开头或结尾" : all.filter((x) => x === h).length > 1 ? "和本次的另一台重名" : hostTaken(h) ? "已有同名的实例" : "");
const ITEM_STAGE = { wait: ["等待执行", "待执行", "amber"], prep: ["准备设备", "执行中", "amber"], run: ["安装系统", "执行中", "amber"], done: ["完成", "已完成", "green"] };
const scopeText = (list) => { const n = {}; list.forEach((t) => (n[t.rack || "未分配机柜"] = (n[t.rack || "未分配机柜"] || 0) + 1)); return Object.entries(n).map(([k, v]) => `${k} ${v} 台`).join("、"); };

/* ---------- 安装任务 ---------- */
registerPage("delivery/installs", {
  module: "installs", title: "安装任务",
  render() {
    const f = { batch: view("insBatch", ""), st: view("insSt", "") }, free = servers().filter((t) => !installGate(t)).length;
    const items = S.installs.flatMap((b) => b.items.map((i, n) => ({ b, i, n }))).filter(({ b, i }) => (!f.batch || b.id === f.batch) && (!f.st || (f.st === "open" ? i.s !== "done" : i.s === "done")));
    const meter = (b) => { const done = b.items.filter((i) => i.s === "done").length; return `完成 ${done} / ${b.items.length}<div class="progress-meter"><i style="width:${(done / b.items.length) * 100}%"></i></div>`; };
    return heading("安装任务", "给就绪的服务器装操作系统：选设备，逐台确定主机名和安装方案，装完自动验收。这里也查看每台的进度、日志和验收结果。", button("刷新数据", "refresh") + `<span ${fp(1)}>${act("新建安装任务", "install-new", { primary: true, gate: free ? "" : "现在没有可以装系统的服务器" })}</span>`) +
      `<div ${fp(2)}>${summary([["可以装系统的服务器", free], ["进行中的批次", S.installs.filter((b) => b.items.some((i) => i.s !== "done")).length], ["正在安装", S.installs.flatMap((b) => b.items).filter((i) => i.s === "run" || i.s === "prep").length], ["已装好的实例", S.instances.length]])}</div>` +
      `<h2 class="section-title">安装批次</h2><div ${fp(3)}>${table(["批次 / 创建时间", "设备", "安装方案", "设备进度", "原因 / 操作者", "操作"], S.installs.map((b) => `<tr><td>${code(b.id)}<span class="cell-sub">${b.at}</span></td><td>${b.items.length} 台<span class="cell-sub">${scopeText(b.items.map((i) => DB.tray(i.tray)))}</span></td><td>${[...new Set(b.items.map((i) => i.os))].map(esc).join("<br>")}</td><td>${meter(b)}</td><td>${esc(b.why)}<span class="cell-sub">${b.by}</span></td><td>${button("逐台查看", "install-batch", false, `data-id="${b.id}"`)}</td></tr>`), "还没有安装批次。点击“新建安装任务”开始。")}</div>` +
      `<h2 class="section-title">逐台任务</h2><div class="filter-bar" ${fp(4)}>${selectField("insBatch", "批次", [["", "全部批次"], ...S.installs.map((b) => [b.id, b.id])], f.batch)}${selectField("insSt", "状态", [["", "全部"], ["open", "未完成"], ["done", "已完成"]], f.st)}<span class="live-small">${items.length} 个任务</span></div>` +
      `<div ${fp(5)}>${table(["任务 / 创建时间", "设备 / 位置", "目标主机名", "安装方案 / 系统盘", "阶段 / 状态", "操作"], items.slice(0, 40).map(({ b, i, n }) => { const t = DB.tray(i.tray), st = ITEM_STAGE[i.s];
        return `<tr><td><a class="link-button" data-live="install-detail" data-batch="${b.id}" data-id="${i.tray}">${code(`${b.id}-${pad2(n + 1)}`)}</a><span class="cell-sub">${b.at}</span></td><td>${code(t.serial)}<span class="cell-sub">${placeText(t)}</span></td><td>${code(i.host)}</td><td>${esc(i.os)}<span class="cell-sub">${i.disk ? "指定 " + esc(i.disk) : "按方案的规则选盘"}</span></td><td>${st[0]}<span class="cell-sub">${badge(st[1], st[2])}</span></td><td>${button("实时日志 / 记录", "install-detail", false, `data-batch="${b.id}" data-id="${i.tray}"`)}</td></tr>`; }), "没有符合筛选条件的任务。")}${items.length > 40 ? `<p class="live-small">显示前 40 个，共 ${items.length} 个。</p>` : ""}</div>` +
      `<div ${fp(6)}>${note("每个任务保留安装进度、BMC 串口日志和安装验收（安装器成功、主机配置、系统盘与 EFI 分区验证、网络配置、SSH 连通、GPU 环境检查、重启验收）。失败的设备暂停等待处理，不影响同批其他设备。")}</div>`;
  },
  spec: {
    purpose: "装系统的入口和进度页。装系统是逐台机器的事：一台机器建一个实例，实例名称就是系统里的主机名。所以这里按台新建和跟踪，机柜只是选择设备时的一个筛选条件。",
    entry: "交付 → 安装任务；机柜详情“装系统”一步里的“新建安装任务”；服务器列表和设备发现里的“新建安装任务”", design: "5 整体操作运维流程（交付）；6.4 交付", existing: "安装任务页。表头、阶段和状态用词、任务详情和“新建安装任务”按钮都沿用；向导改为三步",
    points: [
      { n: 1, name: "新建安装任务", kind: "调整", desc: "打开三步向导：选择设备、逐台配置、核对并确认。从机柜详情、服务器列表或设备发现进入时，向导里已经选好了设备。" },
      { n: 2, name: "统计条", kind: "新增", desc: "现在可以装系统的服务器数、进行中的批次、正在安装的台数、已装好的实例数。" },
      { n: 3, name: "安装批次", kind: "沿用", desc: "一次提交是一个批次：设备数量和分布、用到的安装方案、设备进度、原因和操作者。" },
      { n: 4, name: "筛选", kind: "调整", desc: "按批次和是否完成筛选逐台任务。" },
      { n: 5, name: "逐台任务", kind: "沿用", desc: "任务 / 创建时间、设备、目标主机名、阶段 / 状态、操作沿用；增加“位置”和“安装方案 / 系统盘”，因为这两项现在逐台确定。" },
      { n: 6, name: "任务详情", kind: "沿用", desc: "点击任务编号或“实时日志 / 记录”打开现有的“物理机安装记录”：状态、安装进度、实时日志、执行与恢复记录、安装验收。" },
    ],
    fields: [["可以装系统", "NICo 的机器状态 + 平台检查", "机器就绪、没有实例、没有隔离和维护标记、没有阻止分配的告警；机柜里的还要求机柜就绪、没有整柜泄漏、没有进行中的任务"], ["目标主机名", "新建安装任务时逐台确定", "同时是 NICo 里的实例名称；装好后是系统里的主机名"], ["安装方案", "安装方案档案", "逐台选用，架构要和设备一致"], ["系统盘", "安装方案的选盘规则，或逐台指定", "默认按方案的规则选；个别设备可以指定一块盘"], ["地址", "NICo", "主机管理地址由 NICo 分配，不在这里填写"]],
    rules: ["装系统按台进行：一台机器一个实例。可以跨机柜选择，也可以选不属于机柜的服务器。", "主机名逐台确定：默认按“前缀 + 两位序号”生成，每一台都可以改。只能用小写字母、数字和连字符，不能和已有的实例重名。", "安装方案按架构匹配：只列出已发布、架构与设备一致的方案。", "带维护标记、已隔离或有阻止分配告警的设备不能选；机柜未就绪、有整柜泄漏或有进行中任务时，柜里的设备不能选。原因写在每一行上，平台不提供绕过。", "不属于机柜的服务器纳管后还没有被接管的也可以选：安装任务的第一步“准备设备”让 NICo 给它上电并接管，之后才写系统盘。", "所有实例建在站点的默认租户下，页面上不出现租户；平台不向其他平台分发机器。", "同时装机的台数取站点的默认安装并发。", "阶段用词：等待执行、准备设备、安装前检查、安装系统、启动系统盘、安装验收、GPU 环境检查、重启验收、完成。", "状态用词：待执行、执行中、已完成、需处理、已终止。", "失败的设备暂停等待处理，不影响同批其他设备。"],
    dialogs: [
      { name: "新建安装任务 · 步骤 1 选择设备", desc: "列出服务器，每一行写明现在能不能装系统和原因。范围可以选“全部可以安装的服务器”、某个机柜或“未分配机柜”，只是筛选，可以跨范围累计选择。", fields: [["范围", "否", "全部可以安装的服务器、某个机柜、未分配机柜"], ["勾选设备", "是", "不能安装的行不能勾选"]] },
      { name: "新建安装任务 · 步骤 2 逐台配置", desc: "一台一行。上方的规则用来批量生成，表里每一格都可以单独改。", fields: [["主机名前缀、起始序号", "否", "按“前缀-两位序号”批量生成主机名"], ["安装方案（按架构）", "否", "把同一架构的设备统一设成一个方案"], ["主机名", "是，逐台", "同时是实例名称；不合规或重名时在这一行下面提示"], ["安装方案", "是，逐台", "只列出已发布、架构一致的方案"], ["系统盘", "否，逐台", "默认“按安装方案的规则选择”；可以指定这台设备的一块盘"]] },
      { name: "新建安装任务 · 步骤 3 核对并确认", desc: "显示设备数量和分布、各方案的台数、指定了系统盘的台数、要先接管的台数和并发，以及逐台的主机名。", fields: [["原因", "是", "写入批次和审计"], ["确认所选设备、主机名、安装方案及系统盘", "是", "勾选"], ["允许安装及重启验证", "是", "勾选"]] },
    ],
  },
});
registerAction("install-batch", ({ id }) => { S.view.insBatch = id; S.view.insSt = ""; render(); });
registerAction("install-detail", ({ id, batch }) => {
  const t = DB.tray(id), b = S.installs.find((x) => x.id === batch), i = b.items.find((x) => x.tray === id), done = i.s === "done";
  modal("物理机安装记录", t.serial, defs([["设备", code(t.serial) + ` · ${typeLabel(t)}`], ["位置", placeText(t)], ["目标主机名", code(i.host)], ["实例", done ? code("inst-" + i.host) : "安装完成后建立"], ["安装方案", esc(i.os)], ["目标盘", i.disk ? "指定 " + esc(i.disk) : "按安装方案的规则选择"], ["本次安装目标地址", t.hostIp ? code(t.hostIp) : "接管后由 NICo 分配"], ["BMC 控制台", `https://${t.bmcIp} ↗`], ["阶段 / 状态", `${ITEM_STAGE[i.s][0]} · ${ITEM_STAGE[i.s][1]}`]]) +
    `<h3 class="section-title">安装验收</h3>` + table(["检查项", "结果"], ["安装器成功", "主机配置", "系统盘与 EFI 分区验证", "网络配置", "SSH 连通", "GPU 环境检查", "重启验收"].map((c) => `<tr><td>${c}</td><td>${done ? badge("通过", "green") : badge("待执行", "gray")}</td></tr>`)), button("下载验收报告", "noop") + button("关闭", "close", true));
});

/* ---------- 新建安装任务向导 ----------
   向导的状态放在 S.view.wiz：范围、已选的设备、主机名规则、逐台的主机名 / 安装方案 / 系统盘。 */
const wiz = () => S.view.wiz;
const wizList = () => Object.keys(wiz().picked).map(DB.tray).filter((t) => t && !installGate(t)).sort((a, b) => (a.rack ? 0 : 1) - (b.rack ? 0 : 1) || a.rack.localeCompare(b.rack) || a.slot - b.slot || a.id.localeCompare(b.id));
function wizKeepPicks() { const w = wiz(); document.querySelectorAll("[data-wiz-pick]").forEach((el) => { if (el.checked) w.picked[el.dataset.wizPick] = true; else delete w.picked[el.dataset.wizPick]; }); }
function wizKeepRows() { const w = wiz(); document.querySelectorAll("[data-wiz-host]").forEach((el) => (w.rows[el.dataset.wizHost].host = el.value.trim())); document.querySelectorAll("[data-wiz-os]").forEach((el) => (w.rows[el.dataset.wizOs].os = el.value)); document.querySelectorAll("[data-wiz-disk]").forEach((el) => (w.rows[el.dataset.wizDisk].disk = el.value)); if ($("#wiz-prefix")) { w.prefix = $("#wiz-prefix").value.trim(); w.start = Math.max(0, +$("#wiz-start").value || 0); } }
function wizApplyRule(force) { const w = wiz(); wizList().forEach((t, n) => { const row = w.rows[t.id]; if (force || !row.host) row.host = `${w.prefix}-${pad2(w.start + n)}`; }); }

registerAction("install-new", ({ rack, ids }) => {
  const asked = (ids || "").split(",").filter(Boolean).map(DB.tray).filter(Boolean), pre = asked.filter((t) => !installGate(t)), picked = {};
  (pre.length ? pre : rack ? DB.rack(rack).trays.filter((t) => t.type === "compute" && !installGate(t)) : []).forEach((t) => (picked[t.id] = true));
  const one = asked.length && asked.every((t) => t.rack === asked[0].rack) ? asked[0].rack || "none" : "";
  S.view.wiz = { scope: rack || one, picked, prefix: "", start: 1, rows: {}, why: "" };
  installStep1();
  if (asked.length && !pre.length) toast("所选的设备现在都不能装系统，原因见每一行");
  else if (asked.length > pre.length) toast(`所选的 ${asked.length} 台里有 ${asked.length - pre.length} 台现在不能装系统，已去掉`);
});
function installStep1() {
  const w = wiz(), all = servers(), list = all.filter((t) => (w.scope === "" ? !installGate(t) : w.scope === "none" ? !t.rack : t.rack === w.scope));
  const hidden = w.scope === "" ? all.filter(installGate).length : 0, count = () => Object.keys(w.picked).length;
  const opts = [["", "全部可以安装的服务器"], ...S.racks.map((r) => [r.id, r.id]), ["none", "未分配机柜"]].map(([v, text]) => `<option value="${v}" ${w.scope === v ? "selected" : ""}>${text}</option>`).join("");
  modal("新建安装任务", "步骤 1 / 3 · 选择设备",
    `<div class="filter-bar"><label>范围<select class="input" id="wiz-scope">${opts}</select></label><span class="live-small">装系统按台进行，一台机器一个实例。范围只是筛选，可以切换范围累计选择。已选 <b id="wiz-count">${count()}</b> 台。</span></div>` +
    table(["选择", "设备 / 序列号", "机柜 / 位置", "架构", "NICo 状态", "能否安装"], list.map((t) => { const g = installGate(t);
      return `<tr><td><input type="checkbox" data-wiz-pick="${t.id}" ${w.picked[t.id] && !g ? "checked" : ""} ${g ? "disabled" : ""} aria-label="选择 ${t.serial}"></td><td>${code(t.serial)}<span class="cell-sub">${typeLabel(t)} · ${esc(t.model)}</span></td><td>${placeText(t)}</td><td>${code(t.arch)}</td><td>${t.state ? stateBadge(t.state) : t.declared ? badge("已纳管", "blue") : badge("未纳管", "gray")}</td><td>${g ? badge("不能安装：" + g, "gray") : badge("可以安装", "green") + (t.state ? "" : `<span class="cell-sub">安装时先由 NICo 上电接管</span>`)}</td></tr>`; }), "这个范围里没有服务器。") +
    (hidden ? `<p class="live-small">另有 ${hidden} 台服务器现在不能装系统。选择具体的机柜或“未分配机柜”可以看到每一台的原因。</p>` : ""),
    button("取消", "close") + button("全选可以安装的", "install-all") + button("下一步", "install-to-2", true));
  $("#wiz-scope").onchange = (e) => { wizKeepPicks(); w.scope = e.target.value; installStep1(); };
  $("#overlay-root .modal-body").addEventListener("change", (e) => { if (e.target.dataset.wizPick) { wizKeepPicks(); $("#wiz-count").textContent = count(); } });
}
registerAction("install-all", () => { document.querySelectorAll("[data-wiz-pick]:not([disabled])").forEach((el) => (el.checked = true)); wizKeepPicks(); $("#wiz-count").textContent = Object.keys(wiz().picked).length; });
registerAction("install-to-2", () => {
  const w = wiz(); if ($("[data-wiz-pick]") || $("#wiz-scope")) wizKeepPicks();
  const list = wizList(); if (!list.length) return toast("先勾选要装系统的设备");
  Object.keys(w.picked).forEach((id) => { if (!list.some((t) => t.id === id)) delete w.picked[id]; });
  if (!w.prefix) { const racks = [...new Set(list.map((t) => t.rack))]; w.prefix = racks.length === 1 ? (racks[0] ? "node-" + racks[0].slice(-3).toLowerCase() : "node-srv") : "node"; }
  list.forEach((t) => { w.rows[t.id] = w.rows[t.id] || { host: "", os: (osReady(t.arch)[0] || {}).id || "", disk: "" }; });
  wizApplyRule(false); installStep2();
});
function installStep2() {
  const w = wiz(), list = wizList(), hosts = list.map((t) => w.rows[t.id].host), archs = [...new Set(list.map((t) => t.arch))];
  modal("新建安装任务", "步骤 2 / 3 · 逐台配置",
    `<div class="filter-bar"><label>主机名前缀<input class="input live-code" id="wiz-prefix" value="${esc(w.prefix)}"></label><label>起始序号<input class="input" id="wiz-start" type="number" min="0" value="${w.start}" style="width:96px"></label>${button("按规则重新生成", "install-rule")}` +
      archs.map((a) => `<label>安装方案（${a}）<select class="input" data-wiz-os-all="${a}">${osReady(a).map((o) => `<option>${esc(o.id)}</option>`).join("") || "<option value=\"\">没有已发布的方案</option>"}</select></label>`).join("") + `</div>` +
    `<p class="live-small">主机名按“前缀-两位序号”生成，每一台都可以单独改。<b>主机名同时是 NICo 里的实例名称，装好后就是系统里的主机名。</b>安装方案按设备的架构列出；系统盘默认按方案的规则选，个别设备可以指定一块盘。地址由 NICo 分配，不在这里填。</p>` +
    table(["设备 / 位置", "架构", "主机名", "安装方案", "系统盘"], list.map((t) => { const row = w.rows[t.id], p = w.checked ? hostProblem(row.host, hosts) : "", os = osReady(t.arch);
      return `<tr><td>${code(t.serial)}<span class="cell-sub">${placeText(t)}${t.state ? "" : " · 安装时先接管"}</span></td><td>${code(t.arch)}</td><td><input class="input live-code" data-wiz-host="${t.id}" value="${esc(row.host)}" aria-label="${t.serial} 的主机名">${p ? `<span class="cell-sub" style="color:var(--red)">${p}</span>` : ""}</td>
        <td><select class="input" data-wiz-os="${t.id}" data-arch="${t.arch}" aria-label="${t.serial} 的安装方案">${os.map((o) => `<option ${o.id === row.os ? "selected" : ""}>${esc(o.id)}</option>`).join("") || "<option value=\"\">没有这个架构的已发布方案</option>"}</select></td>
        <td><select class="input" data-wiz-disk="${t.id}" aria-label="${t.serial} 的系统盘"><option value="">按安装方案的规则选择</option>${t.disks.map((d) => `<option ${d === row.disk ? "selected" : ""}>${d}</option>`).join("")}</select></td></tr>`; })),
    button("上一步", "install-back-1") + button("下一步", "install-to-3", true));
  document.querySelectorAll("[data-wiz-os-all]").forEach((el) => { const cur = list.filter((t) => t.arch === el.dataset.wizOsAll).map((t) => w.rows[t.id].os); if (new Set(cur).size === 1) el.value = cur[0];
    el.onchange = () => document.querySelectorAll(`[data-wiz-os][data-arch="${el.dataset.wizOsAll}"]`).forEach((s) => (s.value = el.value)); });
}
registerAction("install-rule", () => { wizKeepRows(); if (!wiz().prefix) return toast("先填写主机名前缀"); wizApplyRule(true); installStep2(); });
registerAction("install-back-1", () => { wizKeepRows(); wiz().checked = false; installStep1(); });
registerAction("install-to-3", () => {
  wizKeepRows(); const w = wiz(), list = wizList(), hosts = list.map((t) => w.rows[t.id].host);
  const bad = list.filter((t) => hostProblem(w.rows[t.id].host, hosts)).length, noOs = list.filter((t) => !w.rows[t.id].os).length;
  if (bad || noOs) { w.checked = true; installStep2(); return toast(bad ? `${bad} 台的主机名需要修改` : `${noOs} 台没有可用的安装方案，先在“安装方案”里发布对应架构的方案`); }
  const byOs = {}; list.forEach((t) => (byOs[w.rows[t.id].os] = (byOs[w.rows[t.id].os] || 0) + 1));
  const fixed = list.filter((t) => w.rows[t.id].disk).length, cold = list.filter((t) => !t.state).length;
  modal("新建安装任务", "步骤 3 / 3 · 核对并确认",
    `<div class="confirm-facts">${defs([["设备", `<b>${list.length} 台</b> · ${scopeText(list)}`], ["安装方案", Object.entries(byOs).map(([k, v]) => `${esc(k)}：${v} 台`).join("<br>")], ["系统盘", fixed ? `${list.length - fixed} 台按方案的规则选盘，<b>${fixed} 台指定了系统盘</b>` : "全部按方案的规则选盘"], ...(cold ? [["要先接管", `<b>${cold} 台</b>还没有被 NICo 接管：安装任务先让 NICo 给它上电并接管，按站点策略可能清理全部磁盘`]] : []), ["受影响的实例", "0 个"], ["并发", "按站点的默认安装并发，同时 5 台"], ["会发生什么", "每台建一个实例，实例名称就是主机名；机器从网络引导安装器，<b>写系统盘</b>，装完重启并验收"]])}</div>` +
    table(["设备 / 位置", "主机名", "安装方案", "系统盘"], list.slice(0, 8).map((t) => { const row = w.rows[t.id]; return `<tr><td>${code(t.serial)}<span class="cell-sub">${placeText(t)}</span></td><td>${code(row.host)}</td><td>${esc(row.os)}</td><td>${row.disk ? "指定 " + esc(row.disk) : "按方案的规则"}</td></tr>`; })) + (list.length > 8 ? `<p class="live-small">显示前 8 台，共 ${list.length} 台。回到上一步可以查看和修改全部。</p>` : "") +
    `<div class="live-form" style="margin-top:14px">${field("原因", `<input class="input" id="wiz-why" value="${esc(w.why)}" placeholder="工单号或原因">`)}</div>
     <label class="live-check"><input type="checkbox" id="wiz-c1"> 确认所选设备、主机名、安装方案及系统盘。</label><label class="live-check"><input type="checkbox" id="wiz-c2"> 允许安装及重启验证。</label>`,
    button("上一步", "install-back-2") + button("确认并安装", "install-run", true));
});
registerAction("install-back-2", () => { wiz().why = $("#wiz-why").value.trim(); installStep2(); });
registerAction("install-run", () => {
  const w = wiz(), why = $("#wiz-why").value.trim(); if (!why) return toast("请填写原因");
  if (!$("#wiz-c1").checked || !$("#wiz-c2").checked) return toast("请勾选确认项");
  const list = wizList(), b = { id: "batch-" + String(S.installs.length + 6).padStart(3, "0"), at: nowText(), by: "ops-01", why, items: list.map((t) => ({ tray: t.id, host: w.rows[t.id].host, os: w.rows[t.id].os, disk: w.rows[t.id].disk, s: "wait" })) };
  S.installs.unshift(b); const rec = addAudit("安装批次 " + b.id, `新建安装任务（${list.length} 台）`, why, "—", "已提交"); closeModal(); S.view.wiz = null; S.guide = Math.max(S.guide, 7); S.view.insBatch = b.id; S.view.insSt = "";
  /* 模拟：同时最多 5 台。还没有被接管的服务器先经过“准备设备”，由 NICo 上电接管。 */
  b.timer = setInterval(() => {
    b.items.filter((i) => i.s === "run").forEach((i) => { const t = DB.tray(i.tray), o = S.osTemplates.find((x) => x.id === i.os); i.s = "done"; t.state = "Assigned/Ready"; t.instance = "inst-" + i.host; if (o) o.used++; S.instances.push({ id: t.instance, tray: t.id, rack: t.rack, host: i.host, os: i.os, state: "Ready", ip: t.hostIp, created: nowText() }); });
    b.items.filter((i) => i.s === "prep").forEach((i) => { takeOverServer(DB.tray(i.tray)); i.s = "run"; });
    const active = b.items.filter((i) => i.s === "run").length;
    b.items.filter((i) => i.s === "wait").slice(0, Math.max(0, 5 - active)).forEach((i) => (i.s = DB.tray(i.tray).state ? "run" : "prep"));
    if (b.items.every((i) => i.s === "done")) { clearInterval(b.timer); b.timer = 0; rec.res = `验收通过 ${b.items.length}/${b.items.length}`; toast(`${b.id}：${b.items.length} 台安装完成并通过验收`); }
    render();
  }, 1000);
  go("delivery/installs");
});

/* ---------- 实例管理 ---------- */
registerPage("delivery/instances", {
  module: "instances", title: "实例管理",
  render() {
    const f = { rack: view("instRack", ""), q: view("instQ", "").toLowerCase() };
    const list = S.instances.filter((i) => (!f.rack || (f.rack === "none" ? !i.rack : i.rack === f.rack)) && (!f.q || [i.id, i.host, i.ip, DB.tray(i.tray).serial, i.os].join(" ").toLowerCase().includes(f.q)));
    return heading("实例管理", "查看已经装好系统的实例，删除实例并回收设备。", button("刷新数据", "refresh") + act("新建安装任务", "install-new", { primary: true })) +
      `<div class="filter-bar" ${fp(1)}>${selectField("instRack", "机柜", [["", "全部"], ...S.racks.map((r) => [r.id, r.id]), ["none", "未分配机柜"]], f.rack)}${searchField("instQ", "搜索实例", view("instQ", ""), "名称、编号、序列号、主机名、IP")}<span class="live-small">${list.length} 个当前实例</span></div>` +
      `<div ${fp(2)}>${table(["实例名称 / ID", "设备序列号 / 位置", "实例地址 / 操作系统", "机器状态 / 回收进度", "操作"], list.map((i) => { const t = DB.tray(i.tray); return `<tr><td><strong>${i.host}</strong><span class="cell-sub live-code">${i.id}</span></td><td>${code(t.serial)}<span class="cell-sub">${t.rack ? `<a class="link-button" data-go="rack/${t.rack}">${t.rack}</a> 槽位 ${pad2(t.slot)}` : "未分配机柜"}</span></td><td>${code(i.ip)}<span class="cell-sub">${esc(i.os)}</span></td><td>${stateBadge(i.releasing ? "回收中" : t.state)}${i.releasing ? `<span class="cell-sub">实例已移除，设备准备中</span>` : ""}</td><td><div class="inline-actions">${button("详情", "tray-detail", false, `data-id="${t.id}"`)}<span ${fp(3)}>${act("删除（退租回收）", "inst-release", { gate: i.releasing ? "正在回收" : "", extra: `data-id="${i.id}"`, compact: true })}</span></div></td></tr>`; }), "未找到匹配的实例。")}</div>` +
      note("实例名称就是系统里的主机名，在新建安装任务时逐台确定。删除实例会发起 NICo 回收：清理磁盘并重新校验。清理完成前，这台设备不能再装系统。");
  },
  spec: {
    purpose: "查看已经装好系统的实例，并在不再使用时删除实例、回收设备。一台机器一个实例。", entry: "交付 → 实例管理", design: "6.4 交付（释放与复用）", existing: "实例管理页。表头、回收用词和确认弹窗沿用，增加机柜和位置",
    points: [
      { n: 1, name: "筛选", kind: "调整", desc: "沿用搜索；增加按机柜筛选，可以选“未分配机柜”。" },
      { n: 2, name: "实例表", kind: "调整", desc: "实例名称 / ID、设备序列号、实例地址 / 操作系统、机器状态 / 回收进度沿用；设备序列号下面增加机柜和位置。" },
      { n: 3, name: "删除（退租回收）", kind: "沿用", desc: "按钮名称、输入设备序列号确认、清理全部磁盘的勾选项都与现有页面一致。" },
    ],
    fields: [["实例名称", "新建安装任务时逐台确定的主机名", "同时是系统里的主机名"], ["实例地址", "NICo", "主机管理网段里分配的地址"]],
    rules: ["一台机器同一时间只有一个实例。", "回收完成并重新校验通过前，设备不能再装系统。", "回收用词：回收请求已接受、实例已移除设备准备中、回收完成、设备回收失败需处理。", "页面上不出现租户：所有实例建在站点的默认租户下。"],
    dialogs: [{ name: "删除（退租回收）", desc: "沿用现有弹窗。", fields: [["输入设备序列号确认范围", "是", ""], ["允许清理本机全部磁盘并回收实例资源。", "是", "勾选"]] }],
  },
});
registerAction("inst-release", ({ id }) => {
  const i = S.instances.find((x) => x.id === id), t = DB.tray(i.tray);
  modal("删除（退租回收）", i.host, defs([["实例名称 / ID", `${i.host} · ${code(i.id)}`], ["设备序列号", code(t.serial)], ["位置", placeText(t)], ["影响", "实例被删除；NICo 清理本机全部磁盘并重新校验"]]) +
    `<div class="live-form" style="margin-top:16px">${field("输入设备序列号确认范围", `<input class="input live-code" id="rl-sn" autocomplete="off" placeholder="${t.serial}">`)}</div><label class="live-check"><input type="checkbox" id="rl-ok"> 允许清理本机全部磁盘并回收实例资源。</label>`,
    button("取消", "close") + `<button class="button danger" data-live="inst-release-run" data-id="${id}">确认删除并回收</button>`, { wide: false });
});
registerAction("inst-release-run", ({ id }) => {
  const i = S.instances.find((x) => x.id === id), t = DB.tray(i.tray);
  if ($("#rl-sn").value.trim() !== t.serial) return toast("输入的序列号与设备不一致");
  if (!$("#rl-ok").checked) return toast("请勾选确认项");
  closeModal(); i.releasing = true; const rec = addAudit(t.rack ? placeText(t) : t.serial, "删除（退租回收）", "不再使用", "—", "回收请求已接受"); render();
  setTimeout(() => { S.instances = S.instances.filter((x) => x.id !== id); t.instance = ""; t.state = "Ready"; rec.res = "回收完成，重新校验通过"; toast(`${t.serial}：回收完成，可以再次装系统`); render(); }, 2600);
});
