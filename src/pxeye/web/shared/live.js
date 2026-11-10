"use strict";
const $ = (s) => document.querySelector(s);
const esc = (v) =>
  String(v ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const labels = {
  topology: "机柜拓扑",
  tasks: "安装任务",
  devices: "设备管理",
  instances: "实例管理",
  os: "操作系统",
  network: "网络管理",
  profiles: "安装方案",
  site: "站点设置",
  nico: "NICo 集群",
};
const groups = [
  ["总览", ["topology"]],
  ["装机", ["tasks"]],
  ["资源", ["devices", "instances", "os", "network"]],
  ["配置", ["profiles", "site", "nico"]],
];
const statuses = {
  queued: "待执行",
  running: "执行中",
  completed: "已完成",
  needs_attention: "需处理",
  cancelled: "已终止",
};
const stages = {
  queued: "等待执行",
  prepare: "准备设备",
  preflight: "安装前检查",
  planning: "同步设备规划",
  materials: "准备设备",
  network: "准备设备",
  configure: "准备设备",
  allocate: "安装系统",
  boot: "安装系统",
  pxe: "安装系统",
  install: "安装系统",
  handoff: "启动系统盘",
  firstboot: "安装验收",
  gpu_check: "GPU 环境检查",
  reboot: "重启验收",
  completed: "完成",
  cancelled: "任务已终止",
};
let state = {
  page: "topology",
  resources: null,
  siteInfo: null,
  readiness: null,
  nico: null,
  tasks: [],
  csrf: null,
  modal: null,
  wizard: null,
  detail: null,
  networks: null,
  batches: [],
  topologyLayout: { racks: [] },
  topologyEditing: false,
  logData: null,
  logFollow: true,
  logScroll: 0,
};
const button = (text, action, primary = false, extra = "") =>
  `<button class="button ${primary ? "primary" : ""}" data-live="${action}" ${extra}>${esc(text)}</button>`;
const badge = (text, color = "gray") =>
  `<span class="status ${color}">${esc(text)}</span>`;
const table = (heads, rows) =>
  `<div class="live-table-wrap"><table class="live-table"><thead><tr>${heads.map((x) => `<th>${esc(x)}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table>${rows.length ? "" : '<div class="live-empty">暂无记录</div>'}</div>`;
const defs = (rows) =>
  `<dl class="live-def">${rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join("")}</dl>`;
const heading = (name, description, actions = "") =>
  `<div class="live-heading"><div><h1 tabindex="-1">${esc(name)}</h1><p>${esc(description)}</p></div><div class="live-tools">${actions}</div></div>`;
const when = (t) =>
  t ? new Date(t * 1000).toLocaleString("zh-CN", { hour12: false }) : "—";
const bytes = (value) =>
  value == null
    ? "—"
    : value >= 1024 ** 3
      ? (value / 1024 ** 3).toFixed(1) + " GiB"
      : value >= 1024 ** 2
        ? (value / 1024 ** 2).toFixed(1) + " MiB"
        : value.toLocaleString() + " B";
function toast(text) {
  $("#toast").textContent = text;
  $("#toast").classList.add("visible");
  setTimeout(() => $("#toast").classList.remove("visible"), 6000);
}
const pendingReads = new Map();
async function api(path, body) {
  if (!body && pendingReads.has(path)) return pendingReads.get(path);
  const request = (async () => {
    const controller = !body ? new AbortController() : null;
    const timer = controller
      ? setTimeout(() => controller.abort(), 20000)
      : null;
    try {
      const result = await fetch(path, {
        method: body ? "POST" : "GET",
        headers: body
          ? {
              "Content-Type": "application/json",
              "X-CSRF-Token": state.csrf || "",
            }
          : {},
        body: body ? JSON.stringify(body) : undefined,
        credentials: "same-origin",
        ...(controller ? { signal: controller.signal } : {}),
      });
      const data = await result.json();
      if (!result.ok) {
        const error = Error(data.error || "请求失败");
        error.status = result.status;
        error.code = data.code;
        error.requestId = data.request_id;
        throw error;
      }
      return data;
    } catch (error) {
      if (error.name === "AbortError")
        throw Error("读取超时，请稍后刷新此页面。");
      throw error;
    } finally {
      if (timer) clearTimeout(timer);
    }
  })();
  if (body) return request;
  pendingReads.set(path, request);
  try {
    return await request;
  } finally {
    pendingReads.delete(path);
  }
}
function active(d) {
  return state.tasks.find(
    (t) =>
      t.device === d.serial &&
      ["queued", "running", "needs_attention"].includes(t.status),
  );
}
function nav() {
  $("#navigation").innerHTML = groups
    .map(
      ([group, pages]) =>
        `<div class="nav-group"><div class="nav-label">${group}</div>${pages
          .map((id) => {
            const unavailable =
              state.readiness &&
              !state.readiness.business_available &&
              !["nico", "site"].includes(id);
            return `<button class="nav-item ${state.page === id ? "active" : ""}" data-page="${id}" ${unavailable ? 'disabled title="请先部署 NICo 并连接站点"' : ""}><span>${labels[id]}</span></button>`;
          })
          .join("")}</div>`,
    )
    .join("");
  $("#breadcrumb").textContent = labels[state.page];
}
function login() {
  nav();
  $("#main").innerHTML =
    `<section class="live-card live-login"><h2>登录装机控制台</h2><form id="login-form" class="live-form"><label for="login-password">操作员口令<input class="input" id="login-password" type="password" autocomplete="current-password" required></label><div id="login-error" class="live-error" role="alert"></div><button class="button primary" type="submit">登录控制台</button></form></section>`;
  $("#login-form").onsubmit = async (e) => {
    e.preventDefault();
    const b = e.target.querySelector("button");
    b.disabled = true;
    try {
      const r = await api("/api/login", {
        password: $("#login-password").value,
      });
      state.csrf = r.csrf;
      await load();
    } catch (e) {
      $("#login-error").textContent = e.message;
    } finally {
      b.disabled = false;
    }
  };
}
state.readErrors = {};
async function readSection(key, read) {
  try {
    await read();
    delete state.readErrors[key];
  } catch (error) {
    state.readErrors[key] = error.message;
  }
  if (!state.wizard) render();
}
const sectionReads = {
  resources: async () => {
    state.resources = await api("/api/resources");
    $("#site-label").textContent = state.resources.site.name;
  },
  tasks: async () => {
    state.tasks = (await api("/api/tasks")).tasks;
  },
  batches: async () => {
    state.batches = (await api("/api/batches")).batches;
  },
  os: () => loadOS(),
  profiles: () => loadProfiles(),
  network: () => loadNetworks(),
  instances: () => loadInstances(),
  site: async () => {
    state.siteInfo = await api("/api/site");
  },
  topologyLayout: async () => {
    state.topologyLayout = await api("/api/topology-layout");
  },
};
async function load() {
  $("#operator").textContent = "站点操作员 · 已登录";
  state.readiness = await api("/api/readiness");
  $("#site-label").textContent = state.readiness.site_name;
  if (!state.readiness.business_available) {
    if (state.page !== "site") state.page = "nico";
    location.hash = state.page;
    syncPollers(state.page);
    await refreshPage(state.page);
    render();
    return;
  }
  render();
  await Promise.allSettled(
    ["resources", "tasks", "batches", "profiles", "os"].map((key) =>
      readSection(key, sectionReads[key]),
    ),
  );
  if (["topology", "network", "instances", "devices"].includes(state.page))
    await refreshPage(state.page);
  if (["nico", "site"].includes(state.page)) await refreshPage(state.page);
}
async function refreshPage(page = state.page) {
  const sections = {
    topology: ["equipment", "network", "topologyLayout"],
    tasks: ["tasks", "batches", "resources"],
    devices: ["resources", "equipment", "equipmentPlanning", "network"],
    instances: ["instances"],
    os: ["os"],
    profiles: ["profiles"],
    network: ["network", "equipment"],
    site: ["site"],
    nico: ["nico"],
  };
  await Promise.allSettled(
    (sections[page] || []).map((key) => readSection(key, sectionReads[key])),
  );
}
async function navigate(page) {
  if (
    state.readiness &&
    !state.readiness.business_available &&
    !["nico", "site"].includes(page)
  ) {
    toast("请先部署 NICo 并连接站点。");
    return;
  }
  state.page = page;
  location.hash = page;
  syncPollers(page);
  render();
  await refreshPage(page);
}
const bmcLink = (ip) =>
  ip
    ? `<a class="link-button" href="https://${esc(ip)}" target="_blank" rel="noopener noreferrer">${esc(ip)} ↗</a>`
    : "—";
const taskStatus = (t) =>
  t.automatic_recovery &&
  !["completed", "blocked", "unknown"].includes(t.automatic_recovery.state)
    ? { label: "自动修复中", tone: "amber" }
    : t.recovery_observing
      ? { label: "等待安装结果", tone: "amber" }
      : {
          label: statuses[t.status],
          tone:
            t.status === "completed"
              ? "green"
              : t.status === "cancelled"
                ? "gray"
                : t.status === "needs_attention"
                  ? "red"
                  : "amber",
        };
function taskRows() {
  return state.tasks.map((t) => {
    const status = taskStatus(t);
    return `<tr><td><button class="link-button" data-task="${esc(t.id)}">${esc(t.id)}</button><span class="live-small">${when(t.created_at)}</span></td><td>${esc(t.device)}<span class="live-small">${esc(t.management_ip)}</span></td><td>${esc(t.hostname)}</td><td>${badge(status.label, status.tone)}<span class="live-small">${esc(stages[t.stage])}</span></td><td>${bmcLink(state.resources?.devices.find((d) => d.serial === t.device)?.bmc_ip)}</td><td><button class="link-button" data-task="${esc(t.id)}">实时日志 / 记录</button></td></tr>`;
  });
}
function sitePage() {
  const s = state.siteInfo;
  if (!s)
    return (
      heading(
        "站点设置",
        "控制面连接、身份和运行目录。",
        button("刷新数据", "refresh"),
      ) + '<div class="live-empty">正在读取站点信息…</div>'
    );
  const identity = s.identity || {},
    core = s.components.find((c) => c.id === "core") || {},
    healthy = core.state === "reachable";
  const storage = s.storage
    .map((x) => {
      const used =
          x.available && x.total_bytes
            ? Math.max(0, x.total_bytes - x.available_bytes)
            : 0,
        pct = x.total_bytes
          ? Math.min(100, Math.round((used / x.total_bytes) * 100))
          : 0;
      return `<div class="site-storage-item"><div class="site-storage-copy"><strong>${esc(x.role)}</strong><span class="live-code">${esc(x.path)}</span></div><div class="site-storage-usage"><span>${x.available ? bytes(used) + " 已用 · " + bytes(x.available_bytes) + " 可用" : "目录不可用"}</span>${x.available ? `<div class="site-storage-meter" aria-label="已使用 ${pct}%"><i style="width:${pct}%"></i></div>` : ""}</div></div>`;
    })
    .join("");
  const services = s.components
    .map((c) => {
      const label =
          c.state === "reachable"
            ? "可达"
            : c.state === "unreachable"
              ? "不可达"
              : "已配置",
        tone =
          c.state === "reachable"
            ? "ok"
            : c.state === "unreachable"
              ? "bad"
              : "set";
      return `<div class="site-service-row"><span class="site-service-dot ${tone}" aria-hidden="true"></span><div class="site-service-name"><strong>${esc(c.name)}</strong><span>${esc(c.role)}</span></div><span class="site-service-endpoint live-code">${esc(c.endpoint)}</span><div class="site-service-state ${tone}"><strong>${label}</strong><span>${esc(c.detail)}${c.latency_ms != null ? " · " + c.latency_ms + " ms" : ""}</span></div></div>`;
    })
    .join("");
  return (
    heading(
      "站点设置",
      "查看和维护 NICo 控制面。",
      button("刷新数据", "refresh") + button("编辑站点", "site-edit", true),
    ) +
    `<section class="site-overview"><div class="site-overview-main"><span class="site-eyebrow">当前站点</span><h2>${esc(s.site.name)}</h2><div class="site-overview-meta"><span>${esc(s.site.namespace)} / ${esc(s.site.deployment)}</span><span class="live-code">${esc(s.core_url)}</span><span>新建安装批次默认并发 ${esc(s.default_install_concurrency || 5)} 台</span></div></div><div class="site-health"><span class="site-status-dot ${healthy ? "ok" : "bad"}"></span><div><strong>${healthy ? "Core 连接正常" : "Core 连接异常"}</strong><span>${esc(core.detail || "尚未获得连接状态")}</span><small>检查于 ${when(s.checked_at)}</small></div></div></section>` +
    `<div class="site-layout"><section class="site-panel"><header class="site-panel-header"><div><span class="site-eyebrow">安全连接</span><h2>连接身份</h2></div></header><dl class="site-identity"><div><dt>客户端身份</dt><dd>${esc(identity.subject || identity.error || "未提供")}</dd></div><div><dt>签发者</dt><dd>${esc(identity.issuer || "—")}</dd></div><div><dt>有效期</dt><dd>${esc(identity.valid_from || "—")}<span>至 ${esc(identity.valid_until || "—")}</span></dd></div></dl></section><section class="site-panel"><header class="site-panel-header"><div><span class="site-eyebrow">本地存储</span><h2>数据目录</h2></div></header><div class="site-storage-list">${storage}</div></section></div>` +
    `<section class="site-panel site-services-panel"><header class="site-panel-header"><div><span class="site-eyebrow">运行依赖</span><h2>网络与基础服务</h2></div>${button("管理 OS DNS", "site-network")}</header><div class="site-services">${services}</div><p class="site-panel-note">${esc(s.dns_maintenance.detail)}</p></section>`
  );
}
function editSite() {
  const s = state.siteInfo;
  state.wizard = { resource: "site-edit" };
  modal(
    "编辑站点",
    "修改站点标识和 NICo Core 连接",
    `<div class="live-form">${inputField("site-name", "站点名称", s.site.name, 'maxlength="100"')}${inputField("site-core", "Core HTTPS 地址", s.core_url, 'type="url"')}${inputField("site-install-concurrency", "默认安装并发", s.default_install_concurrency || 5, 'type="number" min="1" max="50" step="1"')}<p class="live-small">新建安装批次使用保存时的默认并发；已创建批次保持原值。Core 地址保存前会使用当前 mTLS 身份验证。</p><div id="resource-error" class="live-error"></div></div>`,
    button("取消", "close") + button("验证并保存", "site-save", true),
  );
}
async function saveSite() {
  const previouslyConnected = state.readiness?.business_available;
  const result = await api("/api/site", {
    name: $("#site-name").value.trim(),
    core_url: $("#site-core").value.trim(),
    default_install_concurrency: Number($("#site-install-concurrency").value),
  });
  state.siteInfo = result.site;
  if (state.resources) {
    state.resources.site = result.site.site;
    state.resources.core_url = result.site.core_url;
  }
  $("#site-label").textContent = result.site.site.name;
  state.readiness = await api("/api/readiness");
  close();
  render();
  toast(result.detail);
  if (!previouslyConnected && state.readiness.business_available) await load();
}
function render() {
  nav();
  const r = state.resources || { devices: [], site: {} },
    d = r.devices.find((x) => x.os_release) || r.devices[0] || {};
  let body = "";
  const keys =
    {
      topology: ["equipment", "network", "topologyLayout"],
      tasks: ["tasks", "batches", "resources"],
      devices: ["resources", "equipment", "equipmentPlanning", "network"],
      instances: ["instances"],
      os: ["os"],
      profiles: ["profiles"],
      network: ["network", "equipment"],
      site: ["site"],
    }[state.page] || [];
  const errors = keys
    .filter((key) => state.readErrors?.[key])
    .map((key) => state.readErrors[key]);
  body = pageRenderers.get(state.page)?.() || "";
  if (errors.length)
    body =
      '<div class="live-error" role="alert">' +
      esc([...new Set(errors)].join("；")) +
      " 请刷新重试。</div>" +
      body;
  if (
    state.page !== "network" ||
    state.renderedNetwork !== body ||
    !$("#main").querySelector("[data-network-view]")
  ) {
    const scroll = window.scrollY;
    $("#main").innerHTML = body;
    if (
      state.page === "nico" &&
      (state.nico?.busy || state.nico?.operation?.started_at)
    ) {
      document
        .querySelectorAll(".nico-form input,.nico-form select")
        .forEach((input) => (input.disabled = true));
    }
    if (state.page === "network") {
      state.renderedNetwork = body;
      window.scrollTo(0, scroll);
    }
  }
}
function close() {
  runHooks("modalClosed");
  state.modal = null;
  state.detail = null;
  state.wizard = null;
  state.installReviewReturn = null;
  $("#overlay-root").innerHTML = "";
  $(".app-shell").inert = false;
  document.body.style.overflow = "";
}
function modal(title, sub, body, foot) {
  state.modal = true;
  $(".app-shell").inert = true;
  document.body.style.overflow = "hidden";
  $("#overlay-root").innerHTML =
    `<div class="overlay-backdrop"><section class="modal wide" role="dialog" aria-modal="true" aria-labelledby="live-dialog-title"><header class="modal-header"><div><h2 id="live-dialog-title">${esc(title)}</h2><p>${esc(sub)}</p></div><button class="icon-button live-close" data-live="close" aria-label="关闭"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true" focusable="false"><path d="M6 6l12 12M18 6L6 18"/></svg></button></header><div class="modal-body">${body}</div><footer class="modal-footer">${foot}</footer></section></div>`;
  $("#overlay-root button:not([disabled]),#overlay-root input")?.focus();
}
function start(serial) {
  const eligible = state.resources.devices.filter((d) => d.executable);
  if (!eligible.length)
    return toast("暂无可重装设备。请先添加设备，再新建安装任务。");
  state.wizard = {
    step: 1,
    device: serial || eligible[0].serial,
    hostname:
      state.resources.devices.find(
        (d) => d.serial === serial || d.serial === eligible[0].serial,
      )?.intent?.hostname || "",
    request_key:
      crypto.randomUUID?.() ||
      "req-" + Date.now() + "-" + Math.random().toString(36).slice(2),
    check: null,
  };
  wizard();
}
function wizard() {
  const w = state.wizard,
    d = state.resources.devices.find((d) => d.serial === w.device);
  let body = `<div class="live-step">${["选择设备", "安装配置", "检查并确认"].map((x, i) => (i + 1 === w.step ? `<strong>${i + 1}. ${x}</strong>` : `${i + 1}. ${x}`)).join("　→　")}</div>`,
    foot = "";
  if (w.step === 1) {
    body +=
      table(
        ["选择", "设备", "现有 Instance", "管理地址", "状态"],
        state.resources.devices
          .filter((x) => x.executable)
          .map(
            (d) =>
              `<tr><td><input type="radio" name="device" value="${esc(d.serial)}" ${w.device === d.serial ? "checked" : ""} ${!d || active(d) ? "disabled" : ""}></td><td>${esc(d.serial)}</td><td class="live-code">${esc(d.instance_id)}</td><td>当前 ${esc(d.current_management_ip || d.management_ip)}<span class="live-small">安装目标 ${esc(d.management_ip)}</span></td><td>${active(d) ? "任务占用" : "可申请重装"}</td></tr>`,
          ),
      ) +
      `<div class="live-note live-warning">重装将覆盖所选系统盘；保留 Instance 和其他磁盘。</div>`;
    foot =
      button("取消", "close") +
      button("下一步", "next", true, !d || active(d) ? "disabled" : "");
  }
  if (w.step === 2) {
    body += `<form class="live-form" id="install-config"><label for="target-hostname">目标主机名<input class="input" id="target-hostname" name="hostname" value="${esc(w.hostname)}" pattern="[a-z0-9]([a-z0-9]|-){0,62}" maxlength="63" required></label></form><section class="live-card" style="margin-top:20px">${defs(
      [
        ["安装方案", esc(d.profile)],
        ["目标 OS", esc(d.os_release)],
        ["当前连接地址", esc(d.current_management_ip || d.management_ip)],
        ["本次安装目标地址", esc(d.management_ip)],
        [
          "目标系统盘",
          `<span class="live-code">${esc(d.disk_serial ? "Scout serial: " + d.disk_serial : "wwn:" + d.disk_wwn)}</span>`,
        ],
        [
          "安装来源",
          "UI 任务编号将写入 /etc/nico-installation.json 和安装日志目录",
        ],
      ],
    )}</section>`;
    foot = button("上一步", "back") + button("检查安装条件", "check", true);
  }
  if (w.step === 3) {
    const check = w.check;
    body += check
      ? `<div class="live-checks">${check.checks.map((c) => `<div class="${c.passed ? "good" : "bad"}"><strong>${c.passed ? "✓" : "!"} ${esc(c.name)}</strong>${esc(c.detail)}</div>`).join("")}</div>${defs(
          [
            ["设备 / 主机名", esc(d.serial) + " / " + esc(w.hostname)],
            [
              "覆盖范围",
              `<span class="live-code">${esc(d.disk_serial ? "Scout serial: " + d.disk_serial : "wwn:" + d.disk_wwn)}</span>`,
            ],
            ["当前连接地址", esc(check.scope.current_management_ip)],
            ["本次安装目标地址", esc(check.scope.management_ip)],
            ["预检有效期", "5 分钟；执行前再次核对配置与占用"],
          ],
        )}<div class="live-note live-warning">将应用规划地址、覆盖所选系统盘，并重启验证。</div><div class="live-form"><label for="confirm-serial">输入设备 SN 确认范围<input class="input" id="confirm-serial" autocomplete="off" placeholder="${esc(d.serial)}"></label><label class="live-check"><input type="checkbox" id="confirm-disk">确认覆盖所选系统盘，保留其他磁盘。</label><label class="live-check"><input type="checkbox" id="confirm-reboot">允许安装及重启验证。</label></div>`
      : `<div class="live-empty">正在检查安装条件…</div>`;
    foot =
      button("上一步", "back") +
      button("重新检查", "check", false, !check ? "disabled" : "") +
      button("确认并重装", "submit", true, 'id="submit-real" disabled');
  }
  modal(
    "新建物理机重装任务",
    `步骤 ${w.step} / 3`,
    body,
    `<div class="actions">${foot}</div>`,
  );
  state.wizard = w;
}
async function check() {
  const w = state.wizard;
  if (w.step === 2) {
    const input = $("#target-hostname");
    if (!/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(input.value.trim())) {
      input.setCustomValidity(
        "hostname 使用 1–63 位小写字母、数字和短横线，首尾不能为短横线。",
      );
      input.reportValidity();
      input.setCustomValidity("");
      return;
    }
    if (!$("#install-config").reportValidity()) return;
    w.hostname = input.value.trim();
  }
  w.step = 3;
  w.check = null;
  wizard();
  try {
    w.check = await api("/api/preflight", {
      device: w.device,
      hostname: w.hostname,
    });
    if (state.wizard === w) wizard();
  } catch (e) {
    toast(e.message);
    if (state.wizard === w) {
      w.step = 2;
      wizard();
    }
  }
}
function updateSubmit() {
  if (!state.wizard || state.wizard.step !== 3 || !$("#submit-real")) return;
  $("#submit-real").disabled = !(
    state.wizard.check?.passed &&
    $("#confirm-serial").value === state.wizard.device &&
    $("#confirm-disk").checked &&
    $("#confirm-reboot").checked
  );
}
async function submit() {
  const w = state.wizard;
  $("#submit-real").disabled = true;
  try {
    const t = await api("/api/tasks", {
      device: w.device,
      hostname: w.hostname,
      preflight_id: w.check.id,
      request_key: w.request_key,
      confirm_serial: $("#confirm-serial").value,
      confirm_disk: $("#confirm-disk").checked,
      confirm_reboot: $("#confirm-reboot").checked,
    });
    state.wizard = null;
    state.detail = t.id;
    await refreshTasks();
    detail(t.id);
  } catch (e) {
    toast(e.message);
    updateSubmit();
  }
}
function detail(id) {
  const t = state.tasks.find((t) => t.id === id);
  if (!t) return;
  state.wizard = null;
  if (state.detail !== id) {
    state.logFollow = true;
    state.logScroll = 0;
  }
  state.detail = id;
  const after = t.after_reboot,
    status = taskStatus(t),
    acceptance =
      t.status === "completed"
        ? after || t.initial || t.installation_checks
        : t.installation_checks ||
          (t.status === "running" && t.stage === "firstboot" ? null : after || t.initial),
    checks = acceptance?.checks || {};
  let body = `<div class="live-task-title"><div>${badge(status.label, status.tone)} <strong>${esc(stages[t.stage])}</strong></div><span class="live-small">${when(t.created_at)} · ${esc(t.actor)}</span></div>${defs(
    [
      ["设备 / 主机名", esc(t.device) + " / " + esc(t.hostname)],
      ["本次安装目标地址", esc(t.management_ip)],
      [
        "安装前连接地址",
        esc(
          t.mode === "first_install"
            ? "首次安装，无原连接"
            : t.current_management_ip || t.management_ip,
        ),
      ],
      [
        "BMC 控制台",
        bmcLink(
          state.resources?.devices.find((d) => d.serial === t.device)?.bmc_ip,
        ),
      ],
      ["Instance", `<span class="live-code">${esc(t.instance_id)}</span>`],
      [
        "目标盘",
        `<span class="live-code">${esc(t.disk_serial ? "Scout serial: " + t.disk_serial : t.disk_wwn ? "wwn:" + t.disk_wwn : "硬件回报后确定")}</span>`,
      ],
      ["配置版本", esc(t.config_version || "尚未更新")],
      [
        "配置 SHA256",
        `<span class="live-code">${esc(t.user_data_sha256 || "尚未生成")}</span>`,
      ],
    ],
  )}`;
  if (
    t.stage === "prepare" &&
    String(t.preparation_observation?.state || "").startsWith(
      "WaitingForCleanup/HostCleanup",
    )
  )
    body += `<div class="live-note live-warning">等待 Scout 完成磁盘清理，尚未开始 OS 安装。长时间无进展时，请检查 Scout 服务、API 连接和清理日志。</div>`;
  if (t.warnings?.length)
    body += `<div class="live-note live-warning">系统安装及启动验收已通过；${t.warnings.map(esc).join("；")}。这些为环境服务告警。</div>`;
  if (t.installer_progress)
    body += defs([
      [
        "安装进度",
        t.installer_progress.shutdown
          ? "安装器已退出，等待系统启动"
          : t.installer_progress.installed
            ? "安装器已成功收尾"
            : t.installer_progress.identity
              ? "已取得本轮系统身份"
              : "安装环境已启动",
      ],
      [
        "观察串口",
        esc(
          Object.values(t.installer_progress).find((x) => x.console)?.console ||
            "由平台确定",
        ),
      ],
    ]);
  if (t.error)
    body += `<div class="live-note live-warning" role="alert">${esc(t.error)}；任务已暂停，请查看执行记录和日志。</div>`;
  body += `<section class="subsection"><h3>实时安装日志</h3><p class="live-small">BMC 串口日志 · 每 5 秒刷新 · 最近 64 KiB</p><div class="live-log-tools"><label><input type="checkbox" id="log-follow" ${state.logFollow ? "checked" : ""}> 跟随最新输出</label><span id="log-time" class="live-small"></span></div><pre id="sol-output" class="live-log" tabindex="0">正在读取安装日志…</pre></section><section class="subsection"><h3>执行与恢复记录</h3><ol class="live-events">${t.events.map((e) => `<li><time>${when(e.at)}</time>${e.recovery ? "<strong>启动兼容恢复 · </strong>" : ""}${esc(e.message)}</li>`).join("") || "<li>等待后台执行</li>"}</ol></section><section class="subsection"><h3>安装验收</h3><div class="live-checks">${Object.entries(
    {
      installer: "安装器成功",
      identity: "主机配置",
      disk: "系统盘与 EFI 分区验证",
      network: "网络配置",
      ssh: "SSH 连通",
      services: "DNS / HTTP / NTP 连通",
      gpu_environment: "GPU 环境检查",
      normal_reboot: "重启验收",
    },
  )
    .map(([k, v]) => {
      if (k === "gpu_environment") {
        const gpu = t.gpu_check;
        const enabled = t.gpu_environment_check === true;
        const label = !enabled
          ? "已跳过"
          : {
              waiting: "等待状态文件",
              pending: "待执行",
              running: "进行中",
              success: "已通过",
              failed: "需处理",
            }[gpu?.status] || "";
        return `<div class="${!enabled ? "live-small" : gpu?.status === "success" ? "good" : ""}">${gpu?.status === "success" ? "✓" : !enabled ? "—" : "○"} ${v}${label ? ` · ${label}` : ""}${enabled && gpu?.current_stage ? ` · ${esc(gpu.current_stage)}` : ""}</div>`;
      }
      const errors = acceptance?.check_errors?.[k] || [];
      const failed = errors.length > 0 || checks[k] === false;
      const label = checks[k]
        ? "已通过"
        : k === "services" && checks[k] === false && !errors.length
          ? "有环境服务告警"
          : failed
            ? "未通过"
            : k === "normal_reboot" &&
                (t.stage === "firstboot" || Object.keys(acceptance?.check_errors || {}).length)
              ? "等待基础检查通过"
              : t.status === "running" && t.stage === "firstboot" && !acceptance
                ? "检查中"
                : "";
      return `<div class="${checks[k] ? "good" : failed ? "live-error" : ""}">${checks[k] ? "✓" : failed ? "×" : "○"} ${v}${label ? ` · ${label}` : ""}${errors.length ? `<span class="live-small">：${errors.map(esc).join("；")}</span>` : ""}</div>`;
    })
    .join("")}</div></section>`;
  if (t.gpu_environment_check && t.gpu_check) {
    const gpu = t.gpu_check;
    body += `<section class="subsection"><h3>GPU 环境检查</h3>${gpu.detail ? `<p>${esc(gpu.detail)}</p>` : ""}<p class="live-small">${gpu.updated_at ? `部署更新 ${esc(gpu.updated_at)} · ` : ""}最近读取 ${when(gpu.observed_at)}</p>${
      (gpu.stages || []).length
        ? table(
            ["阶段", "状态", "退出码", "日志路径"],
            gpu.stages.map(
              (s) =>
                `<tr><td>${esc(s.name)}</td><td>${esc({ pending: "待执行", running: "进行中", success: "成功", failed: "失败" }[s.status] || s.status)}</td><td>${esc(s.rc ?? "—")}</td><td class="live-code">${esc(s.log || "—")}</td></tr>`,
            ),
          )
        : ""
    }</section>`;
  }
  if (after)
    body += `<section class="live-card">${defs([
      ["主机名", esc(after.hostname)],
      ["新 root UUID", esc(after.root_uuid)],
      ["ESP PARTUUID", esc(after.esp_partuuid)],
      [
        "SSH 指纹",
        `<span class="live-code">${esc(after.hostkey_fingerprint)}</span>`,
      ],
      ["普通重启 boot ID", esc(after.boot_id)],
      [
        "UI 安装来源",
        esc(after.task_receipt.source) +
          " / " +
          esc(after.task_receipt.task_id),
      ],
    ])}</section>`;
  modal(
    "物理机安装记录",
    t.id,
    body,
    `<div class="actions">${t.status === "needs_attention" ? button(t.automatic_recovery ? "查看自动修复" : t.recovery_observing ? "查看恢复进度" : "处理问题", "task-problem", true, `data-id="${esc(t.id)}"`) : ""}${t.receipt ? `<a class="button" href="/api/tasks/${esc(t.id)}/receipt" download>下载验收报告</a>` : ""}${button("关闭", "close")}</div>`,
  );
  state.detail = id;
  refreshLogs(id);
}
async function taskProblem(id) {
  const t = state.tasks.find((t) => t.id === id);
  if (!t || t.status !== "needs_attention") return;
  if (t.automatic_recovery) return automaticRecoveryDialog(t);
  if (t.resume_available) return resumeDialog(id);
  if (t.restart_available) return restartInstallDialog(id);
  if (t.retry_available) return retryInstallDialog(id);
  if (t.prepare_available) return prepareResumeDialog(id);
  if (t.recovery_observing) {
    state.detail = null;
    state.wizard = { resource: "task-problem", id };
    return modal(
      "等待安装结果",
      t.device,
      defs([
        ["当前阶段", esc(stages[t.stage] || t.stage)],
        [
          "当前状态",
          "安装程序已经启动，正在等待本轮安装退出和新系统可信身份。",
        ],
        ["自动观察截止", when(t.observation_deadline)],
      ]) +
        `<div class="live-note">系统每 10 秒只读检查一次。收到可信身份后会自动继续验收，不会重复写盘或再次发送 PXE。</div>`,
      problemFooter(t, { refresh: true }),
    );
  }
  state.detail = null;
  state.wizard = { resource: "task-problem", id };
  modal(
    "处理问题",
    t.device,
    defs([
      ["当前阶段", esc(stages[t.stage] || t.stage)],
      ["具体问题", esc(t.error || "执行结果需要核对")],
      ["下一步", "查看执行记录、串口日志和 BMC 控制台，确认实际状态。"],
    ]) +
      `<div class="live-note">请先确认故障原因和实际状态，再恢复任务。</div>`,
    problemFooter(t, { end: true }),
  );
}

