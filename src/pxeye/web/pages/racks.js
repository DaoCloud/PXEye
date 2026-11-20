"use strict";
// 机柜: the rack objects NICo Core keeps for declared whole racks (GB200/GB300),
// their state machine, health and member devices. Where the site also enables
// rack actions, rack maintenance is requested here through the rack-actions API,
// which repeats every check and records every request before sending it.
state.racks = null;
state.racksCatalog = null;
sectionReads.racks = async () => {
  state.racks = await api("/api/racks");
};
sectionReads.racksCatalog = async () => {
  state.racksCatalog = await api("/api/rack-actions/catalog");
};
async function racksReload() {
  await Promise.allSettled(
    [
      "resources",
      "equipment",
      "deviceStatus",
      "racks",
      ...(racksActionsOn() ? ["racksCatalog"] : []),
    ].map((key) => readSection(key, sectionReads[key])),
  );
}
const racksActivities = [
  ["firmware_upgrade", "固件升级", "按 SOT JSON 升级整柜组件固件。"],
  ["nvos_update", "NVOS 更新", "按 SOT JSON 更新 NVLink 交换机的 NVOS。"],
  ["power_sequence", "电源序列", "依次正常重启计算主机。"],
  ["configure_nmx_cluster", "NVLink 集群配置", "配置 NMX 集群。"],
];
const racksRoles = [
  ["machines", "计算主机", "servers"],
  ["switches", "交换机", "switches"],
  ["power_shelves", "供电框", "power_shelves"],
];
// "Maintenance/FirmwareUpgrade/Start" reads as Maintenance（FirmwareUpgrade/Start）.
function racksStateText(state) {
  const text = String(state || "").trim();
  if (!text) return "未报告";
  const [main, ...rest] = text.split("/");
  return rest.length ? `${main}（${rest.join("/")}）` : main;
}
// Colour comes from Core's own signals (a failed handler, an overdue state);
// the names Ready and Error are the state machine's own verdicts.
function racksStateTone(rack) {
  const life = rack?.lifecycle || {},
    state = String(rack?.state || "");
  if (!state) return "gray";
  if (life.outcome === "error" || state.startsWith("Error")) return "red";
  if (life.above_sla) return "amber";
  if (state.startsWith("Ready")) return "green";
  return "amber";
}
const racksInMaintenance = (rack) =>
  String(rack?.state || "").startsWith("Maintenance");
function racksStateCell(rack) {
  const life = rack.lifecycle || {};
  return (
    badge(racksStateText(rack.state), racksStateTone(rack)) +
    (life.above_sla ? '<span class="live-small">超出状态时限</span>' : "") +
    (life.reason ? `<span class="live-small">${esc(life.reason)}</span>` : "")
  );
}
function racksHealthCell(rack) {
  const h = rack.health;
  if (!h || !h.level) return badge("未报告");
  const [label, tone] =
    deviceStatusHealth[h.level] || deviceStatusHealth.unknown;
  const count = (h.alerts || []).length;
  return badge(count ? `${label} · ${count}` : label, tone);
}
const racksCount = (rack) =>
  racksRoles
    .map(([key, label]) => `${label} ${(rack.devices?.[key] || []).length}`)
    .join(" · ");
const racksExpected = (id) =>
  (state.racks?.expected || []).find((e) => e.rack_id === id) || null;
const racksEntry = (id) =>
  (state.racksCatalog?.actions || []).find((a) => a.id === id) || null;
// Read from readiness each time: the navigation hook may reload this page
// before any hook of this script has run.
const racksActionsOn = () =>
  state.readiness?.rack_operations === true &&
  state.readiness?.rack_actions === true &&
  state.readiness?.read_only !== true;
const racksWritable = () =>
  racksActionsOn() && !document.body.classList.contains("read-only");
