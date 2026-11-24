"use strict";
/* 网络规划：导入设备清单之前，先规划各类设备接口使用的网段和 DHCP 地址池。
   合并现有的“网络管理”和站点设置里的“管理引导网络”，并补上规划检查、按子网的 DHCP 状态和地址分配。
   三个页签：子网、DHCP 服务、地址分配。 */

const roleOf = (id) => NET_ROLES.find((r) => r.id === id);
const subnetLink = (id) => { const n = DB.subnet(id); return n ? `<a class="link-button" data-live="net-view" data-id="${n.id}">${esc(n.name)}</a>` : "—"; };
const usageCell = (n) => { const used = DB.subnetUsed(n.id); return `${used}<small class="muted"> / ${n.capacity}</small><div class="progress-meter"><i style="width:${Math.min(100, (used / n.capacity) * 100)}%"></i></div>`; };

registerPage("network", {
  module: "network", tab: "子网", title: "网络规划",
  render() {
    const checks = DB.planChecks(), ok = checks.every((c) => c.ok);
    return heading("网络规划", "在导入设备清单前，规划各类设备接口使用的网段和 DHCP 地址池。设备通电后按这里的规划获得地址。", button("刷新数据", "refresh") + act("新增子网", "net-new", { primary: true, admin: true })) +
      `<section class="live-card" ${fp(1)}><h2>规划检查　${ok ? badge("全部通过", "green") : badge("未完成", "red")}</h2>${table(["用途", "适用的设备接口", "子网", "每个机柜需要", "需要 / 可分配地址", "结果"], checks.map((c) =>
        `<tr><td><strong>${c.role.label}</strong><span class="cell-sub live-code">${c.role.kind}</span></td><td>${c.role.devices}</td><td>${c.nets.map((n) => subnetLink(n.id)).join("　") || "—"}</td><td>${c.role.perRack}<span class="cell-sub">${c.role.formula}</span></td><td>${c.need}<small class="muted"> / ${c.capacity}</small></td><td>${c.ok ? badge("通过", "green") : badge(c.reason, "red")}</td></tr>`))}
        <p class="live-small">“需要”按清单里的机柜数乘以每个机柜的接口数计算，不按设备台数。规划检查通过后才能导入设备清单；导入新机柜时会把新机柜算进去。</p></section>` +
      `<div ${fp(2)}>${summary([["子网", S.subnets.length], ["可分配地址", S.subnets.reduce((n, x) => n + x.capacity, 0)], ["已分配", S.subnets.reduce((n, x) => n + DB.subnetUsed(x.id), 0)], ["缺少子域的子网", S.subnets.filter((n) => !n.subdomain).length]])}</div>` +
      `<div ${fp(3)}>${table(["子网名称 / 类型", "用途", "前缀 / 网关", "子域", "DHCP 范围", "已分配 / 可分配", "MTU / 保留地址", "NICo 状态", "操作"], S.subnets.map((n) =>
        `<tr><td><a class="link-button" data-live="net-view" data-id="${n.id}"><strong>${esc(n.name)}</strong></a><span class="cell-sub">${n.kind}${n.vlan ? " · 备注：交换机侧 VLAN " + esc(n.vlan) : ""}</span></td><td>${roleOf(n.role).label}</td><td>${code(n.cidr)}<span class="cell-sub live-code">${n.gateway}</span></td><td>${n.subdomain ? code(n.subdomain) : badge("未设置", "red")}</td><td><span class="live-code">${n.pool[0]} – ${n.pool[1]}</span></td><td>${usageCell(n)}</td><td>${n.mtu} / ${n.reserved}</td><td>${badge(n.state, n.state === "READY" ? "green" : "gray")}</td>
         <td><div class="inline-actions" ${fp(4)}>${button("查看", "net-view", false, `data-id="${n.id}"`)}${act("配置 DHCP 地址池", "net-pool", { admin: true, extra: `data-id="${n.id}"` })}${act("删除", "net-delete", { admin: true, gate: DB.subnetUsed(n.id) ? `有 ${DB.subnetUsed(n.id)} 个接口在使用` : "", extra: `data-id="${n.id}"` })}</div></td></tr>`))}</div>` +
      `<div ${fp(5)}>${note("平台只在 NICo 里创建子网和地址池，不配置交换机。每个网段的 VLAN、网关和 DHCP 中继要在交换机上提前配好，中继指向“DHCP 服务”页签里的服务地址。DHCP 地址池可单独配置；子网名称、CIDR、网关及 MTU 创建后不可修改。")}</div>`;
  },
  spec: {
    purpose: "把“网段规划”变成导入设备清单之前的明确一步。回答三个问题：每类设备接口用哪个网段、地址够不够、NICo 里是否已经建好。",
    entry: "接入 → 网络规划 → 子网", design: "5 整体操作运维流程（网络规划）；6.7 网络", existing: "资源 → 网络管理。子网表头、状态和弹窗沿用；增加“用途”和规划检查",
    points: [
      { n: 1, name: "规划检查", kind: "新增", desc: "按用途逐项检查：带外管理、交换机系统管理、主机管理是否都有子网、子网有没有子域、可分配地址是否不少于需要的数量。需要的数量按接口算：一台交换机有一个 BMC 和两个 NVOS 管理口。" },
      { n: 2, name: "统计条", kind: "新增", desc: "子网数、可分配地址、已分配、缺少子域的子网数。" },
      { n: 3, name: "子网表", kind: "调整", desc: "子网名称 / 类型、前缀 / 网关、DHCP 范围、MTU / 保留地址、NICo 状态沿用；增加“用途”“子域”和“已分配 / 可分配”。" },
      { n: 4, name: "行操作", kind: "沿用", desc: "查看、配置 DHCP 地址池、删除。有接口在使用的子网不能删除。" },
      { n: 5, name: "现场前提说明", kind: "调整", desc: "写明平台不配置交换机：VLAN、网关和 DHCP 中继是现场前提。" },
    ],
    fields: [["用途", "平台", "带外管理：各类设备的 BMC；交换机系统管理：NVOS 管理口；主机管理：计算托盘主机网口。NICo 的子网没有这一项，由平台记录"], ["类型", "NICo", "Underlay 用于带外与交换机管理；HostInband 用于主机引导与管理"], ["子域", "NICo", "子网所属的 DNS 子域。没有子域的子网发不出地址"], ["交换机侧 VLAN", "平台", "只是备注，NICo 不保存也不使用"], ["已分配 / 可分配", "NICo", "可分配 = 子网地址数减去保留地址"]],
    rules: ["规划检查未通过时不能导入设备清单。", "新增子网、配置地址池、删除需要管理角色。", "已创建的子网只允许调整 DHCP 地址池。", "这一版计算托盘上的 BlueField 只作为网卡使用，主机从主机管理网段获得地址。", "地址的分配方式是逐台设备决定的，不是子网的属性，见“地址分配”。"],
    dialogs: [
      { name: "新增子网", desc: "在现有“新增子网”弹窗上增加“用途”和“子域”，其余字段沿用。", fields: [["子网名称", "是", ""], ["用途", "是", "带外管理 / 交换机系统管理 / 主机管理；决定 NICo 网络类型"], ["子网 CIDR", "是", ""], ["网关", "是", ""], ["子域", "是", "从站点已有的 DNS 子域里选"], ["DHCP 起始地址、DHCP 结束地址", "否", "留空时使用去掉保留地址后的整个网段"], ["交换机侧 VLAN", "否", "备注"], ["MTU、起始保留地址数", "否", "默认 1500、10"]] },
      { name: "DHCP 地址池", desc: "沿用现有弹窗。", fields: [["DHCP 起始地址", "是", ""], ["DHCP 结束地址", "是", ""]] },
    ],
  },
});
registerAction("net-view", ({ id }) => { const n = DB.subnet(id); modal("子网详情", n.name, defs([["子网名称", esc(n.name)], ["子网 ID", code(n.id)], ["用途", roleOf(n.role).label + "：" + roleOf(n.role).devices], ["类型", n.kind], ["前缀", code(n.cidr)], ["网关", code(n.gateway)], ["起始保留地址数", n.reserved], ["DHCP 地址池", code(n.pool[0] + " – " + n.pool[1])], ["MTU", n.mtu], ["子域", n.subdomain ? code(n.subdomain) : "未设置"], ["交换机侧 VLAN（备注）", esc(n.vlan || "—")], ["关联接口数", DB.subnetUsed(n.id)]]), button("关闭", "close") + act("配置 DHCP 地址池", "net-pool", { admin: true, primary: true, extra: `data-id="${n.id}"` }), { wide: false }); });
registerAction("net-new", () => modal("新增子网", "在 NICo 里创建一个网络段", `<div class="live-form">${field("子网名称", `<input class="input" id="nn-name" placeholder="例如 oob-mgmt-2">`)}${field("用途", `<select class="input" id="nn-role">${NET_ROLES.map((r) => `<option value="${r.id}">${r.label}（${r.kind}）</option>`).join("")}</select>`, "决定 NICo 网络类型，并参与规划检查")}${field("子网 CIDR", `<input class="input live-code" id="nn-cidr" placeholder="例如 192.0.2.0/24">`)}${field("网关", `<input class="input live-code" id="nn-gw">`)}${field("子域", `<select class="input" id="nn-sub"><option>oob.example.internal</option><option>nvos.example.internal</option><option>host.example.internal</option></select>`, "没有子域的子网发不出地址")}${field("DHCP 起始地址", `<input class="input live-code" id="nn-start">`, "可选")}${field("DHCP 结束地址", `<input class="input live-code" id="nn-end">`, "可选")}</div>${note("创建前请确认交换机上已为这个网段配置网关和 DHCP 中继。")}`,
  button("取消", "close") + button("创建到 NICo", "net-create", true), { wide: false }));
