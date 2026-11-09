"use strict";

state.equipmentPlanning = null;
state.equipmentPlanningSearch = "";
state.equipmentPlanningMatching = false;
sectionReads.equipmentPlanning = async () => {
  state.equipmentPlanning = await api("/api/equipment-planning");
};
const equipmentPlanningFields = [
  ["serial", "设备 SN"],
  ["management_ip", "管理 IP"],
  ["management_mac", "管理 MAC"],
  ["management_subnet", "管理子网"],
  ["bmc_ip", "BMC IP"],
  ["bmc_mac", "BMC MAC"],
  ["rack", "机柜"],
];
const equipmentPlanningStates = {
  create: "新增",
  update: "更新",
  unchanged: "无变化",
  invalid: "校验失败",
  saved: "已保存",
  failed: "未匹配",
};
function equipmentPlanningConfiguration(device) {
  const native = state.resources?.devices.find(
    (d) => d.serial === device.serial,
  );
  if (!native) return null;
  const host = (native.interfaces || []).find(
    (n) =>
      n.primary && ["host", "unspecified", 0, 1].includes(n.role || "host"),
  );
  const networkId =
    native.intent?.network_bindings?.[host?.mac_address?.toLowerCase()];
  const network = state.networks?.networks.find((n) => n.id === networkId);
  return {
    serial: native.serial,
    management_ip: host?.fixed_ip || "",
    management_mac: host?.mac_address?.toLowerCase() || "",
    management_subnet: network?.prefixes.map((p) => p.prefix).join(", ") || "",
    bmc_ip: native.bmc_ip_address || "",
    bmc_mac: native.bmc_mac_address?.toLowerCase() || "",
    rack: native.rack_id || "",
  };
}
function equipmentPlanningComparison(row) {
  if (
    !state.equipment ||
    !state.resources ||
    state.equipment.errors?.length ||
    state.readErrors?.equipment ||
    state.readErrors?.resources ||
    state.readErrors?.network
  )
    return { label: "设备信息暂不可读", tone: "gray" };
  const devices = (state.equipment?.devices || []).filter(
    (d) => !d.address_only && d.serial === row.values.serial,
  );
  if (devices.length > 1) return { label: "SN 不唯一", tone: "red" };
  if (!devices.length) return { label: "未纳管", tone: "gray" };
  if (devices[0].kind !== "server")
    return { label: "设备类型不匹配", tone: "red" };
  const current = equipmentPlanningConfiguration(devices[0]);
  if (!current) return { label: "配置暂不可读", tone: "gray" };
  const fields = equipmentPlanningFields.filter(
    ([key]) =>
      key !== "serial" && row.values[key] && row.values[key] !== current[key],
  );
  if (
    (row.interface_rows || []).some((p) => {
      const native = state.resources?.devices.find(
        (d) => d.serial === row.values.serial,
      );
      const nic = native?.interfaces?.find(
        (n) => n.mac_address?.toLowerCase() === p.mac,
      );
      const net = state.networks?.networks.find(
        (n) => n.id === native?.intent?.network_bindings?.[p.mac],
      );
      return (
        nic?.fixed_ip !== p.ip ||
        (nic?.fixed_gateway || "") !== p.gateway ||
        !net?.prefixes.some((n) => n.prefix === p.subnet)
      );
    })
  )
    fields.push(["interfaces", "网卡地址规划"]);
  return {
    label: fields.length ? "存在差异" : "配置一致",
    tone: fields.length ? "gray" : "green",
    current,
    fields,
  };
}
function equipmentPlanningCell(value, current) {
  return `${esc(value || "—")}${current !== undefined && value && current !== value ? `<span class="live-small">设备配置：${esc(current || "未配置")}</span>` : ""}`;
}
function equipmentPlanningMtu(subnet) {
  const matches = (state.networks?.networks || []).filter(
    (n) =>
      n.segment_type === "HOST_INBAND" &&
      n.name !== "static-assignments" &&
      n.prefixes?.length === 1 &&
      n.prefixes[0].prefix === subnet,
  );
  return !state.readErrors?.network &&
    matches.length === 1 &&
    Number.isInteger(matches[0].mtu)
    ? String(matches[0].mtu)
    : "未配置 / 无法匹配";
}
function equipmentPlanningPorts(row) {
  const native = state.resources?.devices.find(
    (d) => d.serial === row.values.serial,
  );
  const saved = new Map((row.interface_rows || []).map((p) => [p.mac, p]));
  const nics = new Map(
    (row.editable_nics || []).map((n) => [n.mac_address, n]),
  );
  for (const p of saved.values())
    if (!nics.has(p.mac)) nics.set(p.mac, { mac_address: p.mac });
  return [...nics.values()].map((n) => {
    const nic = native?.interfaces?.find(
      (p) => p.mac_address?.toLowerCase() === n.mac_address,
    );
    const net = state.networks?.networks.find(
      (p) => p.id === native?.intent?.network_bindings?.[n.mac_address],
    );
    return {
      mac: n.mac_address,
      pci_address: n.pci_address || "",
      ip: nic?.fixed_ip || "",
      subnet: net?.prefixes?.length === 1 ? net.prefixes[0].prefix : "",
      gateway: nic?.fixed_gateway || "",
      ...saved.get(n.mac_address),
    };
  });
}
function equipmentPlanningTable() {
  const data = state.equipmentPlanning;
  if (!data) return '<div class="live-empty">正在读取设备规划…</div>';
  const rows = data.rows.filter((r) =>
    [
      ...Object.values(r.values),
      ...(r.interface_rows || []).flatMap((p) => Object.values(p)),
    ]
      .join(" ")
      .toLowerCase()
      .includes(state.equipmentPlanningSearch.toLowerCase()),
  );
  return (
    `<div class="equipment-planning-toolbar"><span class="live-small">${rows.length} 条规划</span><div class="equipment-planning-search"><label for="planning-search">搜索设备规划</label><input id="planning-search" type="search" placeholder="SN、IP、MAC 或机柜" value="${esc(state.equipmentPlanningSearch)}"></div></div>` +
    table(
      [
        "设备 SN",
        "管理地址 / MAC",
        "管理子网",
        "BMC 地址 / MAC",
        "机柜",
        "网卡地址规划",
        "配置对比",
        "操作",
      ],
      rows.map((row) => {
        const v = row.values,
          comparison = equipmentPlanningComparison(row),
          c = comparison.current;
        const ports = equipmentPlanningPorts(row);
        const interfaces = ports.length
          ? `<details><summary>${ports.length} 个网口</summary>${ports.map((p) => `<div class="live-small">${esc(p.mac)} · ${esc(p.ip || "未配置")} · ${esc(p.subnet || "未配置")} · 网关 ${esc(p.gateway || "无")} · MTU ${esc(equipmentPlanningMtu(p.subnet))}</div>`).join("")}</details>`
          : "—";
        return `<tr><td>${esc(v.serial)}</td><td>${equipmentPlanningCell(v.management_ip, c?.management_ip)}<span class="live-small live-code">${equipmentPlanningCell(v.management_mac, c?.management_mac)}</span></td><td>${equipmentPlanningCell(v.management_subnet, c?.management_subnet)}${v.management_subnet ? `<span class="live-small">MTU ${esc(equipmentPlanningMtu(v.management_subnet))}</span>` : ""}</td><td>${equipmentPlanningCell(v.bmc_ip, c?.bmc_ip)}<span class="live-small live-code">${equipmentPlanningCell(v.bmc_mac, c?.bmc_mac)}</span></td><td>${equipmentPlanningCell(v.rack, c?.rack)}</td><td>${interfaces}</td><td>${badge(comparison.label, comparison.tone)}</td><td>${button("编辑规划", "planning-edit", false, `data-id="${esc(row.id)}"`)}</td></tr>`;
      }),
    ) +
    '<div class="live-note">按序列号与纳管设备对比。规划可随时编辑，在纳管设备中点击“一键匹配”后写入设备配置；机柜用于对比。</div>'
  );
}
async function equipmentPlanningReload() {
  await Promise.allSettled([
    readSection("equipmentPlanning", sectionReads.equipmentPlanning),
    readSection("equipment", sectionReads.equipment),
    readSection("resources", sectionReads.resources),
    readSection("network", sectionReads.network),
  ]);
  render();
}
function equipmentPlanningEdit(id) {
  const row = state.equipmentPlanning?.rows.find((r) => r.id === id);
  if (id && !row) throw Error("设备规划已变化，请刷新。");
  const ports = row ? equipmentPlanningPorts(row) : [];
  state.wizard = { resource: "equipment-planning-edit", row, ports };
  modal(
    row ? "编辑设备规划" : "新增设备规划",
    "按序列号关联，按 MAC 指定管理接口",
    `<div class="live-editor-grid">${equipmentPlanningFields.map(([key, label]) => inputField("planning-" + key, label, row?.values[key] || "", 'maxlength="128"')).join("")}</div><div class="live-note">管理子网填写 CIDR，例如 192.0.2.0/24。填写管理 IP 或子网时必须提供管理 MAC；该 MAC 出现在下方网卡列表时，请在对应网口编辑地址，上方自动同步。</div>` +
      (ports.length
        ? `<h3>主机网卡地址</h3>${table(
            ["MAC / PCIe", "IP", "子网 CIDR", "网关", "MTU"],
            ports.map(
              (p, i) =>
                `<tr><td class="live-code">${esc(p.mac)}<span class="live-small">${esc(p.pci_address || "PCIe 未采集")}</span></td>${["ip", "subnet", "gateway"].map((k) => `<td>${inputField(`planning-port-${i}-${k}`, { ip: "IP", subnet: "子网 CIDR", gateway: "网关" }[k], p[k], 'maxlength="128"')}</td>`).join("")}<td id="planning-port-${i}-mtu">${esc(equipmentPlanningMtu(p.subnet))}</td></tr>`,
            ),
          )}<div class="live-note">留空网口不修改已有配置。MTU 读取网络管理中的子网配置。网口地址保存到系统配置，下次安装生效；主启动接口保持不变。设备级字段仍通过“一键匹配”应用。</div>`
        : '<div class="live-note">尚无已采集网卡，请先获取设备信息或刷新硬件。</div>') +
      eqError(),
    button("取消", "close") + button("保存规划", "planning-save", true),
  );
  equipmentPlanningSyncManagement();
}
function equipmentPlanningSyncManagement() {
  const ports = state.wizard?.ports || [];
  const selected = $("#planning-management_mac")?.value.trim().toLowerCase();
  const index = ports.findIndex((p) => p.mac === selected);
  for (const [field, key] of [
    ["management_ip", "ip"],
    ["management_subnet", "subnet"],
  ]) {
    const input = $("#planning-" + field);
    if (!input) continue;
    input.readOnly = index >= 0;
    input.title = index >= 0 ? "请在下方对应 MAC 的网卡地址中编辑" : "";
    if (index >= 0) input.value = $(`#planning-port-${index}-${key}`).value;
  }
}
async function equipmentPlanningSave() {
  const row = state.wizard.row;
  const interfaces = (state.wizard.ports || []).map((p, i) => ({
    mac: p.mac,
    ...Object.fromEntries(
      ["ip", "subnet", "gateway"].map((k) => [
        k,
        $(`#planning-port-${i}-${k}`).value.trim(),
      ]),
    ),
  }));
  const values = Object.fromEntries(
    equipmentPlanningFields.map(([key]) => [
      key,
      $("#planning-" + key).value.trim(),
    ]),
  );
  const management = interfaces.find(
    (p) => p.mac === values.management_mac.toLowerCase() && p.ip,
  );
  if (management) {
    values.management_ip = management.ip;
    values.management_subnet = management.subnet;
  }
  const r = await api("/api/equipment-planning/save", {
    id: row?.id || "",
    revision: row?.revision || "",
    values,
    ...(interfaces.length ? { interfaces } : {}),
  });
  close();
  await equipmentPlanningReload();
  toast(r.status === "unchanged" ? "规划无变化。" : "设备规划已保存。");
}
function equipmentPlanningImport() {
  state.deviceView = "equipment-planning";
  render();
  state.wizard = { resource: "equipment-planning-import" };
  modal(
    "导入设备规划",
    "支持设备规划表，以及导出的设备网卡列表",
    '<div class="live-form"><a class="link-button" href="/api/equipment-planning/template">下载 CSV 模板</a><label class="live-upload">选择 Excel 或 CSV 文件<input id="planning-file" type="file" accept=".xlsx,.csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv"></label></div><div id="planning-preview"></div>' +
      '<div class="live-note">网卡表每行一个 MAC，填写 IP、子网 CIDR、网关；不使用的网口留空。PCIe 地址为采集信息，导入不会覆盖。子网需已在网络管理中配置。主启动接口保持不变，默认路由只使用管理口；其他网关只保存，不自动生成额外路由。已纳管设备直接保存到系统配置，未纳管设备在确认纳管后带入；均在下次安装时生效。</div>' +
      eqError(),
    button("取消", "close") + button("校验并预览", "planning-preview", true),
  );
}
async function equipmentPlanningPreview() {
  const file = $("#planning-file").files[0];
  if (!file || !/\.(csv|xlsx)$/i.test(file.name))
    throw Error("请选择设备规划 Excel 或 CSV 文件。");
  if (file.size > 1024 * 1024) throw Error("文件最大1 MiB。");
  const marker = state.wizard;
  let payload;
  if (/\.xlsx$/i.test(file.name)) {
    const bytes = new Uint8Array(await file.arrayBuffer());
    let binary = "";
    for (let i = 0; i < bytes.length; i += 8192)
      binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
    payload = { xlsx: btoa(binary) };
  } else payload = { csv: await file.text() };
  const r = await api("/api/equipment-planning/preview", payload);
  if (state.wizard !== marker) return;
  marker.preview_id = r.preview_id;
  $("#planning-preview").innerHTML =
    (r.counts.invalid
      ? `<div class="live-error">校验未通过，本批尚未导入或保存。${r.format === "interfaces" && r.failed_devices?.length ? `失败设备 ${r.failed_devices.length} 台；请按下表 SN、MAC 和原因修正后重新预览。` : "请修正下表错误后重新预览。"}</div>`
      : '<div class="live-note">校验通过；点击“保存导入规划”后才会写入。</div>') +
    `<div class="live-note">待新增 ${r.counts.create} · 待更新 ${r.counts.update} · 无变化 ${r.counts.unchanged} · 校验失败 ${r.counts.invalid}${r.format === "interfaces" ? ` · 跳过空白网口 ${r.skipped}` : ""}</div>` +
    table(
      ["行号", "SN", "操作", "说明"],
      r.rows.map(
        (row) =>
          `<tr><td>${esc(row.line)}</td><td>${esc(row.serial)}</td><td>${esc(row.operation === "invalid" && r.format === "interfaces" ? "导入校验失败" : equipmentPlanningStates[row.operation])}</td><td>${esc(row.detail || [row.values?.management_ip, row.values?.management_subnet, row.values?.bmc_ip].filter(Boolean).join(" / "))}${(row.interfaces || []).map((p) => `<span class="live-small">MAC ${esc(p.mac)} → IP ${esc(p.ip || "空")} · 子网 ${esc(p.subnet || "空")} · 网关 ${esc(p.gateway || "空")}</span>`).join("")}</td></tr>`,
      ),
    );
  $(".modal-footer").innerHTML =
    button("取消", "close") +
    (r.preview_id
      ? button("保存导入规划", "planning-import-apply", true)
      : button("重新预览", "planning-preview", true));
  $("#planning-file").disabled = !!r.preview_id;
}
async function equipmentPlanningImportApply() {
  const r = await api("/api/equipment-planning/import", {
    preview_id: state.wizard.preview_id,
  });
  close();
  await equipmentPlanningReload();
  toast(
    r.format === "interfaces"
      ? `已保存 ${r.count} 台设备的网卡信息；已纳管设备可在系统配置中查看。`
      : `已保存 ${r.count} 条设备规划。`,
  );
}

