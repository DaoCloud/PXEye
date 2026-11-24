"use strict";
/* 设备发现：到货清单里没有 MAC，所以发现分两段。
   前一段是平台做的：设备通电拿到地址后，用清单里的凭据读它的身份，按序列号匹配清单里的一行，把声明写进 NICo。
   后一段是 NICo 做的：按声明探测、接管，设备对象走到 Ready。
   这一页是工作台：匹配上的不用管，人只处理匹配不上的端点。合并现有的“发现设备”和“发现诊断”。 */

const DISCOVERY_STEPS = [
  ["获取地址", "NICo DHCP", "带外管理网段出现一个还没有归属的地址", "一直没有地址：看“DHCP 服务”里这个网段有没有收到请求"],
  ["读取身份", "平台，用清单里的凭据直接读设备的 BMC", "读到设备类型、序列号和型号，并核对管理口的 MAC", "认证失败：在本页给这个端点指定凭据后重试"],
  ["匹配清单", "平台，按序列号", "找到清单里序列号相同的一行，得到机柜和槽位", "清单里没有这个序列号：替换清单中的一行，或补充清单"],
  ["写入声明", "平台写入 NICo", "NICo 里有这台设备的声明：MAC、凭据、机柜和槽位", "—"],
  ["探测与接管", "NICo", "设备对象的状态为 Ready", "看设备的运行状态和失败原因"],
];
const EP_PROBLEM = {
  auth: { text: "认证失败", tip: "清单里的凭据登录不了这台设备。平台不会逐组尝试口令，以免触发 BMC 的登录锁定", action: "指定凭据重试" },
  unlisted: { text: "清单里没有这个序列号", tip: "可能是出厂替换件，也可能是接错网络的设备", action: "替换清单中的一行" },
  unreadable: { text: "读不到序列号", tip: "设备的 BMC 没有返回序列号", action: "指定凭据重试" },
};
/* 清单里一行的进度。匹配之前不知道哪个地址是它，所以只有“等待”这一种状态。 */
function discoveryState(t) {
  const rack = DB.rack(t.rack);
  if (!t.declared) return rack.trays.some((x) => x.declared)
    ? { key: "wait", text: "未出现", color: "amber", tip: "同机柜的其他设备已经出现，但没有读到这个序列号。检查它是否通电、BMC 是否启用 DHCP；也可能是下面某个待处理的端点" }
    : { key: "wait", text: "等待通电", color: "gray", tip: "机柜通电后自动开始" };
  if (!/Ready$/.test(t.state)) return { key: "taking", text: "NICo 接管中", color: "blue", tip: t.reason || "" };
  return { key: "ok", text: "已接管", color: "green", tip: "" };
}

