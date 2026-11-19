"use strict";
// Which switch port each server interface is plugged into, as NICo Scout heard
// it over LLDP. It shows what was observed: there is no intended cabling to
// compare against yet, so nothing here is judged right or wrong except a port
// reported by more than one interface.
state.cablingFilters = { switch: "", search: "" };
const cablingPage = deviceStatusPages.servers;
// Switch names and panel port names the site supplied (PXEye's own table).
state.switchLabels = null;
state.cablingImport = null;
sectionReads.switchLabels = async () => {
  state.switchLabels = await api("/api/switch-labels");
};
async function cablingReload() {
  await Promise.allSettled(
    ["resources", "equipment", "deviceStatus", "switchLabels"].map((key) =>
      readSection(key, sectionReads[key]),
    ),
  );
}
// Lower-case colon form of a MAC, or "" when the value is not one.
function cablingMac(value) {
  const raw = String(value || "")
    .trim()
    .toLowerCase()
    .replace(/[:.-]/g, "");
  return /^[0-9a-f]{12}$/.test(raw) ? raw.match(/../g).join(":") : "";
}
const cablingPortId = (value) =>
  cablingMac(value) ||
  String(value || "")
    .trim()
    .toLowerCase();
function cablingLabelIndex(labels) {
  const switches = {},
    ports = {};
  for (const s of labels?.switches || [])
    switches[cablingMac(s.chassis_mac)] = s;
  for (const p of labels?.ports || [])
    ports[`${cablingMac(p.chassis_mac)}\u0000${cablingPortId(p.port_id)}`] = p;
  return { switches, ports };
}
const cablingSwitchLabel = (neighbor, index) =>
  index.switches[cablingMac(neighbor.switch_id)] || null;
const cablingPortLabel = (neighbor, index) =>
  index.ports[
    `${cablingMac(neighbor.switch_id)}\u0000${cablingPortId(neighbor.remote_port)}`
  ] || null;
// How many labels apply to what LLDP reported; the rest are unmatched.
function cablingLabelCounts(links, labels) {
  const index = cablingLabelIndex(labels),
    seenSwitches = new Set(links.map((l) => cablingMac(l.neighbor.switch_id))),
    seenPorts = new Set(
      links.map(
        (l) =>
          `${cablingMac(l.neighbor.switch_id)}\u0000${cablingPortId(l.neighbor.remote_port)}`,
      ),
    ),
    switchKeys = Object.keys(index.switches),
    portKeys = Object.keys(index.ports);
  return {
    switches: switchKeys.filter((k) => seenSwitches.has(k)).length,
    switchesUnmatched: switchKeys.filter((k) => !seenSwitches.has(k)).length,
    ports: portKeys.filter((k) => seenPorts.has(k)).length,
    portsUnmatched: portKeys.filter((k) => !seenPorts.has(k)).length,
  };
}
const cablingSwitchColumns = [
  "chassis_mac",
  "name",
  "model",
  "serial",
  "management_ip",
  "rack",
];
const cablingPortColumns = ["chassis_mac", "port_id", "port_name"];
function cablingCsvCell(value) {
  const text = String(value ?? "");
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}
function cablingCsv(columns, rows) {
  if (!rows?.length) return "";
  return [columns, ...rows.map((r) => columns.map((c) => r[c]))]
    .map((r) => r.map(cablingCsvCell).join(","))
    .join("\n");
}
// Every observed link, joined to the console's device and its Core machine.
function cablingLinks(servers) {
  return servers.flatMap(([d, reported]) =>
    (Array.isArray(reported?.lldp) ? reported.lldp : []).map((n) => ({
      device: d,
      reported,
      neighbor: n,
      switchKey: n.switch_id || n.switch || n.switch_serial || "",
    })),
  );
}
const cablingPortKey = (link) =>
  `${link.switchKey}\u0000${link.neighbor.remote_port || ""}`;
