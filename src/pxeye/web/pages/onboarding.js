"use strict";
const installMode = (mode) =>
  ({
    first_install: "首次安装",
    reinstall: "重装",
    mixed: "自动安装（混合批次）",
    auto: "自动安装",
  })[mode] || "安装";
const deviceInstallMode = (d) =>
  d.discovery_state === "assigned" || Boolean(d.instance_id)
    ? "reinstall"
    : "first_install";
function batchSummary() {
  if (!state.batches.length) return "";
  return `<section class="subsection"><h2>安装批次</h2>${table(
    ["批次", "类型", "设备进度", "操作"],
    state.batches.map(
      (b) =>
        `<tr><td>${esc(b.id)}<span class="live-small">${when(b.created_at)}</span></td><td>${installMode(b.mode)}</td><td>${badge(statuses[b.status], b.status === "completed" ? "green" : b.status === "needs_attention" ? "red" : "amber")}<span class="live-small">完成 ${b.counts.completed} / ${b.task_ids.length} · 排队 ${b.counts.queued} · 需处理 ${b.counts.needs_attention}</span></td><td>${button("逐台查看", "batch-detail", false, `data-id="${esc(b.id)}"`)}</td></tr>`,
    ),
  )}</section>`;
}
function batchStart(serial) {
  state.installReviewReturn = null;
  state.wizard = {
    resource: "batch",
    step: 1,
    mode: "auto",
    selected: serial ? [serial] : [],
    entries: [],
    profile_id: null,
    request_key:
      crypto.randomUUID?.() ||
      "batch-" + Date.now() + "-" + Math.random().toString(36).slice(2),
  };
  batchWizard();
  readCurrentSystems(state.wizard).catch((error) => toast(error.message));
}
function batchDeviceCondition(d) {
  const mode = deviceInstallMode(d);
  if (d.instance_release_pending)
    return {
      selectable: false,
      ready: false,
      reason:
        d.instance_release?.detail ||
        d.execution_reason ||
        "设备回收尚未完成，请刷新状态",
    };
  if (active(d))
    return {
      selectable: false,
      ready: false,
      reason: "已有安装任务或待处理现场",
    };
  const ready =
    mode === "first_install"
      ? true
      : Boolean(d.executable || d.can_install_with_current_bmc);
  return {
    selectable: true,
    ready,
    reason:
      mode === "first_install" && !d.first_install_ready
        ? "安装时自动准备"
        : ready
          ? "可检查安装条件"
          : mode === "first_install"
            ? d.discovery_reason || "等待硬件准备和 Scout Ready"
            : d.execution_reason || "请完善安装配置",
  };
}
function batchPreparation(d) {
  const mode = deviceInstallMode(d);
  const condition = batchDeviceCondition(d);
  return (
    `${badge(mode === "first_install" && !d.first_install_ready ? "自动准备" : condition.ready ? "可预检" : "待准备", mode === "first_install" && !d.first_install_ready ? "amber" : condition.ready ? "green" : "amber")}<span class="live-small">${esc(condition.reason)}</span>` +
    `<div class="live-tools" style="margin-top:6px"><button class="link-button" data-batch-action="plan" data-serial="${esc(d.serial)}">编辑规划</button>${mode === "first_install" && !condition.ready ? `<button class="link-button" data-batch-action="hardware" data-serial="${esc(d.serial)}">查看硬件信息</button>` : ""}</div>`
  );
}
const currentSystemNames = {
  unknown: "未查询",
  off: "已关机",
  unreachable: "无 SSH，无法访问",
  os: "已读取系统",
  temporary: "发现 / 安装环境",
};
function currentSystem(d) {
  return (
    state.currentSystems?.systems?.[d.serial] || {
      status: "unknown",
      label: "未查询",
    }
  );
}
function currentSystemCell(d) {
  const value = currentSystem(d),
    pending = state.currentSystems?.pending?.includes(d.serial);
  return `${esc(pending ? "查询中…" : value.label)}${!pending && value.checked_at ? `<span class="live-small">${when(value.checked_at)}</span>` : ""}`;
}
async function readCurrentSystems(w) {
  state.currentSystems = await api("/api/devices/current-system");
  if (state.wizard !== w || w.step !== 1) return;
  renderBatchDevices();
  const button = $('[data-batch-action="system-query"]');
  if (button) button.disabled = Boolean(state.currentSystems.pending.length);
  clearTimeout(w.systemPoll);
  if (state.currentSystems.pending.length)
    w.systemPoll = setTimeout(() => {
      if (state.wizard === w && w.step === 1)
        readCurrentSystems(w).catch((error) => toast(error.message));
    }, 2000);
}
async function queryCurrentSystems() {
  const w = state.wizard;
  if (w?.resource !== "batch" || w.step !== 1) return;
  const serials = w.selected.length
    ? [...w.selected]
    : state.resources.devices.filter(batchDeviceMatches).map((d) => d.serial);
  if (!serials.length || serials.length > 50)
    return toast("请选择或筛选1–50台设备后查询当前系统。");
  const button = $('[data-batch-action="system-query"]');
  if (button) button.disabled = true;
  try {
    state.currentSystems = await api("/api/devices/current-system/query", {
      serials,
    });
    if (state.wizard !== w || w.step !== 1) return;
    await readCurrentSystems(w);
  } catch (error) {
    if (button) button.disabled = false;
    throw error;
  }
}
function batchIdentityCells(d) {
  const i = d.selection_identity || {};
  return (
    `<td><strong>${esc(d.serial)}</strong>${d.server_name ? `<span class="live-small">${esc(d.server_name)}</span>` : ""}${d.rack_id ? `<span class="live-small">机柜 ${esc(d.rack_id?.value || d.rack_id)}</span>` : ""}<span class="live-small">${esc(/^lenovo\b/i.test(i.manufacturer || "") ? "Lenovo" : i.manufacturer || "")}</span></td>` +
    `<td>${esc(i.architecture || "未采集")}<span class="live-small">${esc(i.cpu_models?.join(" / ") || "CPU型号未采集")}</span></td>` +
    `<td>${bmcLink(d.bmc_ip || d.bmc_ip_address)}<span class="live-small live-code">${esc(d.bmc_mac_address || "MAC 未登记")}</span>${d.bmc_ip && d.bmc_ip_address && d.bmc_ip !== d.bmc_ip_address ? `<span class="live-small">规划 ${esc(d.bmc_ip_address)}</span>` : ""}</td>`
  );
}
function batchNetworkCell(d) {
  const i = d.selection_identity || {};
  return `<div class="batch-management"><div class="batch-management-address"><strong>${esc(i.management_ip || d.planned_ip || d.management_ip || "待规划")}</strong><span class="batch-management-prefix">${esc(i.management_prefix || "子网未关联")}</span></div><span class="live-small live-code">MAC ${esc(i.management_mac || d.boot_mac || "待规划")}</span></div>`;
}
function batchDeviceMatches(d) {
  const f = state.wizard.filters || {},
    i = d.selection_identity || {};
  const text = [
    d.serial,
    d.server_name,
    d.rack_id?.value || d.rack_id,
    d.bmc_ip,
    d.bmc_ip_address,
    d.bmc_mac_address,
    i.architecture,
    ...(i.cpu_models || []),
    i.manufacturer,
    i.model,
    i.management_ip,
    i.management_prefix,
    i.management_network_name,
    i.management_mac,
    d.intent?.hostname,
    d.instance_id,
    currentSystem(d).label,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  return (
    (!f.query || text.includes(f.query.toLowerCase().trim())) &&
    (!f.architecture || (i.architecture || "unknown") === f.architecture) &&
    (!f.network || (i.management_prefix || "unknown") === f.network) &&
    (!f.os || currentSystem(d).status === f.os) &&
    (!f.available || batchDeviceCondition(d).selectable) &&
    (!f.selected || state.wizard.selected.includes(d.serial))
  );
}
function batchSelectionSummary() {
  const w = state.wizard,
    visible = state.resources.devices.filter(batchDeviceMatches),
    ids = new Set(visible.map((d) => d.serial));
  const hidden = w.selected.filter((s) => !ids.has(s)).length;
  $("#batch-selection-summary").textContent =
    `显示 ${visible.length} / ${state.resources.devices.length} 台 · 已选 ${w.selected.length} / 50 台${hidden ? "（筛选外 " + hidden + " 台）" : ""}`;
  const next = $('[data-live="batch-next"]');
  if (next) next.disabled = !w.selected.length;
}
function renderBatchDevices() {
  const w = state.wizard;
  $("#batch-device-list").innerHTML = table(
    [
      "选择",
      "设备 / 品牌",
      "CPU 架构 / 型号",
      "BMC 地址 / MAC",
      "管理地址",
      "当前系统",
      "安装条件",
    ],
    state.resources.devices.filter(batchDeviceMatches).map((d) => {
      const condition = batchDeviceCondition(d),
        selected = w.selected.includes(d.serial) && condition.selectable;
      return `<tr data-batch-device="${esc(d.serial)}" class="${selected ? "batch-selected" : ""}"><td><input type="checkbox" name="batch-device" value="${esc(d.serial)}" ${selected ? "checked" : ""} ${condition.selectable ? "" : "disabled"} aria-label="选择 ${esc(d.serial)}"></td>${batchIdentityCells(d)}<td>${batchNetworkCell(d)}</td><td>${currentSystemCell(d)}</td><td>${batchPreparation(d)}</td></tr>`;
    }),
  );
  const empty = $("#batch-device-list .live-empty");
  if (empty)
    empty.textContent = state.resources.devices.length
      ? "未找到匹配设备，请调整筛选。"
      : "暂无设备，请先添加或导入设备。";
  batchSelectionSummary();
}
function batchDeviceFilters() {
  const f = state.wizard.filters || {},
    devices = state.resources.devices;
  const arches = [
    ...new Set(
      devices.map((d) => d.selection_identity?.architecture).filter(Boolean),
    ),
  ].sort();
  const nets = [
    ...new Set(
      devices
        .map((d) => d.selection_identity?.management_prefix)
        .filter(Boolean),
    ),
  ].sort();
  return (
    `<div class="batch-filter-grid">${inputField("batch-search", "搜索设备", f.query || "", 'type="search" placeholder="SN、IP、MAC、主机名、型号"')}` +
    selectField(
      "batch-architecture",
      "CPU 架构",
      [["", "全部架构"], ...arches.map((a) => [a, a]), ["unknown", "未采集"]],
      f.architecture || "",
    ) +
    selectField(
      "batch-network",
      "管理网段",
      [["", "全部网段"], ...nets.map((n) => [n, n]), ["unknown", "待规划"]],
      f.network || "",
    ) +
    selectField(
      "batch-current-system",
      "当前系统",
      [["", "全部系统状态"], ...Object.entries(currentSystemNames)],
      f.os || "",
    ) +
    `</div><div class="live-tools batch-selection-tools"><label><input id="batch-only-available" type="checkbox" ${f.available ? "checked" : ""}> 仅看可选设备</label><label><input id="batch-only-selected" type="checkbox" ${f.selected ? "checked" : ""}> 仅看已选</label><button class="link-button" data-batch-action="identity-refresh">刷新设备信息</button><button class="link-button" data-batch-action="system-query" ${state.currentSystems?.pending?.length ? "disabled" : ""} title="查询已选设备；未选择时查询当前筛选结果，最多50台">查询当前系统</button><span id="batch-selection-summary" role="status" aria-live="polite"></span></div>`
  );
}

function installationCheckPresentation(check) {
  const rows = (check?.checks || []).flatMap((device) =>
    (device.checks || []).map((item) => ({ ...item, device: device.device })),
  );
  const groups = [
    {
      label: "设备身份",
      detail: "BMC 登录与序列号",
      match: (item) => /BMC|设备接入条件/.test(item.name),
    },
    {
      label: "安装配置",
      detail: "管理地址、启动接口与系统盘",
      match: (item) => !/BMC|设备接入条件|材料/.test(item.name),
    },
    {
      label: "操作系统材料",
      detail: "kernel、initrd、ISO 与自动安装配置",
      match: (item) => /材料/.test(item.name),
    },
  ];
  const steps = groups.map((group) => {
    const matches = rows.filter(group.match);
    const status = matches.some((item) => !item.passed)
      ? "failed"
      : matches.length
        ? "passed"
        : check
          ? "waiting"
          : "checking";
    return { ...group, status };
  });
  const passed = steps.filter((step) => step.status === "passed").length;
  return `<section class="install-check-panel" aria-label="安装条件检查"><header><div><span class="site-eyebrow">安装条件</span><strong>${check ? (check.passed ? "配置可以执行" : "发现阻断项") : "正在核对配置"}</strong></div><span>${passed} / ${steps.length}</span></header><progress value="${passed}" max="${steps.length}" aria-label="已通过 ${passed} 项，共 ${steps.length} 项"></progress><ol>${steps
    .map(
      (step) =>
        `<li class="${step.status}"><span class="install-check-dot" aria-hidden="true"></span><div><strong>${esc(step.label)}</strong><span>${esc(step.detail)}</span></div><small>${{ passed: "已通过", failed: "需处理", checking: "检查中", waiting: "待核对" }[step.status]}</small></li>`,
    )
    .join("")}</ol></section>`;
}

function finalDiskCell(device, check) {
  const selection = check?.disk_selection || check?.installation_plan?.disk_selection;
  if (!selection) {
    const profile = state.resources.first_install_profiles.find(
      (item) => item.id === device.intent?.profile_id,
    );
    const pending =
      deviceInstallMode(device) === "first_install"
        ? device.intent?.disk_serial || profile?.disk_selection || "等待硬件回报后解析"
        : device.intent?.disk_serial || device.disk_serial || device.disk_wwn || "未关联系统盘";
    return `${esc(pending)}${check?.deferred_first_install ? '<span class="live-small">Scout 回报后执行前确定</span>' : ""}`;
  }
  const size = selection.size_bytes
    ? (selection.size_bytes / 1024 ** 3).toFixed(1) + " GiB"
    : "容量未回报";
  const refreshed = check?.hardware_checked_at
    ? " · 硬件刷新 " + when(check.hardware_checked_at)
    : "";
  return `${esc(selection.model || "型号未回报")}<span class="live-small live-code">${esc(selection.serial)}</span><span class="live-small">${esc(size)} · ${esc(selection.source || "已解析")}${esc(refreshed)}</span>`;
}

function batchWizard() {
  const w = state.wizard;
  let body = `<div class="live-step">${["选择设备", "核对配置"].map((s, i) => `<${w.step === i + 1 ? "strong" : "span"}>${i + 1}. ${s}</${w.step === i + 1 ? "strong" : "span"}>`).join(" → ")}</div>`,
    foot = "";
  if (w.step === 1) {
    body +=
      batchDeviceFilters() +
      `<div id="batch-device-list" class="batch-device-list"></div>`;
    body += ``;
    foot = button("取消", "close") + button("下一步", "batch-next", true);
  }
  if (w.step === 2) {
    const devices = w.entries.map((e) =>
      state.resources.devices.find((d) => d.serial === e.serial),
    );
    const waiting = devices.filter((d) => !batchDeviceCondition(d).ready);
    if (waiting.length)
      body += `<div class="live-note">${waiting.length} 台设备当前仍在等待执行条件；下发后将自动准备设备。</div>`;
    const checks = new Map((w.check?.checks || []).map((item) => [item.device, item]));
    body += table(
      [
        "设备 / 品牌",
        "CPU 架构 / 型号",
        "BMC 地址 / MAC",
        "目标 OS / 方案",
        "主机名 / 管理地址",
        "系统盘",
        "操作",
      ],
      devices.map((d) => {
        const p = state.resources.first_install_profiles.find(
          (p) => p.id === d.intent?.profile_id,
        );
        const os = state.osLibrary?.operating_systems.find(
          (o) =>
            o.id ===
            (d.intent?.effective?.values?.os_id ||
              d.intent?.os_id ||
              p?.settings?.os_id),
        );
        return `<tr>${batchIdentityCells(d)}<td>${esc(os?.name || d.os_release || "未读取目标 OS 名称")}<span class="live-small">${esc(p?.name || "未选择方案")}</span></td><td>${esc(d.intent?.hostname || "未设置主机名")}<span class="live-small">${batchNetworkCell(d)}</span></td><td>${finalDiskCell(d, checks.get(d.serial))}</td><td><div class="live-tools"><button class="link-button" data-batch-action="plan" data-serial="${esc(d.serial)}">编辑设备规划</button><button class="link-button" data-batch-action="hardware" data-serial="${esc(d.serial)}">查看硬件信息</button></div></td></tr>`;
      }),
    );
  }
  if (w.step === 2) {
    body += installationCheckPresentation(w.check);
    if (w.check) {
      const failures = w.check.checks.flatMap((device) =>
        device.checks
          .filter((item) => !item.passed)
          .map(
            (item) =>
              `<div class="install-check-failure"><strong>${esc(device.device)} · ${esc(item.name)}</strong><span>${esc(item.detail)}</span></div>`,
          ),
      );
      if (failures.length)
        body += `<div class="install-check-failures">${failures.join("")}</div>`;
      const cleanup = w.check.checks.filter(
        (device) => device.impact?.cleanup_scope === "all_disks",
      );
      if (cleanup.length)
        body += `<div class="live-note live-warning"><strong>首次接入将清理全部磁盘：</strong>${esc(cleanup.map((device) => device.device).join("、"))}</div>`;
    }
    if (w.checkError)
      body += `<div class="live-error">${esc(w.checkError)}</div>`;
    if (w.check?.passed)
      body += `<div class="live-note live-warning">将安装 ${w.entries.length} 台设备，应用规划地址、覆盖所选系统盘并重启验证。本批最多并发 ${w.check.max_concurrency} 台；失败设备暂停，其余设备继续。</div><div class="live-form"><label class="live-check"><input type="checkbox" id="batch-confirm-disk">确认所选设备、管理地址及系统盘。</label><label class="live-check"><input type="checkbox" id="batch-confirm-reboot">允许安装及重启验证。</label>${w.check.checks.some((c) => c.impact?.cleanup_scope === "all_disks") ? '<label class="live-check live-warning"><input type="checkbox" id="batch-confirm-cleanup">允许需接入设备清理全部磁盘（含非系统盘，清单待核对），并执行站点凭据和固件配置。</label>' : ""}</div>`;
    foot =
      `<div class="batch-review-actions">${button("重新选择设备", "batch-back")}${button(
        w.check ? "更新状态" : "重试检查",
        "batch-check",
        false,
        w.checking ? "disabled" : "",
      )}</div>` +
      button("确认并安装", "batch-submit", true, 'id="batch-submit" disabled');
  }
  body += '<div id="resource-error" class="live-error" role="alert"></div>';
  modal("新建安装任务", `步骤 ${w.step} / 2`, body, foot);
  $(".modal").classList.add("batch-install-modal");
  if (w.step === 1) {
    renderBatchDevices();
    const fields = {
      "batch-search": "query",
      "batch-architecture": "architecture",
      "batch-network": "network",
      "batch-current-system": "os",
      "batch-only-available": "available",
      "batch-only-selected": "selected",
    };
    for (const [id, key] of Object.entries(fields))
      $("#" + id).addEventListener(
        id === "batch-search" ? "input" : "change",
        (event) => {
          w.filters ||= {};
          w.filters[key] =
            event.target.type === "checkbox"
              ? event.target.checked
              : event.target.value;
          renderBatchDevices();
        },
      );
  }
  updateBatchSubmit();
}
async function batchNext() {
  const w = state.wizard;
  w.selected = w.selected.filter((s) => {
    const d = state.resources.devices.find((d) => d.serial === s);
    return d && batchDeviceCondition(d).selectable;
  });
  if (w.selected.length > 50) return toast("每批最多50台，请分批安装。");
  if (!w.selected.length) return toast("请选择需要安装的设备。");
  w.entries = w.selected.map((serial) => ({ serial }));
  w.step = 2;
  batchWizard();
  await batchCheck();
}
function readBatchEntries() {
  const w = state.wizard;
  if (w.step !== 2) return;
  const devices = w.selected.map((serial) =>
    state.resources.devices.find((d) => d.serial === serial),
  );
  if (devices.some((d) => !d)) throw Error("设备清单已变化，请重新选择设备。");
  w.entries = devices.map((d, i) => ({
    serial: d.serial,
    hostname: d.intent?.hostname || "",
    disk_serial: d.intent?.disk_serial || null,
    bmc_choice: d.bmc_ip ? "use_current" : "require_planned",
  }));
  w.profile_id = null;
}
function batchBack() {
  const w = state.wizard;
  w.checkRun = (w.checkRun || 0) + 1;
  w.check = null;
  w.checking = false;
  w.step = 1;
  batchWizard();
  readCurrentSystems(w).catch((error) => toast(error.message));
}
async function batchCheck() {
  const w = state.wizard;
  if (w.checking) return;
  const run = (w.checkRun = (w.checkRun || 0) + 1);
  w.check = null;
  w.checkError = null;
  w.checking = true;
  batchWizard();
  try {
    await sectionReads.resources();
    if (state.wizard !== w || w.checkRun !== run || w.step !== 2) return;
    readBatchEntries();
    const result = await api("/api/batches/preflight", {
      mode: w.mode,
      profile_id: w.profile_id,
      devices: w.entries,
    });
    if (state.wizard === w && w.checkRun === run && w.step === 2)
      w.check = result;
  } catch (e) {
    if (state.wizard === w && w.checkRun === run) w.checkError = e.message;
  } finally {
    if (w.checkRun === run) {
      w.checking = false;
      if (state.wizard === w && w.step === 2) batchWizard();
    }
  }
}
function updateBatchSubmit() {
  if (state.wizard?.resource !== "batch" || !$("#batch-submit")) return;
  const w = state.wizard;
  $("#batch-submit").disabled = !(
    w.check?.passed &&
    $("#batch-confirm-disk")?.checked &&
    $("#batch-confirm-reboot")?.checked &&
    (!$("#batch-confirm-cleanup") || $("#batch-confirm-cleanup").checked)
  );
}
async function batchSubmit() {
  const w = state.wizard;
  if (Date.now() / 1000 - w.check.checked_at >= 840) {
    await batchCheck();
    return toast("检查已过期，请确认更新后的结果。");
  }
  const submit = $("#batch-submit");
  submit.disabled = true;
  submit.textContent = "正在创建任务…";
  try {
    const batch = await api("/api/batches", {
      preflight_id: w.check.id,
      request_key: w.request_key,
      confirm_serials: w.entries.map((e) => e.serial),
      confirm_disk: $("#batch-confirm-disk").checked,
      confirm_reboot: $("#batch-confirm-reboot").checked,
      cleanup_scope: $("#batch-confirm-cleanup")?.checked
        ? "all_disks"
        : "none",
    });
    state.page = "tasks";
    location.hash = "tasks";
    syncPollers("tasks");
    state.tasks = [
      ...batch.tasks,
      ...state.tasks.filter((task) => !batch.task_ids.includes(task.id)),
    ];
    state.batches = [batch, ...state.batches.filter((item) => item.id !== batch.id)];
    close();
    render();
    await batchDetail(batch);
    Promise.allSettled(
      ["tasks", "batches", "resources"].map((key) =>
        readSection(key, sectionReads[key]),
      ),
    );
  } catch (e) {
    if (state.wizard !== w) return;
    const currentSubmit = $("#batch-submit");
    if (currentSubmit) currentSubmit.textContent = "确认并安装";
    if (e.status === 400 && /已变化|已失效/.test(e.message)) {
      await batchCheck();
      toast("配置已变化，请确认更新后的检查结果。");
    } else {
      $("#resource-error").textContent = e.message;
      updateBatchSubmit();
    }
  }
}
async function batchDetail(batch) {
  const b =
    typeof batch === "string"
      ? await api("/api/batches/" + encodeURIComponent(batch))
      : batch;
  const id = b.id;
  state.batches = state.batches.map((x) => (x.id === id ? b : x));
  state.wizard = { resource: "batch-detail", id };
  const body =
    `<div class="live-note">${installMode(b.mode)} · ${b.tasks.length} 台 · 并发执行 ${b.max_concurrency} 台。失败设备暂停，等待处理。</div>` +
    table(
      ["设备", "主机名 / 地址", "阶段 / 状态", "操作"],
      b.tasks.map(
        (t) =>
          `<tr><td>${esc(t.device)}</td><td>${esc(t.hostname)}<span class="live-small">${esc(t.management_ip)}</span></td><td>${badge(statuses[t.status], t.status === "completed" ? "green" : t.status === "needs_attention" ? "red" : "amber")}<span class="live-small">${esc(stages[t.stage])}</span></td><td><button class="link-button" data-task="${esc(t.id)}">日志 / 验收记录</button></td></tr>`,
      ),
    );
  modal(
    "安装批次",
    b.id,
    body,
    button("刷新进度", "batch-detail", false, `data-id="${esc(b.id)}"`) +
      button("关闭", "close"),
  );
}
function admissionStart(selectedSerial) {
  const serial =
    selectedSerial ||
    (state.wizard?.resource === "discovery" ? state.wizard.serial : null);
  state.wizard = { resource: "admission", serial };
  modal(
    "批量接入主机",
    "选择已登记设备 · 每批最多50台",
    table(
      ["选择", "设备 SN", "BMC 地址", "状态"],
      state.resources.devices
        .filter((d) => !d.instance_id && !d.first_install_ready)
        .map(
          (d) =>
            `<tr><td><input type="checkbox" name="admission-device" value="${esc(d.serial)}" ${serial === d.serial ? "checked" : ""} aria-label="接管 ${esc(d.serial)}"></td><td><button class="link-button" data-live="discovery" data-serial="${esc(d.serial)}">${esc(d.serial)}</button></td><td>${esc(d.bmc_ip)}</td><td>${esc(d.machine_id ? "已关联主机，请查看硬件信息" : "尚未关联主机")}</td></tr>`,
        ),
    ) +
      `<div class="live-note">启动主机接入，采集 CPU、网卡和磁盘信息。</div><div id="admission-results" aria-live="polite"></div><div id="resource-error" class="live-error"></div>`,
    button("取消", "close") + button("检查接入条件", "admission-preview", true),
  );
}
async function admissionPreview() {
  return busy(async () => {
    const serials = [
      ...document.querySelectorAll("input[name=admission-device]:checked"),
    ].map((x) => x.value);
    if (!serials.length) throw Error("请选择待接入设备。");
    if (serials.length > 50) throw Error("每批最多50台，请分批接入。");
    const w = state.wizard;
    const run = (w.previewRun || 0) + 1;
    w.previewRun = run;
    w.preview = null;
    $("#resource-error").textContent = "";
    $("#admission-results").innerHTML =
      '<div class="live-note">正在逐项读取 BMC 身份及 NICo 状态…</div>';
    const result = await api("/api/devices/admission-preview", { serials });
    if (state.wizard !== w || w.previewRun !== run) return;
    const current = [
      ...document.querySelectorAll("input[name=admission-device]:checked"),
    ].map((x) => x.value);
    if (JSON.stringify(current) !== JSON.stringify(serials)) {
      $("#admission-results").innerHTML = "";
      throw Error("选择范围已变化，请重新检查。");
    }
    w.preview = result;
    const labels = {
      pass: "通过",
      fail: "未通过",
      wait: "等待 / 需核对",
      skipped: "未检查",
    };
    $("#admission-results").innerHTML =
      result.checks
        .map(
          (c) =>
            `<section class="live-card" style="margin-top:16px"><h3>${esc(c.serial)} · ${badge(c.passed ? "可启动接入" : c.phase === "waiting" ? "需核对接管状态" : "准备条件未通过", c.passed ? "green" : c.phase === "waiting" ? "amber" : "red")}</h3><p>${esc(c.detail)}</p>${table(
              ["检查项目", "结果", "详情"],
              c.items.map(
                (i) =>
                  `<tr><td>${esc(i.label)}</td><td>${badge(labels[i.status] || i.status, i.status === "pass" ? "green" : i.status === "fail" ? "red" : "amber")}</td><td>${esc(i.detail)}</td></tr>`,
              ),
            )}<div class="live-note">下一步：${esc(c.next_action)}</div><button class="link-button" data-live="discovery" data-serial="${esc(c.serial)}">查看该设备硬件信息</button></section>`,
        )
        .join("") +
      (result.passed
        ? `<div class="live-note live-warning">将对以上 ${result.checks.length} 台主机启动接入，允许NICo开机、网络启动并执行本站点的全部磁盘清理、凭据、BIOS/固件策略。请核对所列SN及范围。</div><label class="live-check"><input id="admission-cleanup" type="checkbox">允许清理所选设备全部磁盘（含非系统盘，清单待采集）。</label><div></div>`
        : '<div class="live-note">请处理检查结果中的问题后重新检查。</div>');
    $(".modal-footer").innerHTML =
      button("关闭", "close") +
      button("重新检查 / 刷新", "admission-preview") +
      (result.passed
        ? button("启动所选主机接入", "admission-submit", true)
        : "");
  });
}
async function admissionSubmit() {
  return busy(async () => {
    const w = state.wizard;
    if (!$("#admission-cleanup")?.checked)
      throw Error("请确认全部磁盘的接入清理范围。");
    if (!w.preview?.passed) throw Error("请先检查所选设备的接入条件。");
    const result = await api("/api/devices/admit-batch", {
      preflight_id: w.preview.id,
      confirm_serials: w.preview.checks.map((c) => c.serial),
      confirm_ingestion: true,
      cleanup_scope: "all_disks",
    });
    modal(
      "主机接入请求结果",
      "接入进度见设备详情",
      table(
        ["设备", "请求状态", "说明"],
        result.results.map(
          (c) =>
            `<tr><td>${esc(c.serial)}</td><td>${esc(c.status)}</td><td>${esc(c.detail || "请求已发送")}<span class="live-small"><button class="link-button" data-live="discovery" data-serial="${esc(c.serial)}">查看硬件信息</button></span></td></tr>`,
        ),
      ),
      button("关闭", "close"),
    );
    state.wizard = { resource: "admission-result" };
    await load();
  });
}
observeUI("input", "onboarding.js", updateBatchSubmit, false);
observeUI("change", "onboarding.js", updateBatchSubmit, false);
observeUI(
  "click",
  "onboarding.js",
  async (event) => {
    const action = event.target.closest("[data-batch-action]");
    if (action) {
      try {
        if (action.dataset.batchAction === "system-query") {
          return await queryCurrentSystems();
        } else if (action.dataset.batchAction === "identity-refresh") {
          const w = state.wizard;
          if (w?.resource !== "batch" || w.step !== 1) return;
          action.disabled = true;
          await Promise.all([sectionReads.resources(), sectionReads.tasks()]);
          if (state.wizard !== w || w.step !== 1) return;
          w.selected = w.selected.filter((s) => {
            const d = state.resources.devices.find((d) => d.serial === s);
            return d && batchDeviceCondition(d).selectable;
          });
          batchWizard();
          await readCurrentSystems(w);
          return;
        } else if (action.dataset.batchAction === "refresh") {
          const w = state.wizard;
          if (w?.resource !== "batch") return;
          if (w.step === 2)
            w.entries = w.entries.map((e, i) => ({
              ...e,
              bmc_choice: $("#batch-bmc-" + i)?.checked
                ? "use_current"
                : "require_planned",
            }));
          action.disabled = true;
          await batchCheck();
        } else {
          const d = state.resources.devices.find(
            (d) => d.serial === action.dataset.serial,
          );
          if (!d) return;
          if (action.dataset.batchAction === "plan")
            await openReferencedPlan(d.id);
          else {
            state.installReviewReturn = state.wizard;
            await deviceDetail(d.serial, "hardware");
          }
        }
      } catch (error) {
        action.disabled = false;
        toast(error.message);
      }
      return;
    }
    const row = event.target.closest("[data-batch-device]");
    if (!row || event.target.closest("input,button,a,select,label")) return;
    const checkbox = row.querySelector("input[name=batch-device]");
    if (checkbox && !checkbox.disabled) {
      checkbox.checked = !checkbox.checked;
      checkbox.dispatchEvent(new Event("change", { bubbles: true }));
    }
  },
  false,
);

function firstProfileCards() {
  return state.resources.first_install_profiles
    .map(
      (p) =>
        `<section class="live-card" style="margin-bottom:18px"><h2>${esc(p.name)}</h2>${defs(
          [
            ["用途", "首次安装 / 已交付设备重装"],
            ["OS / 架构", esc(p.os_release) + " / " + esc(p.architecture)],
            [
              "网络模型",
              p.network_mode === "flat"
                ? "零受管 DPU · 既有 Flat VPC"
                : "受管 DPU · 既有租户网络",
            ],
            [
              "安装用户 / 公钥",
              esc(p.ssh_user) + "；管理员方案中的公钥及服务验收公钥",
            ],
            [
              "写盘与启动",
              "按 Scout udev 序列号唯一绑定系统盘；标准 UEFI，无机型硬编码",
            ],
            ["准备方式", "管理员配置并挂载通用模板；此处不接受任意安装脚本"],
          ],
        )}</section>`,
    )
    .join("");
}

observeUI(
  "change",
  "onboarding.js",
  (event) => {
    if (
      event.target.name === "admission-device" &&
      state.wizard?.resource === "admission"
    ) {
      state.wizard.previewRun = (state.wizard.previewRun || 0) + 1;
      state.wizard.preview = null;
      $("#admission-results").innerHTML = "";
      $(".modal-footer").innerHTML =
        button("取消", "close") +
        button("检查接入条件", "admission-preview", true);
    }
  },
  false,
);

observeUI(
  "change",
  "onboarding.js",
  (event) => {
    const checkbox = event.target,
      w = state.wizard;
    if (
      checkbox.name !== "batch-device" ||
      w?.resource !== "batch" ||
      w.step !== 1
    )
      return;
    if (checkbox.checked && !w.selected.includes(checkbox.value)) {
      if (w.selected.length >= 50) {
        checkbox.checked = false;
        toast("每批最多50台，请分批安装。");
        return;
      }
      w.selected.push(checkbox.value);
    } else if (!checkbox.checked)
      w.selected = w.selected.filter((s) => s !== checkbox.value);
    checkbox
      .closest("tr")
      ?.classList.toggle("batch-selected", checkbox.checked);
    if (w.filters?.selected) renderBatchDevices();
    else batchSelectionSummary();
  },
  false,
);
