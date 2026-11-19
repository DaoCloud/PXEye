"use strict";
// Per-kind device pages. They read the same equipment list as 设备管理 and add the
// operational state NICo Core reports; enrollment, addresses and editing stay in
// the existing dialogs, which these pages open rather than reimplement.
const deviceStatusPages = {
  servers: {
    kind: "server",
    label: "服务器",
    description: "查看纳管服务器的运行状态、健康和硬件校验结果。",
    source: "servers",
  },
  switches: {
    kind: "switch",
    label: "交换机",
    description: "查看 NVLink 交换机的运行状态、健康和管理口。",
    source: "switches",
  },
  power_shelves: {
    kind: "power_shelf",
    label: "供电框",
    description: "查看供电框的运行状态、健康和供电规格。",
    source: "power_shelves",
  },
};
const deviceStatusHealth = {
  ok: ["正常", "green"],
  warning: ["告警", "amber"],
  alert: ["告警", "amber"],
  critical: ["严重", "red"],
  unknown: ["未报告", "gray"],
};
state.deviceStatus = null;
state.rackOperations = false;
state.deviceStatusFilters = { rack: "", status: "", search: "" };
sectionReads.deviceStatus = async () => {
  state.deviceStatus = await api("/api/device-status");
};
async function deviceStatusReload() {
  await Promise.allSettled(
    ["resources", "equipment", "deviceStatus"].map((key) =>
      readSection(key, sectionReads[key]),
    ),
  );
}
const deviceStatusTime = (value) =>
  value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "—";
// A server is matched to its Core machine by the machine the console already
// associated with it, then by BMC MAC; the other kinds carry their native ID.
function deviceStatusReported(page, d) {
  const rows = state.deviceStatus?.[page.source] || {};
  if (page.kind !== "server") return rows[d.native_id] || null;
  const native = state.resources?.devices.find((x) => x.serial === d.serial);
  if (native?.machine_id && rows[native.machine_id])
    return rows[native.machine_id];
  const macs = d.ports
    .filter((p) => p.role === "host_bmc")
    .map((p) => p.mac_address);
  return (
    Object.values(rows).find(
      (row) => row.type !== "dpu" && row.bmc.mac && macs.includes(row.bmc.mac),
    ) || null
  );
}
function deviceStatusLifecycle(reported, d) {
  if (!reported)
    return (
      badge("未报告") +
      `<span class="live-small">${esc(d.kind === "server" ? "" : (equipmentStates[d.status] || d.status) + " · ")}NICo 尚未建立设备对象</span>`
    );
  const life = reported.lifecycle,
    tone =
      life.outcome === "error" ? "red" : life.above_sla ? "amber" : "green";
  return (
    badge(life.state || "未报告", life.state ? tone : "gray") +
    (life.above_sla ? '<span class="live-small">超出状态时限</span>' : "") +
    (life.reason ? `<span class="live-small">${esc(life.reason)}</span>` : "")
  );
}
function deviceStatusHealthBadge(reported) {
  if (!reported) return badge("未报告");
  const [label, tone] =
      deviceStatusHealth[reported.health.level] || deviceStatusHealth.unknown,
    count = reported.health.alerts.length;
  return badge(count ? `${label} · ${count}` : label, tone);
}
const deviceStatusAlerting = (reported) =>
  ["warning", "alert", "critical"].includes(reported?.health.level);
// Core's own signals, not a reading of its state vocabulary: the last handler
// run failed, the state outlived its time limit, or a health probe is alerting.
const deviceStatusAttention = (reported) =>
  !!reported &&
  (reported.lifecycle.outcome === "error" ||
    reported.lifecycle.above_sla ||
    deviceStatusAlerting(reported));
