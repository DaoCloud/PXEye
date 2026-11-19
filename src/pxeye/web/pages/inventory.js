"use strict";
// Per-kind device pages. They read the same equipment list as 设备管理 and add the
// operational state NICo Core reports; enrollment, addresses and editing stay in
// the existing dialogs, which these pages open rather than reimplement.
const inventoryPages = {
  servers: {
    kind: "server",
    label: "服务器",
    description: "查看纳管服务器的运行状态、健康和硬件校验结果。",
    insights: "servers",
  },
  switches: {
    kind: "switch",
    label: "交换机",
    description: "查看 NVLink 交换机的运行状态、健康和管理口。",
    insights: "switches",
  },
  power_shelves: {
    kind: "power_shelf",
    label: "供电框",
    description: "查看供电框的运行状态、健康和供电规格。",
    insights: "power_shelves",
  },
};
const inventoryHealth = {
  ok: ["正常", "green"],
  warning: ["告警", "amber"],
  alert: ["告警", "amber"],
  critical: ["严重", "red"],
  unknown: ["未报告", "gray"],
};
state.deviceInsights = null;
state.inventoryEnabled = false;
state.inventoryFilters = { rack: "", health: "", search: "" };
sectionReads.deviceInsights = async () => {
  state.deviceInsights = await api("/api/device-insights");
};
async function inventoryReload() {
  await Promise.allSettled(
    ["resources", "equipment", "deviceInsights"].map((key) =>
      readSection(key, sectionReads[key]),
    ),
  );
}
const inventoryTime = (value) =>
  value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "—";
