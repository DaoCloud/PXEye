"use strict";
/* 设备：按设备类型直达的页面，对应左侧菜单“设备管理”及其子菜单。
   - 设备（总览）：跨类型搜索，以及当前需要处理的设备；
   - 计算托盘 / 交换机 / 供电框：各自的列表，地址和固件直接在表里，行上直接操作；
   - 这一版计算托盘上的 BlueField 只作为网卡使用，不是独立的设备对象，所以没有 DPU 页面；它出现在计算托盘的运行状态里。
   机柜页是这些设备的关联与汇总视图；这里的“机柜 / 位置”链接回机柜。 */

const DEVICE_ROUTE = { compute: "devices/compute", switch: "devices/switch", power_shelf: "devices/power-shelf" };
const FW_PART = { compute: "计算托盘 BMC", switch: "交换机 BMC" };
const fwVersion = (t) => (t.baseline && FW_PART[t.type] ? DB.baseline(t.baseline).parts[FW_PART[t.type]] : "");
/* NICo 只能判断版本和基线是否相同，不能判断高低；供电框没有可读的固件版本。 */
const fwCell = (t) => (fwVersion(t) ? code(fwVersion(t)) + `<span class="cell-sub">${DB.drift(t) ? badge("与基线不同", "amber") : badge("与基线相同", "green")}</span>` : "—");
const fmBadge = (v) => ({ OK: badge("正常", "green"), NOT_OK: badge("异常", "red") })[v] || badge("未知", "gray");
const placeCell = (t) => `<a class="link-button" data-go="rack/${t.rack}">${t.rack}</a><span class="cell-sub">槽位 ${pad2(t.slot)}</span>`;
const stateCell = (t) => stateBadge(t.state) + (t.reason ? `<span class="cell-sub">${esc(t.reason)}</span>` : !t.state ? `<span class="cell-sub">NICo 尚未建立设备对象</span>` : "");
const absent = (t) => (t.state ? "" : "NICo 尚未建立设备对象，不能操作。");
/* 行操作：运行状态、电源快捷入口、全部操作。电源快捷入口只是预选了动作的同一个操作对话框。 */
const rowActions = (t, mark = "") => `<div class="inline-actions" ${mark}>${button("运行状态", "tray-detail", false, `data-id="${t.id}"`)}${act(t.power === "On" ? "关机" : "上电", "tray-op", { gate: absent(t), extra: `data-id="${t.id}" data-action="${t.power === "On" ? "power-off" : "power-on"}"` })}${act("操作", "tray-op", { gate: absent(t), extra: `data-id="${t.id}"` })}</div>`;

const DEVICE_COLUMNS = {
  compute: [["BMC 地址", (t) => (t.bmcIp ? code(t.bmcIp) : "—")], ["管理地址", (t) => (t.hostIp ? code(t.hostIp) : "—")], ["运行状态", stateCell], ["健康", (t) => healthBadge(t.health)], ["电源", (t) => (t.state ? powerText(t.power) : "—")], ["实例", (t) => (t.instance ? code(t.instance) : "—")], ["维护 / 隔离", (t) => [t.maintenance && badge("维护", "amber"), t.quarantine && badge("已隔离", "red")].filter(Boolean).join(" ") || "—"], ["BMC 固件", fwCell]],
  switch: [["BMC 地址", (t) => (t.bmcIp ? code(t.bmcIp) : "—")], ["NVOS 管理口", (t) => (t.nvos.length ? code(t.nvos[0].ip) + `<span class="cell-sub">${t.primary ? "主交换机 · " : ""}共 ${t.nvos.length} 个口</span>` : "—")], ["运行状态", stateCell], ["健康", (t) => healthBadge(t.health)], ["电源", (t) => (t.state ? powerText(t.power) : "—")], ["Fabric Manager", (t) => (t.state ? fmBadge(t.fabricManager) : "—")], ["BMC 固件", fwCell]],
  power_shelf: [["BMC 地址", (t) => (t.bmcIp ? code(t.bmcIp) : "—")], ["运行状态", stateCell], ["健康", (t) => healthBadge(t.health)], ["电源", (t) => (t.state ? powerText(t.power) : "—")]],
};
const DEVICE_TEXT = {
  compute: { sub: "查看计算托盘的地址、运行状态、健康、实例和固件，并直接执行电源、维护和固件操作。", old: "设备管理 → 服务器", own: "实例、维护 / 隔离", addr: "BMC 地址和主机管理地址" },
  switch: { sub: "查看交换机的地址、运行状态、健康、Fabric Manager 和固件，并直接执行电源、复位和固件操作。", old: "设备管理 → 交换机", own: "NVOS 管理口、Fabric Manager", addr: "BMC 地址和 NVOS 管理口" },
  power_shelf: { sub: "查看供电框的地址、运行状态、健康和电源，并直接执行上下电。", old: "设备管理 → 供电框", own: "无", addr: "BMC 地址" },
};

