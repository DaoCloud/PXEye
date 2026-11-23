"use strict";
/* 清单：到货清单是全平台唯一的人工输入。合并现有“设备管理”里的设备规划、U 位导入和交换机信息导入。 */

registerPage("inventory", {
  module: "inventory", tab: "期望清单", title: "设备清单",
  render() {
    const f = { rack: view("invRack", ""), type: view("invType", ""), q: view("invQ", "").toLowerCase() };
    const all = DB.trays(), list = all.filter((t) => (!f.rack || t.rack === f.rack) && (!f.type || t.type === f.type) && (!f.q || [t.serial, t.bmcMac, t.bmcIp, t.rack].join(" ").toLowerCase().includes(f.q)));
    const compare = (t) => (!t.state ? badge("未纳管", "gray") : t.actualSerial && t.actualSerial !== t.serial ? badge("存在差异", "red") : /探测失败/.test(t.state) ? badge("设备信息暂不可读", "gray") : badge("配置一致", "green"));
    return heading("设备清单", "到货清单是唯一的人工输入。导入后生成 NICo 的期望清单，机柜规格由 NICo 推导。", button("刷新数据", "refresh") + button("下载模板", "inv-template") + act("导入清单", "inv-import", { primary: true, gate: !siteReady() ? "站点未就绪，不能导入" : !DB.planOk() ? "网络规划检查未通过，先到“网络规划”补齐子网" : "", extra: fp(1) })) +
      `<div ${fp(2)}>${summary([["清单版本", "v" + S.inventory[0].v], ["NVLink 域", S.domains.length], ["机柜", S.racks.length], ["设备", all.length], ["与 NICo 期望清单", badge("一致", "green")]])}</div>` +
      `<div ${fp(3)}>${table(["机柜", "NVLink 域", "机柜规格", "计算托盘", "交换机", "供电框", "位置"], S.racks.map((r) => `<tr class="row-link" data-go="rack/${r.id}"><td><strong>${r.id}</strong></td><td>${code(r.domain)}</td><td>${code(r.profile)}<span class="cell-sub">由 NICo 推导</span></td><td>18</td><td>9</td><td>8</td><td>${esc(r.location)}</td></tr>`))}</div>` +
      `<h2 class="section-title">设备明细</h2><div class="filter-bar" ${fp(4)}>${selectField("invRack", "机柜", [["", "全部机柜"], ...S.racks.map((r) => [r.id, r.id])], f.rack)}${selectField("invType", "设备类型", [["", "全部类型"], ["compute", "计算托盘"], ["switch", "交换机"], ["power_shelf", "供电框"]], f.type)}${searchField("invQ", "搜索设备", view("invQ", ""), "序列号、IP、MAC 或机柜")}<span class="live-small">${list.length} 条</span></div>` +
      `<div ${fp(5)}>${table(["设备序列号", "类型", "机柜 / 槽位", "BMC 地址 / MAC", "厂商 / 型号", "配置对比"], list.slice(0, 40).map((t) => `<tr><td>${code(t.serial)}</td><td>${TYPE_LABEL[t.type]}</td><td>${t.rack}<span class="cell-sub">槽位 ${pad2(t.slot)}</span></td><td>${code(t.bmcIp)}<span class="cell-sub live-code">${t.bmcMac}</span></td><td>${t.vendor}<span class="cell-sub">${t.model}</span></td><td>${compare(t)}</td></tr>`), "没有符合筛选条件的设备。")}${list.length > 40 ? `<p class="live-small">显示前 40 条，共 ${list.length} 条。</p>` : ""}</div>`;
  },
  spec: {
    calls: [["rack-profile.list", "核对机柜规格是否受支持"], ["segment.list", "核对固定地址落在已有子网内"], ["rack-group.list", "读取机柜组"], ["rack-group.write", "写入机柜组"], ["expected-rack.list", "读取机柜声明和推导出的规格"], ["expected-rack.write", "写入机柜声明"], ["expected-machine.list", "读取计算托盘声明"], ["expected-machine.write", "写入计算托盘声明"], ["expected-switch.list", "读取交换机声明"], ["expected-switch.write", "写入交换机声明"], ["expected-shelf.list", "读取供电框声明"], ["expected-shelf.write", "写入供电框声明"], ["expected-domain.write", "写入 NVLink 域声明"]],
    purpose: "把 DCIM 或出货清单变成 NICo 的期望清单。这是全流程唯一需要人工维护的数据。",
    entry: "接入 → 设备清单 → 期望清单", design: "6.2 清单；7.1 资源与归属", existing: "设备管理 → 设备规划（导入、对比）；服务器页的“导入 U 位”和布线页的“导入交换机信息”并入本页",
    points: [
      { n: 1, name: "导入清单", kind: "调整", desc: "沿用设备规划的“校验并预览 → 保存”两步，但输入是覆盖三类设备的整表，结果是整表差异。预览里同时显示各用途的地址是否够用。" },
      { n: 2, name: "清单概况", kind: "新增", desc: "当前版本、域、机柜、设备数量，以及与 NICo 期望清单是否一致。" },
      { n: 3, name: "机柜与机柜规格", kind: "新增", desc: "每个机柜的域和成员数量。机柜规格不由人填写，显示 NICo 的推导结果。点击进入机柜。" },
      { n: 4, name: "筛选", kind: "沿用", desc: "沿用设备管理的机柜、设备类型和搜索三个筛选。" },
      { n: 5, name: "设备明细与配置对比", kind: "调整", desc: "沿用设备规划的“配置对比”一列和它的用词。槽位来自清单，不再单独导入 U 位。" },
    ],
    fields: [["机柜 / 槽位", "到货清单", "写入 NICo 的期望清单，是位置的唯一来源"], ["机柜规格", "NICo 推导", "由域的拓扑和成员厂商推导，推导失败在导入时报错"], ["配置对比", "清单与 NICo 比对", "配置一致、存在差异、未纳管、设备信息暂不可读"]],
    rules: ["站点未就绪或网络规划检查未通过时不能导入。", "导入预览按新增设备重新计算各用途的地址是否够用。", "凭据不进清单；出厂凭据是站点级档案。", "移除有实例或进行中任务的设备会被拒绝。"],
    dialogs: [{ name: "导入清单", desc: "第一步选文件，第二步确认差异并填写原因。", fields: [["到货清单文件", "是", "CSV 或 Excel；必填列 rack, domain, type, slot, serial, bmc_mac, vendor"], ["原因", "是", "写入审计和版本记录"]] }],
  },
});
registerAction("inv-template", () => toast("模板列：rack, domain, type, slot, serial, bmc_mac, vendor, bmc_ip, host_mac, host_ip"));
registerAction("inv-import", () => modal("导入清单", "步骤 1 / 2 · 一张表，一行一台设备",
  `<div class="live-form">${field("选择 Excel 或 CSV 文件", `<input class="input" value="arrival-2026-11-B.csv（示例文件）" readonly>`)}</div>${note("必填列：" + code("rack, domain, type, slot, serial, bmc_mac, vendor") + "；可选列：" + code("bmc_ip, host_mac, host_ip") + "。凭据不进清单。")}`,
  button("取消", "close") + button("校验并预览", "inv-preview", true), { wide: false }));