function problemFooter(task, { refresh = false, end = false } = {}) {
  return (
    (refresh
      ? button(
          "刷新状态",
          "problem-refresh",
          false,
          `data-id="${esc(task.id)}"`,
        )
      : "") +
    (end
      ? button(
          "结束任务",
          "task-close-dialog",
          false,
          `data-id="${esc(task.id)}"`,
        )
      : "") +
    `<div class="actions">${button("开始验收", "resume", true, `data-resume-id="${esc(task.id)}"`)}${button("关闭", "close")}</div>`
  );
}

function closeTaskDialog(id) {
  const task = state.tasks.find((item) => item.id === id);
  if (!task || task.status !== "needs_attention") return;
  state.wizard = { resource: "close-task", id, serial: task.device };
  modal(
    "结束任务",
    task.device,
    `<p>结束后释放设备占用，任务历史和日志仍会保留。</p><div class="live-note">此操作不会停止物理机上可能仍在运行的安装程序，也不会修改 NICo Instance、Machine、BMC、启动顺序或磁盘。</div><label class="live-check"><input id="close-task-confirm" type="checkbox">确认现场已经停止处理，并结束此任务。</label><div id="resource-error" class="live-error"></div>`,
    button("取消", "close") + button("确认结束", "task-close-confirm", true),
  );
}

