"use strict";
// 操作记录: the append-only audit of device operations (rack_actions switch).
// Records are written by the server before and after each Core call; this page
// only reads them and offers no deletion.
state.rackActionRecords = null;
state.rackActionRecordsCatalog = null;
state.rackActionRecordsFilters = { action: "", status: "", search: "" };
const rackActionRecordsStatuses = {
  sent: ["已发送", "amber"],
  succeeded: ["已完成", "green"],
  failed: ["失败", "red"],
  unknown: ["结果未知", "amber"],
  refused: ["未执行", "gray"],
};
const rackActionRecordsEnabled = () =>
  state.readiness?.rack_actions === true &&
  state.readiness?.read_only !== true &&
  !document.body.classList.contains("read-only");
sectionReads.rackActionRecords = async () => {
  state.rackActionRecords = await api("/api/rack-actions/records?limit=500");
};
// Labels only; a catalog that cannot be read leaves the action IDs shown.
sectionReads.rackActionRecordsCatalog = async () => {
  state.rackActionRecordsCatalog = await api("/api/rack-actions/catalog");
};
async function rackActionRecordsReload() {
  if (!rackActionRecordsEnabled()) return render();
  await Promise.allSettled(
    ["rackActionRecords", "rackActionRecordsCatalog"].map((key) =>
      readSection(key, sectionReads[key]),
    ),
  );
}
// Opened from the operation dialog: show the records of that device.
async function rackActionRecordsShow(target) {
  state.rackActionRecordsFilters = { action: "", status: "", search: target };
  state.rackActionRecordsKeep = true;
  await navigate("action_records");
}
const rackActionRecordsLabel = (id, catalog) =>
  (catalog?.actions || []).find((a) => a.id === id)?.label || id;
const rackActionRecordsBadge = (status) =>
  badge(...(rackActionRecordsStatuses[status] || [status || "未报告", "gray"]));
function rackActionRecordsMatches(r, f, catalog) {
  const search = (f.search || "").trim().toLowerCase();
  return (
    (!f.action || r.action === f.action) &&
    (!f.status || r.status === f.status) &&
    (!search ||
      [
        ...(r.targets || []).flatMap((t) => [t.target, t.serial, t.name]),
        r.reason,
        r.operator,
        rackActionRecordsLabel(r.action, catalog),
      ]
        .join(" ")
        .toLowerCase()
        .includes(search))
  );
}
function rackActionRecordsFilter(records, f, catalog) {
  return [...(records || [])]
    .filter((r) => rackActionRecordsMatches(r, f, catalog))
    .sort((a, b) => (b.created || 0) - (a.created || 0));
}
const rackActionRecordsTargets = (r) =>
  (r.targets || [])
    .map(
      (t) =>
        `${esc(t.name || t.serial || t.target)}<span class="live-small live-code">${esc(t.target)}${t.serial && t.serial !== t.name ? " · SN " + esc(t.serial) : ""}</span>`,
    )
    .join("") || "—";
const rackActionRecordsJson = (title, value, open = false) =>
  `<details ${open ? "open" : ""}><summary>${esc(title)}</summary><pre class="live-code rack-action-records-json">${esc(JSON.stringify(value ?? null, null, 2))}</pre></details>`;
