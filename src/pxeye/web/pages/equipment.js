"use strict";
// Typed equipment extends the existing console. Server task IDs and editors stay intact.
const equipmentKinds = {
  server: "服务器",
  switch: "NVLink 交换机",
  power_shelf: "供电框",
  dpu: "DPU",
  other: "其他设备",
  unknown: "待识别",
};
const equipmentStates = {
  draft: "本地规划",
  declared: "已同步声明",
  managed: "已纳管",
  server: "服务器",
  requesting: "请求中",
  needs_attention: "待核对",
  synced: "声明已读回",
  reserved: "Static 已读回",
};
state.equipment = null;
state.equipmentDeviceSelection = [];
state.equipmentDiscoverySelection = [];
state.equipmentDiscoveryResults = {};
state.equipmentDiscoveryBatch = null;
state.equipmentDiscoveryReading = false;
state.equipmentFilters = { kind: "", rack: "", status: "", search: "" };
sectionReads.equipment = async () => {
  state.equipment = await api("/api/equipment");
};
const eqAttr = (id) => `data-id="${esc(id)}"`;
const eqText = (id, label, value = "", extra = "") =>
  inputField("eq-" + id, label, value, extra);
const eqArea = (id, label, value) =>
  `<label>${esc(label)}<textarea class="input" id="eq-${id}" rows="4">${esc(value)}</textarea></label>`;
const eqError = () =>
  '<div id="resource-error" class="live-error" role="alert"></div>';
const eqNames = (ports) =>
  ports
    .map(
      (p) =>
        `${esc(p.role_label)} ${esc(p.observed?.flatMap((o) => o.addresses).join(", ") || p.target_ip || "待分配")}`,
    )
    .join("<br>");
const equipmentControllerRoles = new Set([
  "host_bmc",
  "switch_bmc",
  "pmc",
  "dpu_bmc",
]);
const equipmentPortAddress = (p) =>
  p.observed?.flatMap((o) => o.addresses)[0] || p.target_ip || "";
function equipmentManagementAddresses(d) {
  const ports = d.ports.filter((p) => !equipmentControllerRoles.has(p.role));
  const port =
    ports.find((p) => p.primary) || ports.find((p) => equipmentPortAddress(p));
  return port
    ? `${esc(port.role_label)} ${esc(equipmentPortAddress(port) || "待分配")}`
    : "待分配";
}
const equipmentBmcAddresses = (d, native) =>
  d.kind === "server" && native
    ? deviceBmcAddress(native)
    : eqNames(d.ports.filter((p) => equipmentControllerRoles.has(p.role))) ||
      "—";
