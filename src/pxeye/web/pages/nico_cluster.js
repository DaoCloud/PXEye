"use strict";

const nicoStates = {
  missing: ["未部署", "gray"],
  pending: ["待执行", "gray"],
  starting: ["启动中", "blue"],
  running: ["执行中", "blue"],
  checking: ["检查中", "blue"],
  deploying: ["部署中", "blue"],
  connecting: ["连接中", "blue"],
  prepared: ["可以部署", "blue"],
  ready: ["已就绪", "green"],
  connected: ["已连接站点", "green"],
  failed: ["需处理", "red"],
  needs_attention: ["需处理", "red"],
  unknown: ["待核对", "amber"],
};
const nicoBadge = (status) =>
  badge(...(nicoStates[status] || ["未知", "gray"]));
state.nicoTab = "";
state.nicoGroup = "全部服务";
state.nicoForm = null;

sectionReads.nico = async (refresh = false) => {
  state.nico = await api(
    "/api/nico-deployment" + (refresh ? "?refresh=1" : ""),
  );
  if (!state.nicoForm) {
    const p = state.nico.packages.find((x) => x.valid);
    state.nicoForm = {
      package_id: p?.id || "",
      site_name: state.readiness?.site_name || "PXEye",
      release_prefix: "mmzhou",
      core_url: "",
      pxe_url: "",
      ...(p?.defaults || {}),
      ...(state.nico.operation?.configuration || {}),
    };
  }
  if (!state.nicoTab)
    state.nicoTab =
      state.nico.operation || state.nico.site_connected ? "services" : "config";
};