// The console's own device for a NICo object, so its status dialog can open.
function racksMember(key, id) {
  const devices = state.equipment?.devices || [];
  if (key === "machines") {
    const native = (state.resources?.devices || []).find(
      (x) => x.machine_id === id,
    );
    return native
      ? devices.find((d) => d.kind === "server" && d.serial === native.serial)
      : null;
  }
  return devices.find((d) => d.native_id === id) || null;
}
function racksMemberCell(key, page, id) {
  const d = racksMember(key, id);
  return d
    ? `<button class="link-button" data-live="device-status-open" data-device-status="${esc(page)}" ${eqAttr(d.id)}>${esc(d.name || d.serial || d.id)}</button><span class="live-small"><code>${esc(id)}</code></span>`
    : `<code>${esc(id)}</code><span class="live-small">设备管理中没有对应设备</span>`;
}
function racksRowActions(rack) {
  const id = `data-id="${esc(rack.id)}"`;
  let html = button("详情", "racks-detail", false, id);
  if (racksWritable() && state.racksCatalog) {
    html += button("机柜维护", "racks-maintenance-open", false, id);
    if (racksInMaintenance(rack))
      html += button("中止维护", "racks-terminate-open", false, id);
  }
  return `<div class="device-row-actions">${html}</div>`;
}
function racksPage() {
  const title = "机柜",
    description =
      "查看 NICo 机柜对象的状态、健康和成员设备" +
      (racksActionsOn() ? "，并发起机柜维护。" : "。");
  if (!state.rackOperations)
    return (
      heading(title, description) +
      '<div class="live-empty">此页面未在当前站点启用。</div>'
    );
  let body = heading(title, description, button("刷新数据", "racks-refresh"));
  const data = state.racks,
    error = state.readErrors?.racks;
  if (error)
    body += `<div class="live-error" role="alert">NICo 机柜读取失败：${esc(error)}</div>`;
  if (!data)
    return body + (error ? "" : '<div class="live-empty">正在读取机柜…</div>');
  for (const message of data.errors || [])
    body += `<div class="live-error" role="alert">${esc(message)}</div>`;
  if (racksActionsOn() && state.readErrors?.racksCatalog)
    body += `<div class="live-error" role="alert">机柜操作目录读取失败：${esc(state.readErrors.racksCatalog)}</div>`;
  const racks = data.racks || [],
    declared = (data.expected || []).filter(
      (e) => !racks.some((r) => r.id === e.rack_id),
    );
  if (!racks.length && !declared.length)
    return (
      body +
      `<div class="live-note">NICo 中没有机柜对象。NICo 只为声明的整柜（如 GB200 / GB300 NVL72）建立机柜对象，并以此管理整柜状态与维护；一般站点的服务器按机柜分组由人工声明，请在<button class="link-button" data-page="topology">机柜拓扑</button>中查看。</div>${racksSource(data)}`
    );
  if (racks.length) {
    const rows = racks.map((r) => {
      const e = racksExpected(r.id);
      return `<tr><td><button class="link-button" data-live="racks-detail" data-id="${esc(r.id)}">${esc(r.name || r.id)}</button>${r.name ? `<span class="live-small"><code>${esc(r.id)}</code></span>` : ""}</td><td>${racksStateCell(r)}</td><td>${racksHealthCell(r)}</td><td>${esc(r.profile || "—")}${r.group ? `<span class="live-small">机柜组 ${esc(r.group)}</span>` : ""}</td><td>${esc(racksCount(r))}</td><td>${e ? badge("已声明", "green") : badge("未声明")}</td><td>${racksRowActions(r)}</td></tr>`;
    });
    body += table(
      ["机柜", "NICo 状态", "健康", "机柜规格", "成员设备", "机柜声明", "操作"],
      rows,
    );
  }
  if (declared.length)
    body +=
      `<h3 style="margin: 20px 0 8px">已声明但 NICo 尚未建立的机柜</h3>` +
      table(
        ["rack_id", "名称", "机柜规格", "机柜组"],
        declared.map(
          (e) =>
            `<tr><td><code>${esc(e.rack_id || "—")}</code></td><td>${esc(e.name || "—")}</td><td>${esc(e.profile || "—")}</td><td>${esc(e.group || "—")}</td></tr>`,
        ),
      );
  return body + racksSource(data);
}
const racksSource = (data) =>
  `<p class="live-small">来自 NICo 机柜对象（FindRacksByIds）与机柜声明（GetAllExpectedRacks），读取于 ${esc(when(data.observed_at))}。</p>`;