function cablingConflicts(links) {
  const seen = {};
  for (const link of links)
    if (link.switchKey && link.neighbor.remote_port)
      (seen[cablingPortKey(link)] ||= new Set()).add(
        `${link.device.serial}\u0000${link.neighbor.mac_address || link.neighbor.local_port}`,
      );
  return new Set(
    Object.entries(seen)
      .filter(([, sources]) => sources.size > 1)
      .map(([key]) => key),
  );
}
// Servers without LLDP data, split by whether NICo has a machine for them.
function cablingMissing(servers) {
  return {
    noMachine: servers.filter(([, i]) => !i).map(([d]) => d),
    noLldp: servers
      .filter(([, i]) => i && !(Array.isArray(i.lldp) && i.lldp.length))
      .map(([d]) => d),
  };
}
function cablingSwitches(links) {
  const switches = {};
  for (const link of links) (switches[link.switchKey] ||= []).push(link);
  return switches;
}
const cablingNameLimit = 20;
function cablingNames(list) {
  const shown = list
    .slice(0, cablingNameLimit)
    .map((d) => esc(d.name || d.serial))
    .join("、");
  return list.length > cablingNameLimit
    ? `${shown} 等 ${list.length} 台`
    : shown;
}
function cablingMatches(link) {
  const f = state.cablingFilters,
    n = link.neighbor,
    d = link.device;
  return (
    (!f.switch || link.switchKey === f.switch) &&
    (!f.search ||
      [
        d.serial,
        d.name,
        n.switch,
        n.switch_id,
        n.switch_serial,
        n.remote_port,
        n.local_port,
        n.mac_address,
      ]
        .join(" ")
        .toLowerCase()
        .includes(f.search.toLowerCase()))
  );
}
function cablingRow(link, conflict, index = { switches: {}, ports: {} }) {
  const d = link.device,
    n = link.neighbor,
    rack = d.rack_id || link.reported?.rack_id,
    label = cablingPortLabel(n, index);
  const port = label
    ? `<strong>${esc(label.port_name)}</strong><span class="live-small live-code">${esc(n.remote_port || "—")}${n.remote_port_type ? ` · ${esc(n.remote_port_type)}` : ""}</span>`
    : `<span class="live-code">${esc(n.remote_port || "—")}</span>${n.remote_port_type ? `<span class="live-small">${esc(n.remote_port_type)}</span>` : ""}`;
  return `<tr${conflict ? ' style="background: var(--red-soft)"' : ""}><td>${port}${conflict ? badge("端口冲突", "red") + '<span class="live-small">同一端口被多个网口报告</span>' : ""}</td><td><button class="link-button" data-live="device-detail" data-serial="${esc(d.serial)}">${esc(d.name || d.serial)}</button><span class="live-small">${esc(d.serial)}</span></td><td>${esc(n.local_port || "—")}<span class="live-small live-code">${esc(n.mac_address || "")}</span></td><td>${esc(rack || "—")}</td></tr>`;
}
function cablingSwitchTitle(first, index) {
  const label = cablingSwitchLabel(first, index);
  if (label)
    return {
      title: label.name,
      detail: [
        `LLDP ${[first.switch, first.switch_id].filter(Boolean).join(" ")}`,
        label.model || first.switch_model,
        label.serial || first.switch_serial
          ? `SN ${label.serial || first.switch_serial}`
          : "",
        label.management_ip ? `管理 IP ${label.management_ip}` : "",
        label.rack ? `机柜 ${label.rack}` : "",
      ].filter(Boolean),
    };
  return {
    title: first.switch || first.switch_id || "未报告名称的交换机",
    detail: [
      first.switch && first.switch_id ? first.switch_id : "",
      first.switch_model,
      first.switch_serial ? `SN ${first.switch_serial}` : "",
    ].filter(Boolean),
  };
}
function cablingSwitchBlock(
  key,
  links,
  conflicts,
  index = { switches: {}, ports: {} },
) {
  const { title, detail } = cablingSwitchTitle(links[0].neighbor, index);
  const rows = [...links]
    .sort((a, b) =>
      String(a.neighbor.remote_port || "").localeCompare(
        String(b.neighbor.remote_port || ""),
        undefined,
        { numeric: true },
      ),
    )
    .map((link) =>
      cablingRow(link, conflicts.has(cablingPortKey(link)), index),
    );
  return `<h3 style="margin: 20px 0 8px">${esc(title)}<span class="live-small">${esc(detail.join(" · "))}${detail.length ? " · " : ""}${links.length} 个网口</span></h3>${table(["交换机端口", "服务器", "服务器网口", "机柜"], rows)}`;
}
function cablingLabelLine(links) {
  if (state.readErrors?.switchLabels)
    return `<div class="live-error" role="alert">交换机信息读取失败：${esc(state.readErrors.switchLabels)}</div>`;
  const labels = state.switchLabels;
  if (!labels) return "";
  if (!labels.switches?.length && !labels.ports?.length)
    return '<p class="live-small" style="margin: 12px 0">尚未导入交换机信息；交换机名称和端口按 LLDP 报告的原样显示。</p>';
  const c = cablingLabelCounts(links, labels);
  return `<p class="live-small" style="margin: 12px 0">交换机信息：${c.switches} 台交换机、${c.ports} 个端口已对应到 LLDP${c.switchesUnmatched || c.portsUnmatched ? `；未匹配 ${c.switchesUnmatched} 台交换机、${c.portsUnmatched} 个端口` : ""}。最后保存于 ${esc(when(labels.updated))}。</p>`;
}
function cablingImportModal() {
  const draft = state.cablingImport,
    errors = draft.errors || [],
    tableName = { switches: "交换机表", ports: "端口表" };
  const errorList = errors.length
    ? `<div class="live-error" role="alert">未保存，请修正以下问题：<ul>${errors
        .map(
          (e) =>
            `<li>${esc(tableName[e.table] || "")}${e.line ? ` 第 ${e.line} 行` : ""}${e.field ? ` ${esc(e.field)}` : ""}：${esc(e.message)}</li>`,
        )
        .join("")}</ul></div>`
    : draft.error
      ? `<div class="live-error" role="alert">${esc(draft.error)}</div>`
      : "";
  const area = (id, label, columns, value) =>
    `<label>${esc(label)}<span class="live-small">列：<span class="live-code">${esc(columns.join(","))}</span></span><textarea class="input live-code" id="${id}" rows="10" spellcheck="false" style="display: block; width: 100%; box-sizing: border-box; margin-top: 6px">${esc(value)}</textarea></label>`;
  modal(
    "导入交换机信息",
    "交换机名称和面板端口名只保存在 PXEye 中，用于布线页显示，不写入 NICo。保存会替换两张表的全部内容；某张表留空即清空。",
    `${errorList}<div class="form-grid">${area("cabling-import-switches", "交换机表", cablingSwitchColumns, draft.switches)}${area("cabling-import-ports", "端口表", cablingPortColumns, draft.ports)}</div><p class="live-small">第一行必须是列名；chassis_mac 为交换机 LLDP 报告的机箱 MAC，大小写和分隔符不限。</p>`,
    `${button("取消", "close")}${button(draft.saving ? "正在保存…" : "保存", "cabling-import-save", true, draft.saving ? "disabled" : "")}`,
  );
}
async function cablingImportSave() {
  const draft = state.cablingImport;
  draft.switches = $("#cabling-import-switches").value;
  draft.ports = $("#cabling-import-ports").value;
  draft.saving = true;
  draft.errors = [];
  draft.error = "";
  cablingImportModal();
  try {
    const result = await fetch("/api/switch-labels", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": state.csrf || "",
      },
      body: JSON.stringify({
        switches_csv: draft.switches,
        ports_csv: draft.ports,
        revision: draft.revision,
      }),
      credentials: "same-origin",
    });
    const data = await result.json().catch(() => ({}));
    if (state.cablingImport !== draft) return;
    if (result.ok) {
      state.switchLabels = data;
      state.cablingImport = null;
      close();
      toast("交换机信息已保存。");
      render();
      return;
    }
    draft.errors = Array.isArray(data.errors) ? data.errors : [];
    draft.error =
      result.status === 409
        ? "交换机信息已被他人更新。请取消后刷新数据，再重新导入。"
        : data.error || "保存失败。";
  } catch (error) {
    if (state.cablingImport !== draft) return;
    draft.error = error.message;
  }
  draft.saving = false;
  cablingImportModal();
}
function cablingRender() {
  let body = heading(
    "布线",
    "按交换机查看服务器网口的实际连接，来自服务器发现时采集的 LLDP。",
    `${state.rackOperations && !document.body.classList.contains("read-only") ? button("导入交换机信息", "cabling-import-open") : ""}${button("刷新数据", "cabling-refresh")}`,
  );
  if (!state.rackOperations)
    return body + '<div class="live-empty">此页面未在当前站点启用。</div>';
  const reports = state.deviceStatus,
    errors = [
      state.readErrors?.equipment,
      state.readErrors?.deviceStatus,
      ...(reports?.errors || []),
    ].filter(Boolean);
  if (errors.length)
    body += `<div class="live-error" role="alert">${esc([...new Set(errors)].join("；"))}</div>`;
  if (!state.equipment || !reports)
    return (
      body +
      (errors.length
        ? ""
        : '<div class="live-empty">正在读取设备与 LLDP 数据…</div>')
    );
  const servers = (state.equipment.devices || [])
      .filter((d) => d.kind === "server" && !d.address_only)
      .map((d) => [d, deviceStatusReported(cablingPage, d)]),
    links = cablingLinks(servers),
    conflicts = cablingConflicts(links),
    { noMachine, noLldp } = cablingMissing(servers),
    switches = cablingSwitches(links),
    names = cablingNames,
    index = cablingLabelIndex(state.switchLabels);
  const notes =
    (noLldp.length
      ? `<div class="live-note">${noLldp.length} 台服务器在 NICo 中有机器对象但没有 LLDP 数据：${names(noLldp)}。</div>`
      : "") +
    (noMachine.length
      ? `<div class="live-note">${noMachine.length} 台服务器 NICo 尚未建立设备对象，没有 LLDP 数据：${names(noMachine)}。</div>`
      : "");
  const labelLine = cablingLabelLine(links);
  if (!links.length)
    return (
      body +
      labelLine +
      '<div class="live-note">还没有任何服务器的 LLDP 数据。LLDP 邻居由 NICo Scout 在服务器上运行时采集（服务器发现阶段）；服务器完成发现后，这里会按交换机显示它的网口连接。</div>' +
      notes
    );
  const f = state.cablingFilters;
  if (f.switch && !switches[f.switch]) f.switch = "";
  const ports = new Set(links.map(cablingPortKey)).size;
  body += `<div class="summary-strip device-status-summary"><div><small>交换机</small><strong>${Object.keys(switches).length}</strong></div><div><small>已连接网口</small><strong>${links.length}</strong></div><div><small>没有 LLDP 数据的服务器</small><strong>${noLldp.length + noMachine.length}</strong></div><div><small>端口冲突</small><strong>${conflicts.size}</strong></div></div>`;
  body += labelLine;
  if (conflicts.size)
    body += `<div class="live-note live-warning">${conflicts.size} 个交换机端口被多个服务器网口报告，已在表中标红；请核对实际接线或交换机端口配置。</div>`;
  body += `<div class="equipment-device-filters">${selectField(
    "cabling-filter-switch",
    "交换机",
    [
      ["", "全部交换机"],
      ...Object.entries(switches).map(([key, list]) => [
        key,
        cablingSwitchLabel(list[0].neighbor, index)?.name ||
          list[0].neighbor.switch ||
          key ||
          "未报告名称",
      ]),
    ],
    f.switch,
  )}${inputField("cabling-filter-search", "搜索服务器、交换机、端口或 MAC", f.search)}</div>`;
  const blocks = Object.entries(switches)
    .map(([key, list]) => [key, list.filter(cablingMatches)])
    .filter(([, list]) => list.length)
    .map(([key, list]) => cablingSwitchBlock(key, list, conflicts, index));
  body += blocks.length
    ? blocks.join("")
    : '<div class="live-empty">没有符合筛选条件的连接。</div>';
  return (
    body +
    notes +
    `<p class="live-small">此页显示观测到的连接，不是与布线规划的比对。LLDP 由 NICo Scout 在服务器上采集，读取于 ${esc(when(reports.observed_at))}；${ports} 个不同的交换机端口。端口按交换机报告的原样显示，类型为 mac 时端口值是交换机端口的 MAC 地址。</p>`
  );
}
registerPage("cabling", cablingRender);
deviceStatusAddNavChild("cabling", "布线", cablingReload);
registerActions(
  "cabling.js",
  ["cabling-refresh", "cabling-import-open", "cabling-import-save"],
  async (e) => {
    const el = e.target.closest(
      '[data-live="cabling-refresh"],[data-live="cabling-import-open"],[data-live="cabling-import-save"]',
    );
    if (!el || el.disabled) return;
    const action = el.dataset.live;
    if (action === "cabling-refresh") return await cablingReload();
    if (action === "cabling-import-save") return await cablingImportSave();
    if (document.body.classList.contains("read-only")) return;
    const labels = state.switchLabels || {};
    state.cablingImport = {
      switches: cablingCsv(cablingSwitchColumns, labels.switches),
      ports: cablingCsv(cablingPortColumns, labels.ports),
      revision: labels.revision || "",
      errors: [],
      error: "",
    };
    cablingImportModal();
  },
);
registerHook("modalClosed", () => {
  state.cablingImport = null;
});
observeUI(
  "change",
  "cabling.js",
  (e) => {
    if (e.target.id === "cabling-filter-switch") {
      state.cablingFilters.switch = e.target.value;
      render();
    }
  },
  false,
);
observeUI(
  "input",
  "cabling.js",
  (e) => {
    if (e.target.id === "cabling-filter-search") {
      const position = e.target.selectionStart;
      state.cablingFilters.search = e.target.value;
      render();
      $("#cabling-filter-search").focus();
      $("#cabling-filter-search").setSelectionRange(position, position);
    }
  },
  false,
);
