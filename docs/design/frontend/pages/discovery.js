"use strict";
/* 设备发现：到货清单里没有 MAC，所以先由平台认出每台设备。
   机柜接电后，BMC 拿到地址；平台用清单里的凭据读它的身份，按序列号匹配清单里的一行。这一段只读设备。
   之后的三件事各有一个人工入口：确认纳管（登记到 NICo）、开始上线（上电并接管）、装系统。机柜里的设备，前两件在机柜详情按机柜做。
   不属于机柜的服务器在这一页逐台确认纳管；它没有上线这一步，第一次装系统时由 NICo 上电接管。
   这一页是工作台：匹配上的不用管，人只处理匹配不上的端点。合并现有的“发现设备”和“发现诊断”。 */

/* 从接电到装好系统的全过程：每一步由谁触发、设备上发生什么。 */
const DISCOVERY_STEPS = [
  ["机柜接电", "现场", "BMC 待机通电并申请地址，NICo DHCP 从带外地址池分配。设备本身不开机", "BMC 的地址在这时确定，之后不变"],
  ["读取身份、匹配清单", "自动", "平台用清单里的凭据登录一次 BMC，读出类型、序列号和型号，按序列号对上清单里的一行", "只读，不改设备。认证失败或清单里没有的，在本页处理"],
  ["确认纳管", "人。机柜里的设备每个机柜一次；不属于机柜的服务器逐台", "平台把声明写进 NICo；NICo 登录 BMC，把口令换成站点凭据。服务器的声明带暂停标记", "不上电、不改 BIOS、不动磁盘、不装系统"],
  ["开始上线", "人，每个机柜一次。不属于机柜的服务器没有这一步", "上线任务按顺序上电：供电框、计算托盘、交换机；放行计算托盘后 NICo 接管它：设置 BIOS 和启动顺序、从网络启动发现程序读硬件。交换机就绪后 NICo 自动做机柜维护：固件、NVOS、NMX-C 集群、校验", "设备会上电和重启；按站点策略可能清理全部磁盘；主机管理地址在这时分配。仍然不装系统"],
  ["装系统", "人，逐台确定", "在“安装任务”里选设备，逐台确定主机名、安装方案和系统盘，装操作系统并验收。不属于机柜的服务器在这时才由 NICo 上电接管", "这一步才写系统盘"],
];
const EP_PROBLEM = {
  auth: { text: "认证失败", tip: "清单里的凭据登录不了这台设备。平台不会逐组尝试口令，以免触发 BMC 的登录锁定", action: "指定凭据重试" },
  unlisted: { text: "清单里没有这个序列号", tip: "可能是出厂替换件，也可能是接错网络的设备", action: "替换清单中的一行" },
  unreadable: { text: "读不到序列号", tip: "设备的 BMC 没有返回序列号", action: "指定凭据重试" },
};
/* 清单里一行的进度。匹配之前不知道哪个地址是它，所以只有“等待”这一种状态。 */
function discoveryState(t) {
  if (!t.rack) return t.state ? (/Ready$/.test(t.state) ? { key: "ok", text: "已接管", color: "green", tip: "" } : { key: "taking", text: "接管中", color: "blue", tip: t.reason || "" })
    : t.declared ? { key: "held", text: "已纳管 · 首次安装时接管", color: "blue", tip: "已经登记到 NICo，设备还没有上电。不属于机柜的服务器没有上线这一步：第一次装系统时由 NICo 上电接管" }
    : { key: "matched", text: "已匹配 · 待确认纳管", color: "blue", tip: "已经对上清单，还没有登记到 NICo。它不属于任何机柜，在这里逐台确认纳管" };
  const rack = DB.rack(t.rack);
  if (!t.matched) return rack.trays.some((x) => x.matched)
    ? { key: "wait", text: "未出现", color: "amber", tip: "同机柜的其他设备已经出现，但没有读到这个序列号。检查它是否通电、BMC 是否启用 DHCP；也可能是上面某个待处理的端点" }
    : { key: "wait", text: "等待接电", color: "gray", tip: "机柜接电后自动开始" };
  if (!t.declared) return { key: "matched", text: "已匹配 · 待确认纳管", color: "blue", tip: "已经对上清单，还没有登记到 NICo。到机柜详情确认纳管" };
  if (!t.state) return { key: "held", text: "已纳管 · 等待上线", color: "blue", tip: "已经登记到 NICo，设备还没有上电。到机柜详情开始上线" };
  if (!/Ready$/.test(t.state)) return { key: "taking", text: "上线中", color: "blue", tip: t.reason || "" };
  return { key: "ok", text: "已接管", color: "green", tip: "" };
}