async function closeTask() {
  return busy(async () => {
    if (!$("#close-task-confirm").checked) throw Error("请确认结束任务。");
    const wizard = state.wizard;
    await api("/api/tasks/" + encodeURIComponent(wizard.id) + "/close", {
      confirm_serial: wizard.serial,
    });
    close();
    await load();
    toast("任务已结束，设备占用已释放。");
  });
}
function automaticRecoveryDialog(t) {
  const recovery = t.automatic_recovery;
  const labels = {
    diagnosing: "正在核对现场",
    config_requesting: "正在修复启动配置",
    config_verified: "启动配置已核对",
    reset_requesting: "正在请求重启",
    observing: "等待 NICo 恢复",
    waiting_reboot: "等待 NICo 网络重启",
    waiting_installation: "等待进入安装器",
    fallback_config_requesting: "正在恢复网络启动",
    fallback_reset_requesting: "正在执行受控重启",
    waiting_installation_retry: "等待安装器启动",
    standard_pxe_override_requesting: "正在设置单次 PXE",
    standard_pxe_reset_requesting: "正在执行单次 PXE 重启",
    waiting_standard_pxe_retry: "等待单次 PXE 进入安装器",
    completed: "自动修复完成",
    blocked: "自动修复已停止",
    unknown: "操作结果需要核对",
  };
  const done = recovery.steps.filter(
    (step) => step.status === "completed",
  ).length;
  const stepper = recovery.steps
    .map(
      (step) =>
        `<li class="incident-step ${esc(step.status)}"><span class="incident-step-dot" aria-hidden="true"></span><strong>${esc(step.label)}</strong><span>${esc(step.detail || (step.status === "pending" ? "等待前序步骤" : step.status === "running" ? "正在执行" : step.status === "completed" ? "已完成" : "需要核对"))}</span></li>`,
    )
    .join("");
  const change = recovery.change || {};
  const impact = change.after
    ? `<section class="incident-change"><span>启动顺序</span><div><del>${esc((change.before || []).join(" → "))}</del><strong>${esc(change.after.join(" → "))}</strong></div></section>`
    : "";
  const error = recovery.error
    ? `<div class="incident-alert"><strong>${recovery.state === "unknown" ? "请求结果未知，系统不会自动重放" : "自动修复已安全停止"}</strong><span>${esc(recovery.error)}</span></div>`
    : "";
  state.detail = null;
  state.wizard = { resource: "task-problem", id: t.id };
  modal(
    "故障处理",
    t.device,
    `<section class="incident-overview"><div><span class="incident-eyebrow">${esc(recovery.source)} · ${esc(recovery.code)}</span><h3>${esc(recovery.title)}</h3><p>${esc(labels[recovery.state] || recovery.state)}</p></div><span class="incident-state ${["blocked", "unknown"].includes(recovery.state) ? "attention" : recovery.state === "completed" ? "complete" : "running"}" aria-hidden="true"></span></section><progress class="incident-progress" value="${done}" max="${recovery.steps.length}" aria-label="自动修复进度"></progress><ol class="incident-stepper">${stepper}</ol>${impact}${error}<section class="incident-safety"><strong>本次恢复边界</strong><span>保留原 Machine、Instance、地址、系统盘和安装任务</span><span>不释放 Instance，不清理磁盘，不重发 custom PXE</span></section>`,
    problemFooter(t, {
      refresh: true,
      end: ["blocked", "unknown"].includes(recovery.state),
    }),
  );
}
function resumeDialog(id) {
  const t = state.tasks.find((t) => t.id === id);
  if (!t || t.status !== "needs_attention") return;
  state.detail = null;
  state.wizard = { resume_id: id };
  modal(
    "开始本轮安装验收",
    id,
    `<div class="live-note">检查本轮安装的系统身份、磁盘和网络配置，并执行启动及重启验收。不会重装系统；检查失败会显示具体原因。</div><form class="live-form"><label for="resume-serial">输入设备 SN<input class="input" id="resume-serial" placeholder="${esc(t.device)}"></label><label class="live-check"><input type="checkbox" id="resume-reboot">允许继续启动及重启验证。</label></form>`,
    button("取消", "close") + button("开始验收", "resume-confirm", true),
  );
}
async function resumeAcceptance() {
  const id = state.wizard.resume_id;
  const task = await api("/api/tasks/" + id + "/resume", {
    confirm_serial: $("#resume-serial").value,
    confirm_reboot: $("#resume-reboot").checked,
  });
  state.wizard = null;
  await refreshTasks();
  detail(task.id);
}

