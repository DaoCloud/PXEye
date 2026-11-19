"use strict";
// The health alerts NICo reports for servers, switches and power shelves,
// gathered on one page and grouped by alert type. It reads the same device
// status as the per-kind pages and opens their status dialog; it owns no data.
state.alertsFilters = { kind: "", classification: "", search: "" };
state.alertsView = "alert";
const alertsPreventAllocations = "PreventAllocations";
// One entry per alert per device; a device whose health level needs attention
// without any alert entries gets one entry with no alert id.
function alertsEntries(devices) {
  return devices.flatMap(([page, d, reported]) => {
    if (!reported) return [];
    const health = reported.health || {},
      list = Array.isArray(health.alerts) ? health.alerts : [];
    if (list.length)
      return list.map((alert) => ({ page, device: d, alert, level: "" }));
    return ["warning", "alert", "critical"].includes(health.level)
      ? [{ page, device: d, alert: null, level: health.level }]
      : [];
  });
}
const alertsClassifications = (entry) =>
  Array.isArray(entry.alert?.classifications)
    ? entry.alert.classifications.filter((c) => typeof c === "string")
    : [];
function alertsGroups(entries) {
  const groups = {};
  for (const entry of entries)
    (groups[entry.alert ? entry.alert.id || "" : "\u0000level"] ||= []).push(
      entry,
    );
  return groups;
}
function alertsSummary(entries) {
  const alerts = entries.filter((e) => e.alert);
  return {
    alerts: alerts.length,
    devices: new Set(entries.map((e) => `${e.page}\u0000${e.device.id}`)).size,
    types: new Set(alerts.map((e) => e.alert.id || "")).size,
    prevent: alerts.filter((e) =>
      alertsClassifications(e).includes(alertsPreventAllocations),
    ).length,
  };
}
// Earliest start among entries; times that cannot be parsed are left out.
function alertsEarliest(entries) {
  const times = entries
    .map((e) => e.alert?.since)
    .filter((t) => t && !Number.isNaN(Date.parse(t)))
    .sort((a, b) => Date.parse(a) - Date.parse(b));
  return times[0] || "";
}
function alertsMatches(entry) {
  const f = state.alertsFilters,
    a = entry.alert || {},
    d = entry.device;
  return (
    (!f.kind || entry.page === f.kind) &&
    (!f.classification ||
      alertsClassifications(entry).includes(f.classification)) &&
    (!f.search ||
      [a.id, a.message, a.target, d.serial, d.name]
        .join(" ")
        .toLowerCase()
        .includes(f.search.toLowerCase()))
  );
}
const alertsLevelText = (level) =>
  `健康等级为${(deviceStatusHealth[level] || deviceStatusHealth.unknown)[0]}但未报告告警项`;
const alertsDevice = (entry) =>
  `<button class="link-button" data-live="device-status-open" data-device-status="${esc(entry.page)}" ${eqAttr(entry.device.id)}>${esc(entry.device.name || entry.device.serial || entry.device.id)}</button><span class="live-small">${esc(deviceStatusPages[entry.page].label)}${entry.device.serial ? " · " + esc(entry.device.serial) : ""}</span>`;
const alertsTags = (list) =>
  list
    .map((c) => badge(c, c === alertsPreventAllocations ? "red" : "gray"))
    .join(" ");