registerPage("discovery", {
  module: "discovery", title: "设备发现",
  render() {
    const f = { type: view("dsType", ""), rack: view("dsRack", ""), res: view("dsRes", ""), q: view("dsQ", "").toLowerCase() };
    const all = DB.trays().map((t) => ({ t, d: discoveryState(t) }));
    const list = all.filter(({ t, d }) => (!f.type || t.type === f.type) && (!f.rack || (f.rack === "none" ? !t.rack : t.rack === f.rack)) && (!f.res || d.key === f.res) && (!f.q || [t.serial, t.bmcIp, t.bmcMac, t.rack].join(" ").toLowerCase().includes(f.q)))
      .sort((a, b) => (a.d.key === "ok" ? 1 : 0) - (b.d.key === "ok" ? 1 : 0) || (a.t.rack ? 1 : 0) - (b.t.rack ? 1 : 0));
    const count = (k) => all.filter(({ d }) => d.key === k).length, open = view("dsWays", false);
    const epRows = S.endpoints.map((e) => { const p = EP_PROBLEM[e.problem];
      return `<tr><td>${code(e.ip)}<span class="cell-sub live-code">${e.mac}</span></td><td>${subnetLink(e.subnet)}<span class="cell-sub">最近 DHCP ${e.seen}</span></td><td>${e.serial ? code(e.serial) + `<span class="cell-sub">${TYPE_LABEL[e.type]} · ${esc(e.model)}</span>` : `<span class="muted">还没有读到</span>`}</td><td>${badge(p.text, "red")}</td><td>${esc(p.tip)}</td>
        <td><div class="inline-actions">${act(p.action, e.problem === "unlisted" ? "ep-replace" : "ep-retry", { extra: `data-id="${e.id}"`, compact: true })}${e.problem === "unlisted" ? button("补充清单", "noop", false, 'data-go="inventory"') : ""}${act("忽略", "ep-ignore", { extra: `data-id="${e.id}"`, compact: true })}</div></td></tr>`; });
    return heading("设备发现", "设备接电后，平台读取每台设备的身份并按序列号匹配清单。这一步只读设备。这里处理匹配不上的设备。机柜里的设备，纳管和上线在机柜详情里按机柜确认；不属于机柜的服务器在这里逐台确认纳管。", button("刷新数据", "refresh") + button("查看 DHCP 服务", "noop", false, 'data-go="network/dhcp"')) +
      `<div ${fp(1)}>${summary([["清单内设备", all.length], ["已接管", count("ok")], ["已纳管 · 等待上线", count("held") + count("taking")], ["已匹配 · 待确认纳管", count("matched")], ["未出现或等待接电", count("wait")], ["待处理的端点", S.endpoints.length]])}</div>` +
      `<h2 class="section-title">待处理的端点</h2><div ${fp(2)}>${table(["地址 / MAC", "来源子网 / 最近 DHCP", "读到的身份", "问题", "说明", "操作"], epRows, "没有待处理的端点：拿到地址的设备都已经匹配上清单。")}</div>` +
      `<section class="live-card" ${fp(3)}><div class="live-heading" style="margin-bottom:${open ? 14 : 0}px"><div><h2 style="margin:0">从接电到装好系统：每一步谁触发、设备上发生什么</h2></div><div class="live-tools">${button(open ? "收起" : "展开", "discovery-ways")}</div></div>${open ? table(["步骤", "谁触发", "发生什么", "对设备的影响"], DISCOVERY_STEPS.map((w, i) => `<tr><td><strong>${i + 1}. ${w[0]}</strong></td><td>${w[1]}</td><td>${w[2]}</td><td>${w[3]}</td></tr>`)) + `<p class="live-small">纳管、上线、装系统是三件事，各要人确认一次。这一页只管前两步，以及不属于机柜的服务器的纳管。交换机另有一处不同：它的 NVOS 管理口也会申请地址，平台从交换机的 BMC 读出这个口的 MAC，和 BMC 的 MAC 一起写进声明。</p>` : ""}</section>` +
      `<h2 class="section-title">清单内设备的进度</h2><div class="filter-bar" ${fp(4)}>${selectField("dsType", "设备类型", [["", "全部类型"], ["compute", "服务器"], ["switch", "交换机"], ["power_shelf", "供电框"]], f.type)}${selectField("dsRack", "机柜", [["", "全部"], ...S.racks.map((r) => [r.id, r.id]), ["none", "未分配机柜"]], f.rack)}${selectField("dsRes", "进度", [["", "全部"], ["wait", "未出现或等待接电"], ["matched", "已匹配 · 待确认纳管"], ["held", "已纳管 · 等待上线"], ["taking", "上线中"], ["ok", "已接管"]], f.res)}${searchField("dsQ", "搜索", view("dsQ", ""), "地址、MAC、序列号或机柜")}</div>` +
      `<div ${fp(5)}>${table(["设备", "管理地址 / MAC", "进度", "NICo 状态", "说明", "操作"], list.slice(0, 40).map(({ t, d }) =>
        `<tr><td><a class="link-button" data-live="tray-detail" data-id="${t.id}">${code(t.serial)}</a><span class="cell-sub">${typeLabel(t)} · ${t.rack ? `<a class="link-button" data-go="rack/${t.rack}">${t.rack}</a> 槽位 ${pad2(t.slot)}` : "未分配机柜"}</span></td><td>${t.bmcIp ? code(t.bmcIp) + `<span class="cell-sub live-code">${t.bmcMac}</span>` : `<span class="muted">通电后获得</span>`}</td><td>${badge(d.text, d.color)}</td><td>${t.state ? stateBadge(t.state) : "—"}</td><td>${esc(d.tip) || "—"}</td><td ${!t.rack && !t.state ? fp(6) : ""}>${t.state ? button("运行状态", "tray-detail", false, `data-id="${t.id}"`) : !t.rack ? (d.key === "matched" ? act("确认纳管", "server-admit", { primary: true, extra: `data-id="${t.id}"`, compact: true }) : act("新建安装任务", "install-new", { extra: `data-ids="${t.id}"`, compact: true })) : d.key === "matched" ? button("去确认纳管", "noop", false, `data-go="rack/${t.rack}"`) : d.key === "held" ? button("去开始上线", "noop", false, `data-go="rack/${t.rack}"`) : ""}</td></tr>`), "没有符合筛选条件的设备。")}${list.length > 40 ? `<p class="live-small">没有接管的排在前面。显示前 40 台，共 ${list.length} 台。</p>` : ""}</div>`;
  },
  spec: {
    purpose: "接入的工作台。清单里没有 MAC，所以设备接电后由平台读出每台设备的序列号去匹配清单。匹配是自动的、只读的；人在这里处理匹配不上的端点。纳管、上线和装系统各自另有人工入口：机柜里的设备在机柜详情按机柜纳管和上线；不属于机柜的服务器在这一页逐台纳管。",
    entry: "接入 → 设备发现；机柜详情“清单核对”里的入口", design: "5 整体操作运维流程（接入）；6.2 清单；6.3 机柜与设备", existing: "设备管理 → 发现设备（DHCP 观察到的端点、读取身份、确认纳管）与 发现诊断（探测结果、失败原因）合并。现有产品逐台人工确认，这里改成按清单自动匹配",
    points: [
      { n: 1, name: "统计条", kind: "调整", desc: "清单内设备、已接管、已纳管等待上线、已匹配待确认纳管、未出现或等待接电、待处理的端点。" },
      { n: 2, name: "待处理的端点", kind: "调整", desc: "拿到了地址、但没能匹配上清单的端点：认证失败、清单里没有这个序列号、读不到序列号。每行给出原因和处理入口。沿用发现设备页的地址、MAC、来源子网和读到的身份。" },
      { n: 3, name: "全过程说明", kind: "新增", desc: "从机柜接电到装好系统的五步：机柜接电、读取身份与匹配、确认纳管、开始上线、装系统。每一步写明谁触发、发生什么、对设备有什么影响。默认折叠。" },
      { n: 4, name: "筛选", kind: "调整", desc: "设备类型、机柜、进度和搜索。" },
      { n: 5, name: "清单内设备的进度", kind: "调整", desc: "清单里每一行走到了哪一步。匹配之前不知道哪个地址属于它，所以只显示“等待接电”或“未出现”；匹配之后显示地址和 MAC；上线之后显示 NICo 的状态原文。" },
      { n: 6, name: "不属于机柜的服务器", kind: "新增", desc: "这类服务器没有机柜页可去，所以在这一行上直接“确认纳管”：逐台登记到 NICo。纳管后显示“已纳管 · 首次安装时接管”，行上给出“新建安装任务”。" },
    ],
    fields: [["读到的身份", "平台读取设备的 BMC", "设备类型、序列号、型号"], ["问题", "平台", "认证失败、清单里没有这个序列号、读不到序列号"], ["进度", "清单 + NICo", "等待接电、未出现、已匹配 · 待确认纳管、已纳管 · 等待上线、上线中、已接管。不属于机柜的服务器没有上线，纳管后显示“已纳管 · 首次安装时接管”"], ["NICo 状态", "NICo Core", "设备对象的状态原文"]],
    rules: ["读取身份和匹配只读设备，不写 NICo，也不改设备。", "纳管、上线、装系统是三件事：纳管只登记并换 BMC 口令；上线才上电和接管；装系统在“安装任务”里。每一件都要人确认。", "纳管是逐台设备的登记。机柜里的设备在机柜详情按机柜批量确认；不属于机柜的服务器在这一页逐台确认。", "不属于机柜的服务器没有上线这一步：纳管时声明带暂停标记，NICo 不给它上电；第一次装系统时才放行，由 NICo 上电接管。", "匹配只按序列号，不按地址或位置猜测。", "读取身份只用这台设备在清单里对应的凭据或批次默认凭据，失败后不再尝试其他口令，交给人指定。", "清单里没有的设备不会写进 NICo。", "“替换清单中的一行”会产生新的清单版本，并写入审计。", "忽略的端点不再显示；它再次申请地址时会重新出现。"],
    dialogs: [
      { name: "确认纳管（不属于机柜的服务器）", desc: "对一台服务器确认纳管。显示会做什么、不会做什么，与机柜详情里的确认纳管相同，只是对象是一台设备。", fields: [["原因", "是", "写入审计"]] },
      { name: "指定凭据重试", desc: "给一个端点单独指定凭据，再读一次身份。读到序列号后按正常流程匹配。", fields: [["用户名", "是", ""], ["口令", "是", "只用于这一次读取和随后的声明"], ["原因", "是", ""]] },
      { name: "替换清单中的一行", desc: "把清单里某一行的序列号改成读到的序列号，机柜和槽位不变。用于出厂替换件。", fields: [["替换哪一行", "是", "只列出同类型、还没有出现的行"], ["原因", "是", ""]] },
    ],
  },
});
registerAction("discovery-ways", () => { S.view.dsWays = !view("dsWays", false); render(); });
/* 不属于机柜的服务器：逐台确认纳管。声明带暂停标记，NICo 不给它上电；第一次装系统时才放行。 */
registerAction("server-admit", ({ id }) => {
  const t = DB.tray(id);
  confirmOperation({ title: "确认纳管", target: `${t.serial}（服务器，未分配机柜）`, action: "把这台服务器登记到 NICo", stages: ["写入设备声明", "NICo 登录 BMC 并更换口令"], why: "到货核对完成", submit: "确认纳管", sub: "纳管只是登记：不上电、不动磁盘、不装系统。",
    extra: doList(["把这台服务器的声明写进 NICo：MAC、凭据、序列号。声明里不带机柜", "NICo 登录它的 BMC，把口令换成站点凭据", "声明带暂停标记：NICo 不给它上电，也不接管"], ADMIT_NOT) + note("<b>这台服务器不属于任何机柜，所以没有“上线”这一步。</b>第一次给它装系统时，NICo 才上电并接管它：设置 BIOS 和启动顺序，从网络启动发现程序读硬件；按站点策略可能清理全部磁盘。", "warning"),
    run: (why) => { t.declared = true; addAudit(t.serial, "确认纳管", why, "—", "已纳管，设备未上电"); toast(`${t.serial} 已纳管。第一次装系统时由 NICo 上电接管`); } });
});
const epGet = (id) => S.endpoints.find((e) => e.id === id);
const epDefs = (e) => defs([["端点", code(e.ip) + " · " + code(e.mac)], ["读到的身份", e.serial ? `${TYPE_LABEL[e.type]} · ${code(e.serial)} · ${esc(e.model)}` : "还没有读到"]]);
registerAction("ep-retry", ({ id }) => { const e = epGet(id);
  modal("指定凭据重试", "只对这一个端点使用，不影响清单里的其他设备", epDefs(e) + `<div class="live-form" style="margin-top:16px">${field("用户名", `<input class="input" id="ep-user" value="admin">`)}${field("口令", `<input class="input" type="password" id="ep-pass">`)}${field("原因", `<input class="input" id="ep-why" value="这台设备的出厂口令与批次默认值不同">`)}</div>`,
    button("取消", "close") + button("读取身份", "ep-retry-run", true, `data-id="${id}"`), { wide: false }); });