registerPage("discovery", {
  module: "discovery", title: "设备发现",
  render() {
    const f = { type: view("dsType", ""), rack: view("dsRack", ""), res: view("dsRes", ""), q: view("dsQ", "").toLowerCase() };
    const all = DB.trays().map((t) => ({ t, d: discoveryState(t) }));
    const list = all.filter(({ t, d }) => (!f.type || t.type === f.type) && (!f.rack || t.rack === f.rack) && (!f.res || d.key === f.res) && (!f.q || [t.serial, t.bmcIp, t.bmcMac, t.rack].join(" ").toLowerCase().includes(f.q)))
      .sort((a, b) => (a.d.key === "ok" ? 1 : 0) - (b.d.key === "ok" ? 1 : 0));
    const count = (k) => all.filter(({ d }) => d.key === k).length, open = view("dsWays", false);
    const epRows = S.endpoints.map((e) => { const p = EP_PROBLEM[e.problem];
      return `<tr><td>${code(e.ip)}<span class="cell-sub live-code">${e.mac}</span></td><td>${subnetLink(e.subnet)}<span class="cell-sub">最近 DHCP ${e.seen}</span></td><td>${e.serial ? code(e.serial) + `<span class="cell-sub">${TYPE_LABEL[e.type]} · ${esc(e.model)}</span>` : `<span class="muted">还没有读到</span>`}</td><td>${badge(p.text, "red")}</td><td>${esc(p.tip)}</td>
        <td><div class="inline-actions">${act(p.action, e.problem === "unlisted" ? "ep-replace" : "ep-retry", { extra: `data-id="${e.id}"`, compact: true })}${e.problem === "unlisted" ? button("补充清单", "noop", false, 'data-go="inventory"') : ""}${act("忽略", "ep-ignore", { extra: `data-id="${e.id}"`, compact: true })}</div></td></tr>`; });
    return heading("设备发现", "设备通电拿到地址后，平台读取它的身份、按序列号匹配清单并把声明写进 NICo，之后由 NICo 探测和接管。这里处理匹配不上的设备。", button("刷新数据", "refresh") + button("查看 DHCP 服务", "noop", false, 'data-go="network/dhcp"')) +
      `<div ${fp(1)}>${summary([["清单内设备", all.length], ["已接管", count("ok")], ["NICo 接管中", count("taking")], ["未出现或等待通电", count("wait")], ["待处理的端点", S.endpoints.length]])}</div>` +
      `<h2 class="section-title">待处理的端点</h2><div ${fp(2)}>${table(["地址 / MAC", "来源子网 / 最近 DHCP", "读到的身份", "问题", "说明", "操作"], epRows, "没有待处理的端点：拿到地址的设备都已经匹配上清单。")}</div>` +
      `<section class="live-card" ${fp(3)}><div class="live-heading" style="margin-bottom:${open ? 14 : 0}px"><div><h2 style="margin:0">发现分几步，各由谁完成</h2></div><div class="live-tools">${button(open ? "收起" : "展开", "discovery-ways")}</div></div>${open ? table(["步骤", "由谁完成", "完成的标志", "卡住时"], DISCOVERY_STEPS.map((w, i) => `<tr><td><strong>${i + 1}. ${w[0]}</strong></td><td>${w[1]}</td><td>${w[2]}</td><td>${w[3]}</td></tr>`)) + `<p class="live-small">交换机另有一步：它的 NVOS 管理口也会申请地址。平台从交换机的 BMC 读出 NVOS 管理口的 MAC，和 BMC 的 MAC 一起写进声明。</p>` : ""}</section>` +
      `<h2 class="section-title">清单内设备的进度</h2><div class="filter-bar" ${fp(4)}>${selectField("dsType", "设备类型", [["", "全部类型"], ["compute", "计算托盘"], ["switch", "交换机"], ["power_shelf", "供电框"]], f.type)}${selectField("dsRack", "机柜", [["", "全部机柜"], ...S.racks.map((r) => [r.id, r.id])], f.rack)}${selectField("dsRes", "进度", [["", "全部"], ["wait", "未出现或等待通电"], ["taking", "NICo 接管中"], ["ok", "已接管"]], f.res)}${searchField("dsQ", "搜索", view("dsQ", ""), "地址、MAC、序列号或机柜")}</div>` +
      `<div ${fp(5)}>${table(["设备", "管理地址 / MAC", "进度", "NICo 状态", "说明", "操作"], list.slice(0, 40).map(({ t, d }) =>
        `<tr><td><a class="link-button" data-live="tray-detail" data-id="${t.id}">${code(t.serial)}</a><span class="cell-sub">${TYPE_LABEL[t.type]} · <a class="link-button" data-go="rack/${t.rack}">${t.rack}</a> 槽位 ${pad2(t.slot)}</span></td><td>${t.bmcIp ? code(t.bmcIp) + `<span class="cell-sub live-code">${t.bmcMac}</span>` : `<span class="muted">通电后获得</span>`}</td><td>${badge(d.text, d.color)}</td><td>${t.state ? stateBadge(t.state) : "—"}</td><td>${esc(d.tip) || "—"}</td><td>${t.state ? button("运行状态", "tray-detail", false, `data-id="${t.id}"`) : ""}</td></tr>`), "没有符合筛选条件的设备。")}${list.length > 40 ? `<p class="live-small">没有接管的排在前面。显示前 40 台，共 ${list.length} 台。</p>` : ""}</div>`;
  },
  spec: {
    purpose: "接入的工作台。清单里没有 MAC，所以由平台读出每台通电设备的序列号去匹配清单；匹配上的自动写进 NICo，人只处理匹配不上的。",
    entry: "接入 → 设备发现；机柜详情“清单核对”里的入口", design: "5 整体操作运维流程（接入）；6.2 清单；6.3 机柜与设备", existing: "设备管理 → 发现设备（DHCP 观察到的端点、读取身份、确认纳管）与 发现诊断（探测结果、失败原因）合并。现有产品逐台人工确认，这里改成按清单自动匹配",
    points: [
      { n: 1, name: "统计条", kind: "调整", desc: "清单内设备、已接管、NICo 接管中、未出现或等待通电、待处理的端点。" },
      { n: 2, name: "待处理的端点", kind: "调整", desc: "拿到了地址、但没能匹配上清单的端点：认证失败、清单里没有这个序列号、读不到序列号。每行给出原因和处理入口。沿用发现设备页的地址、MAC、来源子网和读到的身份。" },
      { n: 3, name: "发现的步骤", kind: "新增", desc: "获取地址、读取身份、匹配清单、写入声明、探测与接管五步，各由谁完成、什么算完成、卡住时去哪。默认折叠。" },
      { n: 4, name: "筛选", kind: "调整", desc: "设备类型、机柜、进度和搜索。" },
      { n: 5, name: "清单内设备的进度", kind: "调整", desc: "清单里每一行走到了哪一步。匹配之前不知道哪个地址属于它，所以只显示“等待通电”或“未出现”；匹配之后显示地址、MAC 和 NICo 的状态原文。" },
    ],
    fields: [["读到的身份", "平台读取设备的 BMC", "设备类型、序列号、型号"], ["问题", "平台", "认证失败、清单里没有这个序列号、读不到序列号"], ["进度", "清单 + NICo", "等待通电、未出现、NICo 接管中、已接管"], ["NICo 状态", "NICo Core", "设备对象的状态原文"]],
    rules: ["匹配只按序列号，不按地址或位置猜测。", "读取身份只用这台设备在清单里对应的凭据或批次默认凭据，失败后不再尝试其他口令，交给人指定。", "清单里没有的设备不会写进 NICo。", "“替换清单中的一行”会产生新的清单版本，并写入审计。", "忽略的端点不再显示；它再次申请地址时会重新出现。"],
    dialogs: [
      { name: "指定凭据重试", desc: "给一个端点单独指定凭据，再读一次身份。读到序列号后按正常流程匹配。", fields: [["用户名", "是", ""], ["口令", "是", "只用于这一次读取和随后的声明"], ["原因", "是", ""]] },
      { name: "替换清单中的一行", desc: "把清单里某一行的序列号改成读到的序列号，机柜和槽位不变。用于出厂替换件。", fields: [["替换哪一行", "是", "只列出同类型、还没有出现的行"], ["原因", "是", ""]] },
    ],
  },
});
registerAction("discovery-ways", () => { S.view.dsWays = !view("dsWays", false); render(); });
const epGet = (id) => S.endpoints.find((e) => e.id === id);
const epDefs = (e) => defs([["端点", code(e.ip) + " · " + code(e.mac)], ["读到的身份", e.serial ? `${TYPE_LABEL[e.type]} · ${code(e.serial)} · ${esc(e.model)}` : "还没有读到"]]);
registerAction("ep-retry", ({ id }) => { const e = epGet(id);
  modal("指定凭据重试", "只对这一个端点使用，不影响清单里的其他设备", epDefs(e) + `<div class="live-form" style="margin-top:16px">${field("用户名", `<input class="input" id="ep-user" value="admin">`)}${field("口令", `<input class="input" type="password" id="ep-pass">`)}${field("原因", `<input class="input" id="ep-why" value="这台设备的出厂口令与批次默认值不同">`)}</div>`,
    button("取消", "close") + button("读取身份", "ep-retry-run", true, `data-id="${id}"`), { wide: false }); });
