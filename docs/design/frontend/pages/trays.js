"use strict";
/* 设备：按设备类型直达的页面，对应左侧菜单“设备管理”及其子菜单。设备是基础对象，机柜是叠在上面的一层。
   - 设备（总览）：跨类型搜索，以及当前需要处理的设备；
   - 服务器 / 交换机 / 供电框：各自的列表，地址和固件直接在表里，行上直接操作。
     服务器可以不属于任何机柜；机柜里的服务器就是计算托盘；
   - DPU：计算托盘上的 BlueField 卡，只读。这一版只支持网卡模式，页面写明支持范围。
   机柜页是这些设备的关联与汇总视图；这里的“机柜 / 位置”链接回机柜。 */

const DEVICE_ROUTE = { compute: "devices/compute", switch: "devices/switch", power_shelf: "devices/power-shelf" };
const FW_PART = { compute: "计算托盘 BMC", switch: "交换机 BMC" };
const fwVersion = (t) => (t.baseline && FW_PART[t.type] ? DB.baseline(t.baseline).parts[FW_PART[t.type]] : "");
/* NICo 只能判断版本和基线是否相同，不能判断高低；供电框没有可读的固件版本。 */
const fwCell = (t) => (fwVersion(t) ? code(fwVersion(t)) + `<span class="cell-sub">${DB.drift(t) ? badge("与基线不同", "amber") : badge("与基线相同", "green")}</span>` : "—");
const fmBadge = (v) => ({ OK: badge("正常", "green"), NOT_OK: badge("异常", "red") })[v] || badge("未知", "gray");
const placeCell = (t) => (t.rack ? `<a class="link-button" data-go="rack/${t.rack}">${t.rack}</a><span class="cell-sub">槽位 ${pad2(t.slot)}</span>` : `<span class="muted">未分配机柜</span>`);
/* 页面和类型的名称：服务器页同时列出机柜里的计算托盘和不属于机柜的服务器。 */
const PAGE_LABEL = { compute: "服务器", switch: "交换机", power_shelf: "供电框" };
const stateCell = (t) => (t.state ? stateBadge(t.state) : t.declared ? badge(t.rack ? "已纳管 · 等待上线" : "已纳管 · 首次安装时接管", "blue") : badge("未纳管", "gray")) + (t.reason ? `<span class="cell-sub">${esc(t.reason)}</span>` : "");
const absent = (t) => (t.state ? "" : t.declared ? (t.rack ? "已纳管，还没有上线，不能操作。" : "已纳管，NICo 还没有接管：第一次装系统时接管，之后才能操作。") : "还没有纳管，不能操作。");
/* 行操作：运行状态、电源快捷入口、全部操作。电源快捷入口只是预选了动作的同一个操作对话框。 */
const rowActions = (t, mark = "") => `<div class="inline-actions" ${mark}>${act(t.power === "On" ? "关机" : "上电", "tray-op", { compact: true, gate: absent(t), extra: `data-id="${t.id}" data-action="${t.power === "On" ? "power-off" : "power-on"}"` })}${act("操作", "tray-op", { compact: true, gate: absent(t), extra: `data-id="${t.id}"` })}${t.type === "compute" ? act("系统配置", "server-config", { compact: true, gate: t.matched ? "" : "设备还没有匹配上清单", extra: `data-id="${t.id}"` }) : ""}</div>`;

/* 列尽量少，让“操作”一列在常见宽度下不用横向滚动就能看到：电源并进运行状态，维护和隔离并进健康。 */
const statePowerCell = (t) => stateCell(t) + (t.state ? `<span class="cell-sub">${powerText(t.power)}${t.instance ? " · 实例 " + t.instance.replace(/^inst-/, "") : ""}</span>` : "");
const healthCell = (t) => healthBadge(t.health) + ([t.maintenance && "维护", t.quarantine && "已隔离"].filter(Boolean).length ? `<span class="cell-sub">${[t.maintenance && "维护标记", t.quarantine && "已隔离"].filter(Boolean).join(" · ")}</span>` : "");
const DEVICE_COLUMNS = {
  compute: [["BMC 地址", bmcCell], ["管理地址", (t) => (t.hostIp ? code(t.hostIp) : "—")], ["运行状态", statePowerCell], ["健康", healthCell], ["BMC 固件", fwCell]],
  switch: [["BMC 地址", bmcCell], ["NVOS 管理口", (t) => (t.nvos.length ? code(t.nvos[0].ip) + `<span class="cell-sub">${t.primary ? "主交换机 · " : ""}共 ${t.nvos.length} 个口</span>` : "—")], ["运行状态", statePowerCell], ["健康", healthCell], ["Fabric Manager", (t) => (t.state ? fmBadge(t.fabricManager) : "—")], ["BMC 固件", fwCell]],
  power_shelf: [["BMC 地址", bmcCell], ["运行状态", statePowerCell], ["健康", healthCell]],
};
const DEVICE_TEXT = {
  compute: { sub: "查看服务器的地址、运行状态、健康、实例和固件，并直接执行电源、维护和固件操作。机柜里的服务器就是计算托盘；不属于机柜的服务器也在这里。", old: "设备管理 → 服务器", own: "无", addr: "BMC 地址和主机管理地址" },
  switch: { sub: "查看交换机的地址、运行状态、健康、Fabric Manager 和固件，并直接执行电源、复位和固件操作。", old: "设备管理 → 交换机", own: "NVOS 管理口、Fabric Manager", addr: "BMC 地址和 NVOS 管理口" },
  power_shelf: { sub: "查看供电框的地址、运行状态、健康和电源，并直接执行上下电。", old: "设备管理 → 供电框", own: "无", addr: "BMC 地址" },
};