registerAction("net-create", () => {
  const v = (id) => $("#" + id).value.trim(), name = v("nn-name"), cidr = v("nn-cidr"), gw = v("nn-gw"), role = v("nn-role");
  if (!name || !cidr || !gw) return toast("子网名称、CIDR 和网关都要填写");
  if (!/^\d+\.\d+\.\d+\.\d+\/\d+$/.test(cidr)) return toast("子网 CIDR 的格式应为 192.0.2.0/24");
  if (S.subnets.some((n) => n.name === name || n.cidr === cidr)) return toast("已有同名或相同前缀的子网");
  const base = cidr.split("/")[0].split(".").slice(0, 3).join("."), size = Math.max(0, 2 ** (32 - +cidr.split("/")[1]) - 2 - 10);
  S.subnets.push({ id: "net-" + name, name, role, kind: roleOf(role).kind, cidr, gateway: gw, subdomain: v("nn-sub"), vlan: "", pool: [v("nn-start") || base + ".11", v("nn-end") || base + ".250"], reserved: 10, capacity: size, mtu: role === "host" ? 9000 : 1500, state: "READY" });
  addAudit("站点", "新增子网 " + name, roleOf(role).label, "—", "读回 READY"); closeModal(); toast("子网已创建，读回 READY"); render();
});
registerAction("net-pool", ({ id }) => { const n = DB.subnet(id); modal("DHCP 地址池", n.name + " · " + n.cidr, `<div class="live-form">${field("DHCP 起始地址", `<input class="input live-code" id="np-start" value="${n.pool[0]}">`)}${field("DHCP 结束地址", `<input class="input live-code" id="np-end" value="${n.pool[1]}">`)}</div>${note("只影响之后的新分配，不改变已经分配出去的地址。")}`, button("取消", "close") + button("应用", "net-pool-apply", true, `data-id="${id}"`), { wide: false }); });
registerAction("net-pool-apply", ({ id }) => { const n = DB.subnet(id), a = $("#np-start").value.trim(), b = $("#np-end").value.trim(); if (!a || !b) return toast("起始和结束地址都要填写"); n.pool = [a, b]; addAudit("站点", "配置 DHCP 地址池 " + n.name, `${a} – ${b}`, "—", "读回一致"); closeModal(); toast("DHCP 地址池已应用"); render(); });
registerAction("net-delete", ({ id }) => { const n = DB.subnet(id); modal("删除子网", n.name, defs([["子网", `${esc(n.name)} · ${code(n.cidr)}`], ["用途", roleOf(n.role).label], ["影响", "删除后这个用途可能缺少子网，规划检查会不通过"]]) + `<label class="live-check"><input type="checkbox" id="nd-ok"> 确认删除此子网</label>`, button("取消", "close") + `<button class="button danger" data-live="net-delete-run" data-id="${id}">确认删除</button>`, { wide: false }); });
registerAction("net-delete-run", ({ id }) => { if (!$("#nd-ok").checked) return toast("请勾选确认项"); const n = DB.subnet(id); S.subnets = S.subnets.filter((x) => x.id !== id); addAudit("站点", "删除子网 " + n.name, "—", "—", "已删除"); closeModal(); toast("子网已删除"); render(); });