registerAction("ep-retry-run", ({ id }) => {
  const e = epGet(id), why = $("#ep-why").value.trim(); if (!$("#ep-user").value.trim() || !$("#ep-pass").value || !why) return toast("用户名、口令和原因都要填写");
  const t = e.sim && DB.tray(e.sim); closeModal(); /* 设计稿里用预设的结果代替真实的身份读取 */
  if (!t) return toast("读到了身份，但清单里没有这个序列号");
  matchEndpoint(id, t.id); addAudit(`${t.rack} / 槽位 ${pad2(t.slot)}`, "指定凭据重试", why, "—", `读到序列号 ${t.serial}，已匹配并写入 NICo`);
  toast(`读到 ${t.serial}：已匹配 ${t.rack} 槽位 ${pad2(t.slot)}，声明已写入 NICo`); render();
});
registerAction("ep-replace", ({ id }) => { const e = epGet(id), rows = S.racks.flatMap((r) => DB.absent(r)).filter((t) => t.type === e.type);
  modal("替换清单中的一行", "把清单里一行的序列号改成读到的序列号", epDefs(e) + (rows.length ? `<div class="live-form" style="margin-top:16px">${field("替换哪一行", `<select class="input" id="ep-row">${rows.map((t) => `<option value="${t.id}" ${t.id === e.sim ? "selected" : ""}>${t.rack} 槽位 ${pad2(t.slot)} · 清单序列号 ${t.serial}</option>`).join("")}</select>`, "只列出同类型、还没有出现的行；机柜和槽位不变")}${field("原因", `<input class="input" id="ep-why" value="出厂替换件，与出货单核对一致">`)}</div>` : note("清单里没有同类型、还没有出现的行。先在设备清单里补充这台设备。", "warning")),
    button("取消", "close") + (rows.length ? button("替换并写入 NICo", "ep-replace-run", true, `data-id="${id}"`) : ""), { wide: false }); });
registerAction("ep-replace-run", ({ id }) => {
  const e = epGet(id), t = DB.tray($("#ep-row").value), why = $("#ep-why").value.trim(); if (!why) return toast("请填写原因");
  const old = t.serial; closeModal(); matchEndpoint(id, t.id, { serial: e.serial });
  S.inventory.unshift({ v: S.inventory[0].v + 1, at: nowText(), by: "ops-01", file: "（更换设备）", note: `${t.rack} 槽位 ${pad2(t.slot)} 序列号 ${old} 改为 ${e.serial}`, why });
  addAudit(`${t.rack} / 槽位 ${pad2(t.slot)}`, "替换清单中的一行", why, "—", "清单已更新，声明已写入 NICo"); toast("清单已更新，声明已写入 NICo"); render();
});
registerAction("ep-ignore", ({ id }) => { const e = epGet(id); S.endpoints = S.endpoints.filter((x) => x.id !== id); addAudit("端点 " + e.ip, "忽略端点", "不属于本站点清单", "—", "不再显示"); toast("已忽略；它再次申请地址时会重新出现"); render(); });