function nicoClusterPage() {
  const data = state.nico;
  if (!data)
    return (
      heading(
        "NICo 集群",
        "在当前 Kubernetes 集群部署 NICo，查看服务运行状态。",
      ) + '<div class="live-empty">正在读取集群信息…</div>'
    );
  const op = data.operation,
    readyCount = data.components.filter(
      (c) => c.required && c.state === "ready",
    ).length,
    requiredCount = data.components.filter((c) => c.required).length,
    existing = !op && data.components.some((c) => c.workloads.length),
    status =
      op?.status ||
      (existing
        ? data.error
          ? "unknown"
          : readyCount === requiredCount
            ? "ready"
            : "starting"
        : "missing"),
    title =
      {
        missing: "准备部署 NICo",
        prepared: "部署配置已检查",
        checking: "正在检查部署环境",
        deploying: "正在部署 NICo",
        connecting: "正在连接站点",
        ready: "NICo 服务已就绪",
        starting: "NICo 服务运行情况",
        unknown: "NICo 服务状态待核对",
        connected: "NICo 已连接站点",
        needs_attention: "部署需要处理",
      }[status] || "NICo 集群",
    subtitle = op?.configuration
      ? `${op.configuration.site_name} · ${op.configuration.release_prefix}`
      : existing
        ? `${state.readiness?.site_name || "NICo"} · 服务运行状态`
        : "先检查部署材料，再按依赖顺序启动服务。";
  let action = "";
  if (status === "prepared")
    action = button(
      "开始部署",
      "nico-start",
      true,
      data.busy ? "disabled" : "",
    );
  else if (data.ready && op && status !== "connected")
    action = button(
      "应用到站点",
      "nico-connect",
      true,
      data.busy ? "disabled" : "",
    );
  else if (status === "needs_attention" && op?.revision)
    action = button(
      "核对并继续",
      "nico-start",
      true,
      data.busy ? "disabled" : "",
    );
  else if (status === "connected")
    action = button("站点设置", "nico-site", true);
  const tabs = [
    ["services", "服务总览"],
    ["progress", "部署流程"],
    ["config", "部署配置"],
  ];
  const completed = op?.phases.filter((p) => p.state === "ready").length || 0;
  const body =
    state.nicoTab === "config"
      ? nicoConfigPanel(data)
      : state.nicoTab === "progress"
        ? nicoProgressPanel(data)
        : nicoServicesPanel(data);
  return (
    heading(
      "NICo 集群",
      "在当前 Kubernetes 集群部署 NICo，查看服务运行状态。",
      button(
        "刷新状态",
        "nico-refresh",
        false,
        data.observing ? "disabled" : "",
      ) + action,
    ) +
    `<section class="nico-overview"><div class="nico-overview-copy"><span class="site-eyebrow">KUBERNETES · ${esc(data.namespace)}</span><div class="nico-overview-title"><span class="nico-cluster-mark" aria-hidden="true"><svg viewBox="0 0 32 32" width="30" height="30" fill="none"><path d="m16 3 11 6.5v13L16 29 5 22.5v-13L16 3Z" stroke="currentColor" stroke-width="1.6"/><path d="m5 9.5 11 6.5 11-6.5M16 16v13M16 3v7" stroke="currentColor" stroke-width="1.6"/><circle cx="16" cy="16" r="3" fill="currentColor"/></svg></span><div><h2>${title}</h2><p>${esc(subtitle)}</p></div></div></div><div class="nico-overview-state">${nicoBadge(status)}<span>${data.checked_at ? "更新于 " + when(data.checked_at) : data.cluster_available ? "正在读取服务状态" : "未取得集群身份"}</span></div></section>` +
    (data.error
      ? `<div class="nico-notice" role="alert"><strong>当前状态读取失败</strong><span>${esc(data.error)} 上次状态仅供参考。</span></div>`
      : "") +
    (op?.error
      ? `<div class="nico-notice" role="alert"><strong>需要处理</strong><span>${esc(op.error)}</span></div>`
      : "") +
    `<div class="nico-metrics"><div><span>必需服务</span><strong>${readyCount}<small> / ${requiredCount}</small></strong><p>已就绪</p></div><div><span>部署阶段</span><strong>${completed}<small> / ${op?.phases.length || "—"}</small></strong><p>已完成</p></div><div><span>初始化与存储</span><strong>${(data.jobs || []).filter((j) => j.state === "ready").length}<small> 项作业完成</small></strong><p>${data.initialization_ready ? "证书与存储已就绪" : "等待初始化完成"}</p></div><div><span>引导材料</span><strong class="nico-metric-text">${data.boot_ready ? "可读取" : "待检查"}</strong><p>由 PXE / HTTP 提供</p></div></div>` +
    `<div class="nico-tabs" role="tablist" aria-label="集群视图">${tabs.map(([id, label]) => `<button role="tab" aria-selected="${state.nicoTab === id}" class="${state.nicoTab === id ? "active" : ""}" data-live="nico-tab" data-tab="${id}">${label}</button>`).join("")}</div><div role="tabpanel">${body}</div>`
  );
}