async function refreshTasks() {
  state.tasks = (await api("/api/tasks")).tasks;
  render();
}
registerActions(
  "live.js",
  [
    "site-edit",
    "site-save",
    "site-network",
    "problem-record",
    "problem-refresh",
    "task-problem",
    "task-close-dialog",
    "task-close-confirm",
    "batch-new",
    "batch-next",
    "batch-back",
    "batch-check",
    "batch-submit",
    "batch-detail",
    "discovery",
    "admission-new",
    "admission-preview",
    "admission-submit",
    "discovery-refresh",
    "import",
    "import-preview",
    "import-apply",
    "device-new",
    "device-edit",
    "device-save",
    "nic-add",
    "network-new",
    "network-edit",
    "network-save",
    "network-save-apply",
    "network-apply",
    "network-delete",
    "network-delete-confirm",
    "new",
    "close",
    "refresh",
    "next",
    "back",
    "check",
    "submit",
    "retry-install-dialog",
    "retry-install-confirm",
    "restart-install-confirm",
    "prepare-resume",
    "prepare-continue",
    "resume",
    "resume-confirm",
  ],
  async (e) => {
    const el = e.target.closest("[data-live]");
    if (!el || el.disabled) return;
    try {
      switch (el.dataset.live) {
        case "site-edit":
          return editSite();
        case "site-save":
          return await saveSite();
        case "site-network":
          return await navigate("network");
        case "problem-record":
          return detail(el.dataset.id);
        case "task-problem":
          return await taskProblem(el.dataset.id);
        case "task-close-dialog":
          return closeTaskDialog(el.dataset.id);
        case "task-close-confirm":
          return await closeTask();
        case "problem-refresh":
          await refreshTasks();
          return await taskProblem(el.dataset.id);
        case "batch-new":
          return batchStart(el.dataset.device);
        case "batch-next":
          return batchNext();
        case "batch-back":
          return batchBack();
        case "batch-check":
          return await batchCheck();
        case "batch-submit":
          return await batchSubmit();
        case "batch-detail":
          return await batchDetail(el.dataset.id);
        case "discovery":
          return await discoveryDialog(el.dataset.serial);
        case "admission-new":
          return admissionStart(el.dataset.serial);
        case "admission-preview":
          return await admissionPreview();
        case "admission-submit":
          return await admissionSubmit();
        case "discovery-refresh":
          return await discoveryDialog(state.wizard.serial);
        case "import":
          return importDialog();
        case "import-preview":
          return await previewCsv();
        case "import-apply":
          return await applyCsv();
        case "device-new":
          return deviceDialog();
        case "device-edit":
          return deviceDialog(el.dataset.id);
        case "device-save":
          return await saveDevice();
        case "nic-add":
          return addNic();
        case "network-new":
          return networkDialog();
        case "network-edit":
          return networkDialog(el.dataset.id);
        case "network-save":
          return await saveNetwork(false);
        case "network-save-apply":
          return await saveNetwork(true);
        case "network-apply":
          return await applyNetwork(el.dataset.id);
        case "network-delete":
          return deleteNetworkDialog(el.dataset.id);
        case "network-delete-confirm":
          return await deleteNetwork();
        case "new":
          return start(el.dataset.device);
        case "close":
          return close();
        case "refresh":
          await refreshPage();
          return;
        case "next":
          state.wizard.device = $("input[name=device]:checked").value;
          state.wizard.step++;
          return wizard();
        case "back":
          state.wizard.step--;
          state.wizard.check = null;
          return wizard();
        case "check":
          return await check();
        case "submit":
          return await submit();
        case "retry-install-dialog":
          return await retryInstallDialog(el.dataset.id);
        case "retry-install-confirm":
          return await retryInstall();
        case "restart-install-confirm":
          return await restartPreinstall();
        case "prepare-resume":
          return await prepareResumeDialog(el.dataset.id);
        case "prepare-continue":
          return await continuePreparation();
        case "resume":
          return resumeDialog(el.dataset.resumeId);
        case "resume-confirm":
          el.disabled = true;
          try {
            return await resumeAcceptance();
          } catch (e) {
            el.disabled = false;
            throw e;
          }
      }
    } catch (e) {
      toast(e.message);
    }
  },
);
observeUI("input", "live.js", updateSubmit, false);
observeUI(
  "change",
  "live.js",
  (e) => {
    updateSubmit();
    if (e.target.id === "log-follow") state.logFollow = e.target.checked;
  },
  false,
);
observeUI(
  "scroll",
  "live.js",
  (e) => {
    if (e.target.id === "sol-output" && !state.logFollow)
      state.logScroll = e.target.scrollTop;
  },
  true,
);
observeUI(
  "keydown",
  "live.js",
  (e) => {
    if (e.key === "Escape" && state.modal) close();
    if (e.key === "Tab" && state.modal) {
      const els = [
        ...document.querySelectorAll(
          ".modal button:not([disabled]),.modal input,.modal select,.modal textarea,.modal a",
        ),
      ];
      const first = els[0],
        last = els.at(-1);
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last?.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first?.focus();
      }
    }
  },
  false,
);
let taskPolling = false;
registerPoller(
  "live.js",
  ["tasks", "instances", "network"],
  async () => {
    if (!state.csrf || state.wizard || taskPolling) return;
    if (state.page === "instances") {
      if (instanceOperationPending()) {
        taskPolling = true;
        try {
          await readSection("instances", sectionReads.instances);
        } finally {
          taskPolling = false;
        }
      }
      return;
    }
    if (state.page === "network") {
      if (networkOperationPending())
        await readSection("network", sectionReads.network);
      return;
    }
    if (state.page !== "tasks") return;
    taskPolling = true;
    try {
      await Promise.allSettled(
        ["tasks", "batches"].map((key) => readSection(key, sectionReads[key])),
      );
      if (state.detail) {
        const scroll = $(".modal-body")?.scrollTop;
        detail(state.detail);
        if ($(".modal-body")) $(".modal-body").scrollTop = scroll || 0;
      }
    } finally {
      taskPolling = false;
    }
  },
  5000,
);
async function startApplication() {
  state.page = labels[location.hash.slice(1)]
    ? location.hash.slice(1)
    : "topology";
  syncPollers(state.page);
  try {
    const s = await api("/api/session");
    state.csrf = s.csrf;
    await load();
  } catch (e) {
    login();
  }
}