function rackActionRecordsPage() {
  const title = "操作记录",
    description = "查看对设备执行过的操作、检查结果和读回状态。";
  if (!state.rackOperations || !rackActionRecordsEnabled())
    return (
      heading(title, description) +
      '<div class="live-empty">此页面未在当前站点启用。</div>'
    );
  let body = heading(
    title,
    description,
    button("刷新数据", "rack-action-records-refresh"),
  );
  const data = state.rackActionRecords,
    catalog = state.rackActionRecordsCatalog,
    error = state.readErrors?.rackActionRecords;
  if (error)
    body += `<div class="live-error" role="alert">操作记录读取失败：${esc(error)}</div>`;
  if (!data)
    return (
      body + (error ? "" : '<div class="live-empty">正在读取操作记录…</div>')
    );
  const all = data.records || [];
  if (!all.length)
    return (
      body +
      '<div class="live-note">还没有操作记录。在<button class="link-button" data-page="servers">服务器</button>、交换机或供电框页面对设备执行操作后，每台设备的每次操作都会记录在这里。</div>'
    );
  const f = state.rackActionRecordsFilters,
    visible = rackActionRecordsFilter(all, f, catalog),
    actions = [...new Set(all.map((r) => r.action))];
  body += `<div class="summary-strip device-status-summary"><div><small>记录总数</small><strong>${all.length}</strong></div><div><small>已完成</small><strong>${all.filter((r) => r.status === "succeeded").length}</strong></div><div><small>结果未知</small><strong>${all.filter((r) => r.status === "unknown" || r.status === "sent").length}</strong></div><div><small>失败 / 未执行</small><strong>${all.filter((r) => r.status === "failed" || r.status === "refused").length}</strong></div></div>`;
  body += `<div class="equipment-device-filters">${selectField(
    "rack-action-records-filter-action",
    "操作",
    [
      ["", "全部操作"],
      ...actions.map((id) => [id, rackActionRecordsLabel(id, catalog)]),
    ],
    f.action,
  )}${selectField(
    "rack-action-records-filter-status",
    "结果",
    [
      ["", "全部"],
      ...Object.entries(rackActionRecordsStatuses).map(([k, [label]]) => [
        k,
        label,
      ]),
    ],
    f.status,
  )}${inputField("rack-action-records-filter-search", "搜索对象 ID、SN、名称、原因或操作者", f.search)}</div>`;
  const rows = visible.map(
    (r) =>
      `<tr><td>${esc(when(r.created))}</td><td><button class="link-button" data-live="rack-action-records-open" data-id="${esc(r.id)}">${esc(rackActionRecordsLabel(r.action, catalog))}</button><span class="live-small live-code">${esc(r.action)}</span></td><td>${rackActionRecordsTargets(r)}</td><td><span class="live-code">${esc(r.operator || "—")}</span></td><td>${esc(r.reason || "—")}</td><td>${rackActionRecordsBadge(r.status)}</td><td>${esc(r.core_message || "—")}</td></tr>`,
  );
  return (
    body +
    '<div class="rack-action-records-table">' +
    table(
      ["时间", "操作", "对象", "操作者", "原因", "结果", "NICo 消息"],
      rows,
    ) +
    "</div>" +
    `<p class="live-small">共 ${all.length} 条，最新在前，显示 ${visible.length} 条。记录只追加、不删除；“结果未知”表示读回无法确认，请先核对设备状态，不要直接重复提交。</p>`
  );
}
function rackActionRecordsDetail(id) {
  const r = (state.rackActionRecords?.records || []).find((x) => x.id === id);
  if (!r) return toast("记录已变化，请刷新。");
  const catalog = state.rackActionRecordsCatalog;
  state.wizard = { resource: "rack-action-records", id };
  modal(
    rackActionRecordsLabel(r.action, catalog),
    "操作记录 · " + when(r.created),
    defs([
      ["记录 ID", `<span class="live-code">${esc(r.id)}</span>`],
      [
        "操作",
        `${esc(rackActionRecordsLabel(r.action, catalog))} <span class="live-code">${esc(r.action)}</span>`,
      ],
      ["对象", rackActionRecordsTargets(r)],
      ["操作者", `<span class="live-code">${esc(r.operator || "—")}</span>`],
      ["原因", esc(r.reason || "—")],
      ["结果", rackActionRecordsBadge(r.status)],
      ["NICo 消息", esc(r.core_message || "—")],
      ["创建时间", esc(when(r.created))],
      ["更新时间", esc(when(r.updated))],
    ]) +
      rackActionRecordsJson("参数", r.params) +
      rackActionRecordsJson("执行前检查", r.checks, true) +
      rackActionRecordsJson("读回状态", r.readback, true),
    button("关闭", "close", true),
  );
}
registerPage("action_records", rackActionRecordsPage);
registerActions(
  "rack_action_records.js",
  ["rack-action-records-refresh", "rack-action-records-open"],
  async (e) => {
    const el = e.target.closest('[data-live^="rack-action-records-"]');
    if (!el || el.disabled) return;
    if (el.dataset.live === "rack-action-records-open")
      return rackActionRecordsDetail(el.dataset.id);
    return await rackActionRecordsReload();
  },
);
observeUI(
  "change",
  "rack_action_records.js",
  (e) => {
    const key = {
      "rack-action-records-filter-action": "action",
      "rack-action-records-filter-status": "status",
    }[e.target.id];
    if (key) {
      state.rackActionRecordsFilters[key] = e.target.value;
      render();
    }
  },
  false,
);
observeUI(
  "input",
  "rack_action_records.js",
  (e) => {
    if (e.target.id === "rack-action-records-filter-search") {
      const position = e.target.selectionStart;
      state.rackActionRecordsFilters.search = e.target.value;
      render();
      $("#rack-action-records-filter-search").focus();
      $("#rack-action-records-filter-search").setSelectionRange(
        position,
        position,
      );
    }
  },
  false,
);
deviceStatusAddNavChild("action_records", "操作记录", async () => {
  if (state.rackActionRecordsKeep) state.rackActionRecordsKeep = false;
  else state.rackActionRecordsFilters = { action: "", status: "", search: "" };
  await rackActionRecordsReload();
});
// The page joins the navigation only where operations are enabled; the shared
// hook above added it with the other children, so take it out otherwise.
registerHook("readiness", (readiness) => {
  if (rackActionRecordsEnabled()) return;
  for (const [, pages] of groups) {
    const index = pages.indexOf("action_records");
    if (index >= 0) pages.splice(index, 1);
  }
});