function nicoConfigPanel(data) {
  const values = state.nicoForm || {},
    packages = data.packages,
    active = data.busy || !!data.operation?.started_at;
  return `<div class="nico-config-layout"><section class="site-panel"><header class="site-panel-header"><div><span class="site-eyebrow">部署目标</span><h2>当前集群配置</h2></div>${badge("Helm 3", "gray")}</header><div class="nico-form live-form"><div class="nico-field-grid">${selectField("nico-package", "部署包", [["", packages.length ? "请选择部署包" : "未找到部署包"], ...packages.filter((p) => p.valid).map((p) => [p.id, `${p.name} · ${p.version}`])], values.package_id)}${inputField("nico-site-name", "站点名称", values.site_name, 'maxlength="100"')}${inputField("nico-prefix", "发布名前缀", values.release_prefix, 'maxlength="32"')}${inputField("nico-namespace", "命名空间", data.namespace, "readonly")}${inputField("nico-core-url", "Core HTTPS 地址", values.core_url, 'type="url" placeholder="https://mmzhou-nico-api.mmzhou.svc:1079"')}${inputField("nico-pxe-url", "PXE / HTTP 对外地址", values.pxe_url, 'type="url" placeholder="http://192.0.2.50:8080"')}</div><p class="live-small">PXE 地址必须能被被安装主机访问。数据库、服务暴露和存储配置使用部署包内的 values。</p>${!data.enabled || !data.cluster_available ? '<div class="nico-notice"><span>需要启用集群部署，并给 PXEye 配置当前集群的 ServiceAccount。</span></div>' : ""}${!packages.length ? '<div class="nico-notice"><span>将已准备的 Helm 部署包只读挂载到 /nico-packages。每个包包含 deployment.json、Chart、values 和初始化作业。</span></div>' : ""}<div class="nico-form-actions">${button("检查部署配置", "nico-preflight", true, active || !data.enabled || !data.cluster_available || !values.package_id ? "disabled" : "")}</div></div></section><aside class="site-panel nico-deployment-notes"><header class="site-panel-header"><div><span class="site-eyebrow">部署顺序</span><h2>从环境到站点</h2></div></header><ol><li><span>01</span><div><strong>检查集群和材料</strong><p>核对权限、文件、Chart 与服务映射。</p></div></li><li><span>02</span><div><strong>启动基础服务</strong><p>证书、数据库、Vault 与初始化作业。</p></div></li><li><span>03</span><div><strong>部署 NICo 服务</strong><p>Core、网络引导、REST 与工作流。</p></div></li><li><span>04</span><div><strong>应用到站点</strong><p>验证 Core 身份，启用业务页面。</p></div></li></ol><p class="site-panel-note">部署不会自动登记设备或执行装机。已有服务保留数据，异常阶段需要核对后继续。</p></aside></div>`;
}

function nicoServicesPanel(data) {
  const groups = [
    "全部服务",
    "控制面",
    "网络与引导",
    "基础服务",
    "REST 与工作流",
    "可选组件",
  ];
  const selected = data.components.filter(
    (c) => state.nicoGroup === "全部服务" || c.group === state.nicoGroup,
  );
  const rows = selected.map((c) => {
    const place = c.workloads
      .map((w) => `${esc(w.namespace)} / ${esc(w.name)}`)
      .join("<br>");
    const ports = c.endpoints
      .flatMap((e) => e.ports)
      .filter((v, i, a) => a.indexOf(v) === i)
      .join(" · ");
    const reason = c.workloads
      .filter((w) => w.state !== "ready")
      .map((w) => w.detail)
      .filter((v, i, a) => a.indexOf(v) === i)
      .join("；");
    return `<tr><td><div class="nico-service-title"><i class="nico-dot ${esc(data.error ? "unknown" : c.state)}" aria-hidden="true"></i><button class="nico-service-link" data-live="nico-service" data-id="${esc(c.id)}">${esc(c.name)}</button>${!c.required ? '<span class="nico-optional">可选</span>' : ""}</div><div class="nico-service-role">${esc(c.role)}</div></td><td><span class="live-code nico-workload">${place || "—"}</span></td><td>${c.desired ? `${c.ready} / ${c.desired}` : "—"}</td><td><span class="live-code">${esc(ports || "—")}</span></td><td>${nicoBadge(data.error ? "unknown" : c.state)}${reason ? `<div class="nico-service-reason">${esc(reason)}</div>` : ""}</td></tr>`;
  });
  return `<section class="site-panel nico-services"><header class="site-panel-header"><div><span class="site-eyebrow">服务运行状态</span><h2>NICo 组件</h2></div><div class="nico-filter">${groups.map((group) => `<button data-live="nico-group" data-group="${esc(group)}" class="${state.nicoGroup === group ? "active" : ""}">${esc(group)}</button>`).join("")}</div></header>${table(["服务 / 作用", "工作负载", "就绪副本", "服务端口", "状态"], rows)}<p class="site-panel-note">点击服务查看镜像与端点。Boot 材料由 Core / PXE 容器提供；服务就绪后仍需验证实际 DHCP 和主机引导路径。</p></section>`;
}

