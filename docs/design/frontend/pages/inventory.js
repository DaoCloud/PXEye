"use strict";
/* 设备清单：对应现有产品的“设备规划”。流程、模板的列名和保存规则都沿用，页面换了样式。
   规划是一份独立的数据：导入只保存规划，不写 NICo，也不自动纳管或下发地址。
   设备被发现、纳管之后，在设备管理里“一键匹配”，规划里的管理口和 BMC 规划地址才写进设备的配置。
   整机柜在主线的 14 列之外只追加三列：slot（槽位）、nvos_username、nvos_password（交换机系统的凭据）；导入时另选机柜拓扑和厂商。 */

const INV_COLUMNS = "kind, serial, management_ip, management_mac, management_subnet, bmc_ip, bmc_mac, bmc_username, bmc_password, pmc_ip, pmc_mac, pmc_username, pmc_password, rack";
const INV_EXTRA = "slot, nvos_username, nvos_password";
const KIND_CODE = { compute: "server", switch: "switch", power_shelf: "power_shelf" };
/* 规划里的管理口（只有服务器有）和控制器地址（服务器、交换机是 BMC，供电框是 PMC）。 */
const planMgmtCell = (t) => (t.type !== "compute" ? `<span class="muted">—</span>` : t.noPlan ? `<span class="muted">没有规划</span>` : (t.plan.mip ? code(t.plan.mip) : `<span class="muted">未填</span>`) + `<span class="cell-sub live-code">${t.plan.mmac || "MAC 未填"}</span>` + (t.plan.msubnet ? `<span class="cell-sub">${t.plan.msubnet}</span>` : ""));
const planBmcCell = (t) => (t.noPlan ? `<span class="muted">没有规划</span>` : (t.plan.bmcIp ? code(t.plan.bmcIp) : `<span class="muted">未填</span>`) + `<span class="cell-sub">${t.declared ? "凭据已交给设备配置" : "凭据已提供"}</span>`);
const planBadge = (t) => { const s = planState(t); return badge(s[0], s[1]); };

