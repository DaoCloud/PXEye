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
    entry: "交付 → 安装任务；机柜详情“装系统”一步里的“新建安装任务”；服务器列表和设备发现里的“新建安装任务”", design: "5 整体操作运维流程（交付）；6.4 交付", existing: "安装任务页。表头、阶段和状态用词、任务详情和“新建安装任务”向导都沿用：向导的选择设备、核对配置两步和安装条件检查照搬，中间增加“逐台配置”一步",
    points: [
      { n: 1, name: "新建安装任务", kind: "调整", desc: "打开三步向导：选择设备、逐台配置、核对配置。第一步和第三步沿用现有向导的页面和检查项；第二步是新增的，因为整机柜的清单里没有主机名和安装方案。从机柜详情、服务器列表或设备发现进入时，向导里已经选好了设备。" },
      { n: 2, name: "统计条", kind: "新增", desc: "现在可以装系统的服务器数、进行中的批次、正在安装的台数、已装好的实例数。" },
      { n: 3, name: "安装批次", kind: "沿用", desc: "一次提交是一个批次：设备数量和分布、用到的安装方案、设备进度、原因和操作者。" },
      { n: 4, name: "筛选", kind: "调整", desc: "按批次和是否完成筛选逐台任务。" },
      { n: 5, name: "逐台任务", kind: "沿用", desc: "任务 / 创建时间、设备、目标主机名、阶段 / 状态、操作沿用；增加“位置”和“安装方案 / 系统盘”，因为这两项现在逐台确定。" },
      { n: 6, name: "任务详情", kind: "沿用", desc: "点击任务编号或“实时日志 / 记录”打开现有的“物理机安装记录”：状态、安装进度、实时日志、执行与恢复记录、安装验收。" },
    ],
    fields: [["可以装系统", "NICo 的机器状态 + 平台检查", "机器就绪、没有实例、没有隔离和维护标记、没有阻止分配的告警；机柜里的还要求机柜就绪、没有整柜泄漏、没有进行中的任务"], ["目标主机名", "新建安装任务时逐台确定", "同时是 NICo 里的实例名称；装好后是系统里的主机名"], ["安装方案", "安装方案档案", "逐台选用，架构要和设备一致"], ["系统盘", "安装方案的选盘规则，或逐台指定", "默认按方案的规则选；个别设备可以指定一块盘"], ["地址", "NICo", "主机管理地址由 NICo 分配，不在这里填写"]],
    rules: ["装系统按台进行：一台机器一个实例。可以跨机柜选择，也可以选不属于机柜的服务器。每批最多 50 台。", "提交前必须通过安装条件检查。检查分三组，逐台进行：设备身份（BMC 认证与序列号）；安装配置（机器就绪且没有实例、主机名与安装方案、管理地址与地址占用、系统盘）；操作系统材料（安装材料可以取到，长度与登记一致）。任何一台的任何一项不通过，整批不能提交。", "系统盘按安装方案的选盘规则解析，必须解析出唯一的一块盘。已经被接管的设备在“逐台配置”里就能看出来：解析不出的标为需要处理，指定一块盘后才能进入下一步；安装条件检查时再核对一次。", "检查通过只表示当时可以执行：提交时服务端再检查一次配置和占用，执行前另做安装材料的完整摘要校验。", "“当前系统”按需查询，只读：用来在覆盖系统盘之前看一眼设备上现在是什么。状态用词：未查询、已关机、无 SSH 无法访问、已读取系统、发现 / 安装环境。", "主机名逐台确定：默认按“前缀 + 两位序号”生成，每一台都可以改。只能用小写字母、数字和连字符，不能和已有的实例重名。", "安装方案按架构匹配：只列出已发布、架构与设备一致的方案。", "带维护标记、已隔离或有阻止分配告警的设备不能选；机柜未就绪、有整柜泄漏或有进行中任务时，柜里的设备不能选。原因写在每一行上，平台不提供绕过。", "不属于机柜的服务器纳管后还没有被接管的也可以选，安装条件显示“自动准备”：安装任务的第一步“准备设备”让 NICo 给它上电并接管，之后才写系统盘。它的“机器就绪”和“系统盘”两项标为“执行前确定”，不算失败；首次接入会清理全部磁盘，要另外勾选确认。", "所有实例建在站点的默认租户下，页面上不出现租户；平台不向其他平台分发机器。", "同时装机的台数取站点的默认安装并发。", "阶段用词：等待执行、准备设备、安装前检查、安装系统、启动系统盘、安装验收、GPU 环境检查、重启验收、完成。", "状态用词：待执行、执行中、已完成、需处理、已终止。", "失败的设备暂停等待处理，不影响同批其他设备。"],
    dialogs: [
      { name: "新建安装任务 · 步骤 1 选择设备", desc: "沿用现有向导的第一步。列出服务器，每一行有“当前系统”和“安装条件”：安装条件写明可预检、自动准备，或不可选及其原因。底部显示“显示 N / M 台 · 已选 n / 50 台”。", fields: [["搜索、机柜、CPU 架构、当前系统", "否", "筛选。现有向导里的“管理网段”换成“机柜”，可以选“未分配机柜”"], ["仅看可选设备、仅看已选", "否", ""], ["查询当前系统", "否", "查询已选的设备；没有选择时查询当前筛选结果，最多 50 台"], ["勾选设备", "是", "不可选的行不能勾选；每批最多 50 台"]] },
      { name: "新建安装任务 · 步骤 2 逐台配置", desc: "新增的一步。这一页只要人做一件事：给每台机器确定主机名。页面从上到下三块：一句话说明要做什么；三项默认值（主机名规则、按架构的默认安装方案、默认系统盘）；逐台确认的表。表里只有主机名是输入框，安装方案和系统盘直接显示按默认值得到的结果；个别设备要不一样时点“单独设置”才展开成下拉框。需要人处理的设备（主机名不合规或重名、方案规则定不出唯一的系统盘）标红并排在最前面，上方显示“需要处理 N 台”；全部处理完才能进入下一步。现有产品里这些值来自事先保存的设备规划；整机柜的清单里没有，所以在这里确定。", fields: [["主机名规则：前缀、起始序号", "否", "按“前缀-两位序号”批量生成，旁边预览生成的范围；“重新生成”覆盖全部主机名"], ["默认安装方案（按架构）", "否", "每种架构一个下拉框，写明这种架构有几台；只列出已发布的方案"], ["主机名", "是，逐台", "同时是实例名称；不合规或重名时在这一行下面即时提示"], ["单独设置", "否，逐台", "展开这一台的安装方案和系统盘；改过的设备标“已单独设置”，可以“恢复默认”"], ["系统盘", "规则定不出时必填", "默认显示按方案规则解析出的那块盘；规则匹配到不止一块盘时，这一格直接是下拉框，要求选一块"], ["只看需要处理的", "否", "有需要处理的设备时出现"]] },
      { name: "新建安装任务 · 步骤 3 核对配置", desc: "沿用现有向导的第二步。上面是逐台的配置表（目标 OS / 方案、主机名 / 管理地址、系统盘）；中间是“安装条件”面板，三组检查各显示已通过、需处理或检查中；不通过的项目逐条列出设备、检查名和原因；需要首次接入的设备提示“将清理全部磁盘”。全部通过后才出现影响说明和确认项。", fields: [["修改配置", "否", "回到第二步；改完重新检查"], ["更新状态", "否", "重新执行一次检查"], ["原因", "是", "写入批次和审计"], ["确认所选设备、主机名、管理地址及系统盘", "是", "勾选"], ["允许安装及重启验证", "是", "勾选"], ["允许需接入设备清理全部磁盘", "有首次接入的设备时", "勾选；含非系统盘"]] },
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
   向导的页面和检查项沿用现有产品的“新建安装任务”：选择设备（带“当前系统”和“安装条件”两列）、核对配置（安装条件检查、失败明细、清理范围、执行确认）。
   与现有产品不同的只有中间多一步“逐台配置”：现有产品的主机名、安装方案和系统盘来自事先保存的设备规划，
   整机柜的到货清单里没有这些，所以在向导里一台一行地确定。
   向导的状态放在 S.view.wiz：筛选条件、已选的设备、主机名规则、逐台的主机名 / 安装方案 / 系统盘、检查结果。 */
const WIZ_STEPS = ["选择设备", "逐台配置", "核对配置"], WIZ_MAX = 50;
const wizHead = (n) => `<div class="live-step">${WIZ_STEPS.map((s, i) => `<${n === i + 1 ? "strong" : "span"}>${i + 1}. ${s}</${n === i + 1 ? "strong" : "span"}>`).join(" → ")}</div>`;
const wiz = () => S.view.wiz;
const wizList = () => Object.keys(wiz().picked).map(DB.tray).filter((t) => t && !installGate(t)).sort((a, b) => (a.rack ? 0 : 1) - (b.rack ? 0 : 1) || a.rack.localeCompare(b.rack) || a.slot - b.slot || a.id.localeCompare(b.id));
function wizKeepPicks() { const w = wiz(); document.querySelectorAll("[data-wiz-pick]").forEach((el) => { if (el.checked) w.picked[el.dataset.wizPick] = true; else delete w.picked[el.dataset.wizPick]; }); }
function wizKeepRows() { const w = wiz(); document.querySelectorAll("[data-wiz-host]").forEach((el) => (w.rows[el.dataset.wizHost].host = el.value.trim())); document.querySelectorAll("[data-wiz-os]").forEach((el) => (w.rows[el.dataset.wizOs].os = el.value)); document.querySelectorAll("select[data-wiz-disk]").forEach((el) => (w.rows[el.dataset.wizDisk].disk = el.value)); if ($("#wiz-prefix")) { w.prefix = $("#wiz-prefix").value.trim(); w.start = Math.max(0, +$("#wiz-start").value || 0); } }
function wizApplyRule(force) { const w = wiz(); wizList().forEach((t, n) => { const row = w.rows[t.id]; if (force || !row.host) row.host = `${w.prefix}-${pad2(w.start + n)}`; }); }
/* 安装条件：这台设备现在能不能选，选了之后是直接检查还是要先由 NICo 接管。用词沿用现有产品。 */
function installCondition(t) {
  const g = installGate(t);
  if (g) return { ok: false, text: "不可选", color: "gray", reason: g };
  return t.state ? { ok: true, text: "可预检", color: "green", reason: "可检查安装条件" } : { ok: true, text: "自动准备", color: "amber", reason: "安装时自动准备：由 NICo 上电并接管" };
}
/* 当前系统：安装前按需查询设备上现在是什么，用来在覆盖系统盘之前再看一眼。状态用词沿用现有产品。 */
const SYS_LABEL = { unknown: "未查询", off: "已关机", unreachable: "无 SSH，无法访问", os: "已读取系统", temporary: "发现 / 安装环境" };
const curSys = (t) => S.currentSystems[t.id] || { status: "unknown" };
const sysCell = (t) => { const v = curSys(t); return v.pending ? "查询中…" : esc(v.status === "os" ? v.label : SYS_LABEL[v.status]) + (v.at ? `<span class="cell-sub">${v.at}</span>` : ""); };

registerAction("install-new", ({ rack, ids }) => {
  const asked = (ids || "").split(",").filter(Boolean).map(DB.tray).filter(Boolean), pre = asked.filter((t) => !installGate(t)), picked = {};
  (pre.length ? pre : rack ? DB.rack(rack).trays.filter((t) => t.type === "compute" && !installGate(t)) : []).slice(0, WIZ_MAX).forEach((t) => (picked[t.id] = true));
  const one = asked.length && asked.every((t) => t.rack === asked[0].rack) ? asked[0].rack || "none" : "", scope = rack || one;
  S.view.wiz = { filters: { scope, arch: "", sys: "", q: "", available: !scope, selected: false }, picked, prefix: "", start: 1, rows: {}, why: "", check: null };
  installStep1();
  if (asked.length && !pre.length) toast("所选的设备现在都不能装系统，原因见“安装条件”一列");
  else if (asked.length > pre.length) toast(`所选的 ${asked.length} 台里有 ${asked.length - pre.length} 台现在不能装系统，已去掉`);
});
function wizVisible() {
  const f = wiz().filters, q = f.q.toLowerCase();
  return servers().filter((t) => (!f.scope || (f.scope === "none" ? !t.rack : t.rack === f.scope)) && (!f.arch || t.arch === f.arch) && (!f.sys || curSys(t).status === f.sys) && (!f.available || !installGate(t)) && (!f.selected || wiz().picked[t.id]) &&
    (!q || [t.serial, t.model, t.rack, t.bmcIp, t.bmcMac, t.hostIp, t.hostMac].join(" ").toLowerCase().includes(q)));
}
function wizRenderList() {
  const w = wiz(), list = wizVisible(), n = Object.keys(w.picked).length, hidden = Object.keys(w.picked).filter((id) => !list.some((t) => t.id === id)).length;
  $("#wiz-list").innerHTML = table(["选择", "设备 / 型号", "机柜 / 位置", "CPU 架构", "BMC 地址 / MAC", "管理地址", "当前系统", "安装条件"], list.map((t) => { const c = installCondition(t);
    return `<tr><td><input type="checkbox" data-wiz-pick="${t.id}" ${w.picked[t.id] && c.ok ? "checked" : ""} ${c.ok ? "" : "disabled"} aria-label="选择 ${t.serial}"></td><td><strong>${t.serial}</strong><span class="cell-sub">${typeLabel(t)} · ${esc(t.model)}</span></td><td>${placeText(t)}</td><td>${code(t.arch)}</td><td>${code(t.bmcIp)}<span class="cell-sub live-code">${t.bmcMac}</span></td><td>${t.hostIp ? code(t.hostIp) : `<span class="muted">接管后由 NICo 分配</span>`}</td><td>${sysCell(t)}</td><td>${badge(c.text, c.color)}<span class="cell-sub">${esc(c.reason)}</span></td></tr>`; }),
    "未找到匹配的设备，请调整筛选。");
  $("#wiz-summary").textContent = `显示 ${list.length} / ${servers().length} 台 · 已选 ${n} / ${WIZ_MAX} 台${hidden ? "（筛选外 " + hidden + " 台）" : ""}`;
}
function installStep1() {
  const w = wiz(), f = w.filters, opt = (list, cur) => list.map(([v, text]) => `<option value="${v}" ${cur === v ? "selected" : ""}>${text}</option>`).join("");
  w.step = 1;
  modal("新建安装任务", "步骤 1 / 3", wizHead(1) +
    `<div class="batch-filter-grid"><label>搜索设备<input class="input" type="search" id="wiz-q" value="${esc(f.q)}" placeholder="序列号、IP、MAC、型号"></label>
      <label>机柜<select class="input" id="wiz-scope">${opt([["", "全部"], ...S.racks.map((r) => [r.id, r.id]), ["none", "未分配机柜"]], f.scope)}</select></label>
      <label>CPU 架构<select class="input" id="wiz-arch">${opt([["", "全部架构"], ["aarch64", "aarch64"], ["x86_64", "x86_64"]], f.arch)}</select></label>
      <label>当前系统<select class="input" id="wiz-sys">${opt([["", "全部系统状态"], ...Object.entries(SYS_LABEL)], f.sys)}</select></label></div>
     <div class="live-tools batch-selection-tools"><label><input id="wiz-available" type="checkbox" ${f.available ? "checked" : ""}> 仅看可选设备</label><label><input id="wiz-selected" type="checkbox" ${f.selected ? "checked" : ""}> 仅看已选</label><button class="link-button" data-live="install-sysquery" title="查询已选设备；未选择时查询当前筛选结果，最多 ${WIZ_MAX} 台">查询当前系统</button><span id="wiz-summary" role="status" aria-live="polite"></span></div>
     <div id="wiz-list" class="batch-device-list"></div>
     <p class="live-small">装系统按台进行，一台机器一个实例；机柜只是筛选条件，可以切换筛选累计选择，每批最多 ${WIZ_MAX} 台。已有安装任务、已有实例或回收未完成的设备不可选，原因写在“安装条件”里。</p>`,
    button("取消", "close") + button("全选当前列表里可选的", "install-all") + button("下一步", "install-to-2", true));
  $("#overlay-root .modal").classList.add("batch-install-modal");
  wizRenderList();
  const body = $("#overlay-root .modal-body"), sync = (e) => {
    if (e.target.dataset.wizPick) { wizKeepPicks(); if (Object.keys(w.picked).length > WIZ_MAX) { e.target.checked = false; wizKeepPicks(); toast(`每批最多 ${WIZ_MAX} 台`); } return wizRenderSummaryOnly(); }
    if (!/^wiz-(q|scope|arch|sys|available|selected)$/.test(e.target.id)) return;
    wizKeepPicks(); Object.assign(f, { q: $("#wiz-q").value, scope: $("#wiz-scope").value, arch: $("#wiz-arch").value, sys: $("#wiz-sys").value, available: $("#wiz-available").checked, selected: $("#wiz-selected").checked }); wizRenderList();
  };
  body.addEventListener("change", sync); body.addEventListener("input", (e) => { if (e.target.id === "wiz-q") sync(e); });
}
function wizRenderSummaryOnly() { const w = wiz(), list = wizVisible(), n = Object.keys(w.picked).length, hidden = Object.keys(w.picked).filter((id) => !list.some((t) => t.id === id)).length; $("#wiz-summary").textContent = `显示 ${list.length} / ${servers().length} 台 · 已选 ${n} / ${WIZ_MAX} 台${hidden ? "（筛选外 " + hidden + " 台）" : ""}`; }
registerAction("install-all", () => {
  const w = wiz(); wizKeepPicks(); let room = WIZ_MAX - Object.keys(w.picked).length, skipped = 0;
  document.querySelectorAll("[data-wiz-pick]:not([disabled])").forEach((el) => { if (el.checked) return; if (room > 0) { el.checked = true; room--; } else skipped++; });
  wizKeepPicks(); wizRenderSummaryOnly(); if (skipped) toast(`每批最多 ${WIZ_MAX} 台，有 ${skipped} 台没有选上`);
});
/* 查询当前系统：对已选的设备查询；没有选择时查询当前筛选出来的设备。只读，不改设备。 */
registerAction("install-sysquery", () => {
  const w = wiz(); wizKeepPicks(); const ids = Object.keys(w.picked).length ? Object.keys(w.picked) : wizVisible().map((t) => t.id);
  if (!ids.length || ids.length > WIZ_MAX) return toast(`请选择或筛选 1–${WIZ_MAX} 台设备后查询当前系统。`);
  ids.forEach((id) => (S.currentSystems[id] = { status: "unknown", pending: true })); wizRenderList();
  setTimeout(() => { ids.forEach((id) => { const t = DB.tray(id); if (!t) return; const inst = t.instance && S.instances.find((i) => i.id === t.instance);
      S.currentSystems[id] = inst ? { status: "os", label: inst.os.split(" · ")[0], at: nowText() } : !t.state || t.power !== "On" ? { status: "off", at: nowText() } : { status: "temporary", at: nowText() }; });
    if (S.view.wiz === w && w.step === 1 && $("#wiz-list")) wizRenderList(); }, 900);
});
registerAction("install-to-2", () => {
  const w = wiz(); if ($("#wiz-list")) wizKeepPicks();
  const list = wizList(); if (!list.length) return toast("先勾选要装系统的设备");
  if (list.length > WIZ_MAX) return toast(`每批最多 ${WIZ_MAX} 台`);
  Object.keys(w.picked).forEach((id) => { if (!list.some((t) => t.id === id)) delete w.picked[id]; });
  if (!w.prefix) { const racks = [...new Set(list.map((t) => t.rack))]; w.prefix = racks.length === 1 ? (racks[0] ? "node-" + racks[0].slice(-3).toLowerCase() : "node-srv") : "node"; }
  list.forEach((t) => { w.rows[t.id] = w.rows[t.id] || { host: "", os: (osReady(t.arch)[0] || {}).id || "", disk: "" }; });
  wizApplyRule(false); w.onlyBad = false; installStep2();
});
/* 第 2 步：逐台配置。这一页只要人做一件事：给每台机器确定主机名。
   安装方案和系统盘按默认值填好，表里只显示结果；只有例外的设备才展开来改。需要人处理的设备会标出来并排在能筛出来的位置。 */
const wizCustom = (t) => { const w = wiz(), r = w.rows[t.id]; return r.os !== w.osDefault[t.arch] || !!r.disk; };
/* 这台设备在这一步还缺什么：主机名不合规或重名；或者方案规则定不出唯一的系统盘。 */
function wizProblem(t, hosts) {
  const row = wiz().rows[t.id], h = hostProblem(row.host, hosts);
  if (h) return { kind: "host", text: h };
  if (!row.os) return { kind: "os", text: "这个架构没有已发布的安装方案" };
  return t.state && resolveDisk(t, row).problem ? { kind: "disk", text: "方案规则匹配到不止一块盘，请选一块" } : null;
}
function wizRuleText() { const w = wiz(), n = wizList().length; return w.prefix ? `${w.prefix}-${pad2(w.start)}` + (n > 1 ? ` 至 ${w.prefix}-${pad2(w.start + n - 1)}` : "") : "先填写前缀"; }
/* 不重画页面，只更新每一行的提示和上方的统计：这样改主机名时不丢焦点，也不会吞掉随后的点击。 */
function wizRefreshProblems() {
  const w = wiz(), list = wizList(), hosts = list.map((t) => w.rows[t.id].host); let bad = 0;
  list.forEach((t) => { const p = wizProblem(t, hosts), tr = document.querySelector(`tr[data-wiz-row="${t.id}"]`); if (p) bad++; if (!tr) return;
    tr.classList.toggle("wiz-attn", !!p);
    tr.querySelector("[data-wiz-hmsg]").textContent = p && p.kind === "host" ? p.text : "";
    const d = tr.querySelector("[data-wiz-dmsg]"); if (d) d.textContent = p && p.kind === "disk" ? p.text : ""; });
  $("#wiz-attn").innerHTML = bad ? badge(`需要处理 ${bad} 台`, "red") : badge("全部填好，可以进入下一步", "green");
  if ($("#wiz-preview")) $("#wiz-preview").textContent = wizRuleText();
  return bad;
}
function installStep2(keepScroll) {
  const w = wiz(), list = wizList(), hosts = list.map((t) => w.rows[t.id].host), archs = [...new Set(list.map((t) => t.arch))], top = keepScroll && $("#overlay-root .modal-body") ? $("#overlay-root .modal-body").scrollTop : 0;
  w.step = 2; w.edit = w.edit || {}; w.osDefault = w.osDefault || {};
  archs.forEach((a) => { if (!w.osDefault[a]) w.osDefault[a] = (osReady(a)[0] || {}).id || ""; });
  const prob = new Map(list.map((t) => [t.id, wizProblem(t, hosts)])), bad = list.filter((t) => prob.get(t.id)), shown = w.onlyBad && bad.length ? bad : [...bad, ...list.filter((t) => !prob.get(t.id))]; /* 需要处理的排在最前面 */
  const osText = (id) => { const p = id.split(" · "); return `${esc(p[0])}<span class="cell-sub">${esc(p[1] || "")}</span>`; };
  const rows = shown.map((t) => { const row = w.rows[t.id], p = prob.get(t.id), editing = w.edit[t.id] || (p && p.kind === "disk"), custom = wizCustom(t), d = t.state ? resolveDisk(t, row) : null;
    const osCell = w.edit[t.id] ? `<select class="input wiz-select" data-wiz-os="${t.id}" aria-label="${t.serial} 的安装方案">${osReady(t.arch).map((o) => `<option ${o.id === row.os ? "selected" : ""}>${esc(o.id)}</option>`).join("")}</select>` : osText(row.os) ;
    const diskCell = !t.state ? `按方案的规则<span class="cell-sub">NICo 接管后才读得到硬盘，执行前确定</span>`
      : editing ? `<select class="input wiz-select" data-wiz-disk="${t.id}" aria-label="${t.serial} 的系统盘"><option value="">${d.problem && !row.disk ? "请选择系统盘" : "按安装方案的规则选择"}</option>${t.disks.map((x) => `<option ${x === row.disk ? "selected" : ""}>${x}</option>`).join("")}</select><span class="cell-sub wiz-msg" data-wiz-dmsg>${p && p.kind === "disk" ? p.text : ""}</span>`
      : `${esc(d.disk)}<span class="cell-sub">${row.disk ? "单独指定" : "按方案的规则"}</span>`;
    return `<tr data-wiz-row="${t.id}" class="${p ? "wiz-attn" : ""}"><td><strong class="live-code">${t.serial}</strong><span class="cell-sub">${placeText(t)} · ${t.arch}${t.state ? "" : " · 安装时先接管"}</span></td>
      <td><input class="input live-code wiz-host" data-wiz-host="${t.id}" value="${esc(row.host)}" aria-label="${t.serial} 的主机名"><span class="cell-sub wiz-msg" data-wiz-hmsg>${p && p.kind === "host" ? p.text : ""}</span></td>
      <td>${osCell}</td><td>${diskCell}</td>
      <td><div class="live-tools">${custom && !editing ? badge("已单独设置", "blue") : ""}<button class="link-button" data-live="install-row-edit" data-id="${t.id}">${w.edit[t.id] ? "完成" : "单独设置"}</button>${custom ? `<button class="link-button" data-live="install-row-reset" data-id="${t.id}">恢复默认</button>` : ""}</div></td></tr>`; });
  modal("新建安装任务", "步骤 2 / 3", wizHead(2) +
    `<div class="wiz-lead"><h3>给这 ${list.length} 台机器确定主机名</h3><p>主机名装好后就是系统里的主机名，也是 NICo 里的实例名称。安装方案和系统盘已经按默认值填好，表里直接显示结果；只有标着“需要处理”的设备，或者你想让个别设备不一样时，才需要动手改。</p></div>
     <div class="wiz-defaults">
       <div><h4><span class="wiz-num">1</span>主机名规则</h4><div class="wiz-inline"><label>前缀<input class="input live-code" id="wiz-prefix" value="${esc(w.prefix)}"></label><label>起始序号<input class="input" id="wiz-start" type="number" min="0" value="${w.start}"></label>${button("重新生成", "install-rule")}</div><p>将生成 <b class="live-code" id="wiz-preview">${wizRuleText()}</b>。规则只用来批量生成，下面每一台都可以单独改。</p></div>
       <div><h4><span class="wiz-num">2</span>默认安装方案</h4>${archs.map((a) => `<label class="wiz-arch"><span>${a} · ${list.filter((t) => t.arch === a).length} 台</span><select class="input" data-wiz-os-all="${a}">${osReady(a).map((o) => `<option ${o.id === w.osDefault[a] ? "selected" : ""}>${esc(o.id)}</option>`).join("") || "<option value=\"\">没有已发布的方案</option>"}</select></label>`).join("")}<p>按设备的架构选用，只列出已发布的方案。</p></div>
       <div><h4><span class="wiz-num">3</span>默认系统盘</h4><p class="wiz-static">按安装方案的规则选盘</p><p>规则定不出唯一一块盘的设备会在下面标出来，由你指定。地址由 NICo 分配，这里不用填。</p></div>
     </div>
     <div class="wiz-table-head"><h4>逐台确认</h4><span id="wiz-attn">${bad.length ? badge(`需要处理 ${bad.length} 台`, "red") : badge("全部填好，可以进入下一步", "green")}</span><span class="grow"></span>${bad.length || w.onlyBad ? `<label><input type="checkbox" id="wiz-onlybad" ${w.onlyBad && bad.length ? "checked" : ""}> 只看需要处理的</label>` : ""}</div>` +
    table(["设备 / 位置", "主机名", "安装方案", "系统盘", "例外"], rows),
    button("上一步", "install-back-1") + button("下一步：检查安装条件", "install-to-3", true));
  $("#overlay-root .modal").classList.add("batch-install-modal", "wiz-config");
  const body = $("#overlay-root .modal-body"); if (top) body.scrollTop = top;
  body.addEventListener("input", (e) => { if (e.target.dataset.wizHost) { w.rows[e.target.dataset.wizHost].host = e.target.value.trim(); wizRefreshProblems(); } if (/^wiz-(prefix|start)$/.test(e.target.id)) { w.prefix = $("#wiz-prefix").value.trim(); w.start = Math.max(0, +$("#wiz-start").value || 0); $("#wiz-preview").textContent = wizRuleText(); } });
  body.addEventListener("change", (e) => {
    if (e.target.dataset.wizOsAll) { wizKeepRows(); const a = e.target.dataset.wizOsAll; w.osDefault[a] = e.target.value; list.filter((t) => t.arch === a).forEach((t) => (w.rows[t.id].os = e.target.value)); return installStep2(true); }
    if (e.target.id === "wiz-onlybad") { wizKeepRows(); w.onlyBad = e.target.checked; return installStep2(); }
    if (e.target.dataset.wizDisk !== undefined || e.target.dataset.wizOs) { wizKeepRows(); wizRefreshProblems(); }
  });
}
registerAction("install-rule", () => { wizKeepRows(); if (!wiz().prefix) return toast("先填写主机名前缀"); wizApplyRule(true); installStep2(true); toast("已按规则重新生成全部主机名"); });
registerAction("install-row-edit", ({ id }) => { wizKeepRows(); const w = wiz(); w.edit[id] = !w.edit[id]; installStep2(true); });
registerAction("install-row-reset", ({ id }) => { wizKeepRows(); const w = wiz(), t = DB.tray(id); w.rows[id].os = w.osDefault[t.arch]; w.rows[id].disk = ""; w.edit[id] = false; installStep2(true); });
registerAction("install-back-1", () => { if ($("[data-wiz-host]")) wizKeepRows(); installStep1(); });
registerAction("install-to-3", () => {
  wizKeepRows(); const w = wiz(), list = wizList(), hosts = list.map((t) => w.rows[t.id].host), bad = list.filter((t) => wizProblem(t, hosts));
  if (bad.length) { wizRefreshProblems(); const tr = document.querySelector(`tr[data-wiz-row="${bad[0].id}"]`); if (tr) tr.scrollIntoView({ block: "center" }); else { w.onlyBad = true; installStep2(); } return toast(`还有 ${bad.length} 台需要处理：${bad[0].serial} ${wizProblem(bad[0], hosts).text}`); }
  w.edit = {}; installRunCheck();
});

/* ---------- 安装条件检查 ----------
   检查项和分组沿用现有产品：设备身份、安装配置、操作系统材料。逐台检查，任何一项不通过都不能提交。
   还没有被 NICo 接管的服务器，有两项要到执行前才能确定（机器就绪、系统盘），标为“执行前确定”，不算失败。 */
const CHECK_GROUPS = [["设备身份", "BMC 登录与序列号"], ["安装配置", "机器状态、主机名、管理地址与系统盘"], ["操作系统材料", "kernel、initrd、ISO 与自动安装配置"]];
const diskSize = (d) => { const m = / · ([\d.]+) (GB|TB)/.exec(d); return m ? +m[1] * (m[2] === "TB" ? 1000 : 1) : 0; };
/* 按安装方案的选盘规则解析系统盘：容量最小或最大的 NVMe，必须唯一。 */
function resolveDisk(t, row) {
  if (row.disk) return { disk: row.disk, source: "逐台指定" };
  const rule = (S.osTemplates.find((o) => o.id === row.os) || {}).disk || "", largest = /最大/.test(rule), sizes = t.disks.map(diskSize), pick = largest ? Math.max(...sizes) : Math.min(...sizes), hit = t.disks.filter((d) => diskSize(d) === pick);
  return hit.length === 1 ? { disk: hit[0], source: "方案规则" } : { disk: "", source: "", problem: `按安装方案的规则（${rule.split("，")[0]}）匹配到 ${hit.length} 块盘，不能确定唯一的系统盘。回到“逐台配置”，为这台设备指定系统盘。` };
}
function installChecks(t, row) {
  const cold = !t.state, d = resolveDisk(t, row), ok = (group, name, detail = "实际检查通过") => ({ group, name, passed: true, detail }), later = (group, name, detail) => ({ group, name, passed: true, deferred: true, detail });
  return [
    t.checkFlaky ? { group: 0, name: "BMC 认证与序列号", passed: false, detail: "BMC 没有响应（连接超时）。确认这台设备的 BMC 在线后点“更新状态”重新检查；也可以回到第一步把它移出本批。" } : ok(0, "BMC 认证与序列号", "登录成功，读到的序列号与设备一致"),
    cold ? later(1, "机器就绪", "当前未要求就绪；创建任务后由 NICo 自动上电接管，并等待它回报就绪") : ok(1, "机器就绪、没有实例"),
    ok(1, "主机名与安装方案", "主机名合规、没有重名；方案已发布，架构一致"),
    cold ? later(1, "管理地址", "接管后由 NICo 分配") : ok(1, "管理地址、子网与地址占用"),
    cold ? later(1, "系统盘", "执行前读取硬件后确定：按方案的规则解析唯一的系统盘") : d.problem ? { group: 1, name: "系统盘", passed: false, detail: d.problem } : ok(1, "系统盘", `${d.source}：${d.disk}`),
    ok(2, "安装材料可以取到，长度与登记一致", "实际检查通过；执行前另做完整摘要校验"),
  ];
}
function installRunCheck() {
  const w = wiz(); w.check = null; w.checking = true; installStep3();
  setTimeout(() => {
    if (S.view.wiz !== w) return;
    const list = wizList(), devices = list.map((t) => ({ id: t.id, serial: t.serial, cleanup: !t.state, disk: t.state ? resolveDisk(t, w.rows[t.id]) : null, checks: installChecks(t, w.rows[t.id]) }));
    w.check = { at: nowText(), devices, passed: devices.every((d) => d.checks.every((c) => c.passed)) }; w.checking = false;
    list.forEach((t) => t.checkFlaky && t.checkFlaky--); /* 模拟：BMC 超时是暂时的，再检查一次就通过 */
    if (w.step === 3) installStep3();
  }, 900);
}
function checkPanel(check) {
  const rows = check ? check.devices.flatMap((d) => d.checks) : [];
  const steps = CHECK_GROUPS.map(([label, detail], g) => { const mine = rows.filter((c) => c.group === g); return { label, detail, status: mine.some((c) => !c.passed) ? "failed" : mine.length ? "passed" : "checking" }; });
  const passed = steps.filter((s) => s.status === "passed").length;
  return `<section class="install-check-panel" aria-label="安装条件检查"><header><div><span class="site-eyebrow">安装条件</span><strong>${check ? (check.passed ? "配置可以执行" : "发现阻断项") : "正在核对配置"}</strong></div><span>${passed} / ${steps.length}</span></header><progress value="${passed}" max="${steps.length}" aria-label="已通过 ${passed} 项，共 ${steps.length} 项"></progress><ol>${steps.map((s) =>
    `<li class="${s.status}"><span class="install-check-dot" aria-hidden="true"></span><div><strong>${s.label}</strong><span>${s.detail}</span></div><small>${{ passed: "已通过", failed: "需处理", checking: "检查中" }[s.status]}</small></li>`).join("")}</ol></section>`;
}
function installStep3() {
  const w = wiz(), list = wizList(), check = w.check, of = (t) => (check ? check.devices.find((d) => d.id === t.id) : null), cold = list.filter((t) => !t.state);
  w.step = 3;
  const diskCell = (t) => { const row = w.rows[t.id], d = of(t); if (!t.state) return `${esc(row.disk || "按方案的规则")}<span class="cell-sub">接管后、执行前确定</span>`; if (!d) return "检查中…"; return d.disk.problem ? badge("未确定", "red") : `${esc(d.disk.disk)}<span class="cell-sub">${d.disk.source}</span>`; };
  let body = wizHead(3) + (cold.length ? `<div class="live-note">${cold.length} 台设备当前还没有被 NICo 接管；提交后将自动准备设备。</div>` : "") +
    table(["设备 / 位置", "CPU 架构", "BMC 地址 / MAC", "目标 OS / 方案", "主机名 / 管理地址", "系统盘", "操作"], list.map((t) => { const row = w.rows[t.id], os = row.os.split(" · ");
      return `<tr><td><strong>${t.serial}</strong><span class="cell-sub">${placeText(t)}</span></td><td>${code(t.arch)}</td><td>${code(t.bmcIp)}<span class="cell-sub live-code">${t.bmcMac}</span></td><td>${esc(os[0])}<span class="cell-sub">${esc(os[1] || "")}</span></td><td>${code(row.host)}<span class="cell-sub live-code">${t.hostIp || "接管后由 NICo 分配"}</span></td><td>${diskCell(t)}</td><td><button class="link-button" data-live="install-back-2">修改配置</button></td></tr>`; })) +
    checkPanel(check);
  if (check) {
    const fails = check.devices.flatMap((d) => d.checks.filter((c) => !c.passed).map((c) => `<div class="install-check-failure"><strong>${d.serial} · ${c.name}</strong><span>${esc(c.detail)}</span></div>`));
    const later = check.devices.flatMap((d) => d.checks.filter((c) => c.deferred).map((c) => `<li>${d.serial} · ${c.name}：${esc(c.detail)}</li>`));
    if (fails.length) body += `<div class="install-check-failures">${fails.join("")}</div>`;
    if (later.length) body += `<div class="live-note"><b>执行前确定的项目</b>（不算失败）：<ul class="live-small" style="margin:6px 0 0;padding-left:18px">${later.join("")}</ul></div>`;
    if (cold.length) body += `<div class="live-note live-warning"><strong>首次接入将清理全部磁盘：</strong>${cold.map((t) => t.serial).join("、")}</div>`;
    if (check.passed) body += `<div class="live-note live-warning">将安装 ${list.length} 台设备：每台建一个实例，实例名称就是主机名；覆盖所选系统盘并重启验证。本批最多并发 5 台；失败设备暂停，其余设备继续。</div>
      <div class="live-form">${field("原因", `<input class="input" id="wiz-why" value="${esc(w.why)}" placeholder="工单号或原因">`)}<label class="live-check"><input type="checkbox" id="wiz-c1">确认所选设备、主机名、管理地址及系统盘。</label><label class="live-check"><input type="checkbox" id="wiz-c2">允许安装及重启验证。</label>${cold.length ? `<label class="live-check live-warning"><input type="checkbox" id="wiz-c3">允许需接入设备清理全部磁盘（含非系统盘），并执行站点凭据和固件配置。</label>` : ""}</div>`;
    body += `<p class="live-small">检查时间 ${check.at}。提交时服务端会再检查一次配置和占用；这里通过不代表之后一定通过。</p>`;
  }
  modal("新建安装任务", "步骤 3 / 3", body, `<div class="batch-review-actions">${button("重新选择设备", "install-back-1")}${button("修改配置", "install-back-2")}${button(check ? "更新状态" : "检查中…", "install-recheck", false, w.checking ? "disabled" : "")}</div>` + button("确认并安装", "install-run", true, 'id="wiz-submit" disabled'));
  $("#overlay-root .modal").classList.add("batch-install-modal");
  const ready = () => { const b = $("#wiz-submit"); if (b) b.disabled = !(check && check.passed && $("#wiz-c1").checked && $("#wiz-c2").checked && (!$("#wiz-c3") || $("#wiz-c3").checked)); };
  $("#overlay-root .modal-body").addEventListener("change", ready);
}
registerAction("install-recheck", () => { if ($("#wiz-why")) wiz().why = $("#wiz-why").value.trim(); installRunCheck(); });
registerAction("install-back-2", () => { if ($("#wiz-why")) wiz().why = $("#wiz-why").value.trim(); installStep2(); });
registerAction("install-run", () => {
  const w = wiz(), why = $("#wiz-why") ? $("#wiz-why").value.trim() : "";
  if (!w.check || !w.check.passed) return toast("安装条件检查没有通过");
  if (!why) return toast("请填写原因");
  if (!$("#wiz-c1").checked || !$("#wiz-c2").checked || ($("#wiz-c3") && !$("#wiz-c3").checked)) return toast("请勾选确认项");
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
