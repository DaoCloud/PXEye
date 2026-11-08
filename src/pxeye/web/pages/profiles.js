"use strict";
const profileFields = [
  "os_id",
  "username",
  "login_mode",
  "authorized_keys",
  "credential",
];
const profileFieldNames = {
  os_id: "OS版本",
  username: "用户名",
  login_mode: "登录方式",
  authorized_keys: "用户公钥",
  credential: "OS密码",
};
async function loadProfiles() {
  state.profiles = (await api("/api/install-profiles")).profiles;
}
function profilePage() {
  return (
    heading(
      "安装方案",
      "设置 OS、系统盘、分区和默认登录配置值。设备可单独覆盖。",
      button("刷新数据", "profile-refresh") +
        button("新建方案", "profile-new", true),
    ) +
    '<div class="profile-list">' +
    table(
      [
        "名称 / 版本",
        "默认OS / 安装器",
        "分区 / 默认登录配置",
        "状态 / 引用",
        "操作",
      ],
      (state.profiles || []).map(
        (p) =>
          `<tr><td>${esc(p.name)}<span class="live-small">v${p.version} · ${esc(p.description)}</span></td><td>${esc(state.osLibrary?.operating_systems.find((o) => o.id === p.settings.os_id)?.name || p.os_release)}<span class="live-small">${esc(p.architecture)} · Ubuntu autoinstall / UEFI</span></td><td>${esc(p.disk_selection)}<span class="live-small">${esc(p.layout)}</span><span class="live-small">${esc(p.settings.username)} · ${p.settings.login_mode === "password" ? "SSH密码" : "SSH公钥"} · ${p.password_present ? "已设置默认密码" : "默认密码未设置"}</span></td><td>${badge(p.status === "draft" ? "草稿" : p.active ? "已发布" : "已停用", p.active ? "green" : "gray")}<span class="live-small">${p.references.devices.length} 台设备 / ${p.references.tasks} 个历史任务</span></td><td>${button(p.status === "draft" ? "编辑草稿" : "查看", "profile-edit", false, `data-id="${esc(p.id)}"`)}${button("复制", "profile-copy", false, `data-id="${esc(p.id)}"`)}${p.status === "published" ? button("新版本", "profile-version", false, `data-id="${esc(p.id)}"`) + button(p.active ? "停用" : "启用", "profile-active", false, `data-id="${esc(p.id)}"`) : button("删除草稿", "profile-delete", false, `data-id="${esc(p.id)}"`)}</td></tr>`,
      ),
    ) +
    "</div>"
  );
}
function multiline(id, label, values) {
  return `<label>${esc(label)}<textarea class="input" id="${id}" rows="3">${esc((values || []).join("\n"))}</textarea></label>`;
}
function lines(id) {
  return $("#" + id)
    .value.split("\n")
    .map((s) => s.trim())
    .filter(Boolean);
}
async function profileEditor(id, copy = false) {
  await loadProfiles();
  try {
    await loadOS();
  } catch (error) {
    state.osLibrary ||= { operating_systems: [], error: error.message };
  }
  const p =
    state.profiles.find((p) => p.id === id) ||
    state.profiles.find((p) => p.network_mode === "flat" && p.active) ||
    state.profiles.find((p) => p.network_mode === "flat");
  if (!p) return toast("站点缺少基础安装方案，请联系管理员配置。");
  const isNew = copy || !id,
    s = structuredClone(p.settings),
    readonly = !isNew && p.status === "published";
  const storage = s.storage || {
    selection: "unique",
    disk_type: "any",
    efi_mib: 1024,
  };
  if (!id) s.login_mode = "password";
  state.wizard = { resource: "profile", profile: p, isNew };
  const os = state.osLibrary.operating_systems.filter(
    (o) =>
      o.status === "registered" &&
      o.native?.is_active &&
      o.architecture === p.architecture &&
      o.installer === "ubuntu-server",
  );
  const options = [["", "稍后选择OS"], ...os.map((o) => [o.id, o.name])];
  if (s.os_id && !options.some((o) => o[0] === s.os_id))
    options.push([s.os_id, "当前 OS（需检查可用性）"]);
  let body = `<fieldset ${readonly ? "disabled" : ""} style="border:0;padding:0"><section class="subsection"><h3>基本信息</h3><div class="live-editor-grid">${inputField("profile-name", "方案名称", isNew ? p.name + " · 副本" : p.name)}${inputField("profile-description", "说明", p.description)}${selectField("profile-os", "默认 OS", options, s.os_id)}</div><p class="live-small">${esc(p.architecture)} · Ubuntu autoinstall · UEFI</p></section><section class="subsection"><h3>安装设置</h3><h4>系统盘选择</h4><div class="live-editor-grid">${selectField(
    "profile-disk-selection",
    "选择规则",
    [
      ["unique", "唯一匹配磁盘"],
      ["smallest", "容量最小磁盘"],
      ["largest", "容量最大磁盘"],
    ],
    storage.selection,
  )}${selectField(
    "profile-disk-type",
    "候选范围",
    [
      ["any", "所有磁盘"],
      ["nvme", "仅 NVMe"],
    ],
    storage.disk_type,
  )}${inputField("profile-disk-serial", "序列号规则（可选）", storage.serial_pattern || "", 'placeholder="例如 S6Z*"')}${inputField("profile-disk-model", "型号规则（可选）", storage.model_pattern || "", 'placeholder="例如 Samsung*"')}${inputField("profile-disk-min", "最小容量（GiB，可选）", storage.min_gib ?? "", 'type="number" min="1" step="any"')}${inputField("profile-disk-max", "最大容量（GiB，可选）", storage.max_gib ?? "", 'type="number" min="1" step="any"')}</div><p class="live-small">全部条件同时匹配；* 匹配任意字符，? 匹配单个字符，区分大小写。设备指定盘优先；无匹配或并列时需指定磁盘。按容量选择需有完整容量信息，当前 Scout 可能仅提供 NVMe 容量。</p><h4>分区布局</h4><div class="live-editor-grid">${selectField(
    "profile-root-fstype",
    "根分区格式",
    [
      ["ext4", "ext4"],
      ["xfs", "XFS"],
    ],
    storage.root_fstype || "ext4",
  )}${inputField("profile-efi", "EFI 分区（MiB）", storage.efi_mib, 'type="number" min="512" max="4096" step="1"')}${inputField("profile-root", "根分区（GiB，留空用剩余空间）", storage.root_gib ?? "", 'type="number" min="20" step="any"')}</div><p class="live-small">单盘 GPT，无 swap。指定根分区大小后，多余空间不分配。重装沿用原系统盘。</p></section><section class="subsection"><h3>默认登录配置</h3><div class="live-editor-grid">${inputField("profile-user", "OS 用户名", s.username)}${selectField(
    "profile-mode",
    "登录方式",
    [
      ["password", "SSH密码登录"],
      ["key", "SSH公钥登录"],
    ],
    s.login_mode,
  )}${inputField("profile-password", p.password_present ? "默认 OS 密码（留空保留）" : "默认 OS 密码（可逐机提供）", "", 'type="password" autocomplete="new-password"')}${selectField(
    "profile-credential-action",
    "默认密码处理",
    [
      ["keep", "保留密码"],
      ["clear", "清除密码"],
    ],
    "keep",
  )}${multiline("profile-keys", "SSH 公钥（每行一个）", s.authorized_keys)}</div><p class="live-small">使用密码登录时，需在此处或设备规划中设置密码。</p></section><details class="subsection"><summary>高级设置</summary><div class="live-editor-grid">${inputField("profile-timezone", "时区", s.timezone)}${multiline("profile-ntp", "NTP 服务器（每行一个）", s.ntp)}${multiline("profile-packages", "额外软件包（每行一个）", s.packages)}${inputField("profile-apt", "APT 软件源 URL", s.apt?.primary?.[0]?.uri || "")}${inputField("profile-security", "APT 安全更新源 URL", s.apt?.security?.[0]?.uri || "")}${multiline("profile-dns-checks", "DNS 验收域名（每行一个）", s.dns_checks)}${multiline("profile-http-checks", "HTTP 验收 URL（每行一个）", s.http_checks)}</div><p class="live-small">留空时仅使用 ISO 内材料；需要额外软件时填写可达的站点内 APT 源。当前不支持自定义脚本、多盘分区或 LVM。</p>${defs(
    [
      ["网络模式", esc(p.network_mode) + " · 继承站点已有租户/VPC"],
      ["验证范围", esc(p.evidence)],
    ],
  )}</details></fieldset><div id="resource-error" class="live-error" role="alert"></div>`;
  let foot = button("关闭", "close");
  if (!readonly) foot += button("保存草稿", "profile-save", true);
  if (!isNew && !readonly)
    foot +=
      button("检查方案", "profile-check") +
      button("发布版本", "profile-publish");
  modal(
    readonly ? "查看安装方案" : "编辑安装方案",
    `${p.name} · ${isNew ? "新草稿" : "v" + p.version}`,
    body,
    foot,
  );
}
async function profileSave() {
  return busy(async () => {
    const w = state.wizard,
      p = w.profile;
    const apt = structuredClone(p.settings.apt || {});
    if ($("#profile-apt").value.trim())
      apt.primary = [
        { arches: ["default"], uri: $("#profile-apt").value.trim() },
      ];
    else delete apt.primary;
    if ($("#profile-security").value.trim())
      apt.security = [
        { arches: ["default"], uri: $("#profile-security").value.trim() },
      ];
    else delete apt.security;
    const config = {
      name: $("#profile-name").value.trim(),
      description: $("#profile-description").value,
      os_id: $("#profile-os").value,
      username: $("#profile-user").value.trim(),
      login_mode: $("#profile-mode").value,
      password: $("#profile-password").value,
      credential_action: $("#profile-credential-action").value,
      authorized_keys: lines("profile-keys"),
      timezone: $("#profile-timezone").value.trim(),
      ntp: lines("profile-ntp"),
      packages: lines("profile-packages"),
      apt,
      dns_checks: lines("profile-dns-checks"),
      http_checks: lines("profile-http-checks"),
      storage: {
        root_fstype: $("#profile-root-fstype").value,
        selection: $("#profile-disk-selection").value,
        disk_type: $("#profile-disk-type").value,
        serial_pattern: $("#profile-disk-serial").value.trim(),
        model_pattern: $("#profile-disk-model").value.trim(),
        min_gib:
          $("#profile-disk-min").value === ""
            ? null
            : Number($("#profile-disk-min").value),
        max_gib:
          $("#profile-disk-max").value === ""
            ? null
            : Number($("#profile-disk-max").value),
        efi_mib: Number($("#profile-efi").value),
        root_gib:
          $("#profile-root").value === ""
            ? null
            : Number($("#profile-root").value),
      },
    };
    const saved = await api("/api/install-profiles/save", {
      id: w.isNew ? "" : p.id,
      revision: w.isNew ? "" : p.revision,
      source_id: p.id,
      config,
    });
    await profileEditor(saved.id);
    toast(saved.export_error || "草稿已保存。");
  });
}
async function profileAction(action, id) {
  const p = state.profiles.find(
    (p) => p.id === (id || state.wizard?.profile?.id),
  );
  if (!p) return;
  if (action === "check") {
    const r = await api("/api/install-profiles/check", { id: p.id });
    return toast(
      r.passed ? "配置检查通过，尚未实机验证。" : r.problems.join("；"),
    );
  }
  if (action === "new-version") {
    const r = await api("/api/install-profiles/new-version", {
      id: p.id,
      revision: p.revision,
    });
    return profileEditor(r.id);
  }
  if (action === "delete" && !confirm("删除此方案草稿？")) return;
  if (
    action === "active" &&
    p.active &&
    !confirm("停用后不能提交使用此版本的新安装；已有规划和历史记录保留。")
  )
    return;
  const result = await api("/api/install-profiles/" + action, {
    id: p.id,
    revision: p.revision,
    ...(action === "active" ? { active: !p.active } : {}),
  });
  close();
  await loadProfiles();
  await load();
  toast(result.export_error || "方案已更新。");
}
function effectiveInstallSummary(device) {
  const e = device?.intent?.effective;
  if (!e) return "";
  const v = e.values,
    src = e.sources;
  return `<section class="live-card"><h3>生效安装配置</h3>${defs([
    ["方案", esc(device.intent.profile_id)],
    [
      "目标OS",
      esc(
        state.osLibrary?.operating_systems.find((o) => o.id === v.os_id)
          ?.name || v.os_id,
      ) +
        " · " +
        esc(src.os_id),
    ],
    ["用户名", esc(v.username) + " · " + esc(src.username)],
    [
      "登录方式",
      esc(v.login_mode === "password" ? "SSH密码" : "SSH公钥") +
        " · " +
        esc(src.login_mode),
    ],
    [
      "OS密码",
      esc(e.password_present ? "已设置" : "未设置") +
        " · " +
        esc(src.credential),
    ],
    [
      "用户公钥",
      esc((v.authorized_keys || []).length) +
        " 个 · " +
        esc(src.authorized_keys),
    ],
    ["时区", esc(v.timezone) + " · 方案"],
  ])}${e.problems.length ? `<div class="live-error">${esc(e.problems.join("；"))}</div>` : ""}</section>`;
}
function installIntentEditor(intent, profiles, os) {
  const modes =
    intent.override_modes ||
    Object.fromEntries(
      profileFields.map((k) => [
        k,
        (k === "credential" ? intent.password_present : !!intent[k])
          ? "override"
          : "inherit",
      ]),
    );
  state.wizard.intentModes = { ...modes };
  const control = (k, id, label, content) =>
    `<div><label>${label}<select class="input" id="mode-${k}"><option value="inherit" ${modes[k] === "inherit" ? "selected" : ""}>继承所选方案</option><option value="override" ${modes[k] === "override" ? "selected" : ""}>为此设备设置</option></select></label><div id="override-${k}">${content}</div><span class="live-small" id="source-${k}"></span></div>`;
  return `<section class="subsection" id="install-intent-section"><h3>安装配置</h3><input id="intent-enable" type="checkbox" checked hidden><div class="live-editor-grid">${inputField("intent-hostname", "主机名", intent.hostname || "")}${selectField("intent-profile", "当前安装方案", [["", "请选择安装方案"], ...profiles.map((p) => [p.id, p.name + " · v" + (p.version || 1)])], intent.profile_id || "")}${selectField("intent-disk", state.wizard.row?.instance_id ? "系统盘（重装沿用）" : "系统盘序列号", [["", "使用所选方案的选盘规则"], ...(state.wizard.row?.disks || []).map((d) => [d.serial, d.model + " / " + d.serial]), ...(intent.disk_serial && !(state.wizard.row?.disks || []).some((d) => d.serial === intent.disk_serial) ? [[intent.disk_serial, intent.disk_serial + "（执行前重新核对）"]] : [])], intent.disk_serial || "")}</div><div class="live-note" id="intent-profile-summary">请选择安装方案。</div><span class="live-small" id="intent-disk-rule"></span><details><summary>设备覆盖设置</summary><div class="live-editor-grid">${control("os_id", "intent-os", "目标 OS", selectField("intent-os", "设备 OS", [["", "稍后选择"], ...os.map((o) => [o.id, o.name])], intent.os_id || ""))}${control("username", "intent-user", "OS 登录用户名", inputField("intent-user", "设备 OS 用户名", intent.username || ""))}${control(
    "login_mode",
    "intent-mode",
    "登录方式",
    selectField(
      "intent-mode",
      "设备登录方式",
      [
        ["password", "SSH密码登录"],
        ["key", "SSH公钥登录"],
      ],
      intent.login_mode || "password",
    ),
  )}${control("credential", "intent-password", "OS 密码", inputField("intent-password", intent.password_present ? "设备密码（留空保留）" : "设备密码", "", 'type="password" autocomplete="new-password"'))}${control("authorized_keys", "intent-keys", "用户公钥", multiline("intent-keys", "设备公钥（替换方案用户公钥）", intent.authorized_keys))}</div></details><p class="live-small">保存后在下次安装生效。系统盘留空时按所选方案规则选择，重装沿用原盘。</p><div id="intent-conflicts" class="live-error"></div></section>`;
}
function refreshIntentDefaults() {
  if (!$("#intent-profile")) return;
  if (state.wizard.row?.instance_id) {
    const el = $("#intent-disk"),
      value = state.wizard.row.disk_serial || state.wizard.row.disk_wwn || "";
    if (value && ![...el.options].some((o) => o.value === value))
      el.add(new Option(value, value));
    el.value = state.wizard.row.disk_serial || "";
    el.disabled = true;
  }
  const p =
    (state.profiles || []).find((p) => p.id === $("#intent-profile").value) ||
    state.resources.first_install_profiles.find(
      (p) => p.id === $("#intent-profile").value,
    );
  const s = p?.settings || {
    username: p?.ssh_user || "",
    login_mode: "password",
    authorized_keys: [],
    os_id: "",
  };
  const profileName = p ? `${p.name} · v${p.version || 1}` : "未选择方案";
  const osName =
    state.osLibrary?.operating_systems.find((o) => o.id === s.os_id)?.name ||
    s.os_id ||
    "未设置 OS";
  const loginName = s.login_mode === "key" ? "SSH 公钥登录" : "SSH 密码登录";
  const summary = $("#intent-profile-summary");
  if (summary)
    summary.textContent = p
      ? `当前引用：${profileName}；${osName}；OS 用户 ${s.username || "未设置"}；${loginName}。`
      : "请选择安装方案后再配置设备覆盖。";
  const diskHint = $("#intent-disk-rule");
  if (diskHint)
    diskHint.textContent = p?.disk_selection || "选择方案后使用其系统盘规则";
  const ids = {
      os_id: "intent-os",
      username: "intent-user",
      login_mode: "intent-mode",
      authorized_keys: "intent-keys",
      credential: "intent-password",
    },
    conflicts = [];
  for (const k of profileFields) {
    const inherit = $("#mode-" + k).value === "inherit",
      el = $("#" + ids[k]);
    el.disabled = inherit;
    if (inherit) {
      if (k === "authorized_keys") el.value = (s[k] || []).join("\n");
      else if (k === "credential") el.value = "";
      else {
        const value = s[k] || "";
        if (
          el.tagName === "SELECT" &&
          value &&
          ![...el.options].some((o) => o.value === value)
        )
          el.add(new Option(value, value));
        el.value = value;
      }
    }
    const inherited = {
      os_id: osName,
      username: s.username || "未设置",
      login_mode: loginName,
      authorized_keys: `${(s.authorized_keys || []).length} 个公钥`,
      credential: p?.password_present ? "密码已设置" : "密码未设置",
    }[k];
    const option = $("#mode-" + k).options[0];
    option.textContent = p
      ? `继承 ${p.name} v${p.version || 1}`
      : "继承所选方案";
    const override = $("#override-" + k);
    if (override) override.hidden = inherit && k === "credential";
    $("#source-" + k).textContent = inherit
      ? `来自 ${profileName}：${inherited}`
      : "使用此设备的覆盖值";
  }
  $("#intent-conflicts").textContent = conflicts.join("；");
}
const previousIntentRequest = intentRequest;
intentRequest = function (w, m) {
  const body = previousIntentRequest(w, m);
  body.intent.override_modes = Object.fromEntries(
    profileFields.map((k) => [k, $("#mode-" + k).value]),
  );
  body.intent.authorized_keys = lines("intent-keys");
  body.intent.disk_serial = $("#intent-disk").value;
  body.intent.credential_action = "keep";
  return body;
};
observeUI(
  "change",
  "profiles.js",
  (e) => {
    if (e.target.id === "intent-profile" || e.target.id?.startsWith("mode-"))
      refreshIntentDefaults();
  },
  false,
);
registerActions(
  "profiles.js",
  [
    "network-dns",
    "network-dns-save",
    "profile-new",
    "profile-refresh",
    "profile-edit",
    "profile-copy",
    "profile-save",
    "profile-check",
    "profile-publish",
    "profile-version",
    "profile-active",
    "profile-delete",
  ],
  async (e) => {
    const el = e.target.closest("[data-live]");
    if (!el || el.disabled) return;
    try {
      switch (el.dataset.live) {
        case "network-dns": {
          const n = state.networks.networks.find((n) => n.id === el.dataset.id);
          state.wizard = { resource: "network-dns", network: n };
          modal(
            "OS DNS",
            n.name,
            multiline(
              "network-dns-servers",
              "DNS 服务器（每行一个）",
              n.services.dns_servers,
            ) +
              '<p class="live-small">用于下次 OS 安装；不修改 DHCP 或当前系统。</p><div id="resource-error" class="live-error"></div>',
            button("取消", "close") + button("保存", "network-dns-save", true),
          );
          return;
        }
        case "network-dns-save": {
          const n = state.wizard.network;
          const r = await api("/api/networks/services", {
            id: n.id,
            revision: n.services.revision,
            dns_servers: lines("network-dns-servers"),
          });
          close();
          await loadNetworks();
          render();
          return toast(r.detail);
        }
        case "profile-new":
          return await profileEditor(null, true);
        case "profile-refresh":
          await loadProfiles();
          return render();
        case "profile-edit":
          return await profileEditor(el.dataset.id);
        case "profile-copy":
          return await profileEditor(el.dataset.id, true);
        case "profile-save":
          return await profileSave();
        case "profile-check":
          return await profileAction("check");
        case "profile-publish":
          return await profileAction("publish");
        case "profile-version":
          return await profileAction("new-version", el.dataset.id);
        case "profile-active":
          return await profileAction("active", el.dataset.id);
        case "profile-delete":
          return await profileAction("delete", el.dataset.id);
      }
    } catch (error) {
      if ($("#resource-error"))
        $("#resource-error").textContent = error.message;
      else toast(error.message);
    }
  },
);