// A server is matched to its Core machine by the machine the console already
// associated with it, then by BMC MAC; the other kinds carry their native ID.
function inventoryInsight(page, d) {
  const rows = state.deviceInsights?.[page.insights] || {};
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
function inventoryLifecycle(insight, d) {
  if (!insight)
    return (
      badge("未报告") +
      `<span class="live-small">${esc(d.kind === "server" ? "" : (equipmentStates[d.status] || d.status) + " · ")}NICo 尚未建立设备对象</span>`
    );
  const life = insight.lifecycle,
    tone =
      life.outcome === "error" ? "red" : life.above_sla ? "amber" : "green";
  return (
    badge(life.state || "未报告", life.state ? tone : "gray") +
    (life.above_sla ? '<span class="live-small">超出状态时限</span>' : "") +
    (life.reason ? `<span class="live-small">${esc(life.reason)}</span>` : "")
  );
}
function inventoryHealthBadge(insight) {
  if (!insight) return badge("未报告");
  const [label, tone] =
      inventoryHealth[insight.health.level] || inventoryHealth.unknown,
    count = insight.health.alerts.length;
  return badge(count ? `${label} · ${count}` : label, tone);
}
function inventoryPlacement(d, insight) {
  const place = insight?.placement || {},
    parts = [
      place.slot != null ? `槽位 ${place.slot}` : "",
      place.tray != null ? `托盘 ${place.tray}` : "",
    ].filter(Boolean);
  return (
    esc(d.rack_id || insight?.rack_id || "—") +
    (parts.length
      ? `<span class="live-small">${esc(parts.join(" · "))}</span>`
      : "")
  );
}
function inventoryMatches(page, d, insight) {
  const f = state.inventoryFilters,
    level = insight ? insight.health.level : "unknown";
  return (
    (!f.rack || d.rack_id === f.rack) &&
    (!f.health ||
      (f.health === "alerting"
        ? ["warning", "alert", "critical"].includes(level)
        : level === f.health)) &&
    (!f.search ||
      [
        d.serial,
        d.name,
        insight?.lifecycle.state,
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
function inventoryFabricManager(fm) {
  if (!fm || (!fm.state && !fm.summary)) return "—";
  return (
    badge(
      { ok: "正常", not_ok: "异常", unknown: "未知" }[fm.state] || fm.summary,
      fm.state === "ok" ? "green" : fm.state === "not_ok" ? "red" : "gray",
    ) + (fm.reason ? `<span class="live-small">${esc(fm.reason)}</span>` : "")
  );
}
function inventoryColumns(page) {
  if (page.kind === "server")
    return [
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
      ["Fabric Manager", (d, i) => inventoryFabricManager(i?.fabric_manager)],
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
function inventoryPage(name) {
  const page = inventoryPages[name];
  if (!state.inventoryEnabled)
    return (
      heading(page.label, page.description) +
      '<div class="live-empty">此页面未在当前站点启用。</div>'
    );
  let body = heading(
    page.label,
    page.description,
    button("刷新数据", "inv-refresh") +
      `<button class="button" data-page="devices">前往设备管理</button>`,
  );
  const data = state.equipment,
    insights = state.deviceInsights;
  const errors = [
    state.readErrors?.equipment,
    state.readErrors?.deviceInsights,
    ...(insights?.errors || []),
  ].filter(Boolean);
  if (errors.length)
    body += `<div class="live-error" role="alert">${esc([...new Set(errors)].join("；"))}</div>`;
  if (!data || !insights)
    return (
      body +
      (errors.length
        ? ""
        : '<div class="live-empty">正在读取设备与运行状态…</div>')
    );
  const all = data.devices
      .filter((d) => d.kind === page.kind && !d.address_only)
      .map((d) => [d, inventoryInsight(page, d)]),
    visible = all.filter(([d, i]) => inventoryMatches(page, d, i)),
    f = state.inventoryFilters,
    alerting = all.filter(([, i]) =>
      ["warning", "alert", "critical"].includes(i?.health.level),
    ).length;
  body += `<div class="summary-strip inventory-summary"><div><small>设备总数</small><strong>${all.length}</strong></div><div><small>NICo 已建立对象</small><strong>${all.filter(([, i]) => i).length}</strong></div><div><small>健康告警</small><strong>${alerting}</strong></div><div><small>超出状态时限</small><strong>${all.filter(([, i]) => i?.lifecycle.above_sla).length}</strong></div></div>`;
  body += `<div class="equipment-device-filters">${selectField("inv-filter-rack", "机柜", [["", "全部机柜"], ...[...new Set(all.map(([d]) => d.rack_id).filter(Boolean))].map((id) => [id, id])], f.rack)}${selectField(
    "inv-filter-health",
    "健康",
    [
      ["", "全部"],
      ["alerting", "有告警"],
      ["ok", "正常"],
      ["unknown", "未报告"],
    ],
    f.health,
  )}${inputField("inv-filter-search", "搜索 SN、名称、状态、MAC 或 IP", f.search)}</div>`;
  const columns = inventoryColumns(page);
  const rows = visible.map(([d, i]) => {
    const native = state.resources?.devices.find((x) => x.serial === d.serial),
      open =
        page.kind === "server"
          ? `data-live="device-detail" data-serial="${esc(d.serial)}"`
          : `data-live="eq-detail" ${eqAttr(d.id)}`;
    return `<tr><td><button class="link-button" ${open}>${esc(d.name || d.serial || d.id)}</button><span class="live-small">${esc(d.serial)}</span></td><td>${inventoryPlacement(d, i)}</td><td>${equipmentBmcAddresses(d, native)}</td><td>${inventoryLifecycle(i, d)}</td><td>${inventoryHealthBadge(i)}</td><td>${equipmentOnline(d)}</td>${columns.map(([, cell]) => `<td>${cell(d, i)}</td>`).join("")}<td><div class="device-row-actions">${button("运行状态", "inv-status", false, `${eqAttr(d.id)} data-inventory="${esc(name)}"`)}${button("地址管理", "address-device", false, eqAttr(d.id))}</div></td></tr>`;
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
    `<p class="live-small">运行状态由 NICo 状态机回报，读取于 ${esc(when(insights.observed_at))}。设备的纳管、地址和安装规划在设备管理中维护。</p>`
  );
}
function inventoryStatus(name, id) {
  const page = inventoryPages[name],
    d = state.equipment?.devices.find((x) => x.id === id);
  if (!page || !d) throw Error("设备归属已变化，请刷新。");
  const i = inventoryInsight(page, d);
  state.wizard = { resource: "inventory-status", device: d };
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
      inventoryHealth[i.health.level] || inventoryHealth.unknown;
  let body =
    defs([
      ["NICo 对象 ID", esc(i.id)],
      ["机柜 / 位置", inventoryPlacement(d, i)],
      ["运行状态", inventoryLifecycle(i, d)],
      ["电源", equipmentOnline(d)],
      ["BMC 地址", esc(i.bmc.ip || "—")],
      ["BMC 固件", esc(i.bmc.firmware_version || i.bmc.version || "—")],
      [
        "健康",
        badge(healthLabel, healthTone) +
          (i.health.observed_at
            ? `<span class="live-small">观测于 ${esc(inventoryTime(i.health.observed_at))}${i.health.source ? " · " + esc(i.health.source) : ""}</span>`
            : ""),
      ],
    ]) +
    "<h3>健康告警</h3>" +
    table(
      ["探针", "对象", "说明", "开始时间"],
      i.health.alerts.map(
        (a) =>
          `<tr><td>${esc(a.id)}</td><td>${esc(a.target || "—")}</td><td>${esc(a.message)}</td><td>${esc(inventoryTime(a.since))}</td></tr>`,
      ),
    );
  if (page.kind === "server") {
    const caps = Object.entries(i.capabilities);
    body +=
      defs([
        ["SKU", esc(i.sku.id || "未分配")],
        ["SKU 最近比对", esc(inventoryTime(i.sku.last_match_attempt))],
        [
          "隔离",
          i.quarantine
            ? badge("已隔离", "red") +
              `<span class="live-small">${esc(i.quarantine.reason || i.quarantine.mode)}</span>`
            : "未隔离",
        ],
        ["维护标记", esc(i.maintenance || "—")],
        ["关联 DPU", esc(i.dpu_ids.join(", ") || "—")],
        ["最近重启", esc(inventoryTime(i.last_reboot))],
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
      "<h3>LLDP 邻居</h3>" +
      table(
        ["本机接口", "邻居交换机", "邻居端口", "交换机 SN"],
        i.lldp.map(
          (n) =>
            `<tr><td>${esc(n.local_port || "—")}<span class="live-small">${esc(n.mac_address)}</span></td><td>${esc(n.switch || n.switch_id || "—")}<span class="live-small">${esc(n.switch_model)}</span></td><td>${esc(n.remote_port || "—")}</td><td>${esc(n.switch_serial || "—")}</td></tr>`,
        ),
      );
  }
  if (page.kind === "switch")
    body +=
      defs([
        ["主交换机", i.primary ? "是" : "否"],
        ["NVLink 域", esc(i.nvlink_domain || "—")],
        ["NMX-C", i.nmxc_enabled ? "已启用" : "未启用"],
        ["Fabric Manager", inventoryFabricManager(i.fabric_manager)],
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
}
registerPage("servers", () => inventoryPage("servers"));
registerPage("switches", () => inventoryPage("switches"));
registerPage("power_shelves", () => inventoryPage("power_shelves"));
registerActions("inventory.js", ["inv-refresh", "inv-status"], async (e) => {
  const el = e.target.closest('[data-live^="inv-"]');
  if (!el || el.disabled) return;
  if (el.dataset.live === "inv-refresh") return await inventoryReload();
  return inventoryStatus(el.dataset.inventory, el.dataset.id);
});
observeUI(
  "change",
  "inventory.js",
  (e) => {
    if (e.target.id?.startsWith("inv-filter-")) {
      state.inventoryFilters[e.target.id.slice(11)] = e.target.value;
      render();
    }
  },
  false,
);
observeUI(
  "input",
  "inventory.js",
  (e) => {
    if (e.target.id === "inv-filter-search") {
      const position = e.target.selectionStart;
      state.inventoryFilters.search = e.target.value;
      render();
      $("#inv-filter-search").focus();
      $("#inv-filter-search").setSelectionRange(position, position);
    }
  },
  false,
);
// The pages join the navigation only where the site enables them, so a site
// without the setting keeps exactly the navigation it had.
registerHook("readiness", (readiness) => {
  state.inventoryEnabled = readiness?.rack_operations === true;
  if (!state.inventoryEnabled) return;
  const group = groups.find(([, pages]) => pages.includes("devices"));
  for (const [name, page] of Object.entries(inventoryPages)) {
    labels[name] = page.label;
    if (group && !group[1].includes(name))
      group[1].splice(
        group[1].indexOf("devices") +
          Object.keys(inventoryPages).indexOf(name) +
          1,
        0,
        name,
      );
  }
  // A reload lands here before the navigation knew these pages existed.
  if (inventoryPages[location.hash.slice(1)]) {
    state.page = location.hash.slice(1);
    inventoryReload();
  }
});
window.addEventListener("hashchange", () => {
  if (state.inventoryEnabled && inventoryPages[location.hash.slice(1)]) {
    state.inventoryFilters = { rack: "", health: "", search: "" };
    inventoryReload();
  }
});