registerPage("inventory", {
  module: "inventory", tab: "设备规划", title: "设备清单",
  render() {
    const f = { rack: view("invRack", ""), type: view("invType", ""), st: view("invSt", ""), q: view("invQ", "").toLowerCase() };
    const all = DB.trays(), list = all.filter((t) => (!f.rack || (f.rack === "none" ? !t.rack : t.rack === f.rack)) && (!f.type || t.type === f.type) && (!f.st || planState(t)[0] === f.st) && (!f.q || [t.serial, t.plan.mip, t.plan.mmac, t.plan.bmcIp, t.rack].join(" ").toLowerCase().includes(f.q)));
    const count = (r, type) => r.trays.filter((t) => t.type === type).length, n = (label) => all.filter((t) => planState(t)[0] === label).length;
    return heading("设备清单", "导入设备规划：每行一台设备，写明类型、序列号、机柜和槽位，以及规划的管理口和 BMC 地址。导入只保存规划，不自动纳管，也不下发地址。", button("刷新规划", "refresh") + button("下载模板", "inv-template") + act("导入规划", "inv-import", { primary: true, gate: !siteReady() ? "站点未就绪，不能导入" : !DB.planOk() ? "网络规划检查未通过，先到“网络规划”补齐子网" : "", extra: fp(1) })) +
      `<div ${fp(2)}>${summary([["规划版本", "v" + S.inventory[0].v], ["机柜", S.racks.length], ["设备规划", `${all.length}<small>　其中未分配机柜 ${DB.servers().length}</small>`], ["未纳管", n("未纳管")], ["存在差异", n("存在差异")], ["配置一致", n("配置一致")]])}</div>` +
      `<div ${fp(3)}>${table(["机柜", "机柜拓扑 / 厂商", "机柜规格", "计算托盘", "交换机", "供电框", "已纳管", "位置"], S.racks.map((r) => `<tr class="row-link" data-go="rack/${r.id}"><td><strong>${r.id}</strong></td><td>${code(r.topology)}<span class="cell-sub">${r.vendor}</span></td><td>${code(r.profile)}<span class="cell-sub">由拓扑和厂商推导 · NICo 已配置</span></td>${["compute", "switch", "power_shelf"].map((k) => `<td>${count(r, k)}<small class="muted"> / ${PROFILE_NEED[k]}</small></td>`).join("")}<td>${r.trays.filter((t) => t.declared).length}<small class="muted"> / ${r.trays.length}</small></td><td>${esc(r.location)}</td></tr>`))}</div>` +
      `<h2 class="section-title">规划明细</h2><div class="filter-bar" ${fp(4)}>${selectField("invRack", "机柜", [["", "全部"], ...S.racks.map((r) => [r.id, r.id]), ["none", "未分配机柜"]], f.rack)}${selectField("invType", "设备类型", [["", "全部类型"], ["compute", "服务器"], ["switch", "交换机"], ["power_shelf", "供电框"]], f.type)}${selectField("invSt", "配置对比", [["", "全部"], ["未纳管", "未纳管"], ["存在差异", "存在差异"], ["配置一致", "配置一致"], ["没有规划", "没有规划"]], f.st)}${searchField("invQ", "搜索规划", view("invQ", ""), "序列号、IP、MAC 或机柜")}<span class="live-small">${list.length} 条</span></div>` +
      `<div ${fp(5)}>${table(["设备序列号", "类型", "机柜 / 槽位", "管理口（服务器）", "BMC / PMC 规划地址", "配置对比", "操作"], list.slice(0, 40).map((t) => `<tr><td>${code(t.serial)}<span class="cell-sub">${t.model ? esc(t.model) : "型号纳管后读取"}</span></td><td>${typeLabel(t)}<span class="cell-sub live-code">${KIND_CODE[t.type]}</span></td><td>${t.rack ? `${t.rack}<span class="cell-sub">槽位 ${pad2(t.slot)}</span>` : `<span class="muted">未分配机柜</span>`}</td><td>${planMgmtCell(t)}</td><td>${planBmcCell(t)}</td><td ${fp(6)}>${planBadge(t)}</td>
        <td ${fp(7)}><div class="inline-actions">${t.noPlan ? act("新增规划", "plan-edit", { compact: true, extra: `data-id="${t.id}"` }) : act("编辑规划", "plan-edit", { compact: true, extra: `data-id="${t.id}"` })}${t.type === "compute" ? act("系统配置", "server-config", { compact: true, gate: t.declared ? "" : "设备纳管之后才有系统配置；现在先编辑规划", extra: `data-id="${t.id}"` }) : ""}</div></td></tr>`), "没有符合筛选条件的规划。")}${list.length > 40 ? `<p class="live-small">显示前 40 条，共 ${list.length} 条。</p>` : ""}</div>` +
      note("<b>规划和纳管是两件事。</b>导入只保存规划。设备接电后在“设备发现”里获取设备信息并加入纳管；纳管之后在“设备管理”里勾选设备“一键匹配”，规划里的管理口、BMC 规划地址、机柜和槽位才写进设备的配置。“配置对比”显示这一步做了没有：未纳管、存在差异、配置一致。");
  },
  spec: {
    purpose: "设备规划：每台设备应该是什么样。对应现有产品的“设备规划”，流程、模板列名和保存规则都沿用。规划是独立的数据，导入不写 NICo，也不自动纳管。",
    entry: "接入 → 设备清单 → 设备规划", design: "6.2 清单；7.1 资源与归属", existing: "设备管理 → 设备规划。下载模板、导入规划、校验并预览、保存导入规划、编辑规划、配置对比都沿用；模板在原有 14 列之外追加槽位和交换机系统凭据三列",
    points: [
      { n: 1, name: "导入规划", kind: "沿用", desc: "选文件 → 校验并预览 → 保存导入规划。预览显示待新增、待更新、无变化、校验失败的数量；任何一行校验失败，整批不能保存。整机柜另外要选机柜拓扑和厂商。" },
      { n: 2, name: "概况", kind: "调整", desc: "规划版本、机柜数、规划条数，以及配置对比三种结果的数量：未纳管、存在差异、配置一致。" },
      { n: 3, name: "机柜与机柜规格", kind: "新增", desc: "每个机柜的拓扑、厂商、推导出的机柜规格，三类设备的规划数量与规格要求，以及已纳管的数量。点击进入机柜。" },
      { n: 4, name: "筛选", kind: "沿用", desc: "按机柜、设备类型、配置对比和搜索词筛选。" },
      { n: 5, name: "规划明细", kind: "沿用", desc: "序列号、类型、机柜 / 槽位、服务器的管理口（管理 IP、管理 MAC、管理子网）、BMC 或 PMC 的规划地址。都是规划里的值，不是设备上当前的值。" },
      { n: 6, name: "配置对比", kind: "沿用", desc: "规划和已纳管设备的配置比一比：未纳管、存在差异、配置一致。存在差异时到设备管理里“一键匹配”。" },
      { n: 7, name: "编辑规划与系统配置", kind: "调整", desc: "“编辑规划”改这一行的规划值，沿用现有弹窗。服务器纳管之后多一个“系统配置”，打开的是设备管理里的同一个弹窗、同一份数据；这里通常是纳管之后第一次配置系统的地方。" },
    ],
    fields: [["kind、serial", "规划（必填）", "kind 是 server、switch、power_shelf 之一；serial 在文件里和已有规划里都不能重复，是匹配设备的依据"], ["rack、slot", "规划", "rack 是机柜编号；slot 是整机柜追加的列。不属于机柜的服务器这两列留空"], ["management_ip、management_mac、management_subnet", "规划（只用于服务器）", "规划的主机管理地址、管理口 MAC 和管理子网。填了管理 IP 或管理子网就必须填管理 MAC；管理 IP 要在管理子网内"], ["bmc_ip、bmc_mac、bmc_username、bmc_password", "规划（服务器、交换机）", "规划的 BMC 地址、BMC 的 MAC 和凭据。BMC MAC 不能和管理 MAC 相同"], ["pmc_ip、pmc_mac、pmc_username、pmc_password", "规划（只用于供电框）", "供电框控制器的规划地址、MAC 和凭据"], ["nvos_username、nvos_password", "规划（只用于交换机）", "整机柜追加的列：交换机系统的凭据"], ["机柜拓扑、机柜规格", "NICo 的站点配置", "导入时选择拓扑和厂商，两者一起推导出机柜规格。NICo 没有配置这个规格时，预览报错"], ["配置对比", "平台", "未纳管、存在差异、配置一致。没有规划的已纳管设备显示“没有规划”"]],
    rules: ["导入只保存规划：不写 NICo，不自动纳管，不下发地址。", "站点未就绪或网络规划检查未通过时不能导入。", "表头必须包含规定的列，顺序不限。填了不适用于这类设备的列会校验失败：供电框只填 pmc_*，服务器和交换机填 bmc_*，management_* 只用于服务器。", "任何一行校验失败，整批都不能保存；预览 15 分钟内有效，期间规划有变化要重新预览。", "更新已有规划时，文件里的空单元格保留原值；要清空某个值，用“编辑规划”。密码留空表示保留原来的。", "已有规划的设备类型不能改；已经和采集到的硬件网卡关联的规划不能改序列号。", "文件最大 1 MiB，最多 5000 行。", "密码只在导入或编辑时提交，页面、版本记录和审计里都不出现。", "规划落到设备上靠“一键匹配”：在设备管理里勾选已纳管的设备，一次 1–50 台。改了规划之后要再匹配一次。"],
    dialogs: [
      { name: "导入设备规划", desc: "沿用现有流程：第一步选文件并“校验并预览”；第二步核对每一行是新增、更新、无变化还是校验失败，然后“保存导入规划”。整机柜在第一步多选机柜拓扑和厂商。", fields: [["选择 Excel 或 CSV 文件", "是", "列：" + INV_COLUMNS + "；整机柜追加 " + INV_EXTRA], ["机柜拓扑、机柜厂商", "有新机柜时", "选项读自 NICo 已配置的机柜规格；两者一起决定机柜规格"], ["原因", "是", "写入审计和版本记录"]] },
      { name: "编辑规划", desc: "沿用现有弹窗：改一行规划。服务器显示管理口三项和 BMC 四项；交换机显示 BMC 四项和交换机系统凭据；供电框显示 PMC 四项。", fields: [["设备序列号、设备类型", "是", "类型不能改；已关联硬件网卡的不能改序列号"], ["机柜、槽位", "否", ""], ["管理 IP、管理 MAC、管理子网", "否（服务器）", "填了管理 IP 或管理子网就必须填管理 MAC"], ["BMC / PMC 规划地址、MAC、用户名、密码", "否", "密码留空保留原来的"]] },
    ],
  },
});
registerAction("inv-template", () => toast("模板列：" + INV_COLUMNS + "；整机柜追加 " + INV_EXTRA));
registerAction("inv-import", () => modal("导入设备规划", "步骤 1 / 2 · 一张表，一行一台设备",
  `<div class="live-form">${field("选择 Excel 或 CSV 文件", `<input class="input" value="device-planning-2026-11-B.xlsx（示例文件）" readonly>`, "文件最大 1 MiB，最多 5000 行")}
    ${field("机柜拓扑", `<select class="input"><option>${TOPOLOGY}</option><option>gb300_nvl72r1_c2g4</option></select>`, "文件里有新机柜时选择。NICo 对机柜硬件布局的命名，选项读自 NICo 已配置的机柜规格")}${field("机柜厂商", `<select class="input"><option>${RACK_VENDOR}</option><option>NVIDIA</option><option>Lenovo</option><option>Supermicro</option></select>`, "整机厂商。和拓扑一起决定机柜规格")}</div>
   ${note("表头要包含这 14 列：" + code(INV_COLUMNS) + "。整机柜追加 " + code(INV_EXTRA) + "。导入只保存规划，不自动纳管，也不下发地址。")}`,
  button("取消", "close") + button("校验并预览", "inv-preview", true), { wide: false }));
