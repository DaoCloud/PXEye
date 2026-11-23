"use strict";
/* 设备发现：设备通电后，NICo 经 DHCP 看到它、探测它、与设备清单比对并接管。
   这一页跨机柜回答“清单里的设备发现到哪一步了、卡在哪、还有哪些清单外的设备”。
   合并现有的“发现设备”和“发现诊断”。机柜详情里的“对账”是同一批数据按机柜的视图。 */

/* 各类设备的发现方式：入口网络、身份依据和完成判据不同。 */
const DISCOVERY_WAYS = [
  ["计算托盘", "BMC 在带外管理网段发 DHCP 请求", "探测 BMC，读取序列号；随后主机从主机管理网段引导，上报硬件", "机器对象状态为 Ready"],
  ["交换机", "BMC 在带外管理网段、NVOS 管理口在交换机系统管理网段各发一次 DHCP 请求", "探测 BMC，读取序列号；关联 NVOS 管理口，配置证书并轮换口令", "交换机对象状态为 Ready"],
  ["供电框", "PMC 在带外管理网段发 DHCP 请求", "探测 PMC，读取序列号", "供电框对象状态为 Ready"],
  ["DPU", "不单独发现", "随所属计算托盘一起识别", "所属计算托盘就绪"],
];
/* 把一台设备映射到发现阶段。阶段只描述读到的事实，不推测原因。 */
function discoveryState(t) {
  const rack = DB.rack(t.rack);
  if (!t.state) return { stage: rack.state === "Created" ? "等待通电" : "未收到 DHCP 请求", result: "none", text: rack.state === "Created" ? "未报告" : "未发现", tip: rack.state === "Created" ? "机柜通电后自动开始" : "检查该设备是否通电、BMC 是否启用 DHCP、所在网段的中继是否到达（见 DHCP 服务）", bad: rack.state !== "Created" };
  if (/探测失败/.test(t.state)) return { stage: "已获取地址", result: "fail", text: "探测失败", code: "NICO-SITEEXPLORER-101", tip: "连接被拒绝：检查带外网络是否可达、出厂凭据是否正确", bad: true };
  if (/不符/.test(t.state)) return { stage: "已探测", result: "fail", text: "序列号不符", tip: "实测序列号与设备清单不一致：在机柜对账里更换设备或更正清单", bad: true };
  return { stage: "已接管", result: "ok", text: "成功", tip: "", bad: false };
}