const lastLease = (n) => DB.interfaces().filter((i) => i.subnet === n.id).map((i) => i.tray.lastSeen).concat(S.endpoints.filter((e) => e.subnet === n.id).map((e) => e.seen)).sort().pop() || "";
registerPage("network/dhcp", {
  module: "network", tab: "DHCP 服务", title: "DHCP 服务",
  render() {
    return heading("DHCP 服务", "查看 NICo DHCP 是否在为每个网段工作：有没有设备从这个网段拿到地址，地址池用了多少。", button("刷新数据", "refresh") + act("管理引导网络", "net-boot", { admin: true })) +
      `<div class="live-grid"><section class="live-card" ${fp(1)}><h2>DHCP 服务</h2>${defs([["DHCP 模式", "NICo DHCP"], ["服务状态", badge("已就绪", "green")], ["服务地址", code("198.51.100.4") + "　交换机的 DHCP 中继指向这个地址"], ["地址下发", "还没有声明的设备从地址池动态分配；声明写入后按声明里的方式分配"]])}</section>
       <section class="live-card" ${fp(3)}><h2>引导服务</h2>${defs([["PXE 引导服务器", code("198.51.100.5")], ["安装材料 HTTP 地址", code("198.51.100.6:8080")], ["DNS 地址", code("198.51.100.2")], ["NTP 地址", code("198.51.100.3")]])}</section></div>` +
      `<div ${fp(2)}>${table(["子网", "用途", "网关", "最近一次给出地址", "已分配 / 地址池", "状态"], S.subnets.map((n) => { const at = lastLease(n); return `<tr><td>${subnetLink(n.id)}<span class="cell-sub live-code">${n.cidr}</span></td><td>${roleOf(n.role).label}</td><td>${code(n.gateway)}</td><td>${at ? code(at) : "—"}</td><td>${usageCell(n)}</td><td>${at ? badge("有设备拿到地址", "green") : badge("还没有设备拿到地址", "amber")}</td></tr>`; }))}</div>` +
      `<div ${fp(4)}>${note("某个子网一直“还没有设备拿到地址”，通常是交换机没有为这个网段配置 DHCP 中继，或中继没有指向服务地址。现场可用随平台提供的 DHCP 检查工具在该网段发一次请求，确认能否收到应答。")}</div>`;
  },
  spec: {
    purpose: "把 DHCP 从“看不见的前提”变成可以检查的状态。设备发现不了时，先在这里判断是不是这个网段根本没有设备拿到地址。",
    entry: "接入 → 网络规划 → DHCP 服务", design: "6.7 网络；8.3 外部依赖缺失时的行为", existing: "站点设置的“DHCP / PXE / DNS / NTP”面板和“管理引导网络”弹窗沿用；按子网的状态是新增",
    points: [
      { n: 1, name: "DHCP 服务", kind: "调整", desc: "DHCP 模式、服务状态、服务地址和地址下发规则。整机柜站点只使用 NICo DHCP。" },
      { n: 2, name: "按子网的状态", kind: "新增", desc: "每个子网最近一次给出地址的时间和地址池使用量。一直没有给出过地址的子网标出来。" },
      { n: 3, name: "引导服务", kind: "沿用", desc: "PXE 引导服务器、安装材料 HTTP、DNS、NTP 的地址，与现有面板一致。" },
      { n: 4, name: "排查提示", kind: "新增", desc: "说明子网一直没有给出地址的常见原因和现场的 DHCP 检查工具。" },
    ],
    fields: [["最近一次给出地址", "NICo 的接口记录", "这个子网里各接口最近一次申请地址的时间里最新的一个。NICo 不按子网统计收到的请求数"], ["状态", "平台", "有设备拿到地址 / 还没有设备拿到地址"]],
    rules: ["管理引导网络需要管理角色。", "平台不配置交换机的 DHCP 中继。"],
    dialogs: [{ name: "管理引导网络", desc: "沿用现有弹窗。", fields: [["PXE 引导服务器 IP", "是", ""], ["引导 HTTP 端点", "是", ""], ["安装材料 HTTP 地址、端口", "是", ""], ["DNS 地址、NTP 地址", "否", ""]] }],
  },
});
registerAction("net-boot", () => toast("沿用现有的“管理引导网络”弹窗，设计稿不重复展示"));