function nicoProgressPanel(data) {
  const op = data.operation;
  if (!op)
    return '<section class="site-panel"><div class="live-empty">尚未开始部署。先在部署配置中检查材料。</div></section>';
  return (
    `<div class="nico-progress-layout"><section class="site-panel"><header class="site-panel-header"><div><span class="site-eyebrow">按依赖顺序执行</span><h2>部署进度</h2></div>${nicoBadge(op.status)}</header><ol class="nico-timeline">${op.phases.map((p, i) => `<li class="${esc(p.state)}"><span class="nico-step-marker">${p.state === "ready" ? "✓" : i + 1}</span><div class="nico-step-content"><div><strong>${esc(p.name)}</strong>${nicoBadge(p.state)}</div><p>${esc(p.detail || (p.state === "running" ? "正在执行" : "等待前序阶段完成"))}</p>${p.release ? `<span class="live-code">${esc(p.release)}</span>` : ""}${p.finished_at ? `<small>完成于 ${when(p.finished_at)}</small>` : ""}</div></li>`).join("")}</ol></section><section class="site-panel"><header class="site-panel-header"><div><span class="site-eyebrow">执行记录</span><h2>操作与命令</h2></div><span class="live-small">${op.events.length} 条</span></header><div class="nico-events">${op.events.map((event) => `<div class="nico-event"><time>${when(event.at)}</time><p>${esc(event.message)}${event.exit_code != null ? ` · 退出码 ${esc(event.exit_code)}` : ""}</p>${event.command ? `<code>${esc(event.command)}</code>` : ""}</div>`).join("") || '<div class="live-empty">等待执行记录</div>'}</div></section></div>` +
    ((data.jobs || []).length
      ? `<section class="site-panel nico-initialization"><header class="site-panel-header"><div><span class="site-eyebrow">初始化</span><h2>作业与依赖</h2></div></header>${table(
          ["类型", "资源", "状态", "说明"],
          [...data.jobs, ...(data.dependencies || [])].map(
            (j) =>
              `<tr><td>${esc(j.kind)}</td><td class="live-code">${esc(j.name)}</td><td>${nicoBadge(j.state)}</td><td>${esc(j.detail)}</td></tr>`,
          ),
        )}</section>`
      : "")
  );
}

function nicoServiceDialog(id) {
  const c = state.nico.components.find((x) => x.id === id);
  if (!c) return;
  modal(
    c.name,
    c.role,
    `<div class="nico-service-detail">${defs([
      ["状态", nicoBadge(c.state)],
      [
        "工作负载",
        c.workloads
          .map((w) => `${esc(w.kind)} · ${esc(w.namespace)} / ${esc(w.name)}`)
          .join("<br>") || "未部署",
      ],
      [
        "运行镜像",
        c.images
          .map((image) => `<span class="live-code">${esc(image)}</span>`)
          .join("<br>") || "—",
      ],
      [
        "初始化镜像",
        (c.init_images || [])
          .map((image) => `<span class="live-code">${esc(image)}</span>`)
          .join("<br>") || "—",
      ],
      [
        "服务端点",
        c.endpoints
          .map(
            (e) =>
              `${esc(e.name)} · ${esc(e.address)}<br>${esc(e.ports.join(" · "))}`,
          )
          .join("<br>") || "—",
      ],
    ])}</div>`,
    button("关闭", "close"),
  );
}

async function nicoPreflight() {
  const v = state.nicoForm;
  if (!v.package_id || !v.core_url || !v.pxe_url) {
    toast("请选择部署包，并填写 Core 与 PXE 地址。");
    return;
  }
  await api("/api/nico-deployment/preflight", {
    package_id: v.package_id,
    site_name: v.site_name,
    release_prefix: v.release_prefix,
    core_url: v.core_url,
    pxe_url: v.pxe_url,
  });
  state.nicoTab = "progress";
  await readSection("nico", sectionReads.nico);
  toast("已启动后台部署预检。");
}