function equipmentOnlineState(d) {
  const value = String(d.power_state ?? "")
    .toLowerCase()
    .replaceAll("_", "");
  if (["on", "poweron", "poweredon"].includes(value))
    return ["online", "在线", "NICo 最近回报设备开机"];
  if (["off", "poweroff", "poweredoff"].includes(value))
    return ["offline", "离线", "NICo 最近回报设备关机"];
  return ["unknown", "未知", "NICo 尚未回报电源状态"];
}
function equipmentOnline(d) {
  const [kind, label, detail] = equipmentOnlineState(d);
  return `<span class="equipment-online ${kind}" title="${esc(detail)}"><i aria-hidden="true"></i><span>${label}</span></span>`;
}
async function equipmentReload() {
  await api("/api/resources/refresh", {});
  await Promise.allSettled([
    readSection("equipment", sectionReads.equipment),
    readSection("resources", sectionReads.resources),
  ]);
  render();
}
function equipmentMatches(row) {
  const f = state.equipmentFilters;
  return (
    (!f.kind ||
      row.kind === f.kind ||
      (f.kind === "dpu" && row.ports.some((p) => p.role.startsWith("dpu_")))) &&
    (!f.rack || row.rack_id === f.rack) &&
    (!f.status || row.status === f.status) &&
    (!f.search ||
      [
        row.serial,
        row.name,
        ...row.ports.flatMap((p) => [
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
function devicePage() {
  if (state.deviceView === "management-addresses") state.deviceView = "managed";
  const data = state.equipment,
    pending = state.deviceView === "equipment-endpoints",
    planning = state.deviceView === "equipment-planning";
  const tools = planning
    ? button("刷新规划", "planning-refresh") +
      button("导入规划", "planning-import") +
      button("下载模板", "planning-template") +
      button("新增规划", "planning-new", true)
    : pending
      ? button("刷新发现结果", "eq-refresh", true)
      : button("刷新数据", "eq-refresh") +
        button("导入设备", "eq-choose-import") +
        button("新增设备", "eq-choose-new", true) +
        button("下载模板", "eq-choose-template");
  let body =
    heading(
      "设备管理",
      planning
        ? "导入设备规划，按序列号与纳管设备对比。"
        : pending
          ? "发现通过 DHCP 获取临时管理地址的设备。"
          : "查看纳管设备，维护地址和安装规划。",
      tools,
    ) +
    `<div class="live-tabs">${button("发现设备", "eq-endpoints", pending)}${button("纳管设备", "eq-managed", !pending && !planning)}${button("设备规划", "planning-tab", planning)}</div>`;
  if (planning) return body + equipmentPlanningTable();
  if (!data) return body + '<div class="live-empty">正在读取设备与接口…</div>';
  if (data.errors.length)
    body += `<div class="live-error">${esc(data.errors.join("；"))}</div>`;
  if (pending) return body + equipmentDiscovery(data.endpoints);
  const f = state.equipmentFilters;
  body += `<div class="live-editor-grid">${selectField("eq-filter-kind", "设备类型", [["", "全部类型"], ...Object.entries(equipmentKinds).filter(([k]) => k !== "unknown")], f.kind)}${selectField("eq-filter-rack", "机柜", [["", "全部机柜"], ...[...new Set(data.devices.map((d) => d.rack_id).filter(Boolean))].map((id) => [id, id])], f.rack)}${selectField("eq-filter-status", "纳管状态", [["", "全部状态"], ...["draft", "declared", "managed", "server"].map((k) => [k, equipmentStates[k]])], f.status)}${eqText("filter-search", "搜索 SN、名称、MAC 或 IP", f.search)}</div>`;
  const selected = state.equipmentDeviceSelection.length,
    disabled = selected ? "" : "disabled";
  const matchable =
    selected > 0 &&
    selected <= 50 &&
    !state.equipmentPlanningMatching &&
    data.devices
      .filter((d) => state.equipmentDeviceSelection.includes(d.id))
      .every((d) => d.kind === "server" && !d.address_only);
  body += `<div class="equipment-batch-bar"><span>已选 ${selected} 台</span><div class="live-tools">${button("一键匹配", "planning-match", false, matchable ? "" : "disabled")}${button("更新 BMC 地址", "eq-batch-bmc", true, disabled)}${button("更新管理地址", "eq-batch-management", false, disabled)}${button("刷新设备详情", "eq-batch-refresh", false, disabled)}</div></div>`;
  const rows = data.devices.filter(equipmentMatches).map((d) => {
    const server = d.kind === "server" && !d.address_only,
      native = state.resources?.devices.find((x) => x.serial === d.serial);
    const detail = d.address_only
      ? `data-live="address-device" ${eqAttr(d.id)}`
      : server
        ? `data-live="device-detail" data-serial="${esc(d.serial)}"`
        : `data-live="eq-detail" ${eqAttr(d.id)}`;
    const status = d.address_only
      ? "地址规划"
      : server
        ? native?.executable
          ? "可重装"
          : native?.first_install_ready
            ? "硬件就绪"
            : native?.machine_id
              ? "主机已关联"
              : "已登记"
        : equipmentStates[d.status] || d.status;
    const child = d.ports.filter((p) => p.role.startsWith("dpu_"));
    return `<tr><td><input type="checkbox" name="eq-device" value="${esc(d.id)}" ${state.equipmentDeviceSelection.includes(d.id) ? "checked" : ""} aria-label="选择 ${esc(d.serial)}"></td><td><button class="link-button" ${detail}>${esc(d.name || d.serial || d.id)}</button><span class="live-small">${esc(d.serial)}</span></td><td>${esc(equipmentKinds[d.kind])}${
      child.length
        ? `<details><summary>DPU 子接口 · ${child.length}</summary>${table(
            ["角色", "MAC / 地址"],
            child.map(
              (p) =>
                `<tr><td>${esc(p.role_label)}</td><td>${esc(p.mac_address)}<span class="live-small">${esc(p.observed?.flatMap((o) => o.addresses).join(", ") || p.target_ip || "待分配")}</span></td></tr>`,
            ),
          )}</details>`
        : ""
    }</td><td>${equipmentManagementAddresses(d)}</td><td>${equipmentBmcAddresses(d, native)}</td><td>${badge(status)}${d.native_state ? `<span class="live-small">${esc(d.native_state)}</span>` : ""}</td><td>${esc(d.rack_id || "—")}</td><td><div class="device-row-actions">${button("地址管理", "address-device", false, eqAttr(d.id))}${server ? button("系统配置", "device-edit", false, eqAttr(d.legacy_id)) : d.address_only ? "" : !d.unplanned ? button("系统配置", "eq-edit", false, eqAttr(d.id)) + button("同步至 NICo", "eq-sync-preview", false, `${eqAttr(d.id)} ${!d.can_sync ? "disabled" : ""}`) : button("查看", "eq-detail", false, eqAttr(d.id))}</div></td><td>${equipmentOnline(d)}</td></tr>`;
  });
  return (
    body +
    table(
      [
        "选择",
        "设备 / SN",
        "类型",
        "管理地址",
        "BMC 地址",
        "纳管状态",
        "机柜",
        "操作",
        "在线",
      ],
      rows,
    ).replace(
      "<th>选择</th>",
      '<th><input type="checkbox" name="eq-all" aria-label="选择当前列表全部设备"></th>',
    ) +
    bmcUpdateHistory()
  );
}
function equipmentBatchRows(rows) {
  return table(
    ["设备 / SN", "接口", "当前地址 → 规划地址", "结果"],
    rows.map(
      (row) =>
        `<tr><td>${esc(row.serial || row.device_id)}</td><td>${esc(row.role_label || "—")}<span class="live-small live-code">${esc(row.mac_address || "")}</span></td><td>${esc(row.current_ip || "—")} → ${esc(row.target_ip || "—")}</td><td>${row.passed ? badge("可执行") : `<span class="live-error">${esc(row.detail || "不可执行")}</span>`}</td></tr>`,
    ),
  );
}
const bmcTicket = () =>
  globalThis.crypto?.randomUUID?.() ||
  "bmc-" + Date.now() + "-" + Math.random().toString(36).slice(2);
const bmcPhases = [
  ["check", "检查地址与身份"],
  ["update", "更新 BMC"],
  ["verify", "验证新地址"],
  ["sync", "同步管理记录"],
];
function bmcStepper(steps) {
  return `<ol class="bmc-stepper" aria-label="BMC 地址更新步骤">${steps.map((step, i) => `<li class="bmc-step ${esc(step.status)}" ${step.status === "running" ? 'aria-current="step"' : ""}><span class="bmc-step-dot" aria-hidden="true"></span><span class="bmc-step-label">${esc(step.label)}</span><span class="bmc-step-status">${esc({ completed: "已完成", running: "进行中", waiting: "待执行", submitted: "等待确认", failed: "需核对" }[step.status] || "待执行")}</span><span class="bmc-step-detail">${esc(step.detail || "")}</span></li>`).join("")}</ol>`;
}
function bmcProgressContent(result) {
  const done = result.rows.reduce(
      (n, r) => n + r.steps.filter((s) => s.status === "completed").length,
      0,
    ),
    total = result.rows.length * 4;
  return `<div class="bmc-progress-summary"><div><span class="bmc-eyebrow">BMC 地址更新</span><strong>${result.running ? "正在执行" : result.completed === result.total ? "更新完成" : "部分步骤需要核对"}</strong><span class="live-small">已完成 ${done} / ${total} 个步骤 · ${result.completed} / ${result.total} 个接口已更新</span></div><span class="bmc-summary-dot ${result.running ? "running" : result.completed === result.total ? "completed" : "failed"}" aria-hidden="true"></span></div><progress class="bmc-progress-meter" value="${done}" max="${total}" aria-label="已完成步骤"></progress><div class="bmc-progress-cards">${result.rows.map((row) => `<section class="bmc-progress-card"><header><div><strong>${esc(row.serial || row.mac_address)}</strong><span class="live-small">${esc(row.role_label)} · ${esc(row.mac_address)}</span></div><div class="bmc-address-change"><span>${esc(row.current_ip)}</span><span class="bmc-address-arrow" aria-hidden="true">→</span><strong>${esc(row.target_ip)}</strong></div></header>${bmcStepper(row.steps)}<div class="bmc-operation-detail ${row.status === "bmc_needs_attention" ? "live-error" : ""}" role="status">${esc(row.detail)}</div>${row.status === "bmc_needs_attention" && !row.patch_attempted ? `<div class="bmc-recovery">${button("重新检查并更新", "eq-bmc-restart", false, eqAttr(row.id))}<span class="live-small">之前尚未发送 BMC 写入；点击后重新检查并执行。</span></div>` : ""}${row.status === "bmc_needs_attention" && row.patch_attempted ? `<div class="bmc-recovery">${button("核对并完成同步", "eq-bmc-finish", false, eqAttr(row.id))}<span class="live-small">验证新地址后继续同步记录，不重复 BMC 写入。</span></div>` : ""}</section>`).join("")}</div>`;
}
function bmcShowProgress(result) {
  state.wizard = {
    resource: "bmc-progress",
    batchId: result.id,
    pollTicket: bmcTicket(),
  };
  modal(
    "更新 BMC 地址",
    "关闭窗口后继续执行；可从近期更新记录再次查看。",
    `<div id="bmc-progress-content" aria-live="polite">${bmcProgressContent(result)}</div>` +
      eqError(),
    button("关闭", "close"),
  );
  if (result.running) bmcPoll(result.id, state.wizard.pollTicket);
}
async function bmcPoll(id, ticket) {
  await new Promise((resolve) => setTimeout(resolve, 3000));
  if (
    state.wizard?.resource !== "bmc-progress" ||
    state.wizard.batchId !== id ||
    state.wizard.pollTicket !== ticket ||
    !state.modal
  )
    return;
  try {
    const result = await api(
      "/api/equipment/bmc-jobs/" + encodeURIComponent(id),
    );
    if (
      state.wizard?.batchId !== id ||
      state.wizard.pollTicket !== ticket ||
      !$("#bmc-progress-content")
    )
      return;
    const active = document.activeElement,
      focusId = active?.dataset.live,
      focusRow = active?.dataset.id;
    $("#bmc-progress-content").innerHTML = bmcProgressContent(result);
    if (focusId && focusRow)
      [...document.querySelectorAll("#bmc-progress-content [data-live]")]
        .find((el) => el.dataset.live === focusId && el.dataset.id === focusRow)
        ?.focus();
    if (result.running) bmcPoll(id, ticket);
    else await equipmentReload();
  } catch (error) {
    if (state.wizard?.batchId === id && state.wizard.pollTicket === ticket) {
      const target = $("#resource-error");
      if (target) target.textContent = "进度读取暂时失败：" + error.message;
      bmcPoll(id, ticket);
    }
  }
}
async function equipmentBatchPreview(scope) {
  if (scope !== "bmc") {
    const r = await api("/api/equipment/batch-redfish-preview", {
      device_ids: state.equipmentDeviceSelection,
      scope,
    });
    state.wizard = { resource: "eq-batch-redfish", preview: r };
    modal(
      "更新管理地址",
      `Redfish 预检通过 ${r.ready} / ${r.rows.length}`,
      equipmentBatchRows(r.rows) + eqError(),
      button("取消", "close"),
    );
    return;
  }
  const selection = [...state.equipmentDeviceSelection];
  state.wizard = { resource: "bmc-confirm", selection };
  modal(
    "确认更新 BMC 地址",
    `已选择 ${selection.length} 台设备`,
    `<div class="live-note live-warning">确认后将检查已保存的地址规划、目标地址占用和设备身份。通过检查的设备会立即关闭 BMC DHCP、写入规划的静态地址，并同步 NICo 管理记录；地址切换时管理连接可能短暂中断。未通过检查的设备不会执行。</div>` +
      eqError(),
    button("取消", "close") +
      button("确认并开始更新", "eq-batch-confirm", true),
  );
}
async function equipmentBatchConfirm() {
  const selection = [...state.wizard.selection],
    marker = bmcTicket();
  state.wizard = { resource: "bmc-preview", marker };
  modal(
    "更新 BMC 地址",
    "正在执行已确认的更新",
    bmcStepper(
      bmcPhases.map(([key, label], i) => ({
        key,
        label,
        status: i ? "waiting" : "running",
        detail: i ? "" : "正在检查规划、地址占用与设备身份…",
      })),
    ) + eqError(),
    button("关闭", "close"),
  );
  const preview = await api("/api/equipment/batch-redfish-preview", {
    device_ids: selection,
    scope: "bmc",
  });
  if (state.wizard?.marker !== marker) return;
  if (!preview.ready) {
    state.wizard = { resource: "bmc-preview-failed", preview };
    modal(
      "更新 BMC 地址",
      `检查通过 0 / ${preview.rows.length} 个接口`,
      bmcStepper(
        bmcPhases.map(([key, label], i) => ({
          key,
          label,
          status: i ? "waiting" : "failed",
          detail: i ? "" : "检查未通过，请查看下方原因。",
        })),
      ) +
        equipmentBatchRows(preview.rows) +
        eqError(),
      button("关闭", "close"),
    );
    return;
  }
  const r = await api("/api/equipment/batch-redfish-apply", {
    preflight_id: preview.id,
    confirm: true,
  });
  if (state.wizard?.marker === marker) bmcShowProgress(r);
  else toast("BMC 更新已提交，可从近期记录查看进度。");
  await equipmentReload();
}
function bmcUpdateHistory() {
  const records = (state.equipment?.management_addresses?.operations || [])
    .filter((r) => r.action === "redfish_bmc")
    .sort((a, b) => b.created_at - a.created_at);
  const batches = [...new Set(records.map((r) => r.batch_id))].slice(0, 10);
  return batches.length
    ? `<section class="subsection bmc-history"><h3>近期 BMC 地址更新</h3>${table(
        ["提交时间", "设备", "进度", "操作"],
        batches.map((id) => {
          const rows = records.filter((r) => r.batch_id === id),
            done = rows.filter((r) => r.status === "verified").length;
          return `<tr><td>${when(rows[0].created_at)}</td><td>${esc(rows.map((r) => r.serial || r.mac_address).join("、"))}</td><td><span class="bmc-history-dot ${done === rows.length ? "completed" : rows.some((r) => r.status === "bmc_running") ? "running" : "failed"}" aria-hidden="true"></span>${done} / ${rows.length} 个接口完成</td><td>${button("查看进度", "eq-bmc-progress", false, eqAttr(id))}</td></tr>`;
        }),
      )}</section>`
    : "";
}
async function equipmentBatchRefresh() {
  const selection = [...state.equipmentDeviceSelection],
    marker = bmcTicket();
  state.wizard = { resource: "eq-batch-refresh", marker };
  modal(
    "刷新设备详情",
    `已启动 ${selection.length} 台设备的后台刷新`,
    `<div class="live-empty">正在通过 Redfish 读取设备身份和型号，请稍候…</div><div class="live-note">可以关闭窗口继续使用页面；刷新完成后设备信息会自动更新。</div>` +
      eqError(),
    button("关闭", "close"),
  );
  const r = await api("/api/equipment/batch-refresh", {
    device_ids: selection,
  });
  await equipmentReload();
  if (state.wizard?.marker !== marker) {
    toast(
      `设备详情刷新完成：${r.rows.filter((row) => row.passed).length} / ${r.rows.length} 台成功。`,
    );
    return;
  }
  state.wizard = { resource: "eq-batch-refresh-result", result: r };
  modal(
    "刷新设备详情",
    `完成 ${r.rows.filter((row) => row.passed).length} / ${r.rows.length} 台`,
    table(
      ["设备 / SN", "地址", "结果", "刷新时间"],
      r.rows.map(
        (row) =>
          `<tr><td>${esc(row.serial || row.device_id)}</td><td>${esc(row.address || "—")}</td><td>${row.passed ? esc([equipmentKinds[row.kind], row.model].filter(Boolean).join(" · ") || "已刷新") : `<span class="live-error">${esc(row.detail)}</span>`}</td><td>${row.refreshed_at ? when(row.refreshed_at) : "—"}</td></tr>`,
      ),
    ) + eqError(),
    button("关闭", "close"),
  );
}
function equipmentOperationTable(operations) {
  return operations.length
    ? "<h3>近期执行记录</h3>" +
        table(
          ["时间", "操作", "状态", "操作"],
          operations
            .slice(-20)
            .reverse()
            .map(
              (o) =>
                `<tr><td>${when(o.created_at)}</td><td>${esc(o.action === "sync" ? "同步至 NICo" : "固定当前 IP")}</td><td>${esc(equipmentStates[o.status] || o.status)}</td><td>${button("只读核对", "eq-reconcile", false, eqAttr(o.id))}</td></tr>`,
            ),
        )
    : "";
}
function equipmentDiscoveryCandidates(rows) {
  return rows.filter(
    (a) =>
      a.last_dhcp &&
      !a.device_id &&
      !a.machine_id &&
      !a.dpu_machine_id &&
      !a.switch_id &&
      !a.power_shelf_id,
  );
}
const equipmentDiscoveryAddresses = (row) =>
  row.addresses.filter((ip) => /^\d+\.\d+\.\d+\.\d+$/.test(ip));
const equipmentDiscoveryReadable = (row) =>
  !row.identity_conflict &&
  row.segment_type === "UNDERLAY" &&
  row.network_name !== "static-assignments" &&
  row.kind !== "dpu" &&
  !["nvos", "host"].includes(row.role) &&
  equipmentDiscoveryAddresses(row).length > 0;
function equipmentDiscoveryProof(row) {
  const result = state.equipmentDiscoveryResults[row.interface_id];
  return result?.passed &&
    result.mac_address === row.mac_address &&
    row.addresses.includes(result.ip) &&
    result.verified_at > Date.now() / 1000 - 900
    ? result
    : null;
}
function equipmentDiscovery(rows) {
  const candidates = equipmentDiscoveryCandidates(rows);
  const networks = [
    ...new Set(candidates.map((a) => a.network_name).filter(Boolean)),
  ].sort();
  const visible = candidates.filter(
    (a) => !state.candidateNetwork || a.network_name === state.candidateNetwork,
  );
  const selectable = visible.filter(equipmentDiscoveryReadable);
  state.equipmentDiscoverySelection = state.equipmentDiscoverySelection.filter(
    (id) => selectable.some((a) => a.interface_id === id),
  );
  const selected = state.equipmentDiscoverySelection.length,
    reading = state.equipmentDiscoveryReading;
  const note =
    '<div class="live-note">设备上电后，管理控制器发出 DHCP 请求，NICo 按请求来源匹配子网并从动态地址池分配临时地址。选择端点并使用 BMC / PMC 账号读取序列号、设备类型和硬件信息，确认后加入纳管设备。</div>';
  const filter = `<div class="live-form" style="margin-bottom:18px">${selectField("eq-discovery-network", "发现子网", [["", "全部发现子网"], ...networks.map((n) => [n, n])], state.candidateNetwork)}</div>`;
  const bar = `<div class="equipment-batch-bar"><span>已选 ${selected} 台 · 每批最多 50 台</span><div class="live-tools">${state.equipmentDiscoveryBatch ? button("查看获取结果", "eq-discovery-results") : ""}${button(reading ? "正在获取设备信息…" : "批量获取设备信息", "eq-identify-many", false, !reading && selected > 0 && selected <= 50 ? "" : "disabled")}</div></div>`;
  const rowsHtml = visible.map((a) => {
    const result = equipmentDiscoveryProof(a),
      failure = state.equipmentDiscoveryResults[a.interface_id],
      readable = equipmentDiscoveryReadable(a);
    const info = a.identity_conflict
      ? "接口归属冲突"
      : result
        ? `${esc(result.identity.serial)}<span class="live-small">${esc([equipmentKinds[result.identity.kind], result.identity.model].filter(Boolean).join(" · "))}</span>`
        : `待获取<span class="live-small">${esc(failure?.passed === false ? failure.detail : "获取后显示序列号和设备类型")}</span>`;
    return `<tr><td><input type="checkbox" name="eq-discovery-device" value="${esc(a.interface_id)}" ${state.equipmentDiscoverySelection.includes(a.interface_id) ? "checked" : ""} ${readable && !reading ? "" : "disabled"} aria-label="选择 ${esc(a.mac_address)}"></td><td>${bmcLink(a.addresses[0])}<span class="live-small live-code">${esc(a.mac_address)}</span></td><td>${esc(a.network_name || "未匹配子网")}<span class="live-small">${esc(a.last_dhcp)}</span></td><td>${info}</td><td>${readable ? button(result ? "确认设备信息" : "获取设备信息", result ? "eq-identify-result" : "eq-identify", false, eqAttr(a.interface_id) + (reading ? " disabled" : "")) : "—"}</td></tr>`;
  });
  return (
    note +
    filter +
    bar +
    table(
      [
        "选择",
        "临时管理地址 / MAC",
        "来源子网 / 最近 DHCP",
        "设备信息",
        "操作",
      ],
      rowsHtml,
    ).replace(
      "<th>选择</th>",
      `<th><input type="checkbox" name="eq-discovery-all" ${selectable.length && selected === selectable.length ? "checked" : ""} ${selectable.length && !reading ? "" : "disabled"} aria-label="选择当前发现列表可获取信息的设备"></th>`,
    )
  );
}
function equipmentEndpointTable(rows) {
  return table(
    [
      "设备 / 类型",
      "接口 / MAC",
      "当前 IP / 目标差异",
      "子网",
      "最近 DHCP",
      "操作",
    ],
    rows.map(
      (a) =>
        `<tr><td>${a.device_id ? button(a.serial || a.device_id, "eq-locate", false, eqAttr(a.device_id)) : esc("待识别")}<span class="live-small">${esc(equipmentKinds[a.kind])}${a.identity_conflict ? " · 归属冲突" : ""}</span></td><td>${esc(a.role_label)}<span class="live-small">${esc(a.mac_address)}</span></td><td>${esc(a.addresses.join(", ") || "未分配")}${a.target_ip && !a.addresses.includes(a.target_ip) ? `<span class="live-small">目标 ${esc(a.target_ip)} · 待迁移</span>` : ""}${a.allocation_type && a.allocation_type !== "待查询" ? `<span class="live-small">${esc(a.allocation_type)}</span>` : ""}</td><td>${esc(a.network_name)}</td><td>${esc(a.last_dhcp || "暂无记录")}</td><td>${button("规划地址", "address-endpoint", false, `data-interface-id="${esc(a.interface_id)}"`)}${!a.identity_conflict && a.kind !== "dpu" && !["nvos", "host"].includes(a.role) ? button("获取设备信息", "eq-identify", false, eqAttr(a.interface_id)) : ""}${a.segment_type === "UNDERLAY" && !["server", "dpu"].includes(a.kind) && !a.identity_conflict ? button("固定当前 IP", "eq-pin-preview", false, eqAttr(a.interface_id)) : ""}</td></tr>`,
    ),
  );
}
function equipmentChoose(mode) {
  state.wizard = { resource: "eq-choose", mode };
  modal(
    mode === "new" ? "新增设备" : mode === "import" ? "导入设备" : "下载模板",
    "选择设备类型",
    selectField(
      "eq-kind",
      "设备类型",
      Object.entries(equipmentKinds).filter(([k]) =>
        ["server", "switch", "power_shelf"].includes(k),
      ),
      "server",
    ) + eqError(),
    button("取消", "close") + button("继续", "eq-choose-confirm", true),
  );
}
function equipmentChooseConfirm() {
  const mode = state.wizard.mode,
    kind = $("#eq-kind").value;
  if (kind === "server") {
    if (mode === "new") return deviceDialog();
    if (mode === "import") return equipmentPlanningImport();
    window.location.href = "/api/equipment-planning/template";
    return close();
  }
  if (mode === "new") return equipmentEdit(null, kind);
  if (mode === "import") return equipmentImport(kind);
  window.location.href =
    "/api/equipment/template?kind=" + encodeURIComponent(kind);
  close();
}
async function equipmentDetail(id) {
  const d = await api("/api/equipment/" + encodeURIComponent(id));
  state.wizard = { resource: "eq-detail", device: d };
  modal(
    d.name || d.serial || "设备详情",
    equipmentKinds[d.kind],
    defs([
      ["设备 ID", esc(d.id)],
      ["SN", esc(d.serial)],
      ["机柜", esc(d.rack_id || "—")],
      ["纳管状态", esc(equipmentStates[d.status] || d.status)],
      ["原生状态", esc(d.native_state || "尚未报告")],
      [
        "原生声明 ID",
        esc(
          d.declaration?.expected_switch_id ||
            d.declaration?.expected_power_shelf_id ||
            "—",
        ),
      ],
    ]) +
      "<h3>管理接口</h3>" +
      equipmentEndpointTable(d.allocations) +
      table(
        ["角色", "MAC", "目标地址"],
        d.ports.map(
          (p) =>
            `<tr><td>${esc(p.role_label)}${p.primary ? " · primary" : ""}</td><td>${esc(p.mac_address)}</td><td>${esc(p.target_ip || "动态 / 未指定")}</td></tr>`,
        ),
      ) +
      equipmentOperationTable(d.operations) +
      `<details><summary>声明与身份依据</summary><pre>${esc(JSON.stringify({ local: d.declaration, native: d.native_declaration, proofs: d.proofs }, null, 2))}</pre></details>` +
      eqError(),
    button("关闭", "close") +
      (!d.unplanned
        ? button("系统配置", "eq-edit", false, eqAttr(id)) +
          button("同步至 NICo", "eq-sync-preview", true, eqAttr(id))
        : ""),
  );
}
function equipmentNetworkOptions(selected) {
  const rows =
    state.networks?.networks.filter(
      (n) => n.segment_type === "UNDERLAY" && n.name !== "static-assignments",
    ) || [];
  return [
    ["", "自动匹配 / 稍后规划"],
    ...rows.map((n) => [
      n.id,
      n.name + " · " + n.prefixes.map((p) => p.prefix).join(", "),
    ]),
    ...(selected && !rows.some((n) => n.id === selected)
      ? [[selected, "原规划网络（当前不可读）"]]
      : []),
  ];
}
function equipmentPortRows() {
  const w = state.wizard;
  return table(
    ["NVOS MAC", "Primary / eth0", "管理网络", "操作"],
    w.ports.map(
      (p, i) =>
        `<tr><td><input class="input" id="eq-port-mac-${i}" value="${esc(p.mac_address || "")}" aria-label="NVOS MAC ${i + 1}"></td><td><input name="eq-primary" id="eq-port-primary-${i}" type="radio" ${p.is_primary || w.ports.length === 1 ? "checked" : ""} aria-label="Primary ${i + 1}"></td><td>${selectField("eq-port-network-" + i, "管理网络", equipmentNetworkOptions(p.network_id), p.network_id)}</td><td>${button("移除", "eq-port-remove", false, `data-index="${i}"`)}</td></tr>`,
    ),
  );
}
function equipmentReadPorts() {
  const w = state.wizard;
  w.ports = w.ports.map((p, i) => ({
    mac_address: $("#eq-port-mac-" + i).value.trim(),
    is_primary: $("#eq-port-primary-" + i).checked,
    network_id: $("#eq-port-network-" + i).value,
  }));
}
function equipmentChangePorts(index) {
  equipmentReadPorts();
  const w = state.wizard;
  if (index === undefined) {
    if (w.ports.length >= 16) throw Error("最多支持 16 个 NVOS 管理口。");
    w.ports.push({
      mac_address: "",
      is_primary: !w.ports.length,
      network_id: "",
    });
  } else w.ports.splice(index, 1);
  $("#eq-port-list").innerHTML = equipmentPortRows();
  $("#eq-nvos-ip").disabled = w.ports.length > 1;
  if (w.ports.length > 1) $("#eq-nvos-ip").value = "";
}
async function equipmentEdit(id, kind) {
  const d = id ? await api("/api/equipment/" + encodeURIComponent(id)) : null;
  await loadNetworks();
  kind = d?.kind || kind;
  const row = d?.declaration || {},
    serialKey =
      kind === "switch" ? "switch_serial_number" : "shelf_serial_number";
  state.wizard = {
    resource: "eq-edit",
    device: d,
    kind,
    serialKey,
    ports: (row.nvos_interfaces || []).map((p) => ({
      ...p,
      network_id: d?.bindings?.[p.mac_address] || "",
    })),
  };
  const lock = d ? "readonly" : "";
  let form = `<div class="live-editor-grid">${eqText("serial", "设备 SN", row[serialKey], lock)}${eqText("name", "设备名称", row.metadata?.name)}${eqText("mac", kind === "switch" ? "BMC MAC" : "PMC / BMC MAC", row.bmc_mac_address, lock)}${eqText("ip", kind === "switch" ? "目标 BMC IPv4（可选）" : "目标 PMC IPv4（可选）", row.bmc_ip_address, d?.allocations?.length ? "readonly" : "")}${selectField("eq-bmc-network", "BMC / PMC 管理网络", equipmentNetworkOptions(d?.bindings?.[row.bmc_mac_address]), d?.bindings?.[row.bmc_mac_address])}${eqText("user", "BMC / PMC 用户名", row.bmc_username)}${eqText("password", d?.credential_present ? "BMC / PMC 密码（留空保留）" : "BMC / PMC 密码（规划可留空）", "", 'type="password" autocomplete="new-password"')}${eqText("rack", "机柜 UUID（可选）", row.rack_id)}${selectField(
    "eq-retain",
    "保留 BMC 凭据",
    [
      ["", "遵循原生默认"],
      ["true", "保留"],
      ["false", "允许原生轮换"],
    ],
    row.bmc_retain_credentials === undefined
      ? ""
      : String(row.bmc_retain_credentials),
  )}</div>`;
  if (kind === "switch")
    form += `<h3>NVOS 管理接口</h3><div id="eq-port-list">${equipmentPortRows()}</div>${button("添加 NVOS 接口", "eq-port-add")}<div class="live-editor-grid">${eqText("nvos-ip", "目标 NVOS IPv4（仅单管理口）", row.nvos_ip_address, state.wizard.ports.length > 1 ? "disabled" : d?.allocations?.length ? "readonly" : "")}${eqText("nvos-user", "NVOS 用户名（可选）", row.nvos_username)}${eqText("nvos-password", d?.nvos_credential_present ? "NVOS 密码（留空保留）" : "NVOS 密码（可选）", "", 'type="password" autocomplete="new-password"')}</div>`;
  form += `<details><summary>说明与标签</summary><div class="live-form">${eqText("description", "说明", row.metadata?.description)}${eqArea("labels", "标签（JSON 数组）", JSON.stringify(row.metadata?.labels || []))}</div></details><div class="live-note">保存仅更新本地规划。交换机 BMC / NVOS、供电框 PMC 使用 Underlay；已发现接口的地址在“管理地址”中规划和应用。</div>`;
  modal(
    id ? "编辑设备规划" : "新增" + equipmentKinds[kind],
    "规划与原生接入分别确认",
    form + eqError(),
    button("取消", "close") + button("保存规划", "eq-save", true),
  );
}
async function equipmentSave() {
  const w = state.wizard,
    old = w.device?.declaration || {},
    value = (id) => $("#eq-" + id).value.trim(),
    row = {
      ...old,
      bmc_mac_address: value("mac"),
      [w.serialKey]: value("serial"),
      bmc_username: value("user"),
      bmc_password: $("#eq-password").value,
      bmc_ip_address: value("ip"),
      rack_id: value("rack") || null,
      metadata: {
        name: value("name"),
        description: value("description"),
        labels: JSON.parse(value("labels")),
      },
    },
    bindings = {};
  if (value("retain")) row.bmc_retain_credentials = value("retain") === "true";
  else delete row.bmc_retain_credentials;
  if ($("#eq-bmc-network").value)
    bindings[row.bmc_mac_address.toLowerCase()] = $("#eq-bmc-network").value;
  if (w.kind === "switch") {
    equipmentReadPorts();
    Object.assign(row, {
      nvos_interfaces: w.ports.map((p) => ({
        mac_address: p.mac_address,
        is_primary: p.is_primary,
      })),
      nvos_ip_address: value("nvos-ip"),
      nvos_username: value("nvos-user"),
      nvos_password: $("#eq-nvos-password").value,
    });
    for (const p of w.ports)
      if (p.network_id) bindings[p.mac_address.toLowerCase()] = p.network_id;
  }
  const result = await api("/api/equipment/save", {
    id: w.device?.id,
    kind: w.kind,
    revision: w.device?.revision || "",
    native_revision: w.device?.native_revision || "",
    declaration: row,
    bindings,
  });
  close();
  await equipmentReload();
  toast("本地规划已保存。");
  await equipmentDetail(result.id);
}
function equipmentImport(kind) {
  state.wizard = { resource: "eq-import", kind };
  modal(
    "导入" + equipmentKinds[kind],
    "每行一台该类型设备；嵌套字段使用 JSON",
    `<div class="live-form"><a class="link-button" href="/api/equipment/template?kind=${kind}" download>下载此类型 CSV 模板</a><label>CSV 文件<input id="eq-file" type="file" accept=".csv,text/csv"></label></div>` +
      eqError(),
    button("取消", "close") + button("预览导入", "eq-import-preview", true),
  );
}
async function equipmentImportPreview() {
  const w = state.wizard,
    file = $("#eq-file").files[0];
  if (!file || file.size > 2 * 1024 * 1024)
    throw Error("请选择不超过 2 MiB 的 CSV。");
  const r = await api("/api/equipment/import-preview", {
    kind: w.kind,
    csv: await file.text(),
  });
  w.preview = r;
  modal(
    "导入预览",
    r.note,
    table(
      ["类型", "SN", "BMC / PMC MAC"],
      r.devices.map(
        (d) =>
          `<tr><td>${esc(equipmentKinds[d.kind])}</td><td>${esc(d.serial)}</td><td>${esc(d.declaration.bmc_mac_address)}</td></tr>`,
      ),
    ) + eqError(),
    button("取消", "close") +
      button("确认保存本地规划", "eq-import-apply", true),
  );
}
async function equipmentSyncPreview(id) {
  const r = await api("/api/equipment/sync-preview", { id });
  state.wizard = { resource: "eq-sync", preview: r };
  modal(
    "同步至 NICo",
    r.serial,
    `<div class="live-note">设备已在 PXEye 清单中；此操作会把本地规划创建或更新为 NICo Expected 设备声明。</div><div class="live-note live-warning">${esc(r.effect)}</div>` +
      defs([
        ["原生操作", esc(r.operation)],
        ["站点开关来源", esc(r.site_explorer.source)],
        [
          "create_switches",
          esc(r.site_explorer.create_switches ?? "未动态确认"),
        ],
        [
          "create_power_shelves",
          esc(r.site_explorer.create_power_shelves ?? "未动态确认"),
        ],
      ]) +
      `<details><summary>本次声明（不含密码）</summary><pre>${esc(JSON.stringify({ current: r.current_declaration, proposed: r.declaration }, null, 2))}</pre></details><div class="live-form">${eqText("confirm-serial", "输入设备 SN 确认")}<label class="live-check"><input id="eq-confirm-management" type="checkbox">确认可能启动原生设备管理和凭据处理。</label></div>` +
      eqError(),
    button("取消", "close") + button("确认接入", "eq-sync-apply", true),
  );
}
async function equipmentPinPreview(id) {
  const r = await api("/api/equipment/pin-preview", { interface_id: id });
  state.wizard = { resource: "eq-pin", preview: r };
  modal(
    "固定当前 IP",
    r.effect,
    defs([
      ["接口 MAC", esc(r.interface.mac_address)],
      ["当前 / 本次固定 IP", esc(r.interface.addresses.join(", "))],
      ["子网", esc(r.interface.network_name)],
    ]) +
      `<label class="live-check"><input id="eq-confirm-ip" type="checkbox">确认仅固定当前 IP，不迁移地址。</label>` +
      eqError(),
    button("取消", "close") + button("确认固定", "eq-pin-apply", true),
  );
}
function equipmentIdentify(id) {
  const row = state.equipment?.endpoints.find((a) => a.interface_id === id);
  if (!row) throw Error("端点已变化，请刷新设备页。");
  state.wizard = { resource: "eq-identify", endpoint: row };
  modal(
    "获取设备信息",
    "使用 DHCP 临时地址登录管理控制器，只读获取硬件信息",
    `<div class="live-form">${selectField(
      "eq-address",
      "临时管理地址",
      row.addresses
        .filter((ip) => /^\d+\.\d+\.\d+\.\d+$/.test(ip))
        .map((ip) => [ip, ip]),
      row.addresses[0],
    )}${eqText("identity-user", "BMC / PMC 用户名")}${eqText("identity-password", "BMC / PMC 密码", "", 'type="password" autocomplete="new-password"')}</div>` +
      eqError(),
    button("取消", "close") +
      button("获取设备信息", "eq-identify-submit", false),
  );
}
async function equipmentIdentifySubmit() {
  const w = state.wizard,
    ip = $("#eq-address").value,
    payload = {
      interface_id: w.endpoint.interface_id,
      ip,
      username: $("#eq-identity-user").value,
      password: $("#eq-identity-password").value,
    };
  let r;
  try {
    r = await api("/api/equipment/identify", payload);
  } finally {
    payload.password = "";
    if ($("#eq-identity-password")) $("#eq-identity-password").value = "";
  }
  state.equipmentDiscoveryResults[w.endpoint.interface_id] = {
    ...r,
    passed: true,
    ip,
    mac_address: w.endpoint.mac_address,
    interface_id: w.endpoint.interface_id,
  };
  render();
  if (state.wizard !== w) {
    toast("设备信息已获取，可从发现列表确认。");
    return;
  }
  equipmentIdentityConfirmation(w.endpoint, r, ip);
}
function equipmentIdentityConfirmation(
  endpoint,
  proof,
  ip,
  returnToBatch = false,
) {
  const r = proof;
  state.wizard = { resource: "eq-identify", endpoint, proof, returnToBatch };
  modal(
    "确认设备信息",
    "根据序列号和设备类型决定是否纳管",
    defs([
      ["设备类型", esc(equipmentKinds[r.identity.kind])],
      ["设备序列号", esc(r.identity.serial)],
      ["型号", esc(r.identity.model || "未提供")],
      ["临时管理地址", esc(ip)],
      ["验证时间", when(r.verified_at)],
    ]) + eqError(),
    (returnToBatch
      ? button("返回获取结果", "eq-discovery-results")
      : button("关闭", "close")) +
      (r.can_enroll ? button("加入纳管设备", "eq-enroll", true) : ""),
  );
}
function equipmentIdentifyResult(id, returnToBatch = false) {
  const endpoint = state.equipment?.endpoints.find(
      (a) => a.interface_id === id,
    ),
    proof = endpoint && equipmentDiscoveryProof(endpoint);
  if (!proof || !equipmentDiscoveryReadable(endpoint))
    throw Error("设备信息已过期或端点已变化，请重新获取。");
  equipmentIdentityConfirmation(endpoint, proof, proof.ip, returnToBatch);
}
function equipmentIdentifyMany() {
  if (state.equipmentDiscoveryReading) return;
  const selected = [...state.equipmentDiscoverySelection],
    endpoints = equipmentDiscoveryCandidates(
      state.equipment?.endpoints || [],
    ).filter(
      (row) =>
        selected.includes(row.interface_id) && equipmentDiscoveryReadable(row),
    );
  if (
    !selected.length ||
    selected.length > 50 ||
    endpoints.length !== selected.length
  )
    throw Error("请选择 1–50 台可获取信息的设备；端点变化时请刷新后重选。");
  state.wizard = {
    resource: "eq-identify-many",
    endpoints: endpoints.map((row) => ({
      interface_id: row.interface_id,
      ip: equipmentDiscoveryAddresses(row)[0],
      mac_address: row.mac_address,
    })),
  };
  modal(
    "批量获取设备信息",
    `为 ${endpoints.length} 台设备输入一次共用 BMC / PMC 账号密码`,
    `<div class="live-form">${eqText("identity-user", "共用 BMC / PMC 用户名", "", 'autocomplete="off" maxlength="16"')}${eqText("identity-password", "共用 BMC / PMC 密码", "", 'type="password" autocomplete="new-password" maxlength="20"')}</div>` +
      eqError(),
    button("取消", "close") +
      button("获取设备信息", "eq-identify-many-submit", true),
  );
}
async function equipmentIdentifyManySubmit() {
  if (state.equipmentDiscoveryReading) return;
  const w = state.wizard,
    payload = {
      endpoints: w.endpoints.map((row) => ({
        interface_id: row.interface_id,
        ip: row.ip,
      })),
      username: $("#eq-identity-user").value,
      password: $("#eq-identity-password").value,
    };
  if (!payload.username || !payload.password)
    throw Error("请输入共用 BMC / PMC 账号和密码。");
  state.equipmentDiscoveryReading = true;
  state.wizard = { resource: "eq-identify-many-running" };
  const marker = state.wizard;
  modal(
    "批量获取设备信息",
    `正在读取 ${w.endpoints.length} 台设备`,
    '<div class="live-empty">正在通过 Redfish 获取序列号、设备类型和型号…</div><div class="live-note">可以关闭窗口。完成后从发现列表查看获取结果。</div>' +
      eqError(),
    button("关闭", "close"),
  );
  render();
  try {
    const r = await api("/api/equipment/identify-many", payload);
    state.equipmentDiscoveryBatch = r.rows.map((row) => ({
      ...row,
      mac_address: w.endpoints.find((a) => a.interface_id === row.interface_id)
        .mac_address,
    }));
    for (const row of state.equipmentDiscoveryBatch)
      state.equipmentDiscoveryResults[row.interface_id] = row;
    if (state.wizard === marker) equipmentDiscoveryResults();
    else
      toast(
        `设备信息获取完成：${r.rows.filter((row) => row.passed).length} / ${r.rows.length} 台成功。`,
      );
  } catch (error) {
    if (state.wizard === marker) {
      state.wizard = null;
      close();
    }
    toast(error.message);
  } finally {
    payload.password = "";
    state.equipmentDiscoveryReading = false;
    render();
  }
}
function equipmentDiscoveryResults() {
  const rows = state.equipmentDiscoveryBatch;
  if (!rows) throw Error("暂无批量获取结果。");
  state.wizard = { resource: "eq-discovery-results" };
  modal(
    "设备信息获取结果",
    `${rows.filter((row) => row.passed).length} / ${rows.length} 台获取成功`,
    table(
      ["临时管理地址 / MAC", "设备 SN", "设备类型 / 型号", "结果", "操作"],
      rows.map((row) => {
        const endpoint = state.equipment?.endpoints.find(
            (a) => a.interface_id === row.interface_id,
          ),
          available =
            endpoint &&
            equipmentDiscoveryProof(endpoint)?.id === row.id &&
            equipmentDiscoveryReadable(endpoint);
        return `<tr><td>${esc(row.ip)}<span class="live-small live-code">${esc(row.mac_address)}</span></td><td>${esc(row.identity?.serial || "—")}</td><td>${esc(row.identity ? [equipmentKinds[row.identity.kind], row.identity.model].filter(Boolean).join(" · ") : "—")}</td><td>${esc(row.enrolled ? "已加入纳管设备" : row.passed ? (available ? "获取成功" : "端点已变化或验证已过期") : row.detail)}</td><td>${row.passed && available && !row.enrolled ? button(row.can_enroll ? "确认并纳管" : "查看信息", "eq-discovery-confirm", false, eqAttr(row.interface_id)) : "—"}</td></tr>`;
      }),
    ) +
      '<div class="live-note">成功信息在当前页面保留；纳管前重新核对端点归属。验证有效期为 15 分钟，页面刷新或验证失效后须重新获取。失败设备可按正确账号另选一批。</div>' +
      eqError(),
    button("关闭", "close"),
  );
}

async function equipmentNetworkAllocations(id) {
  const r = await api(
    "/api/networks/" + encodeURIComponent(id) + "/allocations",
  );
  modal(
    "子网地址分配",
    "Core 分配事实 · " + when(r.observed_at),
    equipmentEndpointTable(r.allocations),
    button("关闭", "close"),
  );
}
observeUI(
  "change",
  "equipment.js",
  (e) => {
    if (e.target.id?.startsWith("eq-filter-")) {
      state.equipmentFilters[e.target.id.slice(10)] = e.target.value;
      render();
    }
    if (e.target.id === "eq-discovery-network") {
      state.candidateNetwork = e.target.value;
      state.equipmentDiscoverySelection = [];
      render();
    }
    if (e.target.name === "eq-discovery-all") {
      state.equipmentDiscoverySelection = [
        ...document.querySelectorAll(
          'input[name="eq-discovery-device"]:not(:disabled)',
        ),
      ]
        .filter(() => e.target.checked)
        .map((input) => input.value);
      render();
    }
    if (e.target.name === "eq-discovery-device") {
      state.equipmentDiscoverySelection =
        state.equipmentDiscoverySelection.filter((id) => id !== e.target.value);
      if (e.target.checked)
        state.equipmentDiscoverySelection.push(e.target.value);
      render();
    }
  },
  false,
);
observeUI(
  "change",
  "equipment.js",
  (e) => {
    if (e.target.name === "eq-device" || e.target.name === "eq-all")
      queueMicrotask(render);
  },
  false,
);
observeUI(
  "input",
  "equipment.js",
  (e) => {
    if (e.target.id === "eq-filter-search") {
      const position = e.target.selectionStart;
      state.equipmentFilters.search = e.target.value;
      render();
      $("#eq-filter-search").focus();
      $("#eq-filter-search").setSelectionRange(position, position);
    }
  },
  false,
);
registerActions(
  "equipment.js",
  [
    "eq-refresh",
    "eq-managed",
    "eq-endpoints",
    "eq-choose-new",
    "eq-choose-import",
    "eq-choose-template",
    "eq-choose-confirm",
    "eq-detail",
    "eq-locate",
    "eq-edit",
    "eq-port-add",
    "eq-port-remove",
    "eq-save",
    "eq-import-preview",
    "eq-import-apply",
    "eq-sync-preview",
    "eq-sync-apply",
    "eq-pin-preview",
    "eq-pin-apply",
    "eq-identify",
    "eq-identify-submit",
    "eq-identify-result",
    "eq-identify-many",
    "eq-identify-many-submit",
    "eq-discovery-results",
    "eq-discovery-confirm",
    "eq-enroll",
    "eq-reconcile",
    "eq-network-allocations",
    "eq-batch-bmc",
    "eq-batch-management",
    "eq-batch-refresh",
    "eq-batch-confirm",
    "eq-bmc-progress",
    "eq-bmc-restart",
    "eq-bmc-finish",
  ],
  async (e) => {
    const el = e.target.closest('[data-live^="eq-"]');
    if (!el || el.disabled) return;
    try {
      switch (el.dataset.live) {
        case "eq-refresh":
          return await equipmentReload();
        case "eq-managed":
          state.deviceView = "managed";
          render();
          return equipmentPlanningReload();
        case "eq-endpoints":
          state.deviceView = "equipment-endpoints";
          await equipmentReload();
          return;
        case "eq-choose-new":
          return equipmentChoose("new");
        case "eq-choose-import":
          return equipmentChoose("import");
        case "eq-choose-template":
          return equipmentChoose("template");
        case "eq-choose-confirm":
          return await equipmentChooseConfirm();
        case "eq-detail":
          return await equipmentDetail(el.dataset.id);
        case "eq-locate": {
          const d = state.equipment?.devices.find(
            (d) => d.id === el.dataset.id,
          );
          if (d?.kind === "server") return deviceDetail(d.serial);
          if (d) return await equipmentDetail(d.id);
          throw Error("设备归属已变化，请刷新。");
        }
        case "eq-edit":
          return await equipmentEdit(el.dataset.id);
        case "eq-port-add":
          return equipmentChangePorts();
        case "eq-port-remove":
          return equipmentChangePorts(Number(el.dataset.index));
        case "eq-save":
          return await busy(equipmentSave);
        case "eq-import-preview":
          return await busy(equipmentImportPreview);
        case "eq-import-apply":
          return await busy(async () => {
            await api("/api/equipment/import-apply", {
              id: state.wizard.preview.id,
            });
            close();
            await equipmentReload();
            toast("已保存本地规划。请按设备分别确认原生接入。");
          });
        case "eq-sync-preview":
          return await busy(() => equipmentSyncPreview(el.dataset.id));
        case "eq-sync-apply":
          return await busy(async () => {
            const r = await api("/api/equipment/sync-apply", {
              preflight_id: state.wizard.preview.id,
              confirm_serial: $("#eq-confirm-serial").value,
              confirm_management: $("#eq-confirm-management").checked,
            });
            close();
            await equipmentReload();
            toast((equipmentStates[r.status] || r.status) + "：" + r.detail);
          });
        case "eq-pin-preview":
          return await busy(() => equipmentPinPreview(el.dataset.id));
        case "eq-pin-apply":
          return await busy(async () => {
            const r = await api("/api/equipment/pin-apply", {
              preflight_id: state.wizard.preview.id,
              confirm_same_ip: $("#eq-confirm-ip").checked,
            });
            close();
            await equipmentReload();
            toast((equipmentStates[r.status] || r.status) + "：" + r.detail);
          });
        case "eq-identify":
          if (state.equipmentDiscoveryReading) return;
          return equipmentIdentify(el.dataset.id);
        case "eq-identify-submit":
          return await busy(equipmentIdentifySubmit);
        case "eq-identify-result":
          return equipmentIdentifyResult(el.dataset.id);
        case "eq-identify-many":
          return equipmentIdentifyMany();
        case "eq-identify-many-submit":
          return await busy(equipmentIdentifyManySubmit);
        case "eq-discovery-results":
          return equipmentDiscoveryResults();
        case "eq-discovery-confirm":
          return equipmentIdentifyResult(el.dataset.id, true);
        case "eq-enroll":
          return await busy(async () => {
            const w = state.wizard;
            await api("/api/equipment/enroll", {
              id: w.proof.id,
              confirm_registration: true,
            });
            const result = state.equipmentDiscoveryBatch?.find(
              (row) => row.id === w.proof.id,
            );
            if (result) result.enrolled = true;
            delete state.equipmentDiscoveryResults[w.endpoint.interface_id];
            if (!w.returnToBatch) {
              close();
              state.deviceView = "managed";
            }
            await equipmentReload();
            if (w.returnToBatch && state.wizard === w)
              equipmentDiscoveryResults();
            toast("已加入纳管设备；可继续维护地址和安装规划。");
          });
        case "eq-reconcile":
          return await busy(async () => {
            const r = await api("/api/equipment/reconcile", {
              id: el.dataset.id,
            });
            toast((equipmentStates[r.status] || r.status) + "：" + r.detail);
            await equipmentReload();
          });
        case "eq-network-allocations":
          return await busy(() => equipmentNetworkAllocations(el.dataset.id));
        case "eq-batch-bmc":
          return await busy(() => equipmentBatchPreview("bmc"));
        case "eq-batch-management":
          return await busy(() => equipmentBatchPreview("management"));
        case "eq-batch-refresh":
          return await busy(equipmentBatchRefresh);
        case "eq-batch-confirm":
          return await busy(equipmentBatchConfirm);
        case "eq-bmc-progress":
          return await busy(async () =>
            bmcShowProgress(
              await api(
                "/api/equipment/bmc-jobs/" + encodeURIComponent(el.dataset.id),
              ),
            ),
          );
        case "eq-bmc-restart":
          return await busy(async () => {
            const r = await api("/api/equipment/bmc-restart-unsent", {
              id: el.dataset.id,
              confirm_update: true,
            });
            bmcShowProgress(r);
            await equipmentReload();
          });
        case "eq-bmc-finish":
          return await busy(async () => {
            const r = await api("/api/equipment/bmc-finish-sync", {
              id: el.dataset.id,
              confirm_sync: true,
            });
            bmcShowProgress(r);
            await equipmentReload();
          });
      }
    } catch (error) {
      const target = $("#resource-error");
      if (target) target.textContent = error.message;
      else toast(error.message);
    }
  },
);

// The session request may finish before the final extension script loads.
if (state.csrf && ["devices", "network"].includes(state.page))
  readSection("equipment", sectionReads.equipment);
