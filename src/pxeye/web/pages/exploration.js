"use strict";
// 发现诊断: what NICo site exploration found at each BMC address it probed. It
// only reads; the addresses and credentials it depends on are maintained in
// site settings and device management, which this page points to.
state.exploration = null;
state.explorationFilters = { result: "", search: "" };
sectionReads.exploration = async () => {
  state.exploration = await api("/api/exploration");
};
async function explorationReload() {
  await Promise.allSettled(
    ["resources", "equipment", "exploration"].map((key) =>
      readSection(key, sectionReads[key]),
    ),
  );
}
const explorationTime = (value) => {
  const t = value ? new Date(value) : null;
  return t && !isNaN(t) ? t.toLocaleString("zh-CN", { hour12: false }) : "—";
};
// The console's own device for an address: a declared or observed port of a
// managed device first, then a server known to the resources view.
function explorationDevice(address) {
  if (!address) return null;
  const d = (state.equipment?.devices || []).find((x) =>
    (x.ports || []).some(
      (p) =>
        p.target_ip === address ||
        (p.observed || []).some((o) => (o.addresses || []).includes(address)),
    ),
  );
  if (d)
    return {
      label: d.name || d.serial || d.id,
      serial: d.serial || "",
      open:
        d.kind === "server" && d.serial
          ? `data-live="device-detail" data-serial="${esc(d.serial)}"`
          : `data-live="eq-detail" ${eqAttr(d.id)}`,
    };
  const r = (state.resources?.devices || []).find((x) => x.bmc_ip === address);
  return r
    ? {
        label: r.serial,
        serial: "",
        open: `data-live="device-detail" data-serial="${esc(r.serial)}"`,
      }
    : null;
}
function explorationDeviceCell(e) {
  const d = explorationDevice(e.address);
  const reported = e.serial
    ? `<span class="live-small">BMC 报告 SN ${esc(e.serial)}${e.model ? " · " + esc(e.model) : ""}</span>`
    : "";
  return d
    ? `<button class="link-button" ${d.open}>${esc(d.label)}</button>${d.serial && d.serial !== d.label ? `<span class="live-small">${esc(d.serial)}</span>` : ""}${reported}`
    : `<span class="live-small">未关联设备</span>${reported}`;
}
function explorationResult(e) {
  if (e.failed)
    return (
      badge(e.error.code || e.error.type || "探测失败", "red") +
      (e.error.text || e.error.type
        ? `<span class="live-small">${esc(e.error.text || e.error.type)}</span>`
        : "")
    );
  if (!e.endpoint_type && !e.vendor && e.latency_seconds == null)
    return badge("未报告");
  return (
    badge("成功", "green") +
    (e.latency_seconds != null
      ? `<span class="live-small">耗时 ${esc(e.latency_seconds.toFixed(1))} 秒</span>`
      : "")
  );
}
function explorationMatches(e) {
  const f = state.explorationFilters;
  return (
    (!f.result || (f.result === "failed" ? e.failed : !e.failed)) &&
    (!f.search ||
      [
        e.address,
        e.serial,
        e.error?.code,
        e.error?.type,
        explorationDevice(e.address)?.label,
      ]
        .join(" ")
        .toLowerCase()
        .includes(f.search.toLowerCase()))
  );
}
function explorationLastRun(run) {
  if (!run) return badge("未报告");
  return (
    `${esc(explorationTime(run.finished_at || run.started_at))}` +
    `<span class="live-small">${run.success ? badge("完成", "green") : badge("失败", "red")}${run.error ? " " + esc(run.error) : ""}</span>`
  );
}
// A failed run is the first thing to show: when Site Explorer cannot run at all
// (for example without BMC credentials) there are no endpoints to explain it.
function explorationRunFailure(run) {
  if (!run || run.success !== false) return "";
  const hint =
    run.failure_category === "missing_credentials"
      ? "站点发现没有可用的 BMC 凭据，因此不会探测任何地址；请在可写的控制台的站点设置中初始化站点凭据。"
      : "";
  return `<div class="live-error" role="alert">NICo 站点发现上次运行失败（${esc(explorationTime(run.finished_at || run.started_at))}）：${esc(run.error || "未报告原因")}${run.failure_category ? `<span class="live-small">类别 ${esc(run.failure_category)}</span>` : ""}${hint ? `<span class="live-small">${hint}</span>` : ""}</div>`;
}
function explorationPage() {
  const title = "发现诊断",
    description =
      "查看 NICo 站点发现对每个 BMC 地址的探测结果，定位设备为什么没有被发现。";
  if (!state.rackOperations)
    return (
      heading(title, description) +
      '<div class="live-empty">此页面未在当前站点启用。</div>'
    );
  let body = heading(
    title,
    description,
    button("刷新数据", "exploration-refresh"),
  );
  const data = state.exploration,
    error = state.readErrors?.exploration;
  if (error)
    body += `<div class="live-error" role="alert">NICo 站点发现报告读取失败：${esc(error)}</div>`;
  if (!data)
    return (
      body +
      (error ? "" : '<div class="live-empty">正在读取站点发现报告…</div>')
    );
  const all = data.endpoints || [];
  body += explorationRunFailure(data.last_run);
  if (!all.length)
    return (
      body +
      `<div class="live-note">NICo 尚未探测任何 BMC 地址。站点发现只探测 NICo 已知的 BMC 地址：请在<button class="link-button" data-page="site">站点设置</button>中检查站点发现与 BMC 凭据，并在<button class="link-button" data-page="devices">设备管理</button>中登记设备的 BMC 地址。</div>${explorationRunNote(data)}`
    );
  const failed = all.filter((e) => e.failed).length,
    f = state.explorationFilters;
  body += `<div class="summary-strip device-status-summary exploration-summary"><div><small>端点总数</small><strong>${all.length}</strong></div><div><small>探测成功</small><strong>${all.length - failed}</strong></div><div><small>探测失败</small><strong>${failed}</strong></div><div><small>上次探测</small><strong>${explorationLastRun(data.last_run)}</strong></div></div>`;
  body += `<div class="equipment-device-filters">${selectField(
    "exploration-filter-result",
    "结果",
    [
      ["", "全部"],
      ["failed", "失败"],
      ["ok", "成功"],
    ],
    f.result,
  )}${inputField("exploration-filter-search", "搜索地址、SN 或错误码", f.search)}</div>`;
  const rows = all
    .filter(explorationMatches)
    .map(
      (e) =>
        `<tr><td><code>${esc(e.address || "—")}</code>${e.managed_host ? '<span class="live-small">已组成受管主机</span>' : ""}</td><td>${explorationDeviceCell(e)}</td><td>${esc(e.endpoint_type || "—")}<span class="live-small">${esc(e.vendor || "")}</span></td><td>${esc(e.preingestion_state || "—")}</td><td>${explorationResult(e)}</td><td>${esc(e.error?.mitigation || "—")}</td></tr>`,
    );
  return (
    body +
    '<div class="exploration-table">' +
    table(
      ["地址", "设备", "类型 / 厂商", "接入阶段", "探测结果", "处理建议"],
      rows,
    ) +
    "</div>" +
    explorationRunNote(data)
  );
}
function explorationRunNote(data) {
  const run = data.last_run;
  const counts =
    run && run.explorations != null
      ? `上次运行探测 ${run.explorations} 次，成功 ${run.succeeded ?? "—"}，失败 ${run.failed ?? "—"}。`
      : "";
  return `<p class="live-small">来自 NICo 站点发现报告（GetSiteExplorationReport），读取于 ${esc(when(data.observed_at))}。${esc(counts)}BMC 地址与凭据在站点设置和设备管理中维护。</p>`;
}
registerPage("exploration", explorationPage);
registerActions("exploration.js", ["exploration-refresh"], async (e) => {
  const el = e.target.closest('[data-live="exploration-refresh"]');
  if (!el || el.disabled) return;
  return await explorationReload();
});
observeUI(
  "change",
  "exploration.js",
  (e) => {
    if (e.target.id === "exploration-filter-result") {
      state.explorationFilters.result = e.target.value;
      render();
    }
  },
  false,
);
observeUI(
  "input",
  "exploration.js",
  (e) => {
    if (e.target.id === "exploration-filter-search") {
      const position = e.target.selectionStart;
      state.explorationFilters.search = e.target.value;
      render();
      $("#exploration-filter-search").focus();
      $("#exploration-filter-search").setSelectionRange(position, position);
    }
  },
  false,
);
deviceStatusAddNavChild("exploration", "发现诊断", explorationReload);