registerPage("discovery", {
  module: "discovery", title: "设备发现",
  render() {
    const f = { type: view("dsType", ""), rack: view("dsRack", ""), res: view("dsRes", ""), q: view("dsQ", "").toLowerCase() };
    const all = DB.trays().map((t) => ({ t, d: discoveryState(t) }));
    const list = all.filter(({ t, d }) => (!f.type || t.type === f.type) && (!f.rack || t.rack === f.rack) && (!f.q || [t.serial, t.bmcIp, t.bmcMac, t.rack].join(" ").toLowerCase().includes(f.q)) &&
      (!f.res || (f.res === "ok" && d.result === "ok") || (f.res === "fail" && d.result === "fail") || (f.res === "none" && d.result === "none")))
      .sort((a, b) => (b.d.bad ? 1 : 0) - (a.d.bad ? 1 : 0));
    const showUnexpected = !f.type && !f.rack && (!f.res || f.res === "extra") && S.unexpected.filter((u) => !f.q || [u.mac, u.ip, u.info].join(" ").toLowerCase().includes(f.q));
    const rows = (f.res === "extra" ? [] : list.slice(0, 40)).map(({ t, d }) =>
      `<tr><td>${t.state ? code(t.bmcIp) : "—"}<span class="cell-sub live-code">${t.bmcMac}</span></td><td>${subnetLink("net-oob")}<span class="cell-sub">${t.lastSeen ? "最近 DHCP " + t.lastSeen : "未收到请求"}</span></td>
       <td><a class="link-button" data-live="tray-detail" data-id="${t.id}">${code(t.serial)}</a><span class="cell-sub">${TYPE_LABEL[t.type]} · <a class="link-button" data-go="rack/${t.rack}">${t.rack}</a> 槽位 ${pad2(t.slot)}</span></td>
       <td>${badge(d.stage, d.stage === "已接管" ? "green" : d.stage === "等待通电" ? "gray" : "amber")}</td><td>${d.result === "ok" ? badge("成功", "green") : d.result === "fail" ? badge(d.code || d.text, "red") + `<span class="cell-sub">${d.text}</span>` : badge(d.text, "gray")}</td><td>${esc(d.tip) || "—"}</td>
       <td><div class="inline-actions">${d.bad ? button("去对账", "discovery-recon", false, `data-rack="${t.rack}"`) : t.state ? button("运行状态", "tray-detail", false, `data-id="${t.id}"`) : ""}</div></td></tr>`)
      .concat((showUnexpected || []).map((u) => `<tr><td>${code(u.ip)}<span class="cell-sub live-code">${u.mac}</span></td><td>${subnetLink(u.subnet)}<span class="cell-sub">最近 DHCP ${u.seen}</span></td><td>${badge("清单外设备", "amber")}<span class="cell-sub">${esc(u.info)}</span></td><td>${badge("已探测", "amber")}</td><td>${badge("未接管", "gray")}</td><td>不在设备清单中：核对到货清单后导入，或确认是否接错了网络</td><td><div class="inline-actions">${button("前往设备清单", "noop", false, 'data-go="inventory"')}</div></td></tr>`));
    const count = (fn) => all.filter(fn).length;
    return heading("设备发现", "设备通电后，NICo 经 DHCP 发现它、探测它，并与设备清单比对后接管。这里查看每台设备走到了哪一步、卡在哪。", button("刷新数据", "refresh") + button("查看 DHCP 服务", "noop", false, 'data-go="network/dhcp"')) +
      `<div ${fp(1)}>${summary([["清单内设备", all.length], ["已接管", count(({ d }) => d.result === "ok")], ["未发现", count(({ d }) => d.result === "none")], ["探测失败或不符", count(({ d }) => d.result === "fail")], ["清单外设备", S.unexpected.length]])}</div>` +
      `<section class="live-card" ${fp(2)}><div class="live-heading" style="margin-bottom:${view("dsWays", false) ? 14 : 0}px"><div><h2 style="margin:0">各类设备的发现方式</h2></div><div class="live-tools">${button(view("dsWays", false) ? "收起" : "展开", "discovery-ways")}</div></div>${view("dsWays", false) ? table(["设备类型", "发现入口", "身份与接管", "完成判据"], DISCOVERY_WAYS.map((w) => `<tr><td><strong>${w[0]}</strong></td><td>${w[1]}</td><td>${w[2]}</td><td>${w[3]}</td></tr>`)) + `<p class="live-small">发现不需要人工确认：只要设备在设备清单里、网段已规划、DHCP 请求能到达，NICo 就会自动完成。</p>` : ""}</section>` +
      `<div class="filter-bar" ${fp(3)}>${selectField("dsType", "设备类型", [["", "全部类型"], ["compute", "计算托盘"], ["switch", "交换机"], ["power_shelf", "供电框"]], f.type)}${selectField("dsRack", "机柜", [["", "全部机柜"], ...S.racks.map((r) => [r.id, r.id])], f.rack)}${selectField("dsRes", "结果", [["", "全部"], ["ok", "已接管"], ["none", "未发现"], ["fail", "探测失败或不符"], ["extra", "清单外设备"]], f.res)}${searchField("dsQ", "搜索", view("dsQ", ""), "地址、MAC、序列号或机柜")}</div>` +
      `<div ${fp(4)}>${table(["管理地址 / MAC", "来源子网 / 最近 DHCP", "设备", "发现阶段", "探测结果", "处理建议", "操作"], rows, "没有符合筛选条件的设备。")}${list.length > 40 && f.res !== "extra" ? `<p class="live-small">有问题的设备排在前面。显示前 40 台，共 ${list.length} 台。</p>` : ""}</div>` +
      `<div ${fp(5)}>${note("发现阶段依次是：等待通电 → 未收到 DHCP 请求 → 已获取地址 → 已探测 → 已接管。卡在“未收到 DHCP 请求”先看 DHCP 服务，卡在“已获取地址”或“已探测”去机柜对账处理。")}</div>`;
  },
  spec: {
    purpose: "跨机柜查看设备发现的进度和失败原因。它回答“为什么这台设备没有出现”，并把人带到 DHCP 服务或机柜对账去处理。",
    entry: "接入 → 设备发现；机柜详情的对账是同一批数据按机柜的视图", design: "5 整体操作运维流程（接入与对账）；6.3 机柜与设备；6.7 网络", existing: "设备管理 → 发现设备（DHCP 观察到的端点、来源子网）与 发现诊断（探测结果、错误码、处理建议）合并。整机柜不再逐台“确认纳管”",
    points: [
      { n: 1, name: "统计条", kind: "调整", desc: "清单内设备、已接管、未发现、探测失败或不符、清单外设备。沿用发现诊断的“探测成功 / 探测失败”，增加与清单的比对。" },
      { n: 2, name: "各类设备的发现方式", kind: "新增", desc: "计算托盘、交换机、供电框、DPU 各自从哪个网段进入、依据什么确认身份、什么算完成。默认折叠。" },
      { n: 3, name: "筛选", kind: "调整", desc: "设备类型、机柜、结果和搜索。现有的“发现子网”筛选改为表里的“来源子网”列。" },
      { n: 4, name: "发现列表", kind: "调整", desc: "管理地址 / MAC、来源子网 / 最近 DHCP 沿用发现设备页；发现阶段、探测结果、处理建议沿用发现诊断页。有问题的排在前面。" },
      { n: 5, name: "阶段说明", kind: "新增", desc: "五个发现阶段的顺序，以及卡在每一步时去哪里处理。" },
    ],
    fields: [["发现阶段", "NICo DHCP 与站点发现", "等待通电、未收到 DHCP 请求、已获取地址、已探测、已接管"], ["探测结果", "NICo 站点发现", "成功，或错误码与原因"], ["清单外设备", "NICo DHCP 对比设备清单", "DHCP 看到了、但设备清单里没有的端点"]],
    rules: ["页面只读。发现由 NICo 自动完成，不需要逐台确认。", "清单外设备不会被接管；要接管就先把它加入设备清单。", "处理入口只有两个：DHCP 服务（请求没到）和机柜对账（探测失败、身份不符）。"],
  },
});
registerAction("discovery-recon", ({ rack }) => { S.view["rackTab:" + rack] = "recon"; go("rack/" + rack); });
registerAction("discovery-ways", () => { S.view.dsWays = !view("dsWays", false); render(); });