function deviceStatusPlacement(d, reported) {
  const rack = d.rack_id || reported?.rack_id;
  if (!rack)
    // The rack is declared, not discovered; the existing editors own that field.
    return d.kind === "server"
      ? `<button class="link-button" data-live="device-edit" ${eqAttr(d.legacy_id)}>填写机柜</button>`
      : `<button class="link-button" data-live="eq-edit" ${eqAttr(d.id)}>填写机柜</button>`;
  const place = reported?.placement || {},
    parts = [
      place.slot != null ? `槽位 ${place.slot}` : "",
      place.tray != null ? `托盘 ${place.tray}` : "",
    ].filter(Boolean);
  return (
    esc(rack) +
    (parts.length
      ? `<span class="live-small">${esc(parts.join(" · "))}</span>`
      : "")
  );
}
function deviceStatusUplinks(reported) {
  const ports = {};
  for (const n of reported?.lldp || []) {
    const name = n.switch || n.switch_id;
    if (name) ports[name] = (ports[name] || 0) + 1;
  }
  return Object.keys(ports).length
    ? Object.entries(ports)
        .map(
          ([name, count]) =>
            `${esc(name)}<span class="live-small">${count} 个接口</span>`,
        )
        .join("")
    : "—";
}
function deviceStatusMatches(page, d, reported) {
  const f = state.deviceStatusFilters;
  return (
    (!f.rack || (f.rack === "-" ? !d.rack_id : d.rack_id === f.rack)) &&
    (!f.status ||
      (f.status === "attention"
        ? deviceStatusAttention(reported)
        : f.status === "alerting"
          ? deviceStatusAlerting(reported)
          : !reported)) /* absent */ &&
    (!f.search ||
      [
        d.serial,
        d.name,
        reported?.lifecycle.state,
        ...(reported?.lldp || []).map((n) => n.switch),
        ...d.ports.flatMap((p) => [
          p.mac_address,
          p.target_ip,
          ...(p.observed || []).flatMap((o) => o.addresses),
        ]),
      ]
        .join(" ")
        .toLowerCase()
        .includes(f.search.toLowerCase()))
  );
}
function deviceStatusFabricManager(fm) {
  if (!fm || (!fm.state && !fm.summary)) return "—";
  return (
    badge(
      { ok: "正常", not_ok: "异常", unknown: "未知" }[fm.state] || fm.summary,
      fm.state === "ok" ? "green" : fm.state === "not_ok" ? "red" : "gray",
    ) + (fm.reason ? `<span class="live-small">${esc(fm.reason)}</span>` : "")
  );
}
function deviceStatusColumns(page) {
  if (page.kind === "server")
    return [
      ["上联交换机", (d, i) => deviceStatusUplinks(i)],
      ["SKU", (d, i) => esc(i?.sku.id || "—")],
      [
        "BMC 固件",
        (d, i) => esc(i?.bmc.firmware_version || i?.bmc.version || "—"),
      ],
    ];
  if (page.kind === "switch")
    return [
      [
        "NVOS 管理口",
        (d, i) => {
          const ports = i?.nvos_ports || [];
          return ports.length
            ? ports
                .map(
                  (p) =>
                    `${esc(p.addresses.join(", ") || "未获取地址")}<span class="live-small">${esc(p.mac)}${p.primary ? " · primary" : ""}</span>`,
                )
                .join("")
            : "—";
        },
      ],
      [
        "Fabric Manager",
        (d, i) => deviceStatusFabricManager(i?.fabric_manager),
      ],
      [
        "BMC 固件",
        (d, i) => esc(i?.bmc.firmware_version || i?.bmc.version || "—"),
      ],
    ];
  return [
    [
      "容量 / 电压",
      (d, i) =>
        i && (i.capacity_watts != null || i.voltage != null)
          ? esc(
              [
                i.capacity_watts != null ? `${i.capacity_watts} W` : "",
                i.voltage != null ? `${i.voltage} V` : "",
              ]
                .filter(Boolean)
                .join(" · "),
            )
          : "—",
    ],
    [
      "BMC 固件",
      (d, i) => esc(i?.bmc.firmware_version || i?.bmc.version || "—"),
    ],
  ];
}
function deviceStatusPage(name) {
  const page = deviceStatusPages[name];
  if (!state.rackOperations)
    return (
      heading(page.label, page.description) +
      '<div class="live-empty">此页面未在当前站点启用。</div>'
    );
  let body = heading(
    page.label,
    page.description,
    button("刷新数据", "device-status-refresh") +
      `<button class="button" data-page="devices">前往设备管理</button>`,
  );
  const data = state.equipment,
    reports = state.deviceStatus;
  const errors = [
    state.readErrors?.equipment,
    state.readErrors?.deviceStatus,
    ...(reports?.errors || []),
  ].filter(Boolean);
  if (errors.length)
    body += `<div class="live-error" role="alert">${esc([...new Set(errors)].join("；"))}</div>`;
  if (!data || !reports)
    return (
      body +
      (errors.length
        ? ""
        : '<div class="live-empty">正在读取设备与运行状态…</div>')
    );
  const all = data.devices
      .filter((d) => d.kind === page.kind && !d.address_only)
      .map((d) => [d, deviceStatusReported(page, d)]),
    visible = all.filter(([d, i]) => deviceStatusMatches(page, d, i)),
    f = state.deviceStatusFilters,
    unracked = all.filter(([d]) => !d.rack_id).length;
  if (!all.length && page.kind !== "server")
    return (
      body +
      `<div class="live-note">${
        page.kind === "switch"
          ? "NICo 中没有 NVLink 交换机。此页面只显示由 NICo 纳管的 NVLink 交换机；通用以太网交换机不由 NICo 管理，可在服务器的运行状态中查看其 LLDP 邻居。"
          : "NICo 中没有供电框。此页面只显示由 NICo 纳管的供电框；机柜 PDU 不由 NICo 管理。"
      }在设备管理中纳管后，设备会出现在这里。</div>`
    );
  body += `<div class="summary-strip device-status-summary"><div><small>设备总数</small><strong>${all.length}</strong></div><div><small>NICo 已建立对象</small><strong>${all.filter(([, i]) => i).length}</strong></div><div><small>需要处理</small><strong>${all.filter(([, i]) => deviceStatusAttention(i)).length}</strong></div><div><small>未填写机柜</small><strong>${unracked}</strong></div></div>`;
  if (unracked)
    body += `<div class="live-note live-warning">${unracked} 台设备未填写机柜，不会出现在机柜拓扑的机柜分组里。机柜由人工声明，NICo 不会自动发现；在“机柜 / 位置”列点击“填写机柜”。</div>`;
  body += `<div class="equipment-device-filters">${selectField("device-status-filter-rack", "机柜", [["", "全部机柜"], ...(unracked ? [["-", "未填写机柜"]] : []), ...[...new Set(all.map(([d]) => d.rack_id).filter(Boolean))].map((id) => [id, id])], f.rack)}${selectField(
    "device-status-filter-status",
    "状态",
    [
      ["", "全部"],
      ["attention", "需要处理"],
      ["alerting", "有健康告警"],
      ["absent", "NICo 未建立对象"],
    ],
    f.status,
  )}${inputField("device-status-filter-search", "搜索 SN、名称、状态、交换机、MAC 或 IP", f.search)}</div>`;
  // A column no device has a value for says nothing; leave it out.
  const columns = deviceStatusColumns(page).filter(([, cell]) =>
    all.some(([d, i]) => cell(d, i) !== "—"),
  );
  const rows = visible.map(([d, i]) => {
    const native = state.resources?.devices.find((x) => x.serial === d.serial),
      task =
        page.kind === "server"
          ? state.tasks.find((t) => t.device === d.serial)
          : null,
      open =
        page.kind === "server"
          ? `data-live="device-detail" data-serial="${esc(d.serial)}"`
          : `data-live="eq-detail" ${eqAttr(d.id)}`;
    return `<tr><td><button class="link-button" ${open}>${esc(d.name || d.serial || d.id)}</button><span class="live-small">${esc(d.serial)}</span></td><td>${deviceStatusPlacement(d, i)}</td><td>${equipmentBmcAddresses(d, native)}</td><td>${deviceStatusLifecycle(i, d)}</td><td>${deviceStatusHealthBadge(i)}</td><td>${equipmentOnline(d)}</td>${columns.map(([, cell]) => `<td>${cell(d, i)}</td>`).join("")}<td><div class="device-row-actions">${button("运行状态", "device-status-open", false, `${eqAttr(d.id)} data-device-status="${esc(name)}"`)}${task ? `<button class="button" data-task="${esc(task.id)}">安装任务</button>` : ""}${button("地址管理", "address-device", false, eqAttr(d.id))}</div></td></tr>`;
  });
  return (
    body +
    table(
      [
        "设备 / SN",
        "机柜 / 位置",
        "BMC 地址",
        "运行状态",
        "健康",
        "电源",
        ...columns.map(([title]) => title),
        "操作",
      ],
      rows,
    ) +
    `<p class="live-small">运行状态由 NICo 状态机回报，读取于 ${esc(when(reports.observed_at))}。“需要处理”指状态机最近一次处理失败、超出状态时限或有健康告警。设备的纳管、地址和安装规划在设备管理中维护。</p>`
  );
}
function deviceStatusStatus(name, id) {
  const page = deviceStatusPages[name],
    d = state.equipment?.devices.find((x) => x.id === id);
  if (!page || !d) throw Error("设备归属已变化，请刷新。");
  const i = deviceStatusReported(page, d);
  const w = { resource: "device-status", device: d };
  state.wizard = w;
  const foot =
    button("关闭", "close") +
    (page.kind === "server"
      ? button(
          "硬件详情",
          "device-detail",
          false,
          `data-serial="${esc(d.serial)}"`,
        )
      : button("设备详情", "eq-detail", false, eqAttr(d.id)));
  if (!i)
    return modal(
      d.name || d.serial || "运行状态",
      page.label,
      `<div class="live-empty">NICo 尚未为此设备建立对象，当前纳管状态为“${esc(equipmentStates[d.status] || d.status)}”。完成发现和纳管后，这里会显示状态机回报的运行状态。</div>`,
      foot,
    );
  const life = i.lifecycle,
    [healthLabel, healthTone] =
      deviceStatusHealth[i.health.level] || deviceStatusHealth.unknown;
  let body =
    defs([
      ["NICo 对象 ID", esc(i.id)],
      ["机柜 / 位置", deviceStatusPlacement(d, i)],
      ["运行状态", deviceStatusLifecycle(i, d)],
      ["电源", equipmentOnline(d)],
      ["BMC 地址", esc(i.bmc.ip || "—")],
      ["BMC 固件", esc(i.bmc.firmware_version || i.bmc.version || "—")],
      [
        "健康",
        badge(healthLabel, healthTone) +
          (i.health.observed_at
            ? `<span class="live-small">观测于 ${esc(deviceStatusTime(i.health.observed_at))}${i.health.source ? " · " + esc(i.health.source) : ""}</span>`
            : ""),
      ],
    ]) +
    "<h3>健康告警</h3>" +
    table(
      ["探针", "对象", "说明", "开始时间"],
      i.health.alerts.map(
        (a) =>
          `<tr><td>${esc(a.id)}</td><td>${esc(a.target || "—")}</td><td>${esc(a.message)}</td><td>${esc(deviceStatusTime(a.since))}</td></tr>`,
      ),
    );
  if (page.kind === "server") {
    const caps = Object.entries(i.capabilities);
    body +=
      defs([
        ["SKU", esc(i.sku.id || "未分配")],
        ["SKU 最近比对", esc(deviceStatusTime(i.sku.last_match_attempt))],
        [
          "隔离",
          i.quarantine
            ? badge("已隔离", "red") +
              `<span class="live-small">${esc(i.quarantine.reason || i.quarantine.mode)}</span>`
            : "未隔离",
        ],
        ["维护标记", esc(i.maintenance || "—")],
        ["关联 DPU", esc(i.dpu_ids.join(", ") || "—")],
        ["最近重启", esc(deviceStatusTime(i.last_reboot))],
        ["Scout 版本", esc(i.scout_version || "—")],
        ...(i.failure ? [["故障详情", esc(i.failure)]] : []),
      ]) +
      "<h3>硬件能力</h3>" +
      table(
        ["类别", "型号", "数量", "容量"],
        caps.flatMap(([kind, items]) =>
          items.map(
            (c) =>
              `<tr><td>${esc(kind.toUpperCase())}</td><td>${esc(c.name)}<span class="live-small">${esc(c.vendor)}</span></td><td>${esc(c.count)}</td><td>${esc(c.capacity || "—")}</td></tr>`,
          ),
        ),
      ) +
      (i.id
        ? '<h3>状态时间线</h3><div id="device-status-history"><p class="live-small">正在读取状态记录…</p></div>'
        : "") +
      "<h3>LLDP 邻居</h3>" +
      table(
        ["本机接口", "邻居交换机", "邻居端口", "交换机 SN"],
        i.lldp.map(
          (n) =>
            `<tr><td>${esc(n.local_port || "—")}<span class="live-small">${esc(n.mac_address)}</span></td><td>${esc(n.switch || n.switch_id || "—")}<span class="live-small">${esc(n.switch_model)}</span></td><td>${esc(n.remote_port || "—")}</td><td>${esc(n.switch_serial || "—")}</td></tr>`,
        ),
      ) +
      '<h3>固件</h3><div id="device-status-firmware" aria-live="polite"><div class="live-empty">正在读取固件清单…</div></div>';
  }
  if (page.kind === "switch")
    body +=
      defs([
        ["主交换机", i.primary ? "是" : "否"],
        ["NVLink 域", esc(i.nvlink_domain || "—")],
        ["NMX-C", i.nmxc_enabled ? "已启用" : "未启用"],
        ["Fabric Manager", deviceStatusFabricManager(i.fabric_manager)],
      ]) +
      "<h3>NVOS 管理口</h3>" +
      table(
        ["MAC", "地址", "角色", "服务端口"],
        i.nvos_ports.map(
          (p) =>
            `<tr><td>${esc(p.mac)}</td><td>${esc(p.addresses.join(", ") || "未获取地址")}</td><td>${p.primary ? "primary" : "—"}</td><td>${esc(p.service_port ?? "—")}</td></tr>`,
        ),
      );
  if (page.kind === "power_shelf")
    body += defs([
      ["容量", esc(i.capacity_watts != null ? `${i.capacity_watts} W` : "—")],
      ["电压", esc(i.voltage != null ? `${i.voltage} V` : "—")],
      ["NVLink 域", esc(i.nvlink_domain || "—")],
    ]);
  modal(
    d.name || d.serial || "运行状态",
    page.label + " · 运行状态",
    body,
    foot,
  );
  if (page.kind === "server" && i.id) {
    deviceStatusReadHistory(w, i.id);
    deviceStatusFirmwareRead(w, i.id);
  }
}
// Whole units, largest first, two at most: “3 天 4 小时”, “12 分钟 5 秒”.
function deviceStatusDuration(seconds) {
  let rest = Math.max(0, Math.floor(Number(seconds) || 0));
  const parts = [];
  for (const [size, unit] of [
    [86400, "天"],
    [3600, "小时"],
    [60, "分钟"],
    [1, "秒"],
  ]) {
    if (rest >= size || (size === 1 && !parts.length))
      parts.push(`${Math.floor(rest / size)} ${unit}`);
    rest %= size;
  }
  return parts.slice(0, 2).join(" ");
}
function deviceStatusHistoryTable(data) {
  if (!data.records.length)
    return '<p class="live-small">NICo 没有这台机器的状态记录。</p>';
  return (
    table(
      ["状态", "进入时间", "停留时长"],
      data.records.map(
        (r) =>
          `<tr><td><code>${esc(r.state || "—")}</code>${r.current ? " " + badge("当前", "amber") : ""}</td><td>${esc(deviceStatusTime(r.entered_at))}</td><td>${esc(deviceStatusDuration(r.duration_seconds))}${r.current ? '<span class="live-small">至读取时</span>' : ""}</td></tr>`,
      ),
    ) +
    `<p class="live-small">状态记录由 NICo 状态机保存，读取于 ${esc(when(data.observed_at))}。</p>`
  );
}
// The dialog may have closed or moved to another device while Core answered;
// only the dialog that asked writes into its own section.
async function deviceStatusReadHistory(w, machineId) {
  let html;
  try {
    const data = await api(
      "/api/device-status/machines/" +
        encodeURIComponent(machineId) +
        "/history",
    );
    html = deviceStatusHistoryTable(data);
  } catch (e) {
    html = `<div class="live-error" role="alert">状态记录读取失败：${esc(e.message)}</div>`;
  }
  const section = $("#device-status-history");
  if (state.wizard !== w || !section) return;
  section.innerHTML = html;
}
// The firmware inventory is read per machine after the dialog opens, and only
// written into it while the same dialog is still the one on screen.
async function deviceStatusFirmwareRead(w, machineId) {
  const place = () =>
    state.wizard === w ? $("#device-status-firmware") : null;
  if (!/^[a-z0-9]{1,128}$/.test(machineId || "")) {
    if (place())
      place().innerHTML =
        '<div class="live-note">此设备的 NICo 机器 ID 无法用于读取固件清单。</div>';
    return;
  }
  let html;
  try {
    const data = await api(
      "/api/device-status/machines/" +
        encodeURIComponent(machineId) +
        "/firmware",
    );
    html = deviceStatusFirmware(data);
  } catch (e) {
    html = `<div class="live-error" role="alert">固件清单读取失败：${esc(e.message)}</div>`;
  }
  if (place()) place().innerHTML = html;
}
function deviceStatusFirmware(data) {
  if (!data.reported)
    return `<div class="live-note">${esc(data.note || "NICo 没有此机器的固件清单。")}</div>`;
  const c = data.chassis,
    sb = data.secure_boot,
    secureBoot =
      sb && Object.keys(sb).length
        ? Object.entries(sb)
            .map(
              ([k, v]) =>
                `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`,
            )
            .join(" · ")
        : "未报告";
  return (
    defs([
      [
        "机型",
        esc(c.model || "—") +
          (c.manufacturer || data.vendor
            ? `<span class="live-small">${esc(c.manufacturer || data.vendor)}</span>`
            : ""),
      ],
      ["部件号", `<span class="live-code">${esc(c.part_number || "—")}</span>`],
      ["锁定状态", esc(data.lockdown || "未报告")],
      ["安全启动", esc(secureBoot)],
    ]) +
    table(
      ["部件", "版本", "发布日期"],
      data.entries.map(
        (f) =>
          `<tr><td>${esc(f.description || f.id)}<span class="live-small live-code">${esc(f.id)}</span></td><td>${esc(f.version || "—")}</td><td>${esc(f.release_date ? f.release_date.slice(0, 10) : "—")}</td></tr>`,
      ),
    ) +
    `<p class="live-small">来自 NICo 站点发现的 BMC 探测报告（GetComponentInventory），共 ${data.entries.length} 项，读取于 ${esc(when(data.observed_at))}。</p>`
  );
}
registerPage("servers", () => deviceStatusPage("servers"));
registerPage("switches", () => deviceStatusPage("switches"));
registerPage("power_shelves", () => deviceStatusPage("power_shelves"));
registerActions(
  "device_status.js",
  ["device-status-refresh", "device-status-open"],
  async (e) => {
    const el = e.target.closest('[data-live^="device-status-"]');
    if (!el || el.disabled) return;
    if (el.dataset.live === "device-status-refresh")
      return await deviceStatusReload();
    return deviceStatusStatus(el.dataset.deviceStatus, el.dataset.id);
  },
);
observeUI(
  "change",
  "device_status.js",
  (e) => {
    if (e.target.id?.startsWith("device-status-filter-")) {
      state.deviceStatusFilters[e.target.id.slice(21)] = e.target.value;
      render();
    }
  },
  false,
);
observeUI(
  "input",
  "device_status.js",
  (e) => {
    if (e.target.id === "device-status-filter-search") {
      const position = e.target.selectionStart;
      state.deviceStatusFilters.search = e.target.value;
      render();
      $("#device-status-filter-search").focus();
      $("#device-status-filter-search").setSelectionRange(position, position);
    }
  },
  false,
);
// The pages join the navigation only where the site enables them, so a site
// without the setting keeps exactly the navigation it had.
// Second-level pages under 设备管理, in navigation order. Other rack operations
// page scripts add theirs with deviceStatusAddNavChild; each says how to reload.
const deviceStatusNavChildren = Object.entries(deviceStatusPages).map(
  ([name, page]) => ({ name, label: page.label, reload: deviceStatusReload }),
);
function deviceStatusAddNavChild(name, label, reload) {
  deviceStatusNavChildren.push({ name, label, reload });
}
const deviceStatusNavChild = (name) =>
  deviceStatusNavChildren.find((child) => child.name === name);
registerHook("readiness", (readiness) => {
  state.rackOperations = readiness?.rack_operations === true;
  if (!state.rackOperations) return;
  const group = groups.find(([, pages]) => pages.includes("devices"));
  deviceStatusNavChildren.forEach((child, index) => {
    labels[child.name] = child.label;
    if (group && !group[1].includes(child.name))
      group[1].splice(group[1].indexOf("devices") + index + 1, 0, child.name);
  });
  // A reload lands here before the navigation knew these pages existed.
  const child = deviceStatusNavChild(location.hash.slice(1));
  if (child) {
    state.page = child.name;
    child.reload();
  }
});
window.addEventListener("hashchange", () => {
  const child =
    state.rackOperations && deviceStatusNavChild(location.hash.slice(1));
  if (!child) return;
  if (deviceStatusPages[child.name])
    state.deviceStatusFilters = { rack: "", status: "", search: "" };
  child.reload();
});