function devicePage(type) {
  const label = TYPE_LABEL[type], text = DEVICE_TEXT[type], cols = DEVICE_COLUMNS[type], K = (k) => `dev:${type}:${k}`, hasFw = !!FW_PART[type];
  return {
    module: type, title: label,
    render() {
      const f = { rack: view(K("rack"), ""), st: view(K("st"), ""), q: view(K("q"), "").toLowerCase() };
      const all = DB.trays().filter((t) => t.type === type), checked = S.view.checked || {};
      const list = all.filter((t) => (!f.rack || t.rack === f.rack) && (!f.q || [t.serial, t.rack, t.bmcIp, t.bmcMac, t.hostIp, ...(t.nvos || []).map((x) => x.ip), t.state, t.instance].join(" ").toLowerCase().includes(f.q)) &&
        (!f.st || (f.st === "attention" && DB.needsAttention(t)) || (f.st === "alerting" && t.alerts.length) || (f.st === "absent" && !t.state) || (f.st === "drift" && DB.drift(t))));
      const picked = Object.keys(checked).filter((k) => checked[k] && DB.tray(k) && DB.tray(k).type === type);
      const mark = (name) => ({ "运行状态": fp(6), ...(hasFw ? { [cols[cols.length - 1][0]]: fp(5) } : {}) })[name] || "";
      return heading(label, text.sub, button("刷新数据", "refresh") + button("按机柜查看", "noop", false, 'data-go="racks"')) +
        `<div ${fp(1)}>${summary([["设备总数", all.length], ["NICo 已建立对象", all.filter((t) => t.state).length], ["需要处理", all.filter(DB.needsAttention).length], ...(hasFw ? [["固件与基线不同", all.filter(DB.drift).length]] : [])])}</div>` +
        `<div class="filter-bar" ${fp(2)}>${selectField(K("rack"), "机柜", [["", "全部机柜"], ...S.racks.map((r) => [r.id, r.id])], f.rack)}${selectField(K("st"), "状态", [["", "全部"], ["attention", "需要处理"], ["alerting", "有健康告警"], ["absent", "NICo 未建立对象"], ...(hasFw ? [["drift", "固件与基线不同"]] : [])], f.st)}${searchField(K("q"), "搜索", view(K("q"), ""), "序列号、机柜、状态、MAC 或 IP")}</div>` +
        `<div class="device-status-action-bar" ${fp(3)}>${act(`批量操作（${picked.length}）`, "tray-batch", { gate: picked.length ? "" : "先勾选设备" })}<span class="live-small">勾选设备后批量操作，一次最多 10 台。</span></div>` +
        `<div ${fp(4)}>${table(["选择", "设备 / 序列号", "机柜 / 位置", ...cols.map((c) => c[0]), "操作"], list.map((t, i) =>
          `<tr><td><input type="checkbox" data-check="${t.id}" ${checked[t.id] ? "checked" : ""} ${t.state ? "" : "disabled"} aria-label="选择 ${t.serial}"></td><td><a class="link-button" data-live="tray-detail" data-id="${t.id}">${code(t.serial)}</a><span class="cell-sub">${t.model}</span></td><td>${placeCell(t)}</td>${cols.map((c) => `<td ${i === 0 ? mark(c[0]) : ""}>${c[1](t)}</td>`).join("")}<td>${rowActions(t, i === 0 ? fp(7) : "")}</td></tr>`), `没有符合筛选条件的${label}。`)}</div>` +
        note("运行状态由 NICo 状态机回报。“需要处理”指状态机最近一次处理失败或有健康告警。没有收到报告显示为未报告，不显示为正常。");
    },
    spec: {
      purpose: `直接面向${label}运维：不需要先找到它在哪个机柜。地址、状态和固件在表里一眼可见，电源等操作在行上一步发起。`,
      entry: `运维 → 设备管理 → ${label}；设备管理的类型卡片；机柜详情的设备页签`, design: "6.3 机柜与设备；9 操作设计", existing: `${text.old}。统计条、筛选、表头、行操作和“需要处理”的规则沿用`,
      points: [
        { n: 1, name: "统计条", kind: "调整", desc: hasFw ? "设备总数、NICo 已建立对象、需要处理沿用；“未填写机柜”换成“固件与基线不同”，因为机柜归属来自清单，不会缺失。" : "设备总数、NICo 已建立对象、需要处理沿用；去掉“未填写机柜”，因为机柜归属来自清单，不会缺失。" },
        { n: 2, name: "筛选", kind: "沿用", desc: "机柜、状态（全部、需要处理、有健康告警、NICo 未建立对象）和搜索。" + (hasFw ? "状态里增加“固件与基线不同”。" : "") },
        { n: 3, name: "批量操作", kind: "沿用", desc: "勾选后对最多 10 台执行同一个动作，逐台检查、逐台出结果。" },
        { n: 4, name: `${label}表`, kind: "沿用", desc: `设备 / 序列号、机柜 / 位置、运行状态、健康、电源沿用。地址列是${text.addr}；专有列是${text.own}。点击序列号打开运行状态。` },
        { n: 5, name: "固件版本", kind: "调整", desc: hasFw ? "直接显示 BMC 固件的版本，并标出与基线相同还是不同。NICo 只能比较是否相同，不能判断高低。完整的部件清单在运行状态里。" : "供电框没有可读的固件版本，这一类设备不显示固件列。" },
        { n: 6, name: "运行状态", kind: "沿用", desc: "显示 NICo 的状态原文；有处理失败原因时显示在下方；没有对象时显示“NICo 尚未建立设备对象”。" },
        { n: 7, name: "行操作", kind: "调整", desc: "“运行状态”打开详情；“上电 / 关机”是预选了电源动作的快捷入口；“操作”打开完整的操作对话框。三者用同一个对话框和同一套检查。" },
      ],
      fields: [["机柜 / 位置", "到货清单", "链接到机柜详情，那里是关联与汇总视图"], ["地址", "NICo Core", text.addr], ...(hasFw ? [[cols[cols.length - 1][0], "NICo 读到的版本对比推荐基线", "版本，以及与基线相同 / 与基线不同"]] : []), ...(type === "compute" ? [["实例", "NICo Core", "有实例的托盘操作前会提示影响"]] : type === "switch" ? [["NVOS 管理口", "NICo Core", "主口的地址和口的数量"], ["Fabric Manager", "NICo Core", "NICo 回报 OK、NOT_OK、UNKNOWN，显示为正常、异常、未知"]] : [["序列号", "到货清单", "NICo 的供电框对象不带序列号，这里显示清单里的"]])],
      rules: ["“需要处理”只用 NICo 的信号：处理失败、有健康告警。", "没有 NICo 对象的设备不能勾选和操作。", type === "compute" ? "有实例的计算托盘，关机等操作要输入序列号确认。" : `${label}的高风险操作按整柜实例计算影响；机柜上还有已分配的计算托盘时不能退役。`, "只读角色的操作按钮禁用。"],
      dialogs: [{ name: "操作对话框（单台与批量共用）", desc: "选对象、选动作、写原因，一个弹窗完成。逐台显示检查结果，只对通过的目标执行。现有的“设备操作 → 确认操作 → 操作结果”三步合成一步，结果进入任务或审计。",
        fields: [["动作", "是", "按设备类型列出，名称与风险等级沿用现有操作目录；从“上电 / 关机”进入时已预选"], ["固件基线", "仅固件更新", "只能选择基线，取代现有的“目标版本”“组件”“强制刷写”"], ["原因", "是", ""], ["输入序列号", "高风险时", "单台输入序列号；批量输入台数"]] }],
    },
  };
}
Object.keys(DEVICE_ROUTE).forEach((type) => registerPage(DEVICE_ROUTE[type], devicePage(type)));