registerPage("network/leases", {
  module: "network", tab: "地址分配", title: "地址分配",
  render() {
    const f = { net: view("leaseNet", ""), kind: view("leaseKind", ""), q: view("leaseQ", "").toLowerCase() };
    const all = DB.interfaces(), list = all.filter((i) => (!f.net || i.subnet === f.net) && (!f.kind || i.tray.type === f.kind) && (!f.q || [i.ip, i.mac, i.tray.serial, i.tray.rack].join(" ").toLowerCase().includes(f.q)));
    return heading("地址分配", "查看每个地址分给了哪台设备的哪个接口。", button("刷新数据", "refresh")) +
      `<div class="filter-bar" ${fp(1)}>${selectField("leaseNet", "子网", [["", "全部子网"], ...S.subnets.map((n) => [n.id, n.name])], f.net)}${selectField("leaseKind", "设备类型", [["", "全部类型"], ["compute", "计算托盘"], ["switch", "交换机"], ["power_shelf", "供电框"]], f.kind)}${searchField("leaseQ", "搜索", view("leaseQ", ""), "地址、MAC、序列号或机柜")}<span class="live-small">${list.length} 个地址</span></div>` +
      `<div ${fp(2)}>${table(["地址", "MAC", "子网", "设备 / 序列号", "接口", "机柜 / 位置", "分配方式", "最近 DHCP"], list.slice(0, 40).map((i) => `<tr><td>${code(i.ip)}</td><td>${code(i.mac)}</td><td>${subnetLink(i.subnet)}</td><td><a class="link-button" data-live="tray-detail" data-id="${i.tray.id}">${code(i.tray.serial)}</a><span class="cell-sub">${TYPE_LABEL[i.tray.type]}</span></td><td>${i.iface}</td><td><a class="link-button" data-go="rack/${i.tray.rack}">${i.tray.rack}</a><span class="cell-sub">槽位 ${pad2(i.tray.slot)}</span></td><td ${fp(3)}>${i.mode}</td><td>${code(i.tray.lastSeen)}</td></tr>`), "没有符合筛选条件的地址。")}${list.length > 40 ? `<p class="live-small">显示前 40 个，共 ${list.length} 个。</p>` : ""}</div>` +
      (S.endpoints.length ? note(`另有 ${S.endpoints.length} 个地址还没有归属到设备，在<a class="link-button" data-go="discovery">设备发现</a>里处理。`) : "");
  },
  spec: {
    purpose: "按地址查设备。排查地址冲突、确认某台设备拿到了哪个地址时使用。", entry: "接入 → 网络规划 → 地址分配", design: "6.7 网络", existing: "网络管理里的“子网地址分配”弹窗扩展为页签",
    points: [
      { n: 1, name: "筛选", kind: "新增", desc: "子网、设备类型和搜索（地址、MAC、序列号、机柜）。" },
      { n: 2, name: "地址表", kind: "调整", desc: "地址、MAC、子网、设备、接口、位置、分配方式和最近一次 DHCP。设备和机柜可点击。" },
      { n: 3, name: "分配方式", kind: "调整", desc: "显示 NICo 对这个接口回报的分配方式。它逐台设备决定：计算托盘的 BMC 默认是保留，其余接口默认是动态分配。" },
    ],
    fields: [["接口", "NICo", "BMC、NVOS 管理口（主、备）、主机管理口、BlueField 网卡的 BMC"], ["分配方式", "NICo", "动态分配、固定地址、保留"]],
    rules: ["页面只读。地址由 NICo 分配，不在这里手工指定。", "还没有归属的地址不在这张表里，在“设备发现”里处理。"],
  },
});
