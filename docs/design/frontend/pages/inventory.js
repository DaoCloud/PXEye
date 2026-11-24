"use strict";
/* 清单：到货清单给出机柜、槽位、设备类型、序列号和设备凭据。它不含 MAC：MAC 要等设备通电后从 DHCP 得到。
   所以导入后清单先保存在平台里（待匹配）；设备通电、平台读出序列号并匹配上清单里的一行（已匹配）；
   人对这个机柜确认接入之后，声明才写进 NICo（已写入）。
   合并现有“设备管理”里的设备规划、U 位导入和交换机信息导入。 */

const INV_COLUMNS = "rack, slot, type, serial";
const INV_OPTIONAL = "location, bmc_user, bmc_password, nvos_user, nvos_password";
const invState = (t) => (t.declared ? badge("已写入 NICo", "green") : t.matched ? badge("已匹配 · 待确认接入", "blue") : badge("待匹配", "gray"));
const invKey = (t) => (t.declared ? "done" : t.matched ? "matched" : "todo");
const credCell = (t) => badge("BMC 已提供", "green") + (t.type === "switch" ? " " + badge("NVOS 已提供", "green") : "");

registerPage("inventory", {
  module: "inventory", tab: "到货清单", title: "设备清单",
  render() {
    const f = { rack: view("invRack", ""), type: view("invType", ""), st: view("invSt", ""), q: view("invQ", "").toLowerCase() };
    const all = DB.trays(), list = all.filter((t) => (!f.rack || t.rack === f.rack) && (!f.type || t.type === f.type) && (!f.st || invKey(t) === f.st) && (!f.q || [t.serial, t.bmcMac, t.bmcIp, t.rack].join(" ").toLowerCase().includes(f.q)));
    const count = (r, type) => r.trays.filter((t) => t.type === type).length;
    return heading("设备清单", "到货清单给出机柜、槽位、序列号和设备凭据。设备通电并按序列号匹配上、机柜确认接入之后，声明才写进 NICo。", button("刷新数据", "refresh") + button("下载模板", "inv-template") + act("导入清单", "inv-import", { primary: true, gate: !siteReady() ? "站点未就绪，不能导入" : !DB.planOk() ? "网络规划检查未通过，先到“网络规划”补齐子网" : "", extra: fp(1) })) +
      `<div ${fp(2)}>${summary([["清单版本", "v" + S.inventory[0].v], ["机柜", S.racks.length], ["设备", all.length], ["已写入 NICo", all.filter((t) => t.declared).length], ["已匹配 · 待确认接入", all.filter((t) => t.matched && !t.declared).length], ["待匹配", all.filter((t) => !t.matched).length]])}</div>` +
      `<div ${fp(3)}>${table(["机柜", "机柜拓扑 / 厂商", "机柜规格", "计算托盘", "交换机", "供电框", "已写入 NICo", "位置"], S.racks.map((r) => `<tr class="row-link" data-go="rack/${r.id}"><td><strong>${r.id}</strong></td><td>${code(r.topology)}<span class="cell-sub">${r.vendor}</span></td><td>${code(r.profile)}<span class="cell-sub">由拓扑和厂商推导 · NICo 已配置</span></td>${["compute", "switch", "power_shelf"].map((k) => `<td>${count(r, k)}<small class="muted"> / ${PROFILE_NEED[k]}</small></td>`).join("")}<td>${r.trays.filter((t) => t.declared).length}<small class="muted"> / ${r.trays.length}</small></td><td>${esc(r.location)}</td></tr>`))}</div>` +
      `<h2 class="section-title">设备明细</h2><div class="filter-bar" ${fp(4)}>${selectField("invRack", "机柜", [["", "全部机柜"], ...S.racks.map((r) => [r.id, r.id])], f.rack)}${selectField("invType", "设备类型", [["", "全部类型"], ["compute", "计算托盘"], ["switch", "交换机"], ["power_shelf", "供电框"]], f.type)}${selectField("invSt", "清单状态", [["", "全部"], ["todo", "待匹配"], ["matched", "已匹配 · 待确认接入"], ["done", "已写入 NICo"]], f.st)}${searchField("invQ", "搜索设备", view("invQ", ""), "序列号、MAC、地址或机柜")}<span class="live-small">${list.length} 条</span></div>` +
      `<div ${fp(5)}>${table(["设备序列号", "类型", "机柜 / 槽位", "设备凭据", "BMC MAC / 地址", "型号", "清单状态"], list.slice(0, 40).map((t) => `<tr><td>${code(t.serial)}</td><td>${TYPE_LABEL[t.type]}</td><td>${t.rack}<span class="cell-sub">槽位 ${pad2(t.slot)}</span></td><td ${fp(6)}>${t.declared ? `<span class="muted">已交给 NICo</span>` : credCell(t)}</td><td>${t.bmcMac ? code(t.bmcMac) + `<span class="cell-sub live-code">${t.bmcIp}</span>` : `<span class="muted">通电后获得</span>`}</td><td>${t.model ? esc(t.model) : `<span class="muted">发现后读取</span>`}</td><td>${invState(t)}</td></tr>`), "没有符合筛选条件的设备。")}${list.length > 40 ? `<p class="live-small">显示前 40 条，共 ${list.length} 条。</p>` : ""}</div>` +
      note("“待匹配”的设备还没有通电或没有读到身份；“已匹配”的设备已经对上清单，但要等这个机柜确认接入后才写进 NICo。匹配进度在“设备发现”，确认接入在机柜详情。");
  },
  spec: {
    purpose: "把到货清单变成设备进入 NICo 的依据：机柜、槽位、设备类型、序列号和设备凭据。清单不要求 MAC。",
    entry: "接入 → 设备清单 → 到货清单", design: "6.2 清单；7.1 资源与归属", existing: "设备管理 → 设备规划（导入、对比）；服务器页的“导入 U 位”和布线页的“导入交换机信息”并入本页",
    points: [
      { n: 1, name: "导入清单", kind: "调整", desc: "沿用设备规划的“校验并预览 → 保存”两步。输入是覆盖三类设备的整表，另选机柜拓扑和机柜厂商。保存只进平台，不写 NICo。" },
      { n: 2, name: "清单概况", kind: "新增", desc: "当前版本、机柜、设备数量，以及已写入 NICo、已匹配待确认接入、待匹配三种状态的数量。" },
      { n: 3, name: "机柜与机柜规格", kind: "新增", desc: "每个机柜的拓扑、厂商、推导出的机柜规格，三类设备的清单数量与规格要求，以及已写入 NICo 的数量。点击进入机柜。" },
      { n: 4, name: "筛选", kind: "调整", desc: "沿用设备管理的机柜、设备类型和搜索；增加“清单状态”。" },
      { n: 5, name: "设备明细", kind: "调整", desc: "序列号、类型、机柜 / 槽位来自清单；BMC MAC、地址和型号在设备被发现后才有，之前显示“通电后获得”“发现后读取”。" },
      { n: 6, name: "设备凭据", kind: "新增", desc: "只显示是否已提供，不显示内容。声明写入 NICo 后，凭据交给 NICo，平台不再保存。" },
    ],
    fields: [["机柜 / 槽位、序列号", "到货清单", "匹配设备的依据是序列号；匹配后机柜和槽位随声明写入 NICo"], ["机柜拓扑", "NICo 的站点配置", "NICo 对一种机柜硬件布局的命名，例如 gb200_nvl72r1_c2g4。可选的值来自 NICo 已配置的机柜规格，平台不维护这张表"], ["机柜规格", "NICo 按机柜拓扑和厂商推导", "规格里写着这种机柜应有几台计算托盘、交换机和供电框，以及用哪份固件清单。NICo 没有配置这个规格时，导入预览报错"], ["设备凭据", "到货清单或批次默认值", "BMC 的用户名和口令；交换机另要 NVOS 的用户名和口令"], ["BMC MAC / 地址", "NICo DHCP", "设备通电后获得"], ["型号", "读取设备身份", "发现后读取，清单里不填"], ["清单状态", "平台", "待匹配、已匹配 · 待确认接入、已写入 NICo"]],
    rules: ["站点未就绪或网络规划检查未通过时不能导入。", "导入预览按新增的机柜重新计算各用途的地址是否够用。", "一台设备的凭据取行内的值；行内留空时取导入时填写的批次默认值。两处都没有的行校验失败。", "口令只在导入时提交一次，加密保存；页面、版本记录和审计里都不出现。", "移除有实例或进行中任务的设备会被拒绝。"],
    dialogs: [{ name: "导入清单", desc: "第一步选文件、机柜拓扑、厂商和批次默认凭据；第二步确认差异并填写原因。", fields: [["到货清单文件", "是", "CSV 或 Excel；必填列 " + INV_COLUMNS + "；可选列 " + INV_OPTIONAL], ["机柜拓扑、机柜厂商", "是", "选项读自 NICo 已配置的机柜规格；两者一起决定机柜规格"], ["批次默认凭据", "否", "BMC 的用户名和口令、NVOS 的用户名和口令；行内留空的设备使用"], ["原因", "是", "写入审计和版本记录"]] }],
  },
});
registerAction("inv-template", () => toast("模板列：" + INV_COLUMNS + "；可选 " + INV_OPTIONAL));
registerAction("inv-import", () => modal("导入清单", "步骤 1 / 2 · 一张表，一行一台设备",
  `<div class="live-form">${field("选择 Excel 或 CSV 文件", `<input class="input" value="arrival-2026-11-B.csv（示例文件）" readonly>`)}
    ${field("机柜拓扑", `<select class="input"><option>${TOPOLOGY}</option><option>gb300_nvl72r1_c2g4</option></select>`, "NICo 对机柜硬件布局的命名。选项读自 NICo 已配置的机柜规格，不在平台里维护")}${field("机柜厂商", `<select class="input"><option>${RACK_VENDOR}</option><option>NVIDIA</option><option>Lenovo</option><option>Supermicro</option></select>`, "整机厂商。和拓扑一起决定机柜规格")}
    ${field("批次默认凭据 · BMC", `<input class="input" value="admin" aria-label="BMC 用户名"><input class="input" type="password" value="demo-demo" aria-label="BMC 口令" style="margin-top:6px">`, "行内没有填凭据的设备使用")}${field("批次默认凭据 · NVOS", `<input class="input" value="admin" aria-label="NVOS 用户名"><input class="input" type="password" value="demo-demo" aria-label="NVOS 口令" style="margin-top:6px">`, "只用于交换机")}</div>
   ${note("必填列：" + code(INV_COLUMNS) + "；可选列：" + code(INV_OPTIONAL) + "。清单里不需要 MAC 和地址。")}`,
  button("取消", "close") + button("校验并预览", "inv-preview", true), { wide: false }));