/* ---------- 设备总览：跨类型搜索与需要处理的设备 ---------- */
registerPage("devices", {
  module: "devices", title: "设备管理",
  render() {
    const q = view("devQ", "").trim().toLowerCase(), trays = DB.trays();
    const hit = (t) => [t.serial, t.rack, t.bmcIp, t.bmcMac, t.hostIp, t.hostMac, ...(t.nvos || []).map((x) => x.ip), t.instance].join(" ").toLowerCase().includes(q);
    const list = q ? trays.filter(hit) : trays.filter(DB.needsAttention);
    const card = (type) => { const all = trays.filter((t) => t.type === type); return `<a class="device-card" data-go="${DEVICE_ROUTE[type]}"><strong>${TYPE_LABEL[type]}</strong><b>${all.length}</b><span>${all.filter(DB.needsAttention).length ? badge(all.filter(DB.needsAttention).length + " 台需要处理", "amber") : badge("无需处理", "green")}　${FW_PART[type] && all.filter(DB.drift).length ? badge(all.filter(DB.drift).length + " 台固件与基线不同", "gray") : ""}</span></a>`; };
    const rows = list.slice(0, 30).map((t) => `<tr><td><a class="link-button" data-live="tray-detail" data-id="${t.id}">${code(t.serial)}</a><span class="cell-sub">${esc(t.model)}</span></td><td>${TYPE_LABEL[t.type]}</td><td>${placeCell(t)}</td><td>${t.bmcIp ? code(t.bmcIp) : "—"}${t.hostIp || (t.nvos && t.nvos.length) ? `<span class="cell-sub live-code">${t.hostIp || t.nvos[0].ip}</span>` : ""}</td><td>${stateCell(t)}</td><td>${healthBadge(t.health)}${t.alerts.length ? `<span class="cell-sub">${esc(t.alerts[0].msg)}</span>` : ""}</td><td>${fwCell(t)}</td><td>${rowActions(t)}</td></tr>`);
    return heading("设备管理", "按序列号、地址或实例直接找到一台设备，查看状态并操作。各类型的完整列表在左侧子菜单。", button("刷新数据", "refresh")) +
      `<div class="filter-bar" ${fp(1)}>${searchField("devQ", "搜索全部设备", view("devQ", ""), "序列号、BMC 或管理地址、MAC、机柜或实例")}</div>` +
      `<div class="device-cards" ${fp(2)}>${["compute", "switch", "power_shelf"].map(card).join("")}</div>` +
      `<h2 class="section-title">${q ? `搜索结果 · ${list.length} 台` : `需要处理的设备 · ${list.length} 台`}</h2>` +
      `<div ${fp(3)}>${table(["设备 / 序列号", "类型", "机柜 / 位置", "地址", "运行状态", "健康", "固件", "操作"], rows, q ? "没有匹配的设备。" : "当前没有需要处理的设备。")}</div>` +
      `<div ${fp(4)}>${note("要看一个机柜里的全部设备及它们的关系，从“机柜 / 位置”进入机柜详情：那里有机柜立面、清单核对和机柜级操作。")}</div>`;
  },
  spec: {
    purpose: "设备运维的起点。知道序列号或地址时一步找到设备；不知道时先看哪些设备需要处理。",
    entry: "运维 → 设备管理", design: "6.3 机柜与设备", existing: "新增页面。现有产品要先选设备类型的页面再搜索",
    points: [
      { n: 1, name: "跨类型搜索", kind: "新增", desc: "一个输入框搜索全部计算托盘、交换机和供电框：序列号、BMC 或管理地址、MAC、机柜、实例。" },
      { n: 2, name: "类型卡片", kind: "新增", desc: "每类设备的数量、需要处理的数量和固件与基线不同的数量。点击进入该类型的列表。" },
      { n: 3, name: "需要处理的设备 / 搜索结果", kind: "调整", desc: "没有搜索词时列出各类型里需要处理的设备；有搜索词时列出匹配的设备。行操作与各类型页面相同。" },
      { n: 4, name: "机柜关联说明", kind: "新增", desc: "说明机柜页是关联与汇总视图，从“机柜 / 位置”进入。" },
    ],
    fields: [["地址", "NICo Core", "BMC 地址；计算托盘另有管理地址，交换机另有 NVOS 管理口"], ["固件", "NICo 读到的版本", "BMC 固件版本与基线是否相同；供电框没有"]],
    rules: ["这一版计算托盘上的 BlueField 只作为网卡使用，不单独列为设备；它在计算托盘的运行状态里。", "列表最多显示 30 台，更多用子菜单里的类型页面筛选。"],
  },
});