function devicePage(type) {
  const label = PAGE_LABEL[type], text = DEVICE_TEXT[type], cols = DEVICE_COLUMNS[type], K = (k) => `dev:${type}:${k}`, hasFw = !!FW_PART[type];
  return {
    module: type, title: label,
    render() {
      const f = { rack: view(K("rack"), ""), st: view(K("st"), ""), q: view(K("q"), "").toLowerCase() };
      const all = DB.trays().filter((t) => t.type === type), checked = S.view.checked || {};
      const list = all.filter((t) => (!f.rack || (f.rack === "none" ? !t.rack : t.rack === f.rack)) && (!f.q || [t.serial, t.rack, t.bmcIp, t.bmcMac, t.hostIp, ...(t.nvos || []).map((x) => x.ip), t.state, t.instance].join(" ").toLowerCase().includes(f.q)) &&
        (!f.st || (f.st === "attention" && DB.needsAttention(t)) || (f.st === "alerting" && t.alerts.length) || (f.st === "absent" && !t.state) || (f.st === "drift" && DB.drift(t))));
      const picked = Object.keys(checked).filter((k) => checked[k] && DB.tray(k) && DB.tray(k).type === type);
      const mark = (name) => ({ "运行状态": fp(6), ...(hasFw ? { [cols[cols.length - 1][0]]: fp(5) } : {}) })[name] || "";
      return heading(label, text.sub, button("刷新数据", "refresh") + button("按机柜查看", "noop", false, 'data-go="racks"')) +
        `<div ${fp(1)}>${summary([["设备总数", all.length], ...(type === "compute" ? [["未分配机柜", all.filter((t) => !t.rack).length]] : []), ["NICo 已建立对象", all.filter((t) => t.state).length], ["需要处理", all.filter(DB.needsAttention).length], ...(hasFw ? [["固件与基线不同", all.filter(DB.drift).length]] : [])])}</div>` +
        `<div class="filter-bar" ${fp(2)}>${selectField(K("rack"), "机柜", [["", "全部"], ...S.racks.map((r) => [r.id, r.id]), ...(type === "compute" ? [["none", "未分配机柜"]] : [])], f.rack)}${selectField(K("st"), "状态", [["", "全部"], ["attention", "需要处理"], ["alerting", "有健康告警"], ["absent", "NICo 未建立对象"], ...(hasFw ? [["drift", "固件与基线不同"]] : [])], f.st)}${searchField(K("q"), "搜索", view(K("q"), ""), "序列号、机柜、状态、MAC 或 IP")}</div>` +
        `<div class="device-status-action-bar" ${fp(3)}>${act(`批量操作（${picked.length}）`, "tray-batch", { gate: picked.length ? "" : "先勾选设备" })}<span ${fp(9)}>${act(`更新 BMC 地址（${picked.length}）`, "bmc-update", { gate: picked.length ? "" : "先勾选设备" })}</span>${type === "compute" ? `<span ${fp(8)}>${act(picked.length ? `为所选 ${picked.length} 台新建安装任务` : "新建安装任务", "install-new", { extra: `data-ids="${picked.join(",")}"` })}</span>` : ""}<span class="live-small">勾选设备后批量操作，一次最多 10 台。</span></div>` +
        `<div ${fp(4)}>${table(["选择", "设备 / 序列号", "机柜 / 位置", ...cols.map((c) => c[0]), "操作"], list.map((t, i) =>
          `<tr><td><input type="checkbox" data-check="${t.id}" ${checked[t.id] ? "checked" : ""} ${t.state || t.declared ? "" : "disabled"} aria-label="选择 ${t.serial}"></td><td><a class="link-button" data-live="tray-detail" data-id="${t.id}">${code(t.serial)}</a><span class="cell-sub">${t.model}</span></td><td>${placeCell(t)}</td>${cols.map((c) => `<td ${i === 0 ? mark(c[0]) : ""}>${c[1](t)}</td>`).join("")}<td>${rowActions(t, i === 0 ? fp(7) : "")}</td></tr>`), `没有符合筛选条件的${label}。`)}</div>` +
        `<div ${fp(10)}>${bmcHistory()}</div>` +
        note("运行状态由 NICo 状态机回报。“需要处理”指状态机最近一次处理失败或有健康告警。没有收到报告显示为未报告，不显示为正常。");
    },
    spec: {
      purpose: `直接面向${label}运维：不需要先找到它在哪个机柜。地址、状态和固件在表里一眼可见，电源等操作在行上一步发起。` + (type === "compute" ? "服务器是基础对象，可以不属于任何机柜；机柜里的服务器就是计算托盘，两种都在这一页。" : ""),
      entry: `运维 → 设备管理 → ${label}；设备管理的类型卡片；机柜详情的设备页签`, design: "6.3 机柜与设备；9 操作设计", existing: `${text.old}。统计条、筛选、表头、行操作和“需要处理”的规则沿用`,
      points: [
        { n: 1, name: "统计条", kind: "调整", desc: type === "compute" ? "设备总数、NICo 已建立对象、需要处理沿用；“未填写机柜”改名“未分配机柜”，表示不属于任何机柜的服务器；增加“固件与基线不同”。" : hasFw ? "设备总数、NICo 已建立对象、需要处理沿用；“未填写机柜”换成“固件与基线不同”，因为交换机都在机柜里。" : "设备总数、NICo 已建立对象、需要处理沿用；去掉“未填写机柜”，因为供电框都在机柜里。" },
        { n: 2, name: "筛选", kind: "沿用", desc: "机柜、状态（全部、需要处理、有健康告警、NICo 未建立对象）和搜索。" + (type === "compute" ? "机柜里可以选“未分配机柜”。" : "") + (hasFw ? "状态里增加“固件与基线不同”。" : "") },
        { n: 3, name: "批量操作", kind: "沿用", desc: "勾选后对最多 10 台执行同一个动作，逐台检查、逐台出结果。" },
        { n: 4, name: `${label}表`, kind: "沿用", desc: `设备 / 序列号、机柜 / 位置、运行状态、健康沿用；电源和实例显示在运行状态下面，维护标记和隔离显示在健康下面，这样“操作”一列不用横向滚动就能看到。地址列是${text.addr}；专有列是${text.own}。点击序列号打开运行状态。` },
        { n: 5, name: "固件版本", kind: "调整", desc: hasFw ? "直接显示 BMC 固件的版本，并标出与基线相同还是不同。NICo 只能比较是否相同，不能判断高低。完整的部件清单在运行状态里。" : "供电框没有可读的固件版本，这一类设备不显示固件列。" },
        { n: 6, name: "运行状态", kind: "沿用", desc: "显示 NICo 的状态原文；有处理失败原因时显示在下方；没有对象时显示“NICo 尚未建立设备对象”。" },
        { n: 7, name: "行操作", kind: "调整", desc: "点序列号打开运行状态；“上电 / 关机”是预选了电源动作的快捷入口；“操作”打开完整的操作对话框，两者用同一个对话框和同一套检查。" + (type === "compute" ? "服务器另有“系统配置”：这台机器下次装系统用的主机名、安装方案和系统盘。" : "") },
        ...(type === "compute" ? [{ n: 8, name: "新建安装任务", kind: "新增", desc: "打开“安装任务”的向导。勾选了服务器时预先选中它们；没有勾选时从选择设备开始。" }] : []),
        { n: 9, name: "更新 BMC 地址", kind: "沿用", desc: "沿用现有产品。勾选设备后打开：逐台列出当前地址和规划地址，规划地址可以直接在表里改；确认后把 BMC 改成规划的固定地址。也可以只保存规划、不动设备。" },
        { n: 10, name: "近期 BMC 地址更新", kind: "沿用", desc: "每次提交一行：提交时间、设备、进度、原因和操作者，可以再打开看每个接口走到四步里的哪一步。没有更新过时不显示。" },
      ],
      fields: [["BMC 地址", "NICo 回报的当前地址 + 平台保存的规划地址", "下面一行写明它和规划的关系：DHCP 分配（没有规划）、待改为某个地址、正在改、已按规划"], ["机柜 / 位置", "到货清单", type === "compute" ? "链接到机柜详情；不属于机柜的服务器显示“未分配机柜”" : "链接到机柜详情，那里是关联与汇总视图"], ["地址", "NICo Core", text.addr], ...(hasFw ? [[cols[cols.length - 1][0], "NICo 读到的版本对比推荐基线", "版本，以及与基线相同 / 与基线不同"]] : []), ...(type === "compute" ? [["实例", "NICo Core", "有实例的托盘操作前会提示影响"]] : type === "switch" ? [["NVOS 管理口", "NICo Core", "主口的地址和口的数量"], ["Fabric Manager", "NICo Core", "NICo 回报 OK、NOT_OK、UNKNOWN，显示为正常、异常、未知"]] : [["序列号", "到货清单", "NICo 的供电框对象不带序列号，这里显示清单里的"]])],
      rules: ["“需要处理”只用 NICo 的信号：处理失败、有健康告警。", "还没有纳管的设备不能勾选。已纳管但 NICo 还没有建立对象的设备可以勾选，只能更新 BMC 地址，不能做电源等操作。", "BMC 地址：设备接电时拿到的是 DHCP 地址池里的任意一个地址；纳管之后才能按规划更新。规划地址要在带外管理子网内，不能是网关，不能和已有地址或其他设备的规划重复。", "更新 BMC 地址是人手动发起的，不会自动执行。通过检查的设备依次走四步：检查地址与身份、更新 BMC、验证新地址、同步管理记录；没通过的写明原因，不执行。地址切换时管理连接可能短暂中断；不触发装机，不影响主机上运行的系统。", ...(type === "compute" ? ["不属于机柜的服务器没有“上线”这一步：纳管后不上电，第一次装系统时由 NICo 上电接管。", "系统配置是一台服务器下次装系统时用的配置。可以改的是管理地址、主机名、安装方案和系统盘，每一项都有默认值，不填也能装；启动网卡只显示，其他网口不管理也不显示。它归这一页维护，新建安装任务只引用它。第一次装机和以后重装用的是同一份，改一次一直有效。", "退役是逐台设备的操作。有实例的服务器不能退役。"] : []), type === "compute" ? "有实例的服务器，关机等操作要输入序列号确认。" : `${label}的高风险操作按整柜实例计算影响；机柜上还有已分配的计算托盘时不能退役。`, "只读角色的操作按钮禁用。"],
      dialogs: [{ name: "更新 BMC 地址", desc: "沿用现有产品的流程。第一屏逐台列出设备、接口（BMC 或 PMC 及其 MAC）、当前地址、规划地址和检查结果；规划地址是输入框，改了立即重新检查。确认后进入进度：上面是汇总（已完成几步、几个接口已更新），下面每个接口一张卡片，显示“旧地址 → 新地址”和四步各自的状态。关闭窗口后继续执行。", fields: [["规划地址", "是，逐台", "可以直接在表里改；一次最多 50 台"], ["原因", "开始更新时", "写入审计"], ["只保存规划", "否", "只记下规划地址，不动设备"], ["确认并开始更新", "否", "只对通过检查的设备执行，按钮上写明台数"]] },
        { name: "操作对话框（单台与批量共用）", desc: "选对象、选动作、写原因，一个弹窗完成。逐台显示检查结果，只对通过的目标执行。现有的“设备操作 → 确认操作 → 操作结果”三步合成一步，结果进入任务或审计。",
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
    const card = (type) => { const all = trays.filter((t) => t.type === type); return `<a class="device-card" data-go="${DEVICE_ROUTE[type]}"><strong>${PAGE_LABEL[type]}</strong><b>${all.length}</b><span>${all.filter(DB.needsAttention).length ? badge(all.filter(DB.needsAttention).length + " 台需要处理", "amber") : badge("无需处理", "green")}　${FW_PART[type] && all.filter(DB.drift).length ? badge(all.filter(DB.drift).length + " 台固件与基线不同", "gray") : ""}${type === "compute" ? "　" + badge(`机柜内 ${all.filter((t) => t.rack).length} · 未分配机柜 ${all.filter((t) => !t.rack).length}`, "gray") : ""}</span></a>`; };
    const rows = list.slice(0, 30).map((t) => `<tr><td><a class="link-button" data-live="tray-detail" data-id="${t.id}">${code(t.serial)}</a><span class="cell-sub">${esc(t.model)}</span></td><td>${typeLabel(t)}</td><td>${placeCell(t)}</td><td>${t.bmcIp ? code(t.bmcIp) : "—"}${t.hostIp || (t.nvos && t.nvos.length) ? `<span class="cell-sub live-code">${t.hostIp || t.nvos[0].ip}</span>` : ""}</td><td>${stateCell(t)}</td><td>${healthBadge(t.health)}${t.alerts.length ? `<span class="cell-sub">${esc(t.alerts[0].msg)}</span>` : ""}</td><td>${fwCell(t)}</td><td>${rowActions(t)}</td></tr>`);
    return heading("设备管理", "按序列号、地址或实例直接找到一台设备，查看状态并操作。各类型的完整列表在左侧子菜单。", button("刷新数据", "refresh")) +
      `<div class="filter-bar" ${fp(1)}>${searchField("devQ", "搜索全部设备", view("devQ", ""), "序列号、BMC 或管理地址、MAC、机柜或实例")}</div>` +
      `<div class="device-cards" ${fp(2)}>${["compute", "switch", "power_shelf"].map(card).join("")}<a class="device-card" data-go="devices/dpu"><strong>DPU</strong><b>${dpuRows().length}</b><span>${badge("网卡模式 " + dpuRows().filter(({ d }) => d.mode === "Nic").length, "green")}　${badge("DPU 模式不支持", "gray")}</span></a></div>` +
      `<h2 class="section-title">${q ? `搜索结果 · ${list.length} 台` : `需要处理的设备 · ${list.length} 台`}</h2>` +
      `<div ${fp(3)}>${table(["设备 / 序列号", "类型", "机柜 / 位置", "地址", "运行状态", "健康", "固件", "操作"], rows, q ? "没有匹配的设备。" : "当前没有需要处理的设备。")}</div>` +
      `<div ${fp(4)}>${note("<b>设备是基础，机柜是叠在上面的一层。</b>每台设备的地址、状态、固件和单台操作都在这里维护。机柜只管必须把整柜当成一个整体的事：上线、整柜电源和固件、机柜维护。要看一个机柜里的全部设备，从“机柜 / 位置”进入机柜详情。不属于任何机柜的服务器只在这里出现。")}</div>`;
  },
  spec: {
    purpose: "设备运维的起点。知道序列号或地址时一步找到设备；不知道时先看哪些设备需要处理。",
    entry: "运维 → 设备管理", design: "6.3 机柜与设备", existing: "新增页面。现有产品要先选设备类型的页面再搜索",
    points: [
      { n: 1, name: "跨类型搜索", kind: "新增", desc: "一个输入框搜索全部服务器、交换机和供电框：序列号、BMC 或管理地址、MAC、机柜、实例。" },
      { n: 2, name: "类型卡片", kind: "新增", desc: "每类设备的数量、需要处理的数量和固件与基线不同的数量；DPU 卡片显示 BlueField 卡的数量和支持范围。点击进入该类型的列表。" },
      { n: 3, name: "需要处理的设备 / 搜索结果", kind: "调整", desc: "没有搜索词时列出各类型里需要处理的设备；有搜索词时列出匹配的设备。行操作与各类型页面相同。" },
      { n: 4, name: "设备与机柜的分工", kind: "新增", desc: "说明设备是基础对象，机柜是叠在上面的一层：单台设备的事在设备管理，整柜的事在机柜管理。不属于机柜的服务器只在设备管理出现。" },
    ],
    fields: [["类型", "清单", "服务器、交换机、供电框。机柜里的服务器显示为计算托盘"], ["地址", "NICo Core", "BMC 地址；服务器另有管理地址，交换机另有 NVOS 管理口"], ["固件", "NICo 读到的版本", "BMC 固件版本与基线是否相同；供电框没有"]],
    rules: ["DPU 不在搜索结果里：这一版 BlueField 只作为网卡使用，不是独立的设备。它有自己的只读页面。", "列表最多显示 30 台，更多用子菜单里的类型页面筛选。"],
  },
});

/* ---------- DPU ----------
   计算托盘上的 BlueField 卡。NICo 对每台主机有一个 DPU 策略：由 NICo 管理（DPU 模式）、当网卡用（网卡模式）、忽略。
   这一版只支持网卡模式：NICo 仍会探测这些卡的 BMC，所以能看到序列号、固件和工作方式，但不把它们当成独立的设备来管理。 */
const POLICY_LABEL = { nic: "网卡模式", manage: "DPU 模式", ignore: "忽略" }, MODE_LABEL = { Nic: "网卡", Dpu: "DPU" };
const dpuRows = () => DB.trays().filter((t) => t.type === "compute" && t.state && t.nics.length).flatMap((t) => t.nics.map((d) => ({ d, t })));
const dpuMatch = (d) => (d.policy === "nic") === (d.mode === "Nic");
registerPage("devices/dpu", {
  module: "dpu", title: "DPU",
  render() {
    const f = { rack: view("dpuRack", ""), q: view("dpuQ", "").toLowerCase() };
    const all = dpuRows(), list = all.filter(({ d, t }) => (!f.rack || t.rack === f.rack) && (!f.q || [d.serial, d.ip, t.serial, t.rack].join(" ").toLowerCase().includes(f.q)));
    return heading("DPU", "查看每个计算托盘上的 BlueField 卡：策略、实际工作方式、固件和 BMC 地址。", button("刷新数据", "refresh")) +
      `<div ${fp(5)}>${note("<b>这一版只支持网卡模式。</b>BlueField 当普通网卡使用，主机直接从主机管理网段获得地址。由 NICo 管理 DPU 的方式（DPU 模式）这一版不支持：那种方式下每块卡是一台独立的设备，有自己的运行状态、系统和固件更新，主机的地址和租户网络也经它提供。", "warning")}</div>` +
      `<div ${fp(1)}>${summary([["BlueField 卡", all.length], ["网卡模式", all.filter(({ d }) => d.mode === "Nic").length], ["DPU 模式（不支持）", all.filter(({ d }) => d.mode === "Dpu").length], ["策略与实际不一致", all.filter(({ d }) => !dpuMatch(d)).length]])}</div>` +
      `<div class="filter-bar" ${fp(2)}>${selectField("dpuRack", "机柜", [["", "全部机柜"], ...S.racks.map((r) => [r.id, r.id])], f.rack)}${searchField("dpuQ", "搜索", view("dpuQ", ""), "卡的序列号、BMC 地址、主机序列号或机柜")}<span class="live-small">${list.length} 块</span></div>` +
      `<div ${fp(3)}>${table(["BlueField / 序列号", "所属计算托盘", "机柜 / 位置", "BMC 地址", "策略", "实际工作方式", "网卡固件", "操作"], list.slice(0, 40).map(({ d, t }) => `<tr><td>${code(d.serial)}<span class="cell-sub">${d.name} · ${d.part}</span></td><td><a class="link-button" data-live="tray-detail" data-id="${t.id}">${code(t.serial)}</a></td><td>${placeCell(t)}</td><td>${code(d.ip)}</td><td>${POLICY_LABEL[d.policy]}</td><td>${badge(MODE_LABEL[d.mode] || "未知", d.mode === "Nic" ? "green" : "amber")}${dpuMatch(d) ? "" : `<span class="cell-sub">与策略不一致</span>`}</td><td>${code(d.fw)}</td><td><div class="inline-actions" ${fp(4)}>${button("所属主机", "tray-detail", false, `data-id="${t.id}"`)}</div></td></tr>`), "还没有计算托盘被 NICo 接管，所以没有读到 BlueField 卡。")}${list.length > 40 ? `<p class="live-small">显示前 40 块，共 ${list.length} 块。</p>` : ""}</div>`;
  },
  spec: {
    purpose: "把计算托盘上的 BlueField 卡单独列出来，回答“每块卡现在是什么工作方式、和策略是否一致、是什么固件”。",
    entry: "运维 → 设备管理 → DPU", design: "3.2 不纳入范围（DPU 模式）；6.3 机柜与设备", existing: "新增页面。现有产品只在设备管理的“DPU 子接口”和服务器运行状态的“关联 DPU”里出现",
    points: [
      { n: 1, name: "统计条", kind: "新增", desc: "BlueField 卡的总数、网卡模式的数量、DPU 模式的数量、策略与实际不一致的数量。" },
      { n: 2, name: "筛选", kind: "新增", desc: "机柜和搜索（卡的序列号、BMC 地址、主机序列号）。" },
      { n: 3, name: "卡的列表", kind: "新增", desc: "序列号和部件号、所属计算托盘、位置、BMC 地址、策略、实际工作方式、网卡固件。" },
      { n: 4, name: "所属主机", kind: "新增", desc: "打开所属计算托盘的运行状态。" },
      { n: 5, name: "支持范围", kind: "新增", desc: "写明这一版只支持网卡模式，以及 DPU 模式不支持的是什么。" },
    ],
    fields: [["策略", "NICo 的设备声明与站点配置", "站点有一个默认策略，单台主机可以覆盖。这一版平台写入的都是网卡模式"], ["实际工作方式", "NICo 探测 BlueField 的 BMC", "卡自己上报的是网卡还是 DPU；固件太旧时读不到，显示未知"], ["网卡固件 / 部件号 / 序列号", "NICo 的探测结果", ""], ["BMC 地址", "NICo", "卡的 BMC 在带外管理网段申请的地址"]],
    rules: ["页面只读。", "这一版只支持网卡模式：卡不是独立的设备对象，没有运行状态，也不单独升级固件。", "实际工作方式与策略不一致时标出来。把卡切换到网卡模式由 NICo 在接管主机时完成，不在这里操作。", "以后支持 DPU 模式时，这一页增加每块卡的运行状态、系统版本和与主机的配对，页面结构不变。"],
  },
});

/* ---------- 托盘运行状态（抽屉） ---------- */
registerAction("tray-detail", ({ id }) => {
  const t = DB.tray(id), r = DB.rack(t.rack), d = DB.domain(r.domain), base = DB.baseline(t.baseline), rec = BASELINES[0];
  /* 不属于机柜的服务器：没有上线这一步，纳管在设备发现里逐台确认，第一次装系统时接管。 */
  if (!t.state && !t.rack) return modal(t.serial, "服务器 · 运行状态", note(t.declared ? "这台服务器已经纳管，不属于任何机柜。NICo 已接手它的 BMC 口令，但没有给它上电，也没有建立设备对象。<b>它没有“上线”这一步：第一次装系统时，NICo 才给它上电并接管。</b>" : "这台服务器已经匹配上清单，还没有纳管。它不属于任何机柜，在“设备发现”里逐台确认纳管。") + defs([["清单里的序列号", code(t.serial)], ["机柜", "未分配机柜"], ["BMC MAC 与地址", code(t.bmcMac) + " · " + code(t.bmcIp)], ["设备凭据", t.declared ? "已交给 NICo" : "已提供，不显示"]]), button("关闭", "close") + (t.declared ? act("新建安装任务", "install-new", { primary: true, extra: `data-ids="${t.id}"` }) : button("去设备发现", "close-go", true, 'data-to="discovery"')), { drawer: true });
  if (!t.state) return modal(t.serial, `${TYPE_LABEL[t.type]} · 运行状态`, note(t.declared ? `这台设备已经纳管（${t.rack} 槽位 ${pad2(t.slot)}），还没有上线：NICo 已接手它的 BMC 口令，但没有给它上电，也没有建立设备对象。在机柜详情开始上线。` : t.matched ? `这台设备已经匹配上清单（${t.rack} 槽位 ${pad2(t.slot)}），还没有纳管。在机柜详情确认纳管。` : `这台设备在到货清单中（${t.rack} 槽位 ${pad2(t.slot)}），还没有读到它的身份。机柜接电并匹配上之后才能纳管。`) + defs([["清单里的序列号", code(t.serial)], ["BMC MAC 与地址", t.bmcIp ? code(t.bmcMac) + " · " + code(t.bmcIp) : "接电后获得"], ["设备凭据", t.declared ? "已交给 NICo" : "已提供，不显示"]]), button("关闭", "close") + (t.matched ? button("去机柜详情", "close-go", true, `data-to="rack/${t.rack}"`) : button("去设备发现", "discovery-rack", true, `data-rack="${t.rack}"`)), { drawer: true });
  const partKeys = { compute: ["计算托盘 BMC", "计算托盘 UEFI"], switch: ["交换机 BMC"], power_shelf: [] }[t.type];
  let body = defs([["NICo 对象 ID", code("obj-" + t.serial.toLowerCase())], ["机柜 / 位置", t.rack ? `${t.rack} · 槽位 ${pad2(t.slot)}` : "未分配机柜"], ["运行状态", stateBadge(t.state) + (t.reason ? ` <span class="live-small">${esc(t.reason)}</span>` : "")], ["电源", powerText(t.power)], ["BMC 地址", code(t.bmcIp) + " · " + code(t.bmcMac) + " · " + t.addrMode + (t.bmcPlan && t.bmcPlan !== t.bmcIp ? ` · 规划 ${code(t.bmcPlan)}，待更新` : t.bmcPlan ? " · 已按规划" : " · 未规划") + ` <button class="link-button" data-live="bmc-update" data-ids="${t.id}">更新 BMC 地址</button>`], ["健康", healthBadge(t.health)], ["最近报告", code(t.lastSeen)]]);
  body += `<h3 class="section-title">健康告警</h3>` + table(["告警", "说明", "开始时间", "分类"], t.alerts.map((a) => `<tr><td>${code(a.id)}${a.target ? `<span class="cell-sub live-code">${esc(a.target)}</span>` : ""}</td><td>${esc(a.msg)}</td><td>${code(a.since)}</td><td>${alertClass(a) || "—"}</td></tr>`), "当前没有健康告警。");
  if (t.type === "compute") {
    body += `<h3 class="section-title">主机</h3>` + defs([["SKU", code(t.sku)], ["实例", t.instance ? code(t.instance) : "未分配"], ["隔离", t.quarantine ? badge("已隔离", "red") + " " + esc(t.quarantine) : "未隔离"], ["维护标记", t.maintenance ? esc(t.maintenance) : "—"], ["架构", code(t.arch)], ["主机管理地址", code(t.hostIp) + " · " + code(t.hostMac)], ["系统配置", (() => { const c = sysCfg(t); return `主机名 ${code(c.host || "未确定")}${c.hostAuto ? "（按管理地址生成）" : ""} · ${esc(c.os.split(" · ")[0])}${c.osAuto ? "（默认方案）" : ""} · 系统盘${c.disk ? " " + esc(c.disk) : "按方案的规则"}`; })()], ...(t.rack ? [["NVLink 域", code(r.domain)]] : [])]);
    if (t.nics.length) body += `<h3 class="section-title">DPU（BlueField）</h3>` + table(["卡 / 序列号", "策略", "实际工作方式", "网卡固件", "BMC 地址"], t.nics.map((c) => `<tr><td>${c.name}<span class="cell-sub live-code">${c.serial}</span></td><td>${POLICY_LABEL[c.policy]}</td><td>${MODE_LABEL[c.mode] || "未知"}</td><td>${code(c.fw)}</td><td>${code(c.ip)}</td></tr>`)) + `<p class="live-small">这一版只支持网卡模式。</p>`;
    body += `<h3 class="section-title">硬件能力</h3>` + table(["类别", "规格"], Object.entries(t.hardware).map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`));
    body += `<h3 class="section-title">LLDP 邻居</h3>` + table(["本机接口", "邻居交换机", "邻居端口"], t.lldp.map((l) => `<tr><td>${code(l.port)}</td><td>${l.sw}</td><td>${code(l.remote)}</td></tr>`));
  }
  if (t.type === "switch") {
    body += `<h3 class="section-title">交换机</h3>` + defs([["主交换机", t.primary ? "是" : "否"], ["NVLink 域", code(r.domain) + (d && d.uuid ? `<span class="cell-sub live-code">${d.uuid}</span>` : "")], ["Fabric Manager", fmBadge(t.fabricManager) + ` <span class="live-code">${t.fabricManager || "—"}</span>`]]);
    body += `<h3 class="section-title">NVOS 管理口</h3>` + table(["接口", "MAC", "地址", "角色"], t.nvos.map((x) => `<tr><td>${x.name}</td><td>${code(x.mac)}</td><td>${code(x.ip)}</td><td>${x.primary ? "主口" : "备用口"}</td></tr>`));
  }
  if (partKeys.length && t.baseline) body += `<h3 class="section-title">固件</h3>` + table(["部件", "版本", "推荐基线版本", "对比"], partKeys.map((k) => `<tr><td>${k}</td><td>${code(base ? base.parts[k] : "—")}</td><td>${code(rec.parts[k])}</td><td>${base && base.parts[k] === rec.parts[k] ? badge("相同", "green") : badge("不同", "amber")}</td></tr>`).concat(t.type === "switch" ? [`<tr><td>NVOS</td><td><span class="muted">NICo 读不到已安装的版本</span></td><td>${code(rec.nvos)}</td><td>—</td></tr>`] : []));
  body += `<h3 class="section-title">状态时间线</h3>` + table(["状态", "进入时间"], [...t.history].reverse().map((h, i) => `<tr><td>${stateBadge(h[1])}${i === 0 ? " " + badge("当前", "amber") : ""}</td><td>${code(h[0])}</td></tr>`));
  modal(t.serial, `${typeLabel(t)} · 运行状态 · ${placeText(t)}`, body, button("关闭", "close") + (t.type === "compute" ? act("系统配置", "server-config", { extra: `data-id="${t.id}"` }) : "") + act("操作", "tray-op", { primary: true, extra: `data-id="${t.id}"` }), { drawer: true });
});

/* ---------- BMC 地址：规划与更新 ----------
   沿用现有产品的“更新 BMC 地址”。设备接电时 BMC 从 DHCP 拿到的是地址池里随便一个地址；纳管之后，按规划把它改成固定地址。
   规划地址可以随到货清单带进来，也可以在这里逐台填。更新是人手动发起的：勾选设备，核对“当前地址 → 规划地址”，确认后执行四步：
   检查地址与身份、更新 BMC、验证新地址、同步管理记录。关掉弹窗后继续执行，可以从近期记录再看进度。 */
const oobSubnet = () => DB.roleSubnets("oob")[0];
const bmcRole = (t) => (t.type === "power_shelf" ? "PMC" : "BMC");
const BMC_PHASES = ["检查地址与身份", "更新 BMC", "验证新地址", "同步管理记录"];
const bmcRunning = (t) => S.bmcJobs.some((j) => j.rows.some((r) => r.tray === t.id && r.at < BMC_PHASES.length));
/* 表里的 BMC 地址：当前地址，以及它和规划的关系。 */
function bmcCell(t) {
  if (!t.bmcIp) return "—";
  const sub = bmcRunning(t) ? `正在改为 ${t.bmcPlan}` : t.bmcPlan && t.bmcPlan !== t.bmcIp ? `待改为 ${t.bmcPlan}` : t.bmcPlan ? "已按规划" : "DHCP 分配";
  return code(t.bmcIp) + `<span class="cell-sub">${sub}</span>`;
}
/* 一台设备现在能不能按这个规划地址更新：返回不能的原因，空字符串表示可以。 */
function bmcCheck(t, plan, plans) {
  const net = oobSubnet();
  if (!t.declared) return "还没有纳管，纳管之后才能更新";
  if (!t.bmcIp) return "设备还没有拿到地址";
  if (bmcRunning(t)) return "这台设备正在更新";
  if (!plan) return "没有填规划地址";
  if (!IP4.test(plan)) return "不是合法的 IPv4 地址";
  if (!inCidr(plan, net.cidr)) return `不在带外管理子网 ${net.cidr} 内`;
  if (plan === net.gateway) return "不能使用网关地址";
  if (plan === t.bmcIp) return "当前已经是规划地址";
  const used = DB.interfaces().find((i) => i.ip === plan && i.tray.id !== t.id); if (used) return `地址已被 ${used.tray.serial} 使用`;
  const dup = Object.entries(plans || {}).find(([id, ip]) => id !== t.id && ip === plan) || DB.trays().filter((x) => x.id !== t.id && !(plans && x.id in plans)).map((x) => [x.id, x.bmcPlan]).find(([, ip]) => ip === plan);
  return dup ? `和 ${DB.tray(dup[0]).serial} 的规划地址重复` : "";
}
registerAction("bmc-update", ({ ids }) => {
  const current = (PAGES[route().id] || {}).module, list = (ids ? ids.split(",") : Object.keys(S.view.checked || {}).filter((k) => S.view.checked[k] && DB.tray(k) && DB.tray(k).type === current)).map(DB.tray).filter(Boolean);
  if (!list.length) return toast("先勾选设备");
  if (list.length > 50) return toast("一次最多 50 台");
  S.view.bmcDraft = { ids: list.map((t) => t.id), plans: Object.fromEntries(list.map((t) => [t.id, t.bmcPlan || ""])), why: "" }; bmcDialog();
});
function bmcDialog() {
  const d = S.view.bmcDraft, list = d.ids.map(DB.tray), net = oobSubnet(), res = (t) => { const why = bmcCheck(t, d.plans[t.id], d.plans); return why ? `<span class="live-error">${esc(why)}</span>` : badge("可执行", "green"); };
  modal("更新 BMC 地址", `已选择 ${list.length} 台设备 · 带外管理子网 ${net.name} · ${net.cidr}`,
    `<p class="wiz-lead-note">设备接电时 BMC 拿到的是 DHCP 地址池里的一个地址。纳管之后，在这里核对每台的规划地址，确认后把 BMC 改成规划的固定地址。<b>规划地址可以直接在表里改。</b></p>` +
    table(["设备 / 位置", "接口", "当前地址", "规划地址", "检查"], list.map((t) => `<tr><td><strong class="live-code">${t.serial}</strong><span class="cell-sub">${typeLabel(t)} · ${placeText(t)}</span></td><td>${bmcRole(t)}<span class="cell-sub live-code">${t.bmcMac || "—"}</span></td><td>${t.bmcIp ? code(t.bmcIp) : "—"}<span class="cell-sub">${t.bmcPlan && t.bmcPlan === t.bmcIp ? "固定地址" : "DHCP 分配"}</span></td><td><input class="input live-code bmc-plan" data-bmc-plan="${t.id}" value="${esc(d.plans[t.id])}" placeholder="${net.cidr.replace(/\d+\/\d+$/, "x")}" autocomplete="off" aria-label="${t.serial} 的规划地址"></td><td data-bmc-res="${t.id}">${res(t)}</td></tr>`)) +
    `<div class="live-note live-warning">确认后将检查规划地址、目标地址占用和设备身份。通过检查的设备会立即关闭 BMC 的 DHCP、写入规划的固定地址，并同步 NICo 的管理记录；<b>地址切换时管理连接可能短暂中断</b>。未通过检查的设备不会执行。更新 BMC 地址不触发装机，也不影响主机上正在运行的系统。</div>
     <div class="live-form">${field("原因", `<input class="input" id="bmc-why" value="${esc(d.why)}" placeholder="工单号或原因">`)}</div>`,
    button("取消", "close") + act("只保存规划", "bmc-plan-save") + act("确认并开始更新", "bmc-update-run", { primary: true, extra: 'id="bmc-go"' }));
  $("#overlay-root .modal").classList.add("wiz-config");
  const sync = () => { document.querySelectorAll("[data-bmc-plan]").forEach((el) => (d.plans[el.dataset.bmcPlan] = el.value.trim())); list.forEach((t) => (document.querySelector(`[data-bmc-res="${t.id}"]`).innerHTML = res(t))); const n = list.filter((t) => !bmcCheck(t, d.plans[t.id], d.plans)).length, b = $("#bmc-go"); if (b && S.role !== "只读") { b.disabled = !n; b.textContent = n ? `确认并开始更新（${n} 台）` : "确认并开始更新"; } };
  $("#overlay-root .modal-body").addEventListener("input", (e) => { if (e.target.dataset.bmcPlan) sync(); }); sync();
}
/* 保存规划：只记下每台的规划地址，不动设备。格式不对的不保存。 */
function bmcSavePlans() {
  const d = S.view.bmcDraft, bad = d.ids.filter((id) => d.plans[id] && !IP4.test(d.plans[id]));
  if (bad.length) { toast(`${DB.tray(bad[0]).serial} 的规划地址不是合法的 IPv4 地址`); return false; }
  d.ids.forEach((id) => (DB.tray(id).bmcPlan = d.plans[id])); return true;
}
registerAction("bmc-plan-save", () => { if (!bmcSavePlans()) return; const n = S.view.bmcDraft.ids.length; addAudit(`${n} 台设备`, "保存 BMC 规划地址", "—", "—", "已保存，设备未改动"); closeModal(); S.view.bmcDraft = null; toast("规划地址已保存，设备没有改动"); render(); });
registerAction("bmc-update-run", () => {
  const d = S.view.bmcDraft, why = $("#bmc-why").value.trim(), pass = d.ids.map(DB.tray).filter((t) => !bmcCheck(t, d.plans[t.id], d.plans));
  if (!pass.length) return toast("没有通过检查的设备");
  if (!why) return toast("请填写原因");
  if (!bmcSavePlans()) return;
  const job = { id: "bmc-" + String(S.bmcJobs.length + 1).padStart(4, "0"), at: nowText(), by: "ops-01", why, rows: pass.map((t) => ({ tray: t.id, serial: t.serial, role: bmcRole(t), mac: t.bmcMac, from: t.bmcIp, to: t.bmcPlan, at: 0 })) };
  S.bmcJobs.unshift(job); S.view.bmcDraft = null; S.view.checked = {}; const rec = addAudit(pass.length === 1 ? pass[0].serial : `${pass.length} 台设备`, "更新 BMC 地址", why, job.id, "已提交");
  /* 模拟：每个接口依次走四步。真实实现里每一步由服务端执行，页面只轮询进度。 */
  job.timer = setInterval(() => {
    job.rows.forEach((r) => { if (r.at >= BMC_PHASES.length) return; r.at++; if (r.at === BMC_PHASES.length) { const t = DB.tray(r.tray); if (t) { t.bmcIp = r.to; t.addrMode = "固定地址"; } } });
    if (job.rows.every((r) => r.at >= BMC_PHASES.length)) { clearInterval(job.timer); job.timer = 0; rec.res = `${job.rows.length} 个接口已更新并验证`; toast(`BMC 地址更新完成：${job.rows.length} 个接口`); }
    if (S.view.bmcOpen === job.id && $("#bmc-progress")) $("#bmc-progress").innerHTML = bmcProgress(job); else if (!S.view.modal) render();
  }, 1100);
  bmcShowProgress(job.id); 
});
const BMC_DETAIL = ["正在检查规划、地址占用与设备身份…", "正在关闭 DHCP 并写入固定地址…", "正在用新地址登录并核对序列号…", "正在把新地址同步到 NICo 的管理记录…", "已完成：BMC 使用规划的固定地址"];
function bmcProgress(job) {
  const total = job.rows.length * BMC_PHASES.length, done = job.rows.reduce((n, r) => n + r.at, 0), finished = job.rows.filter((r) => r.at >= BMC_PHASES.length).length, running = finished < job.rows.length;
  return `<div class="bmc-progress-summary"><div><span class="bmc-eyebrow">BMC 地址更新</span><strong>${running ? "正在执行" : "更新完成"}</strong><span class="live-small">已完成 ${done} / ${total} 个步骤 · ${finished} / ${job.rows.length} 个接口已更新</span></div><span class="bmc-summary-dot ${running ? "running" : "completed"}" aria-hidden="true"></span></div><progress class="bmc-progress-meter" value="${done}" max="${total}" aria-label="已完成步骤"></progress>
    <div class="bmc-progress-cards">${job.rows.map((r) => `<section class="bmc-progress-card"><header><div><strong>${r.serial}</strong><span class="live-small">${r.role} · ${r.mac}</span></div><div class="bmc-address-change"><span>${r.from}</span><span class="bmc-address-arrow" aria-hidden="true">→</span><strong>${r.to}</strong></div></header>
      <ol class="bmc-stepper" aria-label="BMC 地址更新步骤">${BMC_PHASES.map((label, i) => { const st = i < r.at ? "completed" : i === r.at ? "running" : "waiting"; return `<li class="bmc-step ${st}" ${st === "running" ? 'aria-current="step"' : ""}><span class="bmc-step-dot" aria-hidden="true"></span><span class="bmc-step-label">${label}</span><span class="bmc-step-status">${{ completed: "已完成", running: "进行中", waiting: "待执行" }[st]}</span></li>`; }).join("")}</ol>
      <div class="bmc-operation-detail" role="status">${BMC_DETAIL[r.at]}</div></section>`).join("")}</div>`;
}
function bmcShowProgress(id) { const job = S.bmcJobs.find((j) => j.id === id); S.view.bmcOpen = id; modal("更新 BMC 地址", "关闭窗口后继续执行；可从近期更新记录再次查看。", `<div id="bmc-progress" aria-live="polite">${bmcProgress(job)}</div>`, button("关闭", "close", true)); render(); }
registerAction("bmc-progress", ({ id }) => bmcShowProgress(id));
/* 近期 BMC 地址更新：每次提交一行，可以再打开看进度。 */
function bmcHistory() {
  return S.bmcJobs.length ? `<h2 class="section-title">近期 BMC 地址更新</h2>` + table(["提交时间", "设备", "进度", "原因 / 操作者", "操作"], S.bmcJobs.slice(0, 10).map((j) => { const done = j.rows.filter((r) => r.at >= BMC_PHASES.length).length;
    return `<tr><td>${code(j.at)}</td><td>${esc(j.rows.slice(0, 4).map((r) => r.serial).join("、"))}${j.rows.length > 4 ? ` 等 ${j.rows.length} 台` : ""}</td><td>${done === j.rows.length ? badge("已完成", "green") : badge("执行中", "amber")} ${done} / ${j.rows.length} 个接口完成</td><td>${esc(j.why)}<span class="cell-sub">${j.by}</span></td><td>${button("查看进度", "bmc-progress", false, `data-id="${j.id}"`)}</td></tr>`; })) : "";
}