const inputField = (key, label, value = "", extra = "") =>
  `<label>${esc(label)}<input class="input" id="${key}" value="${esc(value)}" ${extra}></label>`;
const selectField = (key, label, options, value) =>
  `<label>${esc(label)}<select class="input" id="${key}">${options.map(([v, n]) => `<option value="${esc(v)}" ${String(value) === String(v) ? "selected" : ""}>${esc(n)}</option>`).join("")}</select></label>`;
async function busy(action) {
  const buttons = [...document.querySelectorAll(".modal-footer button")];
  buttons.forEach((b) => (b.disabled = true));
  try {
    return await action();
  } catch (e) {
    const target = $("#resource-error");
    if (target) target.textContent = e.message;
    else toast(e.message);
  } finally {
    buttons.forEach((b) => (b.disabled = false));
  }
}
function importDialog() {
  return equipmentPlanningImport();
}
async function previewCsv() {
  return busy(async () => {
    const file = $("#csv-file").files[0];
    if (!file) throw Error("请选择 Excel 或 CSV 文件。");
    if (file.size > 1024 * 1024) throw Error("文件最大 1 MiB。");
    let payload;
    if (/\.xlsx$/i.test(file.name)) {
      const bytes = new Uint8Array(await file.arrayBuffer());
      let binary = "";
      for (let i = 0; i < bytes.length; i += 8192)
        binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
      payload = { xlsx: btoa(binary) };
    } else if (/\.csv$/i.test(file.name)) {
      payload = { csv: await file.text() };
    } else throw Error("仅支持 .xlsx 或 .csv 文件。");
    const r = await api("/api/device-plans/preview", payload);
    state.wizard.preview_id = r.preview_id;
    $("#csv-file").disabled = true;
    $("#csv-preview").innerHTML =
      `<div class="live-note">新增 ${r.counts.create} 台 · 更新 ${r.counts.update} 台。新设备默认暂停接管和自动开机。</div>` +
      table(
        ["操作", "序列号", "BMC MAC", "网卡 / 地址"],
        r.rows.map(
          (x) =>
            `<tr><td>${x.operation === "create" ? "新增" : "更新"}</td><td>${esc(x.chassis_serial_number)}</td><td>${esc(x.bmc_mac_address)}</td><td>${(x.interfaces || []).map((n) => esc(n.mac_address || n.physical_ifname) + " / " + esc(n.fixed_ip || "动态")).join("<br>")}</td></tr>`,
        ),
      );
    $(".modal-footer").innerHTML =
      button("取消", "close") + button("保存导入规划", "import-apply", true);
    $("#resource-error").textContent = "";
  });
}
async function applyCsv() {
  return busy(async () => {
    const r = await api("/api/device-plans/import", {
      preview_id: state.wizard.preview_id,
    });
    await load();
    close();
    toast(`已保存 ${r.count} 台设备规划；执行时再同步 NICo。`);
  });
}
function renderNicFields(n = {}, i = 0) {
  return `<fieldset class="live-nic" data-nic="${i}"><legend>网卡 ${i + 1}</legend><div class="live-editor-grid">${inputField("nic-mac-" + i, "MAC 地址", n.mac_address)}${selectField(
    "nic-role-" + i,
    "接口角色",
    [
      ["host", "主机"],
      ["host_bmc", "主机 BMC"],
      ["dpu_os", "DPU OS"],
      ["dpu_bmc", "DPU BMC"],
    ],
    n.role || "host",
  )}${selectField(
    "nic-allocation-" + i,
    "地址分配",
    [
      ["", "沿用 / 自动推断"],
      ["fixed", "固定地址"],
      ["dynamic", "动态分配"],
      ["retained", "保留地址"],
    ],
    n.ip_allocation || "",
  )}${selectField(
    "nic-segment-" + i,
    "NICo 网络类型",
    [
      ["", "由 Relay 选择"],
      ["3", "HostInband"],
      ["1", "Admin"],
      ["2", "Underlay"],
      ["0", "Tenant"],
    ],
    n.network_segment_type ?? "",
  )}${inputField("nic-ip-" + i, "规划 IP", n.fixed_ip)}${inputField("nic-mask-" + i, "掩码", n.fixed_mask)}${inputField("nic-gateway-" + i, "网关", n.fixed_gateway)}${inputField("nic-physical-" + i, "物理接口名（可选）", n.physical_ifname)}${inputField("nic-logical-" + i, "逻辑接口名（可选）", n.logical_ifname)}<label class="live-check"><input id="nic-primary-${i}" type="checkbox" ${n.primary ? "checked" : ""}>主启动接口</label><label class="live-check"><input id="nic-remove-${i}" type="checkbox">删除此接口</label></div></fieldset>`;
}
function renderDevicePlanDialog(id) {
  const row = id ? state.resources.devices.find((x) => x.id === id) : null;
  if (id && !row) return;
  state.wizard = {
    resource: "device",
    row,
    nics: structuredClone(row?.interfaces || []),
  };
  const m = row || {};
  modal(
    row ? "编辑设备" : "新增设备",
    row?.serial || "管理员登记",
    `<div class="live-editor-grid">${inputField("dev-serial", "主机序列号", m.serial, "required " + (row ? "readonly" : ""))}${inputField("dev-mac", "BMC MAC", m.bmc_mac_address, "required " + (row ? "readonly" : ""))}${inputField("dev-user", "BMC 用户名", m.bmc_username, 'required maxlength="16"')}${inputField("dev-password", row ? "BMC 密码（留空保留）" : "BMC 密码", "", `type="password" autocomplete="new-password" maxlength="20" ${row ? "" : "required"}`)}${inputField("dev-bmc-ip", "BMC 规划 IP", m.bmc_ip_address || "")}${selectField(
      "dev-bmc-allocation",
      "BMC 地址策略",
      [
        ["Auto", "自动推断"],
        ["Fixed", "固定地址"],
        ["Retained", "保留地址"],
        ["Dynamic", "动态分配"],
      ],
      m.bmc_ip_allocation || "Auto",
    )}${inputField("dev-name", "设备名称", m.metadata?.name || "")}${inputField("dev-rack", "机柜 ID", m.rack_id || "")}</div><section class="subsection"><h3>网卡与规划地址</h3><div id="nic-list">${state.wizard.nics.map(nicRow).join("")}</div>${button("添加网卡", "nic-add")}</section><div id="resource-error" class="live-error" role="alert"></div>`,
    button("取消", "close") + button("保存规划", "device-save", true),
  );
}
function appendNic() {
  const w = state.wizard;
  const i = w.nics.length;
  w.nics.push({});
  $("#nic-list").insertAdjacentHTML("beforeend", nicRow({}, i));
}
function cellCsv(value) {
  if (value === null || value === undefined) return "";
  const text =
    typeof value === "object" || typeof value === "boolean"
      ? JSON.stringify(value)
      : String(value);
  return '"' + text.replaceAll('"', '""') + '"';
}
async function persistDevicePlan(afterClose) {
  return busy(async () => {
    const w = state.wizard,
      m = {};
    m.chassis_serial_number = $("#dev-serial").value.trim();
    m.bmc_mac_address = $("#dev-mac").value.trim();
    m.bmc_username = $("#dev-user").value;
    m.bmc_password = $("#dev-password").value;
    for (const [k, id] of [
      ["bmc_ip_address", "dev-bmc-ip"],
      ["rack_id", "dev-rack"],
    ]) {
      const v = $("#" + id).value.trim();
      if (v) m[k] = v;
      else if (w.row?.[k]) m[k] = "";
    }
    m.bmc_ip_allocation = $("#dev-bmc-allocation").value;
    for (const k of ["sku_id", "server_name"])
      if (w.row && Object.hasOwn(w.row, k)) m[k] = w.row[k];
    m.dpu_policy = w.row?.dpu_policy || "unspecified";
    m.dpf_enabled = w.row?.dpf_enabled !== false;
    m.bmc_retain_credentials = !!w.row?.bmc_retain_credentials;
    m.default_pause_ingestion_and_poweron =
      w.row?.default_pause_ingestion_and_poweron !== false;
    m.metadata = structuredClone(
      w.row?.metadata || { name: "", description: "", labels: [] },
    );
    m.metadata.name = $("#dev-name").value.trim();
    m.fallback_dpu_serial_numbers = structuredClone(
      w.row?.fallback_dpu_serial_numbers || [],
    );
    m.host_lifecycle_profile = structuredClone(
      w.row?.host_lifecycle_profile || {},
    );
    m.interfaces = w.nics.flatMap((old, i) => {
      if ($("#nic-remove-" + i).checked) return [];
      const n = {};
      for (const k of ["nic_type"]) if (old[k]) n[k] = old[k];
      for (const [k, id] of [
        ["mac_address", "mac"],
        ["fixed_ip", "ip"],
        ["fixed_mask", "mask"],
        ["fixed_gateway", "gateway"],
        ["physical_ifname", "physical"],
        ["logical_ifname", "logical"],
      ]) {
        const v = $("#nic-" + id + "-" + i).value.trim();
        if (v) n[k] = v;
      }
      n.role = $("#nic-role-" + i).value;
      const allocation = $("#nic-allocation-" + i).value;
      if (allocation) n.ip_allocation = allocation;
      const segment = $("#nic-segment-" + i).value;
      if (segment !== "") n.network_segment_type = Number(segment);
      n.primary = $("#nic-primary-" + i).checked;
      return [n];
    });
    const result = await api("/api/device-plans/save", {
      id: w.row?.id || null,
      revision: w.row?.plan_revision || "",
      machine: m,
      intent: intentRequest(w, m).intent,
    });
    close();
    if (afterClose) afterClose();
    toast(result.detail);
    try {
      await load();
    } catch (error) {
      toast("规划已保存；列表刷新失败，可稍后刷新。");
    }
  });
}
async function loadNetworks() {
  state.networks = await api("/api/networks");
}
const syncLabel = (s) =>
  ({
    saved: "已保存 · 待应用",
    applied: "已应用",
    migration_required: "已保存 · 待迁移",
    needs_attention: "需核对现场",
    applying: "应用中",
    waiting_deletion: "等待 NICo 回收旧子网 · 自动继续",
  })[s] || "NICo 当前配置";