/* ---------- 托盘运行状态（抽屉） ---------- */
registerAction("tray-detail", ({ id }) => {
  const t = DB.tray(id), r = DB.rack(t.rack), d = DB.domain(r.domain), base = DB.baseline(t.baseline), rec = BASELINES[0];
  if (!t.state) return modal(t.serial, `${TYPE_LABEL[t.type]} · 运行状态`, note(`NICo 尚未为此设备建立对象。它在到货清单中（${t.rack} 槽位 ${pad2(t.slot)}），通电并按序列号匹配上之后才会写进 NICo。`) + defs([["清单里的序列号", code(t.serial)], ["BMC MAC 与地址", "通电后获得"], ["设备凭据", "已提供，不显示"]]), button("关闭", "close") + button("去设备发现", "discovery-rack", true, `data-rack="${t.rack}"`), { drawer: true });
  const partKeys = { compute: ["计算托盘 BMC", "计算托盘 UEFI"], switch: ["交换机 BMC"], power_shelf: [] }[t.type];
  let body = defs([["NICo 对象 ID", code("obj-" + t.serial.toLowerCase())], ["机柜 / 位置", `${t.rack} · 槽位 ${pad2(t.slot)}`], ["运行状态", stateBadge(t.state) + (t.reason ? ` <span class="live-small">${esc(t.reason)}</span>` : "")], ["电源", powerText(t.power)], ["BMC 地址", code(t.bmcIp) + " · " + code(t.bmcMac) + " · " + t.addrMode], ["健康", healthBadge(t.health)], ["最近报告", code(t.lastSeen)]]);
  body += `<h3 class="section-title">健康告警</h3>` + table(["告警", "说明", "开始时间", "分类"], t.alerts.map((a) => `<tr><td>${code(a.id)}${a.target ? `<span class="cell-sub live-code">${esc(a.target)}</span>` : ""}</td><td>${esc(a.msg)}</td><td>${code(a.since)}</td><td>${alertClass(a) || "—"}</td></tr>`), "当前没有健康告警。");
  if (t.type === "compute") {
    body += `<h3 class="section-title">主机</h3>` + defs([["SKU", code(t.sku)], ["实例", t.instance ? code(t.instance) : "未分配"], ["隔离", t.quarantine ? badge("已隔离", "red") + " " + esc(t.quarantine) : "未隔离"], ["维护标记", t.maintenance ? esc(t.maintenance) : "—"], ["主机管理地址", code(t.hostIp) + " · " + code(t.hostMac)], ["NVLink 域", code(r.domain)]]);
    body += `<h3 class="section-title">BlueField 网卡</h3>` + table(["网卡", "工作方式", "BMC MAC", "BMC 地址"], t.nics.map((c) => `<tr><td>${c.name}</td><td>网卡模式</td><td>${code(c.mac)}</td><td>${code(c.ip)}</td></tr>`));
    body += `<h3 class="section-title">硬件能力</h3>` + table(["类别", "规格"], Object.entries(t.hardware).map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`));
    body += `<h3 class="section-title">LLDP 邻居</h3>` + table(["本机接口", "邻居交换机", "邻居端口"], t.lldp.map((l) => `<tr><td>${code(l.port)}</td><td>${l.sw}</td><td>${code(l.remote)}</td></tr>`));
  }
  if (t.type === "switch") {
    body += `<h3 class="section-title">交换机</h3>` + defs([["主交换机", t.primary ? "是" : "否"], ["NVLink 域", code(r.domain) + (d && d.uuid ? `<span class="cell-sub live-code">${d.uuid}</span>` : "")], ["Fabric Manager", fmBadge(t.fabricManager) + ` <span class="live-code">${t.fabricManager || "—"}</span>`]]);
    body += `<h3 class="section-title">NVOS 管理口</h3>` + table(["接口", "MAC", "地址", "角色"], t.nvos.map((x) => `<tr><td>${x.name}</td><td>${code(x.mac)}</td><td>${code(x.ip)}</td><td>${x.primary ? "主口" : "备用口"}</td></tr>`));
  }
  if (partKeys.length) body += `<h3 class="section-title">固件</h3>` + table(["部件", "版本", "推荐基线版本", "对比"], partKeys.map((k) => `<tr><td>${k}</td><td>${code(base ? base.parts[k] : "—")}</td><td>${code(rec.parts[k])}</td><td>${base && base.parts[k] === rec.parts[k] ? badge("相同", "green") : badge("不同", "amber")}</td></tr>`).concat(t.type === "switch" ? [`<tr><td>NVOS</td><td><span class="muted">NICo 读不到已安装的版本</span></td><td>${code(rec.nvos)}</td><td>—</td></tr>`] : []));
  body += `<h3 class="section-title">状态时间线</h3>` + table(["状态", "进入时间"], [...t.history].reverse().map((h, i) => `<tr><td>${stateBadge(h[1])}${i === 0 ? " " + badge("当前", "amber") : ""}</td><td>${code(h[0])}</td></tr>`));
  modal(t.serial, `${TYPE_LABEL[t.type]} · 运行状态 · ${t.rack} 槽位 ${pad2(t.slot)}`, body, button("关闭", "close") + act("操作", "tray-op", { primary: true, extra: `data-id="${t.id}"` }), { drawer: true });
});
