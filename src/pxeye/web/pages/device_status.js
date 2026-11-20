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
// U positions are kept by PXEye (NICo has none for a general server) and read
// only where the site enables rack operations.
state.rackUnits = null;
sectionReads.rackUnits = async () => {
  state.rackUnits = await api("/api/rack-units");
};
async function deviceStatusReload() {
  await Promise.allSettled(
    [
      "resources",
      "equipment",
      "deviceStatus",
      ...(state.rackOperations ? ["rackUnits"] : []),
    ].map((key) => readSection(key, sectionReads[key])),
  );
}
const deviceStatusUnitText = (p) =>
  p.height > 1 ? `U${p.unit}–U${p.unit + p.height - 1}` : `U${p.unit}`;
const deviceStatusUnit = (serial) =>
  (state.rackUnits?.positions || []).find((p) => p.serial === serial) || null;
const deviceStatusReadOnly = () =>
  document.body.classList.contains("read-only");
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
  const rack = d.rack_id || reported?.rack_id,
    position = d.kind === "server" ? deviceStatusUnit(d.serial) : null,
    unit = position
      ? `<span class="live-small">${esc(deviceStatusUnitText(position))}</span>`
      : "";
  if (!rack)
    // The rack is declared, not discovered; the existing editors own that field.
    return d.kind === "server"
      ? `<button class="link-button" data-live="device-edit" ${eqAttr(d.legacy_id)}>填写机柜</button>${unit}`
      : `<button class="link-button" data-live="eq-edit" ${eqAttr(d.id)}>填写机柜</button>`;
  const place = reported?.placement || {},
    parts = [
      place.slot != null ? `槽位 ${place.slot}` : "",
      place.tray != null ? `托盘 ${place.tray}` : "",
    ].filter(Boolean);
  return (
    esc(rack) +
    unit +
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
      (page.kind === "server" && !deviceStatusReadOnly()
        ? button("导入 U 位", "device-status-rack-units-open")
        : "") +
      `<button class="button" data-page="devices">前往设备管理</button>`,
  );
  const data = state.equipment,
    reports = state.deviceStatus;
  const errors = [
    state.readErrors?.equipment,
    state.readErrors?.deviceStatus,
    ...(reports?.errors || []),
    page.kind === "server" && state.readErrors?.rackUnits
      ? "U 位读取失败：" + state.readErrors.rackUnits
      : "",
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
  if (page.kind === "server") body += deviceStatusRackUnitsNote();
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
  // Operations exist only where the site enables them; a read-only observer
  // never shows them (its backend refuses them regardless).
  const actions = deviceStatusActionEnabled(),
    selectable = actions
      ? visible.map(([d, i]) => deviceStatusActionTarget(d, i)).filter(Boolean)
      : [];
  if (actions) {
    state.deviceStatusSelection = state.deviceStatusSelection.filter((id) =>
      all.some(([d, i]) => deviceStatusActionTarget(d, i)?.target === id),
    );
    const count = state.deviceStatusSelection.length,
      limit = deviceStatusActionLimit();
    body += `<div class="device-status-action-bar">${button(
      count ? `批量操作（${count}）` : "批量操作",
      "device-status-action-batch",
      false,
      count && count <= limit ? "" : "disabled",
    )}<span class="live-small">${count > limit ? `一次最多操作 ${limit} 台，当前已选 ${count} 台。` : `勾选设备后批量操作，一次最多 ${limit} 台。`}</span></div>`;
  }
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
    const target = deviceStatusActionTarget(d, i),
      pick = actions
        ? `<td>${target ? `<input type="checkbox" name="device-status-action-pick" value="${esc(target.target)}" ${state.deviceStatusSelection.includes(target.target) ? "checked" : ""} aria-label="选择 ${esc(target.label)}">` : ""}</td>`
        : "",
      act = actions
        ? target
          ? button(
              "操作",
              "device-status-action-open",
              false,
              `data-target="${esc(target.target)}" data-device-status="${esc(name)}"`,
            )
          : '<button class="button" disabled title="NICo 尚未建立设备对象，不能操作。">操作</button>'
        : "";
    return `<tr>${pick}<td><button class="link-button" ${open}>${esc(d.name || d.serial || d.id)}</button><span class="live-small">${esc(d.serial)}</span></td><td>${deviceStatusPlacement(d, i)}</td><td>${equipmentBmcAddresses(d, native)}</td><td>${deviceStatusLifecycle(i, d)}</td><td>${deviceStatusHealthBadge(i)}</td><td>${equipmentOnline(d)}</td>${columns.map(([, cell]) => `<td>${cell(d, i)}</td>`).join("")}<td><div class="device-row-actions">${button("运行状态", "device-status-open", false, `${eqAttr(d.id)} data-device-status="${esc(name)}"`)}${act}${task ? `<button class="button" data-task="${esc(task.id)}">安装任务</button>` : ""}${button("地址管理", "address-device", false, eqAttr(d.id))}</div></td></tr>`;
  });
  const selectedAll =
    selectable.length &&
    selectable.every((t) => state.deviceStatusSelection.includes(t.target));
  return (
    body +
    table(
      [
        ...(actions ? ["选择"] : []),
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
    ).replace(
      "<th>选择</th>",
      `<th><input type="checkbox" name="device-status-action-all" ${selectedAll ? "checked" : ""} ${selectable.length ? "" : "disabled"} aria-label="选择当前列表前 ${deviceStatusActionLimit()} 台可操作设备"></th>`,
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
      (i.id
        ? '<h3>健康历史</h3><div id="device-status-health" aria-live="polite"><p class="live-small">正在读取健康记录…</p></div><h3>硬件校验</h3><div id="device-status-validation" aria-live="polite"><p class="live-small">正在读取校验记录…</p></div>'
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
    deviceStatusSectionRead(
      w,
      i.id,
      "health",
      "#device-status-health",
      "健康记录",
      deviceStatusHealthHistory,
    );
    deviceStatusSectionRead(
      w,
      i.id,
      "validation",
      "#device-status-validation",
      "校验记录",
      deviceStatusValidation,
    );
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
// Per-machine sections read after the dialog opens; like the timeline, only the
// dialog that asked writes into its own section.
async function deviceStatusSectionRead(
  w,
  machineId,
  part,
  selector,
  what,
  show,
) {
  const place = () => (state.wizard === w ? $(selector) : null);
  if (!/^[a-z0-9]{1,128}$/.test(machineId || "")) {
    if (place())
      place().innerHTML = `<div class="live-note">此设备的 NICo 机器 ID 无法用于读取${esc(what)}。</div>`;
    return;
  }
  let html;
  try {
    html = show(
      await api(
        "/api/device-status/machines/" +
          encodeURIComponent(machineId) +
          "/" +
          part,
      ),
    );
  } catch (e) {
    html = `<div class="live-error" role="alert">${esc(what)}读取失败：${esc(e.message)}</div>`;
  }
  if (place()) place().innerHTML = html;
}
const deviceStatusTags = (items) =>
  (items || []).map((c) => badge(c)).join(" ");
function deviceStatusHealthHistory(data) {
  if (!data.record_count)
    return '<p class="live-small">NICo 没有这台机器的健康记录。</p>';
  const span = `${data.record_count} 条记录（${esc(deviceStatusTime(data.first_record))} 至 ${esc(deviceStatusTime(data.last_record))}）`;
  if (!data.alerts.length)
    return `<p class="live-small">这台机器在 ${span}中没有告警。</p>`;
  return (
    table(
      ["告警", "开始", "最后出现", "状态", "说明"],
      data.alerts.map(
        (a) =>
          `<tr><td><code>${esc(a.id || "—")}</code>${a.target ? `<span class="live-small">${esc(a.target)}</span>` : ""}</td><td>${esc(deviceStatusTime(a.since))}</td><td>${esc(deviceStatusTime(a.last_seen))}</td><td>${a.active ? badge("仍存在", "amber") : badge("已恢复", "green")}</td><td>${esc(a.message || "—")}${a.classifications.length ? `<div>${deviceStatusTags(a.classifications)}</div>` : ""}</td></tr>`,
      ),
    ) +
    `<p class="live-small">来自 NICo 保存的健康记录，共 ${span}，读取于 ${esc(when(data.observed_at))}。</p>`
  );
}
const deviceStatusValidationTones = {
  Success: "green",
  Failed: "red",
  Skipped: "gray",
};
const deviceStatusValidationLabels = {
  Success: "通过",
  Failed: "失败",
  Skipped: "已跳过",
};
function deviceStatusValidation(data) {
  if (!data.runs.length)
    return '<p class="live-small">NICo 没有这台机器的校验记录。</p>';
  const rows = data.runs.map((r) => {
    const results = data.results[r.validation_id] || [],
      s = r.status,
      label =
        s.phase === "completed"
          ? deviceStatusValidationLabels[s.outcome] || s.outcome
          : s.phase === "in_progress"
            ? "进行中"
            : s.phase === "started"
              ? "已开始"
              : "未报告",
      tone =
        s.phase === "completed"
          ? deviceStatusValidationTones[s.outcome] || "gray"
          : s.phase
            ? "amber"
            : "gray",
      progress =
        s.total != null
          ? `<span class="live-small">${esc(s.completed_tests ?? 0)} / ${esc(s.total)} 项</span>`
          : "",
      detail = results.length
        ? results
            .map(
              (t) =>
                `<div>${esc(t.name || t.test_id || "—")} ${t.exit_code === 0 ? badge("通过", "green") : badge("失败", "red")} 退出码 ${esc(t.exit_code)} · ${esc(deviceStatusTime(t.start))}</div>`,
            )
            .join("")
        : '<span class="live-small">这次校验没有结果记录。</span>';
    return `<tr><td>${esc(r.name || r.validation_id || "—")}<span class="live-small">${esc(r.context || "—")}</span></td><td>${esc(deviceStatusTime(r.start))}</td><td>${r.duration_seconds != null ? esc(deviceStatusDuration(r.duration_seconds)) : "—"}</td><td><span title="${esc(s.text || s.outcome || "")}">${badge(label, tone)}</span>${progress}</td></tr><tr><td colspan="4">${detail}</td></tr>`;
  });
  return (
    table(["名称 / 场景", "开始", "耗时", "结果"], rows) +
    `<p class="live-small">来自 NICo 机器校验记录，共 ${data.runs.length} 次，读取于 ${esc(when(data.observed_at))}。</p>`
  );
}
// Names in a note: the first few, then the count.
function deviceStatusFirstNames(names) {
  return names.length > 3
    ? `${names.slice(0, 3).join("、")} 等 ${names.length} 台`
    : names.join("、");
}
function deviceStatusRackUnitsNote() {
  const data = state.rackUnits;
  if (!data || (!data.mismatches.length && !data.unknown.length)) return "";
  const parts = [];
  if (data.mismatches.length)
    parts.push(
      `${data.mismatches.length} 台服务器的 U 位记录机柜与设备管理中的机柜不一致（${esc(
        deviceStatusFirstNames(
          data.mismatches.map(
            (m) =>
              `${m.serial}：记录 ${m.recorded_rack || "空"}，设备 ${m.device_rack || "未填写"}`,
          ),
        ),
      )}）`,
    );
  if (data.unknown.length)
    parts.push(
      `${data.unknown.length} 个序列号不在设备列表中（${esc(deviceStatusFirstNames(data.unknown))}）`,
    );
  return `<div class="live-note live-warning">${parts.join("；")}。机柜以设备管理为准，U 位导入不修改机柜。${
    deviceStatusReadOnly()
      ? ""
      : ' <button class="link-button" data-live="device-status-rack-units-open">修改 U 位</button>'
  }</div>`;
}
function deviceStatusRackUnitsOpen() {
  if (deviceStatusReadOnly()) return;
  const data = state.rackUnits;
  if (!data) return toast("U 位尚未读取，请先刷新数据。");
  state.wizard = { resource: "rack-units", revision: data.revision };
  modal(
    "导入 U 位",
    "服务器 · 机柜内位置",
    `<div class="live-form"><label for="device-status-rack-units-csv">U 位 CSV<textarea class="input live-code" id="device-status-rack-units-csv" rows="14" spellcheck="false">${esc(data.csv)}</textarea></label><div class="live-note">格式：首行为表头 <code>serial,rack,unit</code> 或 <code>serial,rack,unit,height</code>，每台服务器一行。unit 为设备最低占用的 U 位，height 为占用 U 数，均为 1 到 60 的整数，省略 height 列时为 1。rack 只用于与设备管理中的机柜比对，不会写入。保存后替换全部已有 U 位，不写入 NICo。</div></div><div id="device-status-rack-units-errors" role="alert"></div>`,
    button("取消", "close") +
      button("保存", "device-status-rack-units-save", true),
  );
}
function deviceStatusRackUnitsErrors(data) {
  const errors = data.errors || [];
  return `<div class="live-error">${esc(data.error || "保存失败")}${
    errors.length
      ? `<ul>${errors
          .map(
            (e) =>
              `<li>${e.line ? `第 ${esc(e.line)} 行` : "文件"} · <code>${esc(e.field)}</code>：${esc(e.message)}</li>`,
          )
          .join("")}</ul>`
      : ""
  }</div>`;
}
// The import answers with every line error, which api() would reduce to one
// message, so this POST reads the response itself.
async function deviceStatusRackUnitsSave(el) {
  const w = state.wizard;
  if (w?.resource !== "rack-units") return;
  el.disabled = true;
  try {
    const response = await fetch("/api/rack-units", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": state.csrf || "",
      },
      body: JSON.stringify({
        csv: $("#device-status-rack-units-csv").value,
        revision: w.revision,
      }),
      credentials: "same-origin",
    });
    const data = await response.json().catch(() => ({}));
    if (state.wizard !== w) return;
    if (!response.ok) {
      $("#device-status-rack-units-errors").innerHTML =
        deviceStatusRackUnitsErrors(data);
      return;
    }
    state.rackUnits = data;
    close();
    render();
    toast(`已保存 ${data.positions.length} 台服务器的 U 位。`);
  } catch (e) {
    if (state.wizard === w)
      $("#device-status-rack-units-errors").innerHTML =
        deviceStatusRackUnitsErrors({ error: e.message });
  } finally {
    el.disabled = false;
  }
}
// Device operations (rack_actions switch). The catalog, checks, confirmation and
// audit all live on the server; this dialog only collects the choice, shows the
// server's preview and sends what it previewed once. Nothing is retried.
state.rackActions = false;
state.deviceStatusSelection = [];
const deviceStatusActionKinds = {
  server: "machine",
  switch: "switch",
  power_shelf: "power_shelf",
};
const deviceStatusActionGroupIds = [
  [
    "电源",
    [
      "power_on",
      "graceful_shutdown",
      "force_off",
      "graceful_restart",
      "force_restart",
      "ac_powercycle",
      "tray_power_on",
      "tray_power_off",
      "tray_power_restart",
      "switch_power_on",
      "switch_power_off",
      "switch_power_restart",
      "shelf_power_on",
      "shelf_power_off",
    ],
  ],
  [
    "维护与隔离",
    [
      "maintenance_enable",
      "maintenance_disable",
      "quarantine_set",
      "quarantine_clear",
    ],
  ],
  ["校验", ["validation_on_demand", "sku_verify"]],
  ["退役", ["switch_decommission", "shelf_decommission"]],
  ["复位", ["host_reset", "bmc_reset", "switch_reset"]],
];
const deviceStatusActionRisks = {
  low: ["低风险", "green"],
  medium: ["中风险", "amber"],
  high: ["高风险", "red"],
};
const deviceStatusActionResults = {
  succeeded: ["已完成", "green"],
  failed: ["失败", "red"],
  unknown: ["结果未知", "amber"],
  refused: ["未执行", "gray"],
  sent: ["已发送", "amber"],
};
const deviceStatusActionEnabled = () =>
  state.rackActions === true && !deviceStatusReadOnly();
const deviceStatusActionLimit = () =>
  state.deviceStatusCatalog?.limits?.max_targets || 10;
// The object an operation names: the Core object of the row, never a guess.
const deviceStatusActionTarget = (d, reported) =>
  reported?.id
    ? {
        target: reported.id,
        serial: d.serial || "",
        label: d.name || d.serial || d.id,
      }
    : null;
function deviceStatusActionGrouped(actions, kind) {
  const own = (actions || []).filter((a) => a.kind === kind),
    known = new Set(deviceStatusActionGroupIds.flatMap(([, ids]) => ids)),
    groups = deviceStatusActionGroupIds.map(([label, ids]) => [
      label,
      ids.map((id) => own.find((a) => a.id === id)).filter(Boolean),
    ]);
  groups.push(["固件与其他", own.filter((a) => !known.has(a.id))]);
  return groups.filter(([, items]) => items.length);
}
// Form values to request parameters: empty values are left out, list fields
// are one item per line, and the catalog's required rules are checked first.
function deviceStatusActionCollect(entry, raw) {
  const params = {};
  for (const spec of entry.params || []) {
    let value = raw[spec.name];
    if (spec.type === "list")
      value = String(value || "")
        .split(/[\n,]/)
        .map((x) => x.trim())
        .filter(Boolean);
    else if (spec.type === "multi")
      value = (value || []).filter((x) => (spec.choices || []).includes(x));
    else if (spec.type === "bool") value = value === true;
    else value = String(value ?? "").trim();
    const empty =
      value === "" ||
      (Array.isArray(value) && !value.length) ||
      value === false;
    if (empty) {
      if (spec.required) return { params, error: `请填写${spec.label}。` };
      continue;
    }
    if (spec.type === "json")
      try {
        JSON.parse(value);
      } catch {
        return { params, error: `${spec.label}不是有效的 JSON。` };
      }
    params[spec.name] = value;
  }
  for (const spec of entry.params || []) {
    const needed = (spec.required_with || []).filter((a) =>
      (params.activities || []).includes(a),
    );
    if (needed.length && !(spec.name in params))
      return { params, error: `所选维护项目需要${spec.label}。` };
  }
  return { params, error: "" };
}
// High-risk confirmations: each eligible target must be confirmed by typing its
// serial (or its ID when it has none); anything else blocks execution.
function deviceStatusActionConfirm(preview, typed) {
  const eligible = (preview?.targets || []).filter((t) => t.eligible),
    confirm = {},
    missing = [];
  for (const t of eligible) {
    if (!preview.action.needs_confirm_serial) continue;
    const expected = t.confirm_with === "id" ? t.target : t.serial,
      value = String(typed?.[t.target] || "").trim();
    if (value && value === expected) confirm[t.target] = value;
    else missing.push(t.target);
  }
  return {
    eligible: eligible.length,
    confirm,
    missing,
    ready: eligible.length > 0 && !missing.length,
  };
}
const deviceStatusActionRiskBadge = (entry) =>
  badge(...(deviceStatusActionRisks[entry.risk] || ["未知风险", "gray"]));
const deviceStatusActionResultBadge = (status) =>
  badge(...(deviceStatusActionResults[status] || [status || "未报告", "gray"]));
function deviceStatusActionParamField(spec, value) {
  const id = "device-status-action-param-" + spec.name,
    label = esc(spec.label) + (spec.required ? "" : "（可选）"),
    hint = spec.required_with?.length
      ? `<span class="live-small">选择 ${esc(spec.required_with.join("、"))} 时必填。</span>`
      : "";
  if (spec.type === "bool")
    return `<label class="live-check"><input type="checkbox" id="${id}" ${value === true ? "checked" : ""}>${esc(spec.label)}</label>`;
  if (spec.type === "choice")
    return `<label for="${id}">${label}<select class="input" id="${id}"><option value="">请选择</option>${(spec.choices || []).map((c) => `<option value="${esc(c)}" ${value === c ? "selected" : ""}>${esc(c)}</option>`).join("")}</select>${hint}</label>`;
  if (spec.type === "multi")
    return `<fieldset class="device-status-action-multi"><legend>${label}</legend>${(spec.choices || []).map((c) => `<label class="live-check"><input type="checkbox" name="${id}" value="${esc(c)}" ${(value || []).includes(c) ? "checked" : ""}><span class="live-code">${esc(c)}</span></label>`).join("")}${hint}</fieldset>`;
  if (spec.type === "list" || spec.type === "json")
    return `<label for="${id}">${label}<textarea class="input live-code" id="${id}" rows="${spec.type === "json" ? 8 : 3}" spellcheck="false">${esc(Array.isArray(value) ? value.join("\n") : value || "")}</textarea><span class="live-small">${spec.type === "json" ? "JSON 文本。" : "每行一项。"}</span>${hint}</label>`;
  return `<label for="${id}">${label}<input class="input" id="${id}" value="${esc(value || "")}" autocomplete="off">${hint}</label>`;
}
function deviceStatusActionReadForm(entry) {
  const raw = {};
  for (const spec of entry.params || []) {
    const id = "device-status-action-param-" + spec.name;
    if (spec.type === "multi")
      raw[spec.name] = [
        ...document.querySelectorAll(`input[name="${id}"]:checked`),
      ].map((x) => x.value);
    else if (spec.type === "bool") raw[spec.name] = !!$("#" + id)?.checked;
    else raw[spec.name] = $("#" + id)?.value ?? "";
  }
  return raw;
}
const deviceStatusActionTargetsLine = (w) =>
  w.targets.length === 1
    ? `${w.targets[0].label}${w.targets[0].serial && w.targets[0].serial !== w.targets[0].label ? " · " + w.targets[0].serial : ""}`
    : `${w.targets.length} 台设备`;
function deviceStatusActionChooseBody(w) {
  const catalog = state.deviceStatusCatalog,
    groups = deviceStatusActionGrouped(catalog.actions, w.kind),
    entry = catalog.actions.find((a) => a.id === w.action),
    rms = catalog.rms || {};
  if (!groups.length)
    return '<div class="live-empty">没有适用于此类设备的操作。</div>';
  let body = `<div class="live-note">操作对象：${w.targets.map((t) => `<span class="live-code">${esc(t.label)}</span>`).join("、")}</div>`;
  body += `<p class="live-small">RMS：${rms.reachable ? `可连接${rms.version ? "，版本 " + esc(rms.version) : ""}` : `未连接${rms.error ? "（" + esc(rms.error) + "）" : ""}`}。仅供参考，不阻止提交；需要 RMS 的操作在 RMS 不可用时会被 NICo 拒绝。</p>`;
  body += groups
    .map(
      ([label, items]) =>
        `<fieldset class="device-status-action-group"><legend>${esc(label)}</legend>${items
          .map(
            (a) =>
              `<label class="device-status-action-item ${a.available ? "" : "unavailable"}"><input type="radio" name="device-status-action-choice" value="${esc(a.id)}" ${a.id === w.action ? "checked" : ""} ${a.available ? "" : "disabled"}><span><strong>${esc(a.label)}</strong> ${deviceStatusActionRiskBadge(a)}${a.needs_rms ? ` <span title="${esc(a.rms_reason)}">${badge("需要 RMS", "gray")}</span>` : ""}<span class="live-small">${esc(a.available ? a.effect : a.unavailable_reason)}${a.needs_rms && a.rms_reason ? ` · ${esc(a.rms_reason)}` : ""}</span></span></label>`,
          )
          .join("")}</fieldset>`,
    )
    .join("");
  if (entry)
    body += `<h3>${esc(entry.label)} · 参数</h3><div class="live-form device-status-action-form">${(entry.params || []).map((p) => deviceStatusActionParamField(p, w.raw?.[p.name])).join("") || '<p class="live-small">此操作没有参数。</p>'}</div>`;
  return body + '<div id="device-status-action-error" role="alert"></div>';
}
function deviceStatusActionPreviewBody(w) {
  const p = w.preview,
    entry = p.action,
    paramRows = Object.entries(p.params || {}).map(([k, v]) => [
      (entry.params || []).find((x) => x.name === k)?.label || k,
      `<span class="live-code">${esc(typeof v === "object" ? JSON.stringify(v) : String(v))}</span>`,
    ]);
  const rows = p.targets.map((t) => {
    const expected = t.confirm_with === "id" ? t.target : t.serial;
    return `<tr><td>${esc(t.name || t.serial || t.target)}<span class="live-small live-code">${esc(t.target)}</span>${t.serial ? `<span class="live-small">SN ${esc(t.serial)}</span>` : ""}</td><td>${t.state ? `<code>${esc(t.state)}</code>` : "—"}</td><td>${t.eligible ? badge("可执行", "green") : badge("不可执行", "red")}${(t.reasons || []).map((r) => `<span class="live-small">${esc(r)}</span>`).join("")}</td>${
      entry.needs_confirm_serial
        ? `<td>${t.eligible ? `<input class="input live-code" data-device-status-confirm="${esc(t.target)}" value="${esc(w.typed[t.target] || "")}" placeholder="输入 ${t.confirm_with === "id" ? "对象 ID" : "SN"}" aria-label="输入 ${esc(expected)} 确认" autocomplete="off">` : "—"}</td>`
        : ""
    }</tr>`;
  });
  return (
    defs([
      ["操作", `${esc(entry.label)} ${deviceStatusActionRiskBadge(entry)}`],
      ["影响", esc(entry.effect)],
      ["NICo 接口", `<span class="live-code">${esc(entry.rpc)}</span>`],
      ...paramRows,
    ]) +
    '<div class="device-status-action-table">' +
    table(
      [
        "对象",
        "NICo 状态",
        "检查结果",
        ...(entry.needs_confirm_serial ? ["输入确认"] : []),
      ],
      rows,
    ) +
    "</div>" +
    `<p class="live-small">${entry.needs_confirm_serial ? "高风险操作需要为每台可执行设备输入其 SN（无 SN 时输入对象 ID）。" : ""}不可执行的设备不会发送。检查结果在 ${esc(when(p.expires_at))} 前有效，过期后需重新检查；提交时服务端会再次检查。</p>` +
    '<div id="device-status-action-error" role="alert"></div>'
  );
}
function deviceStatusActionResultBody(w) {
  const entry = w.preview.action,
    names = Object.fromEntries(
      w.preview.targets.map((t) => [t.target, t.name || t.serial || t.target]),
    );
  const rows = w.result.results.map(
    (r) =>
      `<tr><td>${esc(names[r.target] || r.target)}<span class="live-small live-code">${esc(r.target)}</span></td><td>${deviceStatusActionResultBadge(r.status)}</td><td>${
        [...(r.reasons || []), r.core_message]
          .filter(Boolean)
          .map((x) => `<span class="live-small">${esc(x)}</span>`)
          .join("") || "—"
      }</td><td>${r.readback ? `<details><summary>读回状态</summary><pre class="live-code">${esc(JSON.stringify(r.readback, null, 2))}</pre></details>` : "—"}</td></tr>`,
  );
  const unknown = w.result.results.filter((r) => r.status === "unknown").length;
  return (
    `<div class="live-note">${esc(entry.label)}：已按设备逐台记录。${unknown ? `${unknown} 台结果未知：请先查看读回状态和设备当前状态，不要直接重复提交。` : ""}不会自动重试。</div>` +
    '<div class="device-status-action-table">' +
    table(["对象", "结果", "原因 / NICo 消息", "读回"], rows) +
    "</div>"
  );
}
function deviceStatusActionRender() {
  const w = state.wizard;
  if (w?.resource !== "rack-actions") return;
  const line = deviceStatusActionTargetsLine(w);
  if (w.step === "result")
    return modal(
      "操作结果",
      line,
      deviceStatusActionResultBody(w),
      button("查看操作记录", "device-status-action-records") +
        button("关闭", "close", true),
    );
  if (w.step === "preview") {
    const c = deviceStatusActionConfirm(w.preview, w.typed);
    return modal(
      "确认操作",
      line,
      deviceStatusActionPreviewBody(w),
      button("返回修改", "device-status-action-back") +
        button("重新检查", "device-status-action-preview") +
        button(
          c.eligible ? `执行（${c.eligible} 台）` : "执行",
          "device-status-action-execute",
          true,
          c.ready ? "" : "disabled",
        ),
    );
  }
  modal(
    "设备操作",
    line,
    deviceStatusActionChooseBody(w),
    button("取消", "close") +
      button(
        "检查",
        "device-status-action-preview",
        true,
        w.action ? "" : "disabled",
      ),
  );
}
async function deviceStatusActionOpen(name, ids) {
  if (!deviceStatusActionEnabled()) return;
  const page = deviceStatusPages[name],
    rows = (state.equipment?.devices || [])
      .filter((d) => d.kind === page.kind && !d.address_only)
      .map((d) => deviceStatusActionTarget(d, deviceStatusReported(page, d)))
      .filter(Boolean),
    targets = ids
      .map((id) => rows.find((t) => t.target === id))
      .filter(Boolean);
  if (!targets.length) return toast("设备已变化，请刷新后重新选择。");
  if (targets.length > deviceStatusActionLimit())
    return toast(`一次最多操作 ${deviceStatusActionLimit()} 台设备。`);
  try {
    state.deviceStatusCatalog = await api("/api/rack-actions/catalog");
  } catch (e) {
    return toast("操作目录读取失败：" + e.message);
  }
  state.wizard = {
    resource: "rack-actions",
    kind: deviceStatusActionKinds[page.kind],
    targets,
    step: "choose",
    action: "",
    raw: {},
    typed: {},
  };
  deviceStatusActionRender();
}
const deviceStatusActionError = (text) => {
  const place = $("#device-status-action-error");
  if (place) place.innerHTML = `<div class="live-error">${esc(text)}</div>`;
};
async function deviceStatusActionPreview(el) {
  const w = state.wizard;
  if (w?.resource !== "rack-actions") return;
  const entry = state.deviceStatusCatalog.actions.find(
    (a) => a.id === w.action,
  );
  if (!entry) return;
  if (w.step === "choose") {
    w.raw = deviceStatusActionReadForm(entry);
    const { params, error } = deviceStatusActionCollect(entry, w.raw);
    if (error) return deviceStatusActionError(error);
    w.params = params;
  }
  el.disabled = true;
  try {
    const preview = await api("/api/rack-actions/preview", {
      action: entry.id,
      targets: w.targets.map((t) => t.target),
      params: w.params,
    });
    if (state.wizard !== w) return;
    w.preview = preview;
    w.step = "preview";
    deviceStatusActionRender();
  } catch (e) {
    if (state.wizard === w) deviceStatusActionError(e.message);
  } finally {
    el.disabled = false;
  }
}
async function deviceStatusActionExecute(el) {
  const w = state.wizard;
  if (w?.resource !== "rack-actions" || w.step !== "preview" || w.sending)
    return;
  const c = deviceStatusActionConfirm(w.preview, w.typed);
  if (!c.ready) return;
  if (w.preview.expires_at * 1000 < Date.now())
    return deviceStatusActionError("检查结果已过期，请点击“重新检查”。");
  // One request per preview: the button stays disabled whatever happens, and a
  // failed submission only offers a fresh check.
  w.sending = true;
  el.disabled = true;
  el.textContent = "正在执行…";
  try {
    const result = await api("/api/rack-actions/execute", {
      preview_token: w.preview.preview_token,
      confirm_serials: c.confirm,
    });
    if (state.wizard !== w) return;
    w.result = result;
    w.step = "result";
    deviceStatusActionRender();
    toast(
      `${w.preview.action.label}：已记录 ${result.results.length} 台设备的结果。`,
    );
  } catch (e) {
    if (state.wizard === w) {
      w.sending = false;
      el.textContent = "执行";
      deviceStatusActionError(
        e.message + " 请求可能已被处理，请在操作记录中核对后再重新检查。",
      );
    }
  }
}
registerPage("servers", () => deviceStatusPage("servers"));
registerPage("switches", () => deviceStatusPage("switches"));
registerPage("power_shelves", () => deviceStatusPage("power_shelves"));
registerActions(
  "device_status.js",
  [
    "device-status-refresh",
    "device-status-open",
    "device-status-rack-units-open",
    "device-status-rack-units-save",
    "device-status-action-open",
    "device-status-action-batch",
    "device-status-action-preview",
    "device-status-action-execute",
    "device-status-action-back",
    "device-status-action-records",
  ],
  async (e) => {
    const el = e.target.closest('[data-live^="device-status-"]');
    if (!el || el.disabled) return;
    if (el.dataset.live === "device-status-refresh")
      return await deviceStatusReload();
    if (el.dataset.live === "device-status-rack-units-open")
      return deviceStatusRackUnitsOpen();
    if (el.dataset.live === "device-status-rack-units-save")
      return await deviceStatusRackUnitsSave(el);
    if (el.dataset.live === "device-status-action-open")
      return await deviceStatusActionOpen(el.dataset.deviceStatus, [
        el.dataset.target,
      ]);
    if (el.dataset.live === "device-status-action-batch")
      return await deviceStatusActionOpen(state.page, [
        ...state.deviceStatusSelection,
      ]);
    if (el.dataset.live === "device-status-action-preview")
      return await deviceStatusActionPreview(el);
    if (el.dataset.live === "device-status-action-execute")
      return await deviceStatusActionExecute(el);
    if (el.dataset.live === "device-status-action-back") {
      state.wizard.step = "choose";
      return deviceStatusActionRender();
    }
    if (el.dataset.live === "device-status-action-records") {
      const targets = state.wizard?.targets || [];
      close();
      if (typeof rackActionRecordsShow === "function")
        return await rackActionRecordsShow(
          targets.length === 1 ? targets[0].target : "",
        );
      return;
    }
    return deviceStatusStatus(el.dataset.deviceStatus, el.dataset.id);
  },
);
observeUI(
  "change",
  "device_status.js",
  (e) => {
    if (e.target.name === "device-status-action-choice") {
      const w = state.wizard,
        entry = state.deviceStatusCatalog?.actions.find(
          (a) => a.id === w?.action,
        );
      if (entry) w.raw = deviceStatusActionReadForm(entry);
      w.action = e.target.value;
      deviceStatusActionRender();
      $(".device-status-action-form")?.scrollIntoView({ block: "nearest" });
      $(
        `input[name="device-status-action-choice"][value="${w.action}"]`,
      )?.focus();
      return;
    }
    if (e.target.name === "device-status-action-pick") {
      const id = e.target.value,
        list = state.deviceStatusSelection;
      state.deviceStatusSelection = e.target.checked
        ? [...new Set([...list, id])]
        : list.filter((x) => x !== id);
      return render();
    }
    if (e.target.name === "device-status-action-all") {
      state.deviceStatusSelection = e.target.checked
        ? [
            ...document.querySelectorAll(
              'input[name="device-status-action-pick"]',
            ),
          ]
            .map((x) => x.value)
            .slice(0, deviceStatusActionLimit())
        : [];
      return render();
    }
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
    const confirm = e.target.dataset?.deviceStatusConfirm;
    if (confirm && state.wizard?.resource === "rack-actions") {
      state.wizard.typed[confirm] = e.target.value;
      const execute = $('[data-live="device-status-action-execute"]');
      if (execute && !state.wizard.sending)
        execute.disabled = !deviceStatusActionConfirm(
          state.wizard.preview,
          state.wizard.typed,
        ).ready;
      return;
    }
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
  state.rackActions =
    readiness?.rack_actions === true && readiness?.read_only !== true;
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
  if (deviceStatusPages[child.name]) {
    state.deviceStatusFilters = { rack: "", status: "", search: "" };
    state.deviceStatusSelection = [];
  }
  child.reload();
});