const networkPolicy = (value) =>
  ({ DYNAMIC: "动态分配", RESERVED: "仅预留", UNKNOWN: "未提供" })[value] ||
  "待核对";
function networkPolicyDisplay(network) {
  if (network.name === "static-assignments")
    return { label: "—", note: "系统内部地址登记，不在此设置分配策略。" };
  if (["DYNAMIC", "RESERVED"].includes(network.observed_allocation_strategy))
    return {
      label: networkPolicy(network.observed_allocation_strategy),
      note: "NICo 当前生效策略。",
    };
  if (
    network.allocation_strategy_source === "site-config" &&
    ["DYNAMIC", "RESERVED"].includes(network.allocation_strategy)
  )
    return {
      label: networkPolicy(network.allocation_strategy) + "（站点配置）",
      note: "来自站点配置，尚未核实 NICo 当前是否采用此策略。",
    };
  if (network.allocation_strategy_source === "console-created")
    return {
      label: "动态分配（创建默认）",
      note: "创建时使用默认动态分配，尚未核实当前生效策略。",
    };
  return { label: "待确认", note: "当前无法确认此子网的地址分配策略。" };
}
const networkDeletionLabel = (value) =>
  ({
    deleting: "正在删除 · 等待 NICo 回收",
    delete_unknown: "删除结果待核对",
    deleted: "已删除",
  })[value] || value;