const racksFind = (id) => (state.racks?.racks || []).find((r) => r.id === id);
function racksBoundary() {
  const entries = [
    ["rack_power_on", "整柜上电 / 整柜下电（NICo 未实现）"],
    ["rack_cold_reboot", "整柜冷重启（仅 RMS 提供，NICo 未接入）"],
  ];
  return `<div class="racks-boundary">${entries
    .map(
      ([id, label]) =>
        `<button class="button" disabled title="${esc(racksEntry(id)?.unavailable_reason || "")}">${esc(label)}</button>`,
    )
    .join("")}</div>`;
}
function racksDetail(id) {
  const rack = racksFind(id);
  if (!rack) throw Error("机柜已变化，请刷新。");
  const w = { resource: "racks-detail", rack: id };
  state.wizard = w;
  const e = racksExpected(id),
    life = rack.lifecycle || {};
  let body = defs([
    ["rack_id", `<code>${esc(rack.id)}</code>`],
    ["名称", esc(rack.name || "—")],
    ["NICo 状态", racksStateCell(rack)],
    ["健康", racksHealthCell(rack)],
    ["机柜规格", esc(rack.profile || "—")],
    ["机柜组", esc(rack.group || "—")],
    [
      "机柜声明",
      e
        ? `已声明${e.name ? " · " + esc(e.name) : ""}${(e.labels || []).length ? `<span class="live-small">${esc(e.labels.map((l) => (l.key || "") + (l.value ? "=" + l.value : "")).join("，"))}</span>` : ""}`
        : "未声明",
    ],
  ]);
  if ((rack.health?.alerts || []).length)
    body +=
      "<h3>当前健康告警</h3>" +
      table(
        ["告警", "对象", "说明"],
        rack.health.alerts.map(
          (a) =>
            `<tr><td>${esc(a.id || "—")}</td><td>${esc(a.target || "—")}</td><td>${esc(a.message || "—")}</td></tr>`,
        ),
      );
  body += "<h3>成员设备</h3>";
  const members = racksRoles.flatMap(([key, label, page]) =>
    (rack.devices?.[key] || []).map(
      (mid) =>
        `<tr><td>${esc(label)}</td><td>${racksMemberCell(key, page, mid)}</td></tr>`,
    ),
  );
  body += table(["类型", "设备"], members);
  body += `<h3>状态历史</h3><div id="racks-history"><div class="live-empty">正在读取…</div></div>`;
  if (racksActionsOn()) body += "<h3>整柜电源</h3>" + racksBoundary();
  let foot = button("关闭", "close");
  if (racksWritable() && state.racksCatalog) {
    if (racksInMaintenance(rack))
      foot += button(
        "中止维护",
        "racks-terminate-open",
        false,
        `data-id="${esc(id)}"`,
      );
    foot += button(
      "机柜维护",
      "racks-maintenance-open",
      true,
      `data-id="${esc(id)}"`,
    );
  }
  modal(rack.name || rack.id, "机柜 · NICo 状态与成员设备", body, foot);
  racksHistory(w, id);
}
async function racksHistory(w, id) {
  let html;
  try {
    const data = await api("/api/racks/" + encodeURIComponent(id) + "/history");
    html = (data.errors || [])
      .map((m) => `<div class="live-error" role="alert">${esc(m)}</div>`)
      .join("");
    const states = (data.states || []).slice().reverse();
    html += states.length
      ? table(
          ["状态", "进入时间", "停留"],
          states.map(
            (s) =>
              `<tr><td>${badge(racksStateText(s.state), s.current ? "green" : "gray")}</td><td>${esc(deviceStatusTime(s.entered_at))}</td><td>${esc(racksDuration(s.duration_seconds))}${s.current ? "（至今）" : ""}</td></tr>`,
          ),
        )
      : '<div class="live-note">NICo 未记录此机柜的状态历史。</div>';
    const health = data.health || [];
    if (health.length)
      html +=
        "<h3>健康记录（最近 50 条）</h3>" +
        table(
          ["时间", "告警"],
          health.map(
            (h) =>
              `<tr><td>${esc(deviceStatusTime(h.time))}</td><td>${h.alerts.length ? esc(h.alerts.map((a) => a.id + (a.target ? "@" + a.target : "")).join("，")) : badge("无告警", "green")}</td></tr>`,
          ),
        );
    html += `<p class="live-small">来自 FindRackStateHistories 与 FindRackHealthHistories，读取于 ${esc(when(data.observed_at))}。</p>`;
  } catch (e) {
    html = `<div class="live-error" role="alert">机柜历史读取失败：${esc(e.message)}</div>`;
  }
  if (state.wizard === w && $("#racks-history"))
    $("#racks-history").innerHTML = html;
}
function racksDuration(seconds) {
  if (seconds == null) return "—";
  const d = Math.floor(seconds / 86400),
    h = Math.floor((seconds % 86400) / 3600),
    m = Math.floor((seconds % 3600) / 60);
  return d ? `${d} 天 ${h} 小时` : h ? `${h} 小时 ${m} 分` : `${m} 分`;
}
// ---- maintenance -----------------------------------------------------------
// The form as plain values, then the request parameters. Kept free of the DOM so
// the rules can be tested on their own.
function racksMaintenanceParams(form) {
  const activities = form.activities || [];
  if (!activities.length) throw Error("请至少选择一个维护项目。");
  const params = { activities };
  const needsSot = activities.some((a) =>
    ["firmware_upgrade", "nvos_update"].includes(a),
  );
  const sot = String(form.sot || "").trim();
  if (needsSot) {
    if (!sot) throw Error("固件升级和 NVOS 更新需要 SOT JSON。");
    try {
      JSON.parse(sot);
    } catch {
      throw Error("SOT JSON 不是有效的 JSON。");
    }
    params.sot_json = sot;
  }
  if (activities.includes("firmware_upgrade")) {
    const components = String(form.components || "")
      .split(/[\s,，]+/)
      .filter(Boolean);
    if (components.length) params.components = components;
  }
  if (form.force) params.force_update = true;
  if (form.scope === "devices") {
    const picked = {
      machine_ids: form.machines || [],
      switch_ids: form.switches || [],
      power_shelf_ids: form.power_shelves || [],
    };
    if (!Object.values(picked).some((v) => v.length))
      throw Error("请至少选择一台设备，或改为整个机柜。");
    for (const [k, v] of Object.entries(picked)) if (v.length) params[k] = v;
  }
  const reason = String(form.reason || "").trim();
  if (reason) params.reason = reason;
  return params;
}
// What the confirmation must name: the rack and what each activity does.
function racksMaintenanceSummary(params) {
  const names = Object.fromEntries(racksActivities.map(([k, l]) => [k, l]));
  const scope = ["machine_ids", "switch_ids", "power_shelf_ids"].some(
    (k) => params[k],
  )
    ? `所选设备：计算主机 ${(params.machine_ids || []).length} · 交换机 ${(params.switch_ids || []).length} · 供电框 ${(params.power_shelf_ids || []).length}`
    : "整个机柜";
  return {
    scope,
    activities: params.activities.map((a) => names[a] || a).join("、"),
  };
}
function racksChoice(name, value, label, checked = false, hint = "") {
  return `<label><input type="checkbox" name="${esc(name)}" value="${esc(value)}"${checked ? " checked" : ""}><span>${esc(label)}${hint ? `<span class="live-small">${esc(hint)}</span>` : ""}</span></label>`;
}
function racksMaintenanceOpen(id) {
  const rack = racksFind(id),
    entry = racksEntry("rack_maintenance");
  if (!rack || !racksWritable()) return;
  if (!entry?.available)
    return toast(entry?.unavailable_reason || "机柜维护当前不可用。");
  state.wizard = { resource: "racks-maintenance", rack: id };
  const rms = state.racksCatalog?.rms || {};
  const activities = racksActivities
    .map(([k, l, hint]) =>
      racksChoice("racks-activity", k, l + "（需要 RMS）", false, hint),
    )
    .join("");
  const devices = racksRoles
    .map(([key, label, page]) => {
      const ids = rack.devices?.[key] || [];
      return ids.length
        ? `<p class="live-small">${esc(label)}</p><div class="racks-choices">${ids
            .map((mid) => {
              const d = racksMember(key, mid);
              return racksChoice(
                "racks-device-" + key,
                mid,
                d ? d.name || d.serial || mid : mid,
                false,
                d ? mid : "",
              );
            })
            .join("")}</div>`
        : "";
    })
    .join("");
  const body = `<div class="live-form">
<div class="live-note">机柜维护由 NICo 交给 RMS 执行，状态机进入 Maintenance，完成后回到 Ready。${rms.reachable ? `RMS 可达${rms.version ? "，版本 " + esc(rms.version) : ""}。` : `RMS 状态：${esc(rms.error || "未报告")}。`}</div>
<fieldset><legend>维护范围</legend><div class="racks-choices">
<label><input type="radio" name="racks-scope" value="rack" checked><span>整个机柜 <code>${esc(rack.id)}</code></span></label>
<label><input type="radio" name="racks-scope" value="devices"><span>所选设备</span></label></div>
<div id="racks-scope-devices" hidden>${devices || '<div class="live-note">NICo 未报告此机柜的成员设备。</div>'}</div></fieldset>
<fieldset><legend>维护项目</legend><div class="racks-choices">${activities}</div></fieldset>
<label for="racks-sot">SOT JSON<textarea class="input live-code" id="racks-sot" rows="6" spellcheck="false" placeholder="{ ... }"></textarea><span class="live-small">固件升级、NVOS 更新时必填；保存时只记录摘要。</span></label>
<label for="racks-components">固件组件<input class="input" id="racks-components"><span class="live-small">仅用于固件升级；多个用逗号分隔，留空表示全部组件。</span></label>
<div class="racks-choices">${racksChoice("racks-force", "1", "强制更新（force_update）")}</div>
<label for="racks-reason">原因<input class="input" id="racks-reason"><span class="live-small">可选，写入操作记录。</span></label>
</div><div id="racks-errors" role="alert"></div>`;
  modal(
    "机柜维护",
    `${rack.name || rack.id} · ${racksStateText(rack.state)}`,
    body,
    button("取消", "close") + button("预览", "racks-maintenance-preview", true),
  );
}
function racksMaintenanceForm() {
  const checked = (name) =>
    [...document.querySelectorAll(`input[name="${name}"]:checked`)].map(
      (x) => x.value,
    );
  return {
    scope: document.querySelector('input[name="racks-scope"]:checked')?.value,
    activities: checked("racks-activity"),
    machines: checked("racks-device-machines"),
    switches: checked("racks-device-switches"),
    power_shelves: checked("racks-device-power_shelves"),
    sot: $("#racks-sot").value,
    components: $("#racks-components").value,
    force: checked("racks-force").length > 0,
    reason: $("#racks-reason").value,
  };
}
async function racksPreview(action, params, lines) {
  const w = state.wizard;
  const preview = await api("/api/rack-actions/preview", {
    action,
    targets: [w.rack],
    params,
  });
  if (state.wizard !== w) return;
  w.preview = preview;
  const t = preview.targets[0] || {},
    entry = preview.action || {},
    high = entry.needs_confirm_serial;
  let body = defs([
    [
      "机柜",
      `<code>${esc(t.target)}</code>${t.name ? " · " + esc(t.name) : ""}`,
    ],
    ["当前状态", esc(racksStateText(t.state))],
    ...lines,
    ["影响", esc(entry.effect || "—")],
    [
      "NICo 接口",
      `<code>${esc(entry.rpc || "")}</code>${entry.needs_rms ? " · 需要 RMS" : ""}`,
    ],
  ]);
  body += t.eligible
    ? ""
    : `<div class="live-error" role="alert">不能执行：${esc((t.reasons || []).join("；") || "未说明原因")}</div>`;
  if (t.eligible && high)
    body += `<div class="live-form"><label for="racks-confirm">输入机柜 ID <code>${esc(t.confirm_with === "serial" ? t.serial : t.target)}</code> 以确认<input class="input" id="racks-confirm" autocomplete="off"></label></div>`;
  body += `<p class="live-small">预览有效期至 ${esc(when(preview.expires_at))}，执行前会重新检查。请求先记录为已发送，再发往 NICo，不会自动重发。</p><div id="racks-errors" role="alert"></div>`;
  modal(
    entry.label || "机柜操作",
    "确认 · " + (t.name || t.target),
    body,
    button("取消", "close") +
      (t.eligible ? button("执行", "racks-execute", true) : ""),
  );
}
async function racksMaintenancePreview(el) {
  let params;
  try {
    params = racksMaintenanceParams(racksMaintenanceForm());
  } catch (e) {
    $("#racks-errors").innerHTML =
      `<div class="live-error">${esc(e.message)}</div>`;
    return;
  }
  const s = racksMaintenanceSummary(params);
  el.disabled = true;
  try {
    await racksPreview("rack_maintenance", params, [
      ["范围", esc(s.scope)],
      ["维护项目", esc(s.activities)],
      ...(params.components
        ? [["固件组件", esc(params.components.join("，"))]]
        : []),
      ...(params.force_update ? [["强制更新", "是"]] : []),
    ]);
  } catch (e) {
    if ($("#racks-errors"))
      $("#racks-errors").innerHTML =
        `<div class="live-error">${esc(e.message)}</div>`;
  } finally {
    el.disabled = false;
  }
}
async function racksTerminateOpen(id) {
  const rack = racksFind(id);
  if (!rack || !racksWritable()) return;
  state.wizard = { resource: "racks-maintenance", rack: id };
  try {
    await racksPreview("rack_maintenance_terminate", {}, []);
  } catch (e) {
    toast(e.message);
    close();
  }
}
const racksResultTone = {
  succeeded: "green",
  failed: "red",
  refused: "red",
  unknown: "amber",
};
const racksResultText = {
  succeeded: "已确认",
  failed: "失败",
  refused: "已拒绝",
  unknown: "结果未知",
};
async function racksExecute(el) {
  const w = state.wizard,
    t = w?.preview?.targets?.[0];
  if (!t) return;
  const confirm = $("#racks-confirm")?.value.trim();
  el.disabled = true;
  let result;
  try {
    result = await api("/api/rack-actions/execute", {
      preview_token: w.preview.preview_token,
      confirm_serials: confirm ? { [t.target]: confirm } : {},
    });
  } catch (e) {
    el.disabled = false;
    $("#racks-errors").innerHTML =
      `<div class="live-error">${esc(e.message)}</div>`;
    return;
  }
  const rows = (result.results || []).map(
    (r) =>
      `<tr><td><code>${esc(r.target)}</code></td><td>${badge(racksResultText[r.status] || r.status, racksResultTone[r.status] || "gray")}${(r.reasons || []).length ? `<span class="live-small">${esc(r.reasons.join("；"))}</span>` : ""}</td><td>${esc(r.core_message || "—")}</td><td><code>${esc(r.record_id || "")}</code></td></tr>`,
  );
  modal(
    w.preview.action?.label || "机柜操作",
    "执行结果",
    table(["机柜", "结果", "NICo 返回", "记录"], rows) +
      '<p class="live-small">“结果未知”表示请求可能已被 NICo 接受但读回无法确认；请刷新机柜状态核对，不要重复提交。</p>',
    button("关闭", "close"),
  );
  readSection("racks", sectionReads.racks);
}
registerPage("racks", racksPage);
registerActions(
  "racks.js",
  [
    "racks-refresh",
    "racks-detail",
    "racks-maintenance-open",
    "racks-maintenance-preview",
    "racks-terminate-open",
    "racks-execute",
  ],
  async (e) => {
    const el = e.target.closest('[data-live^="racks-"]');
    if (!el || el.disabled) return;
    const action = el.dataset.live;
    if (action === "racks-refresh") return await racksReload();
    if (action === "racks-detail") return racksDetail(el.dataset.id);
    if (action === "racks-maintenance-open")
      return racksMaintenanceOpen(el.dataset.id);
    if (action === "racks-maintenance-preview")
      return await racksMaintenancePreview(el);
    if (action === "racks-terminate-open")
      return await racksTerminateOpen(el.dataset.id);
    if (action === "racks-execute") return await racksExecute(el);
  },
);
observeUI(
  "change",
  "racks.js",
  (e) => {
    if (e.target.name === "racks-scope" && $("#racks-scope-devices"))
      $("#racks-scope-devices").hidden = e.target.value !== "devices";
  },
  false,
);
deviceStatusAddNavChild("racks", "机柜", racksReload);
if (typeof module !== "undefined")
  module.exports = {
    racksStateText,
    racksStateTone,
    racksMaintenanceParams,
    racksMaintenanceSummary,
  };