function nicoConfirm(action) {
  const connecting = action === "connect",
    op = state.nico.operation;
  state.wizard = { resource: "nico-confirm", action, operationId: op.id };
  modal(
    connecting ? "应用到站点" : "部署 NICo",
    connecting
      ? "验证身份后启用业务页面"
      : "在当前 Kubernetes 集群执行 Helm 部署",
    `<div class="live-form">${defs([
      ["站点", esc(op.configuration.site_name)],
      ["命名空间", esc(op.configuration.namespace)],
      [
        "Core",
        `<span class="live-code">${esc(op.configuration.core_url)}</span>`,
      ],
      [
        "PXE / HTTP",
        `<span class="live-code">${esc(op.configuration.pxe_url)}</span>`,
      ],
    ])}<p class="live-small">${connecting ? "将更新站点连接和材料服务地址；Core 验证失败时保留原配置。" : "将创建包内声明的 NICo 服务与依赖。失败时保留发布记录和持久数据，继续前会核对 Helm 状态。"}</p><div id="resource-error" class="live-error" role="alert"></div></div>`,
    button("取消", "close") +
      button(connecting ? "验证并应用" : "确认部署", "nico-confirm", true),
  );
}

registerActions(
  "nico_cluster.js",
  [
    "nico-refresh",
    "nico-tab",
    "nico-group",
    "nico-service",
    "nico-preflight",
    "nico-start",
    "nico-connect",
    "nico-confirm",
    "nico-site",
  ],
  async (event) => {
    const target = event.target.closest("[data-live]"),
      action = target.dataset.live;
    if (action === "nico-tab") {
      state.nicoTab = target.dataset.tab;
      render();
    } else if (action === "nico-group") {
      state.nicoGroup = target.dataset.group;
      render();
    } else if (action === "nico-service") nicoServiceDialog(target.dataset.id);
    else if (action === "nico-site") await navigate("site");
    else if (action === "nico-refresh") {
      await readSection("nico", () => sectionReads.nico(true));
      if (state.nico?.observing) toast("正在后台读取集群服务状态。");
    } else if (action === "nico-preflight") {
      target.disabled = true;
      try {
        await nicoPreflight();
      } finally {
        if (target.isConnected) target.disabled = false;
      }
    } else if (["nico-start", "nico-connect"].includes(action))
      nicoConfirm(action === "nico-connect" ? "connect" : "start");
    else if (action === "nico-confirm")
      await busy(async () => {
        const result = await api(
          "/api/nico-deployment/" + state.wizard.action,
          { id: state.wizard.operationId, confirm: true },
        );
        close();
        state.nicoTab = "progress";
        await readSection("nico", sectionReads.nico);
        toast(result.detail);
      });
  },
);

observeUI("input", "nico_cluster.js", (event) => {
  const keys = {
    "nico-site-name": "site_name",
    "nico-prefix": "release_prefix",
    "nico-core-url": "core_url",
    "nico-pxe-url": "pxe_url",
  };
  const key = keys[event.target.id];
  if (key && state.nicoForm) state.nicoForm[key] = event.target.value;
});
observeUI("change", "nico_cluster.js", (event) => {
  if (event.target.id !== "nico-package") return;
  const p = state.nico.packages.find((x) => x.id === event.target.value);
  state.nicoForm = {
    ...state.nicoForm,
    ...(p?.defaults || {}),
    package_id: event.target.value,
  };
  render();
});
let nicoPolling = false;
registerPoller(
  "nico_cluster.js",
  ["nico"],
  async () => {
    if (
      !state.csrf ||
      state.wizard ||
      nicoPolling ||
      (state.nicoTab === "config" &&
        !state.nico?.busy &&
        !state.nico?.observing &&
        state.nico?.checked_at)
    )
      return;
    nicoPolling = true;
    try {
      await readSection("nico", sectionReads.nico);
      if (
        state.nico?.operation?.status === "connected" &&
        !state.readiness?.business_available
      ) {
        await load();
      }
    } finally {
      nicoPolling = false;
    }
  },
  5000,
);