function networkOperationPending() {
  return Boolean(
    state.networks?.deletions?.some((n) => n.status === "deleting") ||
      state.networks?.drafts?.some((n) =>
        ["applying", "waiting_deletion"].includes(n.status),
      ) ||
      state.networks?.networks?.some((n) =>
        ["applying", "waiting_deletion"].includes(n.saved?.status),
      ),
  );
}
function networkPage() {
  const data = state.networks;
  let body = heading(
    "网络管理",
    "管理 NICo 子网。",
    button("刷新数据", "refresh") + button("新增子网", "network-new", true),
  );
  if (!data)
    return (
      body +
      '<div class="live-empty" data-network-view>正在读取 NICo 子网…</div>'
    );
  body +=
    "<div data-network-view>" +
    table(
      [
        "子网名称 / 类型",
        "前缀 / 网关",
        "地址策略",
        "MTU / 保留地址",
        "NICo 状态 / 配置同步",
        "操作",
      ],
      data.networks.map(
        (n) =>
          `<tr><td>${esc(n.name)}<span class="live-small">${esc(n.segment_type)} · ${n.interface_count} 个接口</span></td><td>${n.prefixes.map((p) => `${esc(p.prefix)}<span class="live-small">网关 ${esc(p.gateway || "—")}</span>`).join("")}<span class="live-small">OS DNS：${esc((n.services?.dns_servers || []).join(", ") || "待配置")} · ${esc(n.services?.source)}</span></td><td title="${esc(networkPolicyDisplay(n).note)}">${esc(networkPolicyDisplay(n).label)}</td><td>${esc(n.mtu)} / ${n.prefixes.map((p) => esc(p.reserveFirst ?? 0)).join(", ")}</td><td>${badge(n.state, n.state === "READY" ? "green" : "gray")}<span class="live-small">${n.deletion ? esc(networkDeletionLabel(n.deletion.status)) : "NICo 当前配置"}</span></td><td>${n.name === "static-assignments" ? "系统地址段" : button("查看", "network-edit", false, `data-id="${esc(n.id)}"`) + " " + button("删除", "network-delete", false, `data-id="${esc(n.id)}" ${n.delete_allowed ? "" : "disabled"} title="${esc(n.delete_reason || "删除前重新检查占用和设备规划")}"`) + (!n.delete_allowed ? `<span class="live-small">${esc(n.delete_reason)}</span>` : "")}</td></tr>`,
      ),
    );
  if (data.drafts.length)
    body += `<section class="subsection"><h3>子网草稿</h3>${table(
      ["名称", "前缀", "地址策略", "同步状态", "操作"],
      data.drafts.map(
        (n) =>
          `<tr><td>${esc(n.config.name)}</td><td>${esc(n.config.prefix)}</td><td>${esc(networkPolicy(n.config.allocation_strategy || "DYNAMIC"))}<span class="live-small">未应用</span></td><td>${syncLabel(n.status)}${n.error ? `<span class="live-small">${esc(n.error)}</span>` : ""}</td><td>${button("编辑", "network-edit", false, `data-id="${esc(n.id)}" ${["applying", "waiting_deletion"].includes(n.status) ? "disabled" : ""}`)} ${n.status === "saved" ? button("创建到 NICo", "network-apply", true, `data-id="${esc(n.id)}"`) : ""} ${button("删除草稿", "network-delete", false, `data-id="${esc(n.id)}" ${["saved", "migration_required"].includes(n.status) && !n.before && !n.replacement_id ? "" : "disabled"}`)}</td></tr>`,
      ),
    )}</section>`;
  if (data.deletions?.length)
    body += `<section class="subsection"><h3>子网删除进度</h3>${table(
      ["子网", "状态", "说明"],
      data.deletions.map(
        (n) =>
          `<tr><td>${esc(n.name)}</td><td>${esc(networkDeletionLabel(n.status))}</td><td>${esc(n.detail || "等待 NICo 完成回收。")}</td></tr>`,
      ),
    )}</section>`;
  return (
    body +
    `<div class="live-note">已有子网仅支持查看和删除；名称及网络配置暂不可修改。</div></div>`
  );
}
function deleteNetworkDialog(id) {
  const row = state.networks.networks.find((n) => n.id === id),
    draft = state.networks.drafts.find((n) => n.id === id);
  if (!row && !draft) throw Error("子网已变化，请刷新。");
  state.wizard = {
    resource: "network-delete",
    id,
    revision: row ? row.revision : null,
    draft,
  };
  modal(
    row ? "删除子网" : "删除子网草稿",
    row?.name || draft.config.name,
    `<div class="live-note">${row ? "将删除 NICo 子网；被接口或设备规划引用时不可删除。" : "仅删除草稿，NICo 子网不受影响。"}</div>${defs([["子网", esc(row ? row.prefixes.map((p) => p.prefix).join("、") : draft.config.prefix)]])}<label class="live-check"><input id="network-delete-confirm" type="checkbox">确认删除此子网${row ? "" : "草稿"}</label><div id="resource-error" class="live-error" role="alert"></div>`,
    button("取消", "close") +
      button("确认删除", "network-delete-confirm", true),
  );
}
async function deleteNetwork() {
  return busy(async () => {
    if (!$("#network-delete-confirm").checked) throw Error("请勾选确认删除。");
    const w = state.wizard;
    const revision = w.draft ? w.draft.delete_revision : w.revision;
    const result = await api("/api/networks/delete", {
      id: w.id,
      revision,
      confirm_delete: true,
    });
    close();
    await loadNetworks();
    render();
    toast(result.detail);
  });
}
function networkDialog(id) {
  const live = state.networks?.networks.find((x) => x.id === id);
  if (live) {
    const pending =
      live.saved &&
      ["saved", "migration_required", "needs_attention"].includes(
        live.saved.status,
      );
    return modal(
      "子网详情",
      live.name,
      defs([
        ["子网名称", esc(live.name)],
        ["子网 ID", esc(live.id)],
        ["类型", esc(live.segment_type)],
        ...live.prefixes.flatMap((p) => [
          ["前缀", esc(p.prefix)],
          ["网关", esc(p.gateway || "—")],
          ["起始保留地址数", esc(p.reserveFirst ?? 0)],
        ]),
        ["MTU", esc(live.mtu)],
        ["DNS 子域 UUID", esc(live.subdomain_id || "—")],
        ["地址策略", esc(networkPolicyDisplay(live).label)],
        ["策略说明", esc(networkPolicyDisplay(live).note)],
        ["关联接口数", esc(live.interface_count)],
      ]) +
        `<div class="live-note">当前子网不支持修改。</div>${pending ? '<div class="live-note">存在未应用的历史规划；本页显示 NICo 生效配置。</div>' : ""}`,
      button("关闭", "close"),
    );
  }
  const draft = state.networks?.drafts.find((x) => x.id === id);
  if (id && !draft) throw Error("子网已变化，请刷新。");
  const c = draft?.config || {
    name: "",
    segment_type: "HOST_INBAND",
    prefix: "",
    gateway: "",
    mtu: 1500,
    reserve_first: 0,
    allocation_strategy: "DYNAMIC",
    subdomain_id:
      state.networks?.networks.find((x) => x.subdomain_id)?.subdomain_id || "",
  };
  state.wizard = { resource: "network", id: id || null, revision: null };
  modal(
    id ? "编辑新子网草稿" : "新增子网",
    "尚未创建到 NICo",
    `<div class="live-editor-grid">${inputField("net-name", "子网名称", c.name)}${selectField(
      "net-type",
      "网络类型",
      [
        ["HOST_INBAND", "HostInband · 主机带内"],
        ["ADMIN", "Admin · 管理"],
        ["UNDERLAY", "Underlay"],
      ],
      c.segment_type,
    )}${inputField("net-prefix", "子网 CIDR", c.prefix, 'placeholder="192.0.2.0/24"')}${inputField("net-gateway", "网关", c.gateway)}${inputField("net-mtu", "MTU", c.mtu, 'type="number" min="576" max="9216"')}${inputField("net-reserve", "起始保留地址数", c.reserve_first, 'type="number" min="0"')}${inputField("net-domain", "DNS 子域 UUID", c.subdomain_id)}${selectField("net-strategy", "地址策略", [["DYNAMIC", "动态分配"]], "DYNAMIC")}</div><div class="live-note">保存草稿后可继续编辑；创建到 NICo 后生效。当前仅支持动态地址策略。</div><div id="resource-error" class="live-error" role="alert"></div>`,
    button("取消", "close") +
      button("保存草稿", "network-save") +
      button("创建到 NICo", "network-save-apply", true),
  );
  if (state.networks?.networks.some((n) => n.id === id))
    $(".modal-footer").insertAdjacentHTML(
      "afterbegin",
      button("查看地址分配", "eq-network-allocations", false, eqAttr(id)),
    );
}
async function saveNetwork(apply) {
  return busy(async () => {
    const w = state.wizard;
    const config = {
      name: $("#net-name").value.trim(),
      segment_type: $("#net-type").value,
      prefix: $("#net-prefix").value.trim(),
      gateway: $("#net-gateway").value.trim(),
      mtu: Number($("#net-mtu").value),
      reserve_first: Number($("#net-reserve").value),
      subdomain_id: $("#net-domain").value.trim(),
      allocation_strategy: $("#net-strategy").value,
    };
    const r = await api("/api/networks/save", {
      id: w.id,
      revision: w.revision,
      config,
    });
    let applied = null;
    if (apply) {
      try {
        applied = await api("/api/networks/apply", { id: r.id });
      } catch (e) {
        await loadNetworks();
        render();
        throw e;
      }
    }
    close();
    await loadNetworks();
    render();
    toast(
      applied?.status === "migration_required"
        ? "规划已保存；需要站点配置或网络迁移，当前 NICo 网络保留。"
        : applied?.status === "waiting_deletion"
          ? "正在等待 NICo 回收旧子网，完成后自动应用；可在列表查看状态。"
          : apply
            ? "子网已应用到 NICo，并完成读回。"
            : "子网配置文件已保存，等待应用。",
    );
  });
}
async function applyNetwork(id) {
  return busy(async () => {
    try {
      const r = await api("/api/networks/apply", { id });
      toast(
        r.status === "migration_required"
          ? "规划已保存；需要站点配置或网络迁移，当前 NICo 网络保留。"
          : r.status === "waiting_deletion"
            ? "等待 NICo 回收旧子网，完成后自动应用。"
            : "子网已应用到 NICo。",
      );
    } finally {
      await loadNetworks();
      render();
    }
  });
}
async function refreshLogs(id) {
  try {
    const log = await api("/api/tasks/" + id + "/logs");
    if (state.detail !== id || !$("#sol-output")) return;
    $("#sol-output").textContent = log.text || "本轮串口暂未输出日志。";
    $("#log-time").textContent =
      `采集 ${when(log.updated_at)} · ${log.bytes.toLocaleString()} 字节`;
    $("#sol-output").scrollTop = state.logFollow
      ? $("#sol-output").scrollHeight
      : state.logScroll;
  } catch (e) {
    if (state.detail === id && $("#log-time"))
      $("#log-time").textContent = "日志更新失败：" + e.message;
  }
}