function alertsGroupBlock(key, entries) {
  const level = key === "\u0000level",
    tags = [...new Set(entries.flatMap(alertsClassifications))],
    since = alertsEarliest(entries),
    devices = new Set(entries.map((e) => `${e.page}\u0000${e.device.id}`)).size,
    title = level ? "未报告告警项" : key || "未命名告警";
  const rows = entries.map(
    (e) =>
      `<tr><td>${alertsDevice(e)}</td><td>${e.alert ? `<span class="live-code">${esc(e.alert.target || "—")}</span>` : "—"}</td><td>${esc(e.alert ? deviceStatusTime(e.alert.since) : "—")}</td><td>${esc(e.alert ? e.alert.message || "—" : alertsLevelText(e.level))}</td></tr>`,
  );
  return `<h3 style="margin: 20px 0 8px"><span class="live-code">${esc(title)}</span><span class="live-small">${devices} 台设备${since ? " · 最早开始于 " + esc(deviceStatusTime(since)) : ""}${tags.length ? " · " : ""}${alertsTags(tags)}</span></h3>${table(["设备", "对象", "开始", "说明"], rows)}`;
}
function alertsDeviceRows(entries) {
  return entries.map(
    (e) =>
      `<tr><td>${alertsDevice(e)}</td><td>${e.alert ? `<span class="live-code">${esc(e.alert.id || "—")}</span>${alertsClassifications(e).length ? `<span class="live-small">${alertsTags(alertsClassifications(e))}</span>` : ""}` : badge((deviceStatusHealth[e.level] || deviceStatusHealth.unknown)[0], (deviceStatusHealth[e.level] || deviceStatusHealth.unknown)[1])}</td><td>${e.alert ? `<span class="live-code">${esc(e.alert.target || "—")}</span>` : "—"}</td><td>${esc(e.alert ? deviceStatusTime(e.alert.since) : "—")}</td><td>${esc(e.alert ? e.alert.message || "—" : alertsLevelText(e.level))}</td></tr>`,
  );
}
function alertsRender() {
  let body = heading(
    "告警",
    "汇总 NICo 对服务器、交换机和供电框当前报告的健康告警，按告警类型查看影响了哪些设备。",
    button("刷新数据", "alerts-refresh"),
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
        : '<div class="live-empty">正在读取设备健康数据…</div>')
    );
  const devices = Object.entries(deviceStatusPages).flatMap(([name, page]) =>
      (state.equipment.devices || [])
        .filter((d) => d.kind === page.kind && !d.address_only)
        .map((d) => [name, d, deviceStatusReported(page, d)]),
    ),
    reported = devices.filter(([, , r]) => r).length,
    missing = devices.length - reported,
    entries = alertsEntries(devices),
    read = `读取于 ${esc(when(reports.observed_at))}`,
    missingNote = missing
      ? `<p class="live-small">另有 ${missing} 台设备 NICo 尚未建立设备对象，没有健康数据，不计入告警。</p>`
      : "";
  if (!entries.length)
    return (
      body +
      `<div class="live-note">NICo 报告了 ${reported} 台设备的健康状态，均未报告告警，${read}。</div>` +
      missingNote
    );
  const f = state.alertsFilters,
    classifications = [
      ...new Set(entries.flatMap(alertsClassifications)),
    ].sort();
  if (f.classification && !classifications.includes(f.classification))
    f.classification = "";
  const s = alertsSummary(entries);
  body += `<div class="summary-strip device-status-summary"><div><small>告警数</small><strong>${s.alerts}</strong></div><div><small>涉及设备</small><strong>${s.devices}</strong></div><div><small>告警类型</small><strong>${s.types}</strong></div><div><small>阻止分配</small><strong>${s.prevent}</strong></div></div>`;
  body += `<div class="equipment-device-filters">${selectField(
    "alerts-filter-kind",
    "设备类型",
    [
      ["", "全部"],
      ...Object.entries(deviceStatusPages).map(([name, page]) => [
        name,
        page.label,
      ]),
    ],
    f.kind,
  )}${selectField(
    "alerts-filter-classification",
    "分类",
    [["", "全部分类"], ...classifications.map((c) => [c, c])],
    f.classification,
  )}${inputField("alerts-filter-search", "搜索告警、说明、设备名称或序列号", f.search)}</div>`;
  body += `<div class="live-tools" style="margin: 12px 0">${button("按告警", "alerts-view-alert", state.alertsView === "alert", 'data-alerts-view="alert"')}${button("按设备", "alerts-view-device", state.alertsView === "device", 'data-alerts-view="device"')}</div>`;
  const shown = entries.filter(alertsMatches);
  if (!shown.length)
    body += '<div class="live-empty">没有符合筛选条件的告警。</div>';
  else if (state.alertsView === "device")
    body += table(
      ["设备", "告警", "对象", "开始", "说明"],
      alertsDeviceRows(shown),
    );
  else
    body += Object.entries(alertsGroups(shown))
      .sort(([a, x], [b, y]) => y.length - x.length || a.localeCompare(b))
      .map(([key, list]) => alertsGroupBlock(key, list))
      .join("");
  return (
    body +
    missingNote +
    `<p class="live-small">来自 NICo 报告的设备健康状态，共 ${reported} 台设备，${read}。点击设备名称查看它的运行状态。</p>`
  );
}
registerPage("alerts", alertsRender);
deviceStatusAddNavChild("alerts", "告警", deviceStatusReload);
registerActions(
  "alerts.js",
  ["alerts-refresh", "alerts-view-alert", "alerts-view-device"],
  async (e) => {
    const el = e.target.closest('[data-live^="alerts-"]');
    if (!el || el.disabled) return;
    if (el.dataset.live === "alerts-refresh") return await deviceStatusReload();
    state.alertsView = el.dataset.alertsView;
    render();
  },
);
observeUI(
  "change",
  "alerts.js",
  (e) => {
    if (e.target.id?.startsWith("alerts-filter-")) {
      state.alertsFilters[e.target.id.slice(14)] = e.target.value;
      render();
    }
  },
  false,
);
observeUI(
  "input",
  "alerts.js",
  (e) => {
    if (e.target.id === "alerts-filter-search") {
      const position = e.target.selectionStart;
      state.alertsFilters.search = e.target.value;
      render();
      $("#alerts-filter-search").focus();
      $("#alerts-filter-search").setSelectionRange(position, position);
    }
  },
  false,
);