async function equipmentExportInterfaces() {
  const discovery = state.deviceView === "equipment-endpoints";
  if (
    !discovery &&
    equipmentSelectedDevices().length !== state.equipmentDeviceSelection.length
  )
    throw Error("所选设备已变化，请刷新后重新选择。");
  const ids = discovery
    ? [...state.equipmentDiscoverySelection]
    : equipmentSelectedServers().map((d) => d.id);
  if (!ids.length || ids.length > 50)
    throw Error("一次请选择1–50台服务器导出设备网卡列表。");
  const r = await api("/api/equipment-planning/export-interfaces", { ids });
  const data = Uint8Array.from(atob(r.xlsx), (c) => c.charCodeAt(0));
  const url = URL.createObjectURL(
    new Blob([data], {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = "device-interfaces.xlsx";
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  toast(
    `已导出 ${r.count} 个主机网口，含 PCIe 和已保存地址；填写后可用原入口导入。`,
  );
}
async function equipmentPlanningMatch() {
  if (state.equipmentPlanningMatching) return;
  const selected = state.equipment.devices.filter((d) =>
    state.equipmentDeviceSelection.includes(d.id),
  );
  if (selected.length !== state.equipmentDeviceSelection.length)
    throw Error("所选设备已变化，请刷新后重新选择。");
  if (!selected.length || selected.length > 50)
    throw Error("一次请选择1–50台纳管服务器。");
  const selections = selected.map((d) => {
    if (d.kind !== "server" || d.address_only)
      throw Error("一键匹配仅支持纳管服务器。");
    const plan = state.equipmentPlanning?.rows.find(
      (r) => r.values.serial === d.serial,
    );
    const device = state.resources?.devices.find((r) => r.serial === d.serial);
    return {
      serial: d.serial,
      device_id: d.id,
      device_revision: device?.plan_revision || "",
      plan_id: plan?.id || "",
      plan_revision: plan?.revision || "",
    };
  });
  const marker = { resource: "equipment-planning-match" };
  state.wizard = marker;
  modal(
    "一键匹配",
    "按序列号匹配并保存设备地址规划",
    '<div class="live-empty">正在核对规划与管理接口…</div>' + eqError(),
    button("关闭", "close"),
  );
  state.equipmentPlanningMatching = true;
  render();
  let r;
  try {
    r = await api("/api/equipment-planning/match", {
      selections,
      network_revisions: Object.fromEntries(
        (state.networks?.networks || []).map((n) => [n.id, n.revision]),
      ),
    });
    await equipmentPlanningReload();
  } finally {
    state.equipmentPlanningMatching = false;
    render();
  }
  const summary = `已保存 ${r.counts.saved} · 无变化 ${r.counts.unchanged} · 未匹配 ${r.counts.failed}`;
  if (state.wizard !== marker) return toast(summary);
  modal(
    "匹配结果",
    summary,
    table(
      ["SN", "结果", "配置变化 / 原因"],
      r.rows.map(
        (row) =>
          `<tr><td>${esc(row.serial)}</td><td>${badge(equipmentPlanningStates[row.status], row.status === "failed" ? "red" : "green")}</td><td>${row.changes.length ? row.changes.map((c) => `<div>${esc(c.field)}：${esc(c.before || "未配置")} → ${esc(c.after || "未配置")}</div>`).join("") : esc(row.detail)}</td></tr>`,
      ),
    ) +
      '<div class="live-note">BMC 地址通过“更新 BMC 地址”生效；主机管理配置由安装任务应用。</div>' +
      eqError(),
    button("关闭", "close"),
  );
}
observeUI("input", "equipment_planning.js", (event) => {
  if (
    state.wizard?.resource === "equipment-planning-edit" &&
    (event.target.id.startsWith("planning-port-") ||
      event.target.id === "planning-management_mac")
  )
    equipmentPlanningSyncManagement();
  const subnet = /^planning-port-(\d+)-subnet$/.exec(event.target.id);
  if (subnet) {
    $(`#planning-port-${subnet[1]}-mtu`).textContent = equipmentPlanningMtu(
      event.target.value.trim(),
    );
    return;
  }
  if (event.target.id !== "planning-search") return;
  const position = event.target.selectionStart;
  state.equipmentPlanningSearch = event.target.value;
  render();
  $("#planning-search").focus();
  $("#planning-search").setSelectionRange(position, position);
});
registerActions(
  "equipment_planning.js",
  [
    "planning-tab",
    "planning-refresh",
    "planning-new",
    "planning-edit",
    "planning-save",
    "planning-import",
    "planning-template",
    "planning-preview",
    "planning-import-apply",
    "planning-match",
  ],
  async (event) => {
    const el = event.target.closest("[data-live]");
    switch (el.dataset.live) {
      case "planning-tab":
        state.deviceView = "equipment-planning";
        render();
        return equipmentPlanningReload();
      case "planning-refresh":
        return equipmentPlanningReload();
      case "planning-new":
        return equipmentPlanningEdit();
      case "planning-edit":
        return equipmentPlanningEdit(el.dataset.id);
      case "planning-save":
        return busy(equipmentPlanningSave);
      case "planning-import":
        return equipmentPlanningImport();
      case "planning-template":
        window.location.href = "/api/equipment-planning/template";
        return;
      case "planning-preview":
        return busy(equipmentPlanningPreview);
      case "planning-import-apply":
        return busy(equipmentPlanningImportApply);
      case "planning-match":
        return busy(equipmentPlanningMatch);
    }
  },
);