registerAction("inv-preview", () => {
  if (DB.rack("RACK-A03")) return modal("导入清单", "步骤 2 / 2", note("文件与当前期望清单一致，没有需要写入的变化。"), button("关闭", "close", true), { wide: false });
  modal("导入清单", "步骤 2 / 2 · 确认差异",
    `<p class="live-small">校验通过：35 行。待新增 35 · 待更新 0 · 无变化 70 · 待移除 0 · 校验失败 0</p>` +
    table(["操作", "对象", "说明"], [
      `<tr><td>${badge("新增", "green")}</td><td><strong>NVLink 域 NVL-D02</strong></td><td>包含机柜 RACK-A03</td></tr>`,
      `<tr><td>${badge("新增", "green")}</td><td><strong>机柜 RACK-A03</strong></td><td>机柜规格推导为 ${code(PROFILE)}</td></tr>`,
      `<tr><td>${badge("新增", "green")}</td><td>计算托盘 × 18、交换机 × 9、供电框 × 8</td><td>槽位 01–35；BMC 地址由 NICo 分配</td></tr>`,
      `<tr><td>${badge("无变化", "gray")}</td><td>RACK-A01、RACK-A02（70 台）</td><td>—</td></tr>`,
      `<tr><td>${DB.planOk({ oob: 35, nvos: 9, host: 18 }) ? badge("地址够用", "green") : badge("地址不足", "red")}</td><td>网络规划</td><td>${DB.planChecks({ oob: 35, nvos: 9, host: 18 }).map((c) => `${c.role.label} 需要 ${c.need} / 可分配 ${c.capacity}`).join("；")}</td></tr>`,
    ]) + `<div class="live-form">${field("原因", `<input class="input" id="inv-why" value="到货批次 2026-11-B">`)}</div>`,
    button("重新预览", "inv-import") + button("保存导入清单", "inv-save", true, DB.planOk({ oob: 35, nvos: 9, host: 18 }) ? "" : 'disabled title="地址不足，先到网络规划扩容"'));
});
registerAction("inv-save", () => {
  const why = $("#inv-why").value.trim(); if (!why) return toast("请填写原因");
  S.racks.push(makeRack("RACK-A03", 3, "NVL-D02", false, "", "机房 1 · A 列 03"));
  S.domains.push({ id: "NVL-D02", topology: "gb200_nvl72r1_c2g4", racks: ["RACK-A03"], health: "none", partitions: 0 });
  S.inventory.unshift({ v: S.inventory[0].v + 1, at: nowText(), by: "ops-01", file: "arrival-2026-11-B.csv", note: "新增 RACK-A03（35 台）", why });
  addAudit("站点", "导入清单 v" + S.inventory[0].v, why, "—", "读回一致"); S.guide = 4; closeModal(); toast("期望清单已写入 NICo，读回一致"); render();
});

registerPage("inventory/versions", {
  module: "inventory", tab: "版本记录", title: "版本记录",
  render() {
    return heading("版本记录", "每次导入或更换设备都会产生一个清单版本，可用于重建期望清单。", button("刷新数据", "refresh")) +
      `<div ${fp(1)}>${table(["版本", "时间", "操作者", "文件", "变化", "原因"], S.inventory.map((v) => `<tr><td><strong>v${v.v}</strong></td><td>${code(v.at)}</td><td>${v.by}</td><td>${code(v.file)}</td><td>${esc(v.note)}</td><td>${esc(v.why || "—")}</td></tr>`))}</div>` + note("版本记录只追加。清单文件按版本保存在平台本地，不包含凭据。");
  },
  spec: {
    purpose: "记录期望清单每次变化的来源，作为审计和恢复的依据。", entry: "接入 → 设备清单 → 版本记录", design: "6.2 清单；10 非功能设计（备份）", existing: "新增页面",
    points: [{ n: 1, name: "版本列表", kind: "新增", desc: "版本、时间、操作者、文件、变化和原因。更换设备和机柜退役也会产生版本。" }],
    rules: ["只追加，不删除。"],
  },
});