registerAction("inv-preview", () => {
  if (DB.rack("RACK-A03")) return modal("导入清单", "步骤 2 / 2", note("文件与当前清单一致，没有需要保存的变化。"), button("关闭", "close", true), { wide: false });
  modal("导入清单", "步骤 2 / 2 · 确认差异",
    `<p class="live-small">校验通过：35 行。待新增 35 · 待更新 0 · 无变化 70 · 待移除 0 · 校验失败 0</p>` +
    table(["操作", "对象", "说明"], [
      `<tr><td>${badge("新增", "green")}</td><td><strong>机柜 RACK-A03</strong></td><td>机柜规格推导为 ${code(PROFILE)}，站点已配置；对应一个 NVLink 域</td></tr>`,
      `<tr><td>${badge("新增", "green")}</td><td>计算托盘 × 18、交换机 × 9、供电框 × 8</td><td>数量与机柜规格一致；槽位 01–35</td></tr>`,
      `<tr><td>${badge("凭据齐全", "green")}</td><td>设备凭据</td><td>35 台有 BMC 凭据（3 台行内填写，32 台用批次默认值）；9 台交换机有 NVOS 凭据</td></tr>`,
      `<tr><td>${badge("无变化", "gray")}</td><td>RACK-A01、RACK-A02（70 台）</td><td>—</td></tr>`,
      `<tr><td>${DB.planOk(1) ? badge("地址够用", "green") : badge("地址不足", "red")}</td><td>网络规划</td><td>${DB.planChecks(1).map((c) => `${c.role.label} 需要 ${c.need} / 可分配 ${c.capacity}`).join("；")}</td></tr>`,
    ]) + note("保存后清单留在平台里，状态为“待匹配”。设备通电并按序列号匹配上、你在机柜详情里确认接入之后，才写进 NICo。") + `<div class="live-form">${field("原因", `<input class="input" id="inv-why" value="到货批次 2026-11-B">`)}</div>`,
    button("重新预览", "inv-import") + button("保存清单", "inv-save", true, DB.planOk(1) ? "" : 'disabled title="地址不足，先到网络规划扩容"'));
});
registerAction("inv-save", () => {
  const why = $("#inv-why").value.trim(); if (!why) return toast("请填写原因");
  const r = makeRack("RACK-A03", 3, false, "", "机房 1 · A 列 03"); S.racks.push(r); S.domains.push(makeDomain(r, false));
  S.inventory.unshift({ v: S.inventory[0].v + 1, at: nowText(), by: "ops-01", file: "arrival-2026-11-B.csv", note: "新增 RACK-A03（35 台，待匹配）", why });
  addAudit("站点", "导入清单 v" + S.inventory[0].v, why, "—", "已保存，35 台待匹配"); S.guide = 4; closeModal(); toast("清单已保存：35 台待匹配，等待设备通电"); render();
});

registerPage("inventory/versions", {
  module: "inventory", tab: "版本记录", title: "版本记录",
  render() {
    return heading("版本记录", "每次导入、更换设备或机柜退役都会产生一个清单版本。", button("刷新数据", "refresh")) +
      `<div ${fp(1)}>${table(["版本", "时间", "操作者", "文件", "变化", "原因"], S.inventory.map((v) => `<tr><td><strong>v${v.v}</strong></td><td>${code(v.at)}</td><td>${v.by}</td><td>${code(v.file)}</td><td>${esc(v.note)}</td><td>${esc(v.why || "—")}</td></tr>`))}</div>` + note("版本记录只追加。清单文件按版本保存在平台本地，保存前去掉口令两列。");
  },
  spec: {
    purpose: "记录清单每次变化的来源，作为审计和恢复的依据。", entry: "接入 → 设备清单 → 版本记录", design: "6.2 清单；10 非功能设计（备份）", existing: "新增页面",
    points: [{ n: 1, name: "版本列表", kind: "新增", desc: "版本、时间、操作者、文件、变化和原因。更换设备和机柜退役也会产生版本。" }],
    rules: ["只追加，不删除。", "保存的清单文件不含口令。"],
  },
});