registerAction("inv-preview", () => {
  if (DB.rack("RACK-A03")) return modal("导入设备规划", "步骤 2 / 2", `<p class="live-small">待新增 0 · 待更新 0 · 无变化 ${DB.trays().length} · 校验失败 0</p>` + note("文件与当前规划一致，没有需要保存的变化。"), button("关闭", "close", true), { wide: false });
  const row = (line, serial, kind, detail) => `<tr><td>${line}</td><td>${code(serial)}</td><td>${kind}</td><td>${badge("新增", "green")}</td><td>${detail}</td></tr>`;
  modal("导入设备规划", "步骤 2 / 2 · 核对后保存",
    `<p class="live-small">待新增 35 · 待更新 0 · 无变化 ${DB.trays().length} · 校验失败 0</p>` +
    table(["行号", "SN", "类型", "操作", "说明"], [row(2, "DEMO-P-A03-01", "power_shelf", "RACK-A03 槽位 01；PMC 凭据已填"), row(6, "DEMO-C-A03-05", "server", "RACK-A03 槽位 05；管理 IP 198.51.100.95，管理 MAC 02:10:03:00:00:05"), row(16, "DEMO-S-A03-15", "switch", "RACK-A03 槽位 15；BMC 和交换机系统凭据已填"), row(7, "DEMO-C-A03-06", "server", "RACK-A03 槽位 06；管理 IP 198.51.100.96，管理 MAC 02:10:03:00:00:06")]) + `<p class="live-small">显示 4 行，共 35 行待新增。</p>` +
    table(["整机柜的检查", "结果", "说明"], [
      `<tr><td>机柜规格</td><td>${badge("通过", "green")}</td><td>新机柜 RACK-A03 的规格推导为 ${code(PROFILE)}，NICo 已配置；计算托盘 18、交换机 9、供电框 8，与规格一致</td></tr>`,
      `<tr><td>地址够不够</td><td>${DB.planOk(1) ? badge("通过", "green") : badge("不够", "red")}</td><td>${DB.planChecks(1).map((c) => `${c.role.label} 需要 ${c.need} / 可分配 ${c.capacity}`).join("；")}</td></tr>`,
    ]) + note("保存后只是多了 35 条规划：不写 NICo，不自动纳管，也不下发地址。设备接电后到“设备发现”里获取设备信息并纳管。") + `<div class="live-form">${field("原因", `<input class="input" id="inv-why" value="到货批次 2026-11-B">`)}</div>`,
    button("重新预览", "inv-import") + button("保存导入规划", "inv-save", true, DB.planOk(1) ? "" : 'disabled title="地址不足，先到网络规划扩容"'));
});
registerAction("inv-save", () => {
  const why = $("#inv-why").value.trim(); if (!why) return toast("请填写原因");
  const r = makeRack("RACK-A03", 3, false, "", "机房 1 · A 列 03"); S.racks.push(r); S.domains.push(makeDomain(r, false));
  /* 这份规划带了服务器的管理口：管理 IP、管理 MAC 和管理子网。 */
  r.trays.filter((t) => t.type === "compute").forEach((t) => Object.assign(t.plan, { mip: `198.51.100.${(t.n - 1) * 40 + t.slot + 10}`, mmac: `02:10:${pad2(t.n)}:00:00:${hex2(t.slot)}`, msubnet: "198.51.100.0/24" }));
  S.inventory.unshift({ v: S.inventory[0].v + 1, at: nowText(), by: "ops-01", file: "device-planning-2026-11-B.xlsx", note: "新增 RACK-A03（35 条规划）", why });
  addAudit("站点", "导入设备规划 v" + S.inventory[0].v, why, "—", "已保存 35 条设备规划"); S.guide = 4; closeModal(); toast("已保存 35 条设备规划。"); render();
});
/* 编辑规划：改一行规划的值。只保存规划，不动设备，也不改设备配置。 */
registerAction("plan-edit", ({ id }) => {
  const t = DB.tray(id), p = t.plan, srv = t.type === "compute", ctl = t.type === "power_shelf" ? "PMC" : "BMC", inp = (pid, v, ph = "") => `<input class="input live-code" id="${pid}" value="${esc(v || "")}" placeholder="${ph}" autocomplete="off">`;
  modal(t.noPlan ? "新增规划" : "编辑规划", `${t.serial} · ${typeLabel(t)}`,
    `<div class="confirm-facts">${defs([["设备序列号", code(t.serial)], ["设备类型", `${typeLabel(t)} · ${code(KIND_CODE[t.type])}`], ["机柜 / 槽位", t.rack ? `${t.rack} · 槽位 ${pad2(t.slot)}` : "未分配机柜"]])}</div>
     <div class="live-form">${srv ? field("管理 IP", inp("pe-mip", p.mip), "规划的主机管理地址") + field("管理 MAC", inp("pe-mmac", p.mmac), "管理口的 MAC；填了管理 IP 或管理子网就必须填") + field("管理子网", `<select class="input" id="pe-msub"><option value="">未填</option>${DB.roleSubnets("host").map((n) => `<option ${n.cidr === p.msubnet ? "selected" : ""}>${n.cidr}</option>`).join("")}</select>`) : ""}
       ${field(ctl + " 规划 IP", inp("pe-bmc", p.bmcIp), "纳管之后按它更新；留空表示不规划")}${field(ctl + " 用户名 / 密码", `<input class="input" value="admin" aria-label="${ctl} 用户名"><input class="input" type="password" placeholder="留空保留原来的密码" aria-label="${ctl} 密码" style="margin-top:6px">`)}</div>
     ${note("保存的是规划，不动设备，也不改已纳管设备的配置。改完之后到设备管理里对这台设备再“一键匹配”一次。")}`,
    button("取消", "close") + button("保存规划", "plan-save", true, `data-id="${id}"`), { wide: false });
});
registerAction("plan-save", ({ id }) => {
  const t = DB.tray(id), srv = t.type === "compute", v = (pid) => ($("#" + pid) ? $("#" + pid).value.trim() : ""), net = DB.roleSubnets("host")[0], oob = DB.roleSubnets("oob")[0];
  const mip = v("pe-mip"), mmac = v("pe-mmac").toLowerCase(), msub = v("pe-msub"), bmc = v("pe-bmc");
  if (srv && (mip || msub) && !mmac) return toast("填了管理 IP 或管理子网，就必须填管理 MAC");
  if (mip && !IP4.test(mip)) return toast("管理 IP 不是合法的 IPv4 地址");
  if (mip && msub && !inCidr(mip, msub)) return toast(`管理 IP 不在管理子网 ${msub} 内`);
  if (mmac && !/^([0-9a-f]{2}:){5}[0-9a-f]{2}$/.test(mmac)) return toast("管理 MAC 的写法不对");
  if (mmac && mmac === t.bmcMac) return toast("管理 MAC 不能和 BMC MAC 相同");
  if (bmc && (!IP4.test(bmc) || !inCidr(bmc, oob.cidr))) return toast(`规划的控制器地址要在带外管理子网 ${oob.cidr} 内`);
  if (srv) Object.assign(t.plan, { mip, mmac, msubnet: msub }); t.plan.bmcIp = bmc; t.noPlan = false;
  S.inventory.unshift({ v: S.inventory[0].v + 1, at: nowText(), by: "ops-01", file: "（编辑规划）", note: `${t.serial} 的规划已修改`, why: "—" });
  addAudit(t.rack ? placeText(t) : t.serial, "编辑规划", "—", "—", "规划已保存，设备未改动"); closeModal(); toast("规划已保存。已纳管的设备要再“一键匹配”一次"); render();
});

registerPage("inventory/versions", {
  module: "inventory", tab: "版本记录", title: "版本记录",
  render() {
    return heading("版本记录", "每次导入规划、编辑规划或删除机柜都会产生一个版本。", button("刷新数据", "refresh")) +
      `<div ${fp(1)}>${table(["版本", "时间", "操作者", "文件", "变化", "原因"], S.inventory.map((v) => `<tr><td><strong>v${v.v}</strong></td><td>${code(v.at)}</td><td>${v.by}</td><td>${code(v.file)}</td><td>${esc(v.note)}</td><td>${esc(v.why || "—")}</td></tr>`))}</div>` + note("版本记录只追加。规划文件按版本保存在平台本地，保存前去掉密码列。");
  },
  spec: {
    purpose: "记录设备规划每次变化的来源，作为审计和恢复的依据。", entry: "接入 → 设备清单 → 版本记录", design: "6.2 清单；10 非功能设计（备份）", existing: "新增页面",
    points: [{ n: 1, name: "版本列表", kind: "新增", desc: "版本、时间、操作者、文件、变化和原因。编辑规划和删除机柜也会产生版本。" }],
    rules: ["只追加，不删除。", "保存的规划文件不含密码。"],
  },
});