async function prepareResumeDialog(id) {
  state.detail = null;
  const w = { resource: "prepare-resume", id };
  state.wizard = w;
  modal(
    "处理问题",
    "核对当前规划与准备条件",
    '<div class="live-empty">正在读取原任务、已保存规划和接入范围…</div>',
    button("关闭", "close"),
  );
  let check;
  try {
    check = await api(
      "/api/tasks/" + encodeURIComponent(id) + "/prepare-preflight",
      {},
    );
  } catch (error) {
    if (state.wizard === w) {
      modal(
        "处理问题",
        id,
        `<div class="live-error">${esc(error.message)}</div>`,
        button(
          "查看原任务与日志",
          "problem-record",
          false,
          `data-id="${esc(id)}"`,
        ) + button("关闭", "close"),
      );
    }
    return;
  }
  if (state.wizard !== w) return;
  w.check = check;
  const d = state.resources.devices.find((d) => d.serial === check.device);
  modal(
    "继续准备设备",
    check.device,
    defs([
      ["主机名", esc(check.hostname)],
      ["管理地址", esc(check.scope.management_ip)],
      ["系统盘", esc(check.disk_serial || "硬件回报后唯一匹配；多盘需选择")],
    ]) +
      `<p>使用当前规划继续准备并安装；接入时可能执行站点磁盘清理、凭据和固件配置。</p>${defs(
        [
          [
            "原规划 → 当前规划",
            esc(check.previous_plan?.management_ip || "—") +
              " → " +
              esc(check.scope.management_ip) +
              "；系统盘 " +
              esc(check.previous_plan?.disk_serial || "未指定") +
              " → " +
              esc(check.disk_serial || "待唯一匹配"),
          ],
          ["接入清理范围", esc(check.impact?.cleanup_detail)],
        ],
      )}${check.impact?.cleanup_scope === "all_disks" ? '<label class="live-check live-warning"><input id="prepare-cleanup" type="checkbox">确认本设备全部磁盘的接入清理及站点凭据、固件策略。</label>' : ""}${button("编辑设备规划", "device-detail-plan", false, `data-id="${esc(d.id)}"`)}<label class="live-check"><input id="prepare-confirm" type="checkbox">确认使用上列规划继续设备准备及安装。</label><div id="resource-error" class="live-error"></div>`,
    button("取消", "close") + button("继续原任务", "prepare-continue", true),
  );
}
async function continuePreparation() {
  return busy(async () => {
    const w = state.wizard;
    if (!$("#prepare-confirm").checked) throw Error("请核对规划及执行范围。");
    const task = await api(
      "/api/tasks/" + encodeURIComponent(w.id) + "/continue-prepare",
      {
        preflight_id: w.check.id,
        confirm_serial: w.check.device,
        confirm_reboot: true,
        cleanup_scope: $("#prepare-cleanup")?.checked ? "all_disks" : "none",
      },
    );
    close();
    await load();
    detail(task.id);
  });
}

async function retryInstallDialog(id) {
  state.detail = null;
  const w = { resource: "retry-install", id };
  state.wizard = w;
  modal(
    "处理问题",
    "核对安装失败与恢复范围",
    '<div class="live-empty">正在核对原 Instance、安装失败证据和系统盘范围…</div>',
    button("关闭", "close"),
  );
  let check;
  try {
    check = await api(
      "/api/tasks/" + encodeURIComponent(id) + "/retry-preflight",
      {},
    );
  } catch (error) {
    if (state.wizard === w) {
      modal(
        "处理问题",
        id,
        `<div class="live-error">${esc(error.message)}</div>`,
        button(
          "查看原任务与日志",
          "problem-record",
          false,
          `data-id="${esc(id)}"`,
        ) + button("关闭", "close"),
      );
    }
    return;
  }
  if (state.wizard !== w) return;
  w.check = check;
  modal(
    "重试安装",
    check.device,
    defs([
      ["主机名", esc(check.hostname)],
      ["管理地址", esc(check.management_ip)],
      ["系统盘", esc(check.disk_serial)],
      ["复用 Instance", esc(check.instance_id)],
      ["暂停原因", esc(check.failure_detail)],
    ]) +
      `${check.requires_disk_confirmation ? `<p>系统盘可能已被改写。请先处理故障；重试将再次覆盖上列系统盘。</p><div class="live-form"><label>输入系统盘序列号确认覆盖<input id="retry-disk-serial" autocomplete="off"></label></div>` : "<p>尚未开始写盘；重试将按原规划安装。</p>"}<p>复用原 Instance，不重新接入清理或分配地址。</p><label class="live-check"><input id="retry-install-confirm" type="checkbox">确认按原任务规划重试安装及重启验收。</label><div id="resource-error" class="live-error"></div>`,
    button("取消", "close") + button("重试安装", "retry-install-confirm", true),
  );
}
async function retryInstall() {
  return busy(async () => {
    const w = state.wizard;
    if (!$("#retry-install-confirm").checked)
      throw Error("请核对系统盘及重试范围。");
    const t = await api(
      "/api/tasks/" + encodeURIComponent(w.id) + "/retry-install",
      {
        preflight_id: w.check.id,
        confirm_serial: w.check.device,
        confirm_reboot: true,
        ...(w.check.requires_disk_confirmation
          ? { confirm_disk_serial: $("#retry-disk-serial").value.trim() }
          : {}),
      },
    );
    close();
    await load();
    detail(t.id);
  });
}

async function restartInstallDialog(id) {
  state.detail = null;
  const w = { resource: "restart-preinstall", id };
  state.wizard = w;
  modal(
    "重新检查并继续",
    "安装配置更新前暂停",
    '<div class="live-empty">正在核对原任务、当前系统身份及规划同步结果…</div>',
    button("关闭", "close"),
  );
  let check;
  try {
    check = await api(
      "/api/tasks/" + encodeURIComponent(id) + "/restart-preflight",
      {},
    );
  } catch (error) {
    if (state.wizard === w)
      modal(
        "重新检查并继续",
        id,
        `<div class="live-error">${esc(error.message)}</div>`,
        button(
          "查看原任务与日志",
          "problem-record",
          false,
          `data-id="${esc(id)}"`,
        ) + button("关闭", "close"),
      );
    return;
  }
  if (state.wizard !== w) return;
  w.check = check;
  const checks = `<div class="live-checks">${check.checks.map((c) => `<div class="${c.passed ? "good" : "live-error"}">${c.passed ? "✓" : "×"} ${esc(c.name)}${c.passed ? "" : "：" + esc(c.detail)}</div>`).join("")}</div>`;
  modal(
    "重新检查并继续",
    check.device,
    defs([
      ["主机名", esc(check.hostname)],
      [
        "当前管理地址 → 安装目标地址",
        esc(check.current_management_ip) + " → " + esc(check.management_ip),
      ],
      ["系统盘", esc(check.disk_serial || check.disk_wwn)],
      ["复用 Instance", esc(check.instance_id)],
    ]) +
      checks +
      (check.passed
        ? `<p>继续后将应用原任务规划、覆盖上列系统盘，并重启验证。</p><label class="live-check"><input id="restart-install-confirm" type="checkbox">确认按原任务规划继续安装及重启验收。</label>`
        : "<p>请先处理未通过的检查，再重新打开此入口。</p>") +
      '<div id="resource-error" class="live-error"></div>',
    button("取消", "close") +
      (check.passed
        ? button(
            "继续原任务安装",
            "restart-install-confirm",
            true,
            'id="restart-install-submit" disabled',
          )
        : ""),
  );
}
async function restartPreinstall() {
  return busy(async () => {
    const w = state.wizard;
    if (!w?.check?.passed || !$("#restart-install-confirm")?.checked)
      throw Error("请核对系统盘、地址及重装范围。");
    const task = await api(
      "/api/tasks/" + encodeURIComponent(w.id) + "/restart-install",
      {
        preflight_id: w.check.id,
        confirm_serial: w.check.device,
        confirm_reboot: true,
        ...(w.check.requires_disk_confirmation
          ? { confirm_disk_serial: $("#retry-disk-serial").value.trim() }
          : {}),
      },
    );
    close();
    await load();
    detail(task.id);
  });
}
observeUI(
  "change",
  "live.js",
  (e) => {
    if (e.target.id === "restart-install-confirm")
      $("#restart-install-submit").disabled = !e.target.checked;
  },
  false,
);