registerAction("ep-retry-run", ({ id }) => {
  const e = epGet(id), why = $("#ep-why").value.trim(); if (!$("#ep-user").value.trim() || !$("#ep-pass").value || !why) return toast("用户名、口令和原因都要填写");
  const t = e.sim && DB.tray(e.sim); closeModal(); /* 设计稿里用预设的结果代替真实的身份读取 */
  if (!t) return toast("读到了身份，但清单里没有这个序列号");
  matchEndpoint(id, t.id); const wrote = DB.rack(t.rack).admit ? "已纳管" : "机柜确认纳管后登记到 NICo";
  addAudit(`${t.rack} / 槽位 ${pad2(t.slot)}`, "指定凭据重试", why, "—", `读到序列号 ${t.serial}，已匹配；${wrote}`);
  toast(`读到 ${t.serial}：已匹配 ${t.rack} 槽位 ${pad2(t.slot)}，${wrote}`); render();
});
registerAction("ep-replace", ({ id }) => { const e = epGet(id), rows = S.racks.flatMap((r) => DB.absent(r)).filter((t) => t.type === e.type);
  modal("替换清单中的一行", "把清单里一行的序列号改成读到的序列号", epDefs(e) + (rows.length ? `<div class="live-form" style="margin-top:16px">${field("替换哪一行", `<select class="input" id="ep-row">${rows.map((t) => `<option value="${t.id}" ${t.id === e.sim ? "selected" : ""}>${t.rack} 槽位 ${pad2(t.slot)} · 清单序列号 ${t.serial}</option>`).join("")}</select>`, "只列出同类型、还没有出现的行；机柜和槽位不变")}${field("原因", `<input class="input" id="ep-why" value="出厂替换件，与出货单核对一致">`)}</div>` : note("清单里没有同类型、还没有出现的行。先在设备清单里补充这台设备。", "warning")),
    button("取消", "close") + (rows.length ? button("替换清单中的这一行", "ep-replace-run", true, `data-id="${id}"`) : ""), { wide: false }); });
registerAction("ep-replace-run", ({ id }) => {
  const e = epGet(id), t = DB.tray($("#ep-row").value), why = $("#ep-why").value.trim(); if (!why) return toast("请填写原因");
  const old = t.serial; closeModal(); matchEndpoint(id, t.id, { serial: e.serial });
  S.inventory.unshift({ v: S.inventory[0].v + 1, at: nowText(), by: "ops-01", file: "（更换设备）", note: `${t.rack} 槽位 ${pad2(t.slot)} 序列号 ${old} 改为 ${e.serial}`, why });
  const wrote = DB.rack(t.rack).admit ? "已纳管" : "机柜确认纳管后登记到 NICo";
  addAudit(`${t.rack} / 槽位 ${pad2(t.slot)}`, "替换清单中的一行", why, "—", "清单已更新，" + wrote); toast("清单已更新，" + wrote); render();
});
registerAction("ep-ignore", ({ id }) => { const e = epGet(id); S.endpoints = S.endpoints.filter((x) => x.id !== id); addAudit("端点 " + e.ip, "忽略端点", "不属于本站点清单", "—", "不再显示"); toast("已忽略；它再次申请地址时会重新出现"); render(); });
