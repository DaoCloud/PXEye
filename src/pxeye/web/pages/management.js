"use strict";
// Extend the existing product primitives; no second UI framework or design system.
state.osLibrary = null;
state.candidates = null;
state.deviceView = "managed";
state.candidateNetwork = "";
state.candidateSelection = [];
state.planSelection = [];
const osStates = {
  importing: "导入中",
  uploading: "上传中",
  preparing: "准备中",
  registering: "登记中",
  prepared: "已准备 · 待登记",
  registered: "已登记",
  failed: "准备失败",
  needs_attention: "需核对",
  external: "NICo 既有记录",
};
async function loadOS() {
  state.osLibrary = await api("/api/operating-systems");
}
async function loadCandidates() {
  state.candidates = await api("/api/discovery/candidates");
}
function osPage() {
  const data = state.osLibrary;

  return (
    heading(
      "操作系统",
      "导入 ISO，管理可用于装机的 OS 版本。",
      button("刷新 OS", "os-refresh") +
        button("上传 ISO", "os-upload") +
        button("使用服务器 ISO", "os-import", true),
    ) +
    "" +
    (data?.error ? `<div class="live-error">${esc(data.error)}</div>` : "") +
    (data
      ? table(
          ["OS 版本 / 架构", "准备状态", "NICo 状态", "操作"],
          data.operating_systems.map(
            (o) =>
              `<tr><td><button class="link-button" data-live="os-detail" data-id="${esc(o.id)}">${esc(o.name)}</button><span class="live-small">${esc(o.architecture || "等待识别")}</span></td><td>${badge(osStates[o.status] || o.status, o.status === "failed" ? "red" : "gray")}<span class="live-small">${["uploading", "importing"].includes(o.status) ? Math.floor((100 * o.received) / o.size) + "% · " : ""}${esc(o.error || "")}</span></td><td>${o.native ? badge(o.native.is_active ? "已启用" : "未启用", o.native.is_active ? "green" : "gray") : "尚未登记"}${o.usage?.length ? `<span class="live-small">活动任务：${o.usage.map((t) => esc(t.id)).join("、")}</span>` : ""}</td><td>${o.status === "uploading" ? button("继续上传", "os-resume", false, `data-id="${esc(o.id)}"`) : ""}${["failed", "needs_attention"].includes(o.status) ? button("核对 / 重新准备", "os-recover", false, `data-id="${esc(o.id)}"`) : ""}${["uploading", "failed", "prepared"].includes(o.status) || (o.status === "needs_attention" && o.pending_operation === "import") ? button("取消此版本", "os-cancel", false, `data-id="${esc(o.id)}"`) : ""}${o.status === "prepared" ? button("继续准备并登记", "os-register", true, `data-id="${esc(o.id)}"`) : ""}${o.status === "registered" ? button(o.native?.is_active ? "停用" : "设为可用", "os-activate", false, `data-id="${esc(o.id)}" ${o.native?.is_active && o.disable_reason ? 'disabled title="' + esc(o.disable_reason) + '"' : ""}`) : ""}</td></tr>`,
          ),
        )
      : '<div class="live-empty">正在读取 OS 版本…</div>') +
    '<div class="live-note">当前支持 Ubuntu Server 自动安装；其他安装器需单独适配。</div>'
  );
}
function uploadDialog(key) {
  const row = state.osLibrary?.operating_systems.find((o) => o.id === key);
  state.wizard = { resource: "os-upload", row };
  modal(
    row ? "继续上传 ISO" : "上传 ISO",
    "操作系统管理",
    `<div class="live-form">${inputField("os-name", "OS 版本名称", row?.name || "", 'maxlength="100"')}<label>ISO 文件<input id="os-file" type="file" accept=".iso"></label>${inputField("os-sha", "SHA256 校验值（可选）", row?.expected_sha256 || "")}<div id="upload-progress" role="status">${row ? `已接收 ${row.received.toLocaleString()} / ${row.size.toLocaleString()} 字节，请重新选择同一文件。` : "支持断点续传。"}</div><progress id="iso-progress" max="100" value="0"></progress><div id="resource-error" class="live-error" role="alert"></div></div>`,
    button("关闭", "close") + button("上传并准备", "os-upload-start", true),
  );
}
async function uploadISO() {
  const w = state.wizard,
    file = $("#os-file").files[0];
  if (!file || !file.name.toLowerCase().endsWith(".iso"))
    throw Error("请选择 ISO 文件。");
  if (w.row && (file.size !== w.row.size || file.name !== w.row.filename))
    throw Error("请选择与原上传相同的 ISO 文件。");
  if (!w.row)
    w.row = await api("/api/operating-systems/upload", {
      name: $("#os-name").value.trim(),
      filename: file.name,
      size: file.size,
      sha256: $("#os-sha").value.trim(),
    });
  let offset = w.row.received;
  const id = w.row.id;
  while (offset < file.size) {
    if (state.wizard !== w) return;
    const end = Math.min(offset + 8 * 1024 * 1024, file.size);
    const r = await fetch(
      "/api/operating-systems/" + id + "/content?offset=" + offset,
      {
        method: "PUT",
        credentials: "same-origin",
        headers: {
          "X-CSRF-Token": state.csrf,
          "Content-Type": "application/octet-stream",
        },
        body: file.slice(offset, end),
      },
    );
    const data = await r.json();
    if (!r.ok) throw Error(data.error || "上传失败。");
    offset = data.received;
    w.row = data;
    if (state.wizard === w) {
      $("#upload-progress").textContent =
        `已接收 ${offset.toLocaleString()} / ${file.size.toLocaleString()} 字节`;
      $("#iso-progress").value = (100 * offset) / file.size;
    }
  }
  await api("/api/operating-systems/prepare", { id });
  close();
  await loadOS();
  render();
  toast("上传完成，正在准备 OS。");
}
async function osImportDialog() {
  const data = await api("/api/operating-systems/sources");
  state.wizard = { resource: "os-import", sources: data.sources };
  const choices = data.sources.flatMap((s) =>
    s.files.map((f) => [
      s.id + "|" + f.filename,
      `${s.name} / ${f.filename} · ${(f.size / 1024 ** 3).toFixed(2)} GiB`,
    ]),
  );
  modal(
    "使用服务器 ISO",
    "操作系统管理",
    `<div class="live-form">${inputField("os-name", "OS 版本名称", "", 'maxlength="100"')}${selectField("os-source-file", "目录中的 ISO", [["", "请选择 ISO"], ...choices], "")}${inputField("os-sha", "SHA256 校验值（可选）", "")}<p class="live-small">导入后自动准备并登记到 NICo；源 ISO 保留。完成后设为可用。</p>${data.sources.map((s) => `<div class="live-note">${esc(s.name)}：${esc(s.error || s.note || s.files.length + " 个可选 ISO")}</div>`).join("")}${!data.sources.length ? '<div class="live-note">未配置 ISO 目录，请管理员挂载目录后刷新。</div>' : ""}${!data.import_enabled ? '<div class="live-error">未配置 PXE 文件发布服务，请联系管理员。</div>' : ""}<div id="resource-error" class="live-error" role="alert"></div></div>`,
    button("关闭", "close") +
      button(
        "导入并准备",
        "os-import-start",
        true,
        choices.length && data.import_enabled ? "" : "disabled",
      ),
  );
}
async function importISO() {
  const w = state.wizard,
    selected = $("#os-source-file").value;
  const match = w.sources
    .flatMap((s) =>
      s.files.map((f) => ({ s, f, key: s.id + "|" + f.filename })),
    )
    .find((x) => x.key === selected);
  if (!match) throw Error("请选择服务器目录中的 ISO。");
  await api("/api/operating-systems/import", {
    name: $("#os-name").value.trim(),
    source_id: match.s.id,
    filename: match.f.filename,
    fingerprint: match.f.fingerprint,
    sha256: $("#os-sha").value.trim(),
  });
  close();
  await loadOS();
  render();
  toast("正在导入 ISO，进度见 OS 列表。");
}
function osDetail(key) {
  const o = state.osLibrary.operating_systems.find((o) => o.id === key);
  state.wizard = { resource: "os-detail" };
  modal(
    "OS 版本详情",
    o.name,
    defs([
      ["状态", esc(osStates[o.status])],
      [
        "材料来源",
        esc(
          o.source
            ? o.source.name + " / " + o.source.filename
            : "浏览器上传 / 既有记录",
        ),
      ],
      ["安装器", esc(o.installer || "待识别")],
      ["发行信息", esc(o.iso_info || o.os_release || "—")],
      ["NICo OS ID", esc(o.native?.id || "尚未登记")],
    ]) +
      table(
        ["材料", "发布 URL", "大小 / SHA256"],
        (o.materials || []).map(
          (m) =>
            `<tr><td>${esc(m.name)}</td><td><span class="live-code">${esc(m.url)}</span></td><td>${m.size.toLocaleString()}<span class="live-code live-small">${esc(m.sha256)}</span></td></tr>`,
        ),
      ),
    button("关闭", "close"),
  );
}
function deviceBmcAddress(d) {
  const current = String(d.bmc_address?.current_ip || d.bmc_ip || "").trim();
  const planned = String(d.bmc_ip_address || "").trim();
  const mismatch = Boolean(current && planned && current !== planned);
  return `<div class="${mismatch ? "bmc-address-mismatch" : ""}">${bmcLink(current)}<span class="live-small">规划 ${esc(planned || "待规划")}</span>${mismatch ? '<span class="live-small">规划与当前地址不一致</span>' : ""}</div><span class="live-small">${esc(d.bmc_mac_address)}</span>${d.bmc_address?.status && !["unverified", "verified"].includes(d.bmc_address.status) ? `<span class="live-small">${esc(bmcAddressLabel(d.bmc_address.status))}</span>` : ""}`;
}

const bmcAddressLabel = (s) =>
  ({
    unverified: "",
    planned: "规划已保存 · 待应用",
    assigning: "地址应用中",
    waiting_address: "等待地址采用 / 验证",
    verified: "",
    needs_attention: "应用结果需核对",
  })[s] || "待验证";

const selectedCandidates = () =>
  [...document.querySelectorAll("input[name=candidate]:checked")].map(
    (e) => e.value,
  );
function candidateAuthDialog() {
  const ids = selectedCandidates();
  if (!ids.length) throw Error("请先选择候选。");
  state.wizard = { resource: "candidate-auth", ids };
  modal(
    "认证候选设备",
    `${ids.length} 台 · 获取设备信息`,
    `<div class="live-form">${inputField("candidate-user", "BMC 用户名", "")}${inputField("candidate-password", "BMC 密码", "", 'type="password" autocomplete="new-password"')}<p class="live-small">使用以下账号登录所选 BMC，获取序列号和网卡信息。不同账号请分批读取。</p><div id="resource-error" class="live-error" role="alert"></div></div>`,
    button("取消", "close") +
      button("认证并获取设备信息", "candidate-auth-submit", true),
  );
}
async function authenticateCandidates() {
  const w = state.wizard;
  const result = await api("/api/discovery/authenticate", {
    ids: w.ids,
    username: $("#candidate-user").value,
    password: $("#candidate-password").value,
  });
  close();
  await loadCandidates();
  render();
  toast(
    `认证通过 ${result.results.filter((r) => r.passed).length} / ${result.results.length} 台；失败原因保留在候选列表。`,
  );
}
async function candidateEnrollDialog() {
  const ids = selectedCandidates();
  if (!ids.length) throw Error("请先选择候选。");
  const rows = ids.map((id) =>
    state.candidates.candidates.find((c) => c.id === id),
  );
  if (rows.some((r) => !r.authenticated))
    throw Error("必须先提供 BMC 账号密码并获取设备信息。");
  state.wizard = { resource: "candidate-enroll", ids, rows };
  modal(
    "加入设备清单",
    `${rows.length} 台 · 确认硬件身份`,
    table(
      ["序列号", "型号", "当前 BMC / MAC"],
      rows.map(
        (r) =>
          `<tr><td>${esc(r.serial)}</td><td>${esc(r.model || "未提供")}</td><td>${esc(r.bmc_ip)}<span class="live-small">${esc(r.bmc_mac)}</span></td></tr>`,
      ),
    ) +
      `<div class="live-note">加入后可规划网络和安装配置；不会自动开机或装机。</div><div id="resource-error" class="live-error" role="alert"></div>`,
    button("取消", "close") +
      button("确认加入清单", "candidate-enroll-submit", true),
  );
}
async function enrollCandidates() {
  const w = state.wizard;
  const r = await api("/api/discovery/enroll", {
    ids: w.ids,
    confirm_registration: true,
  });
  close();
  state.deviceView = "managed";
  await load();
  modal(
    "设备登记结果",
    "可继续规划设备",
    table(
      ["SN", "结果", "说明"],
      r.results.map(
        (x) =>
          `<tr><td>${esc(x.serial)}</td><td>已登记</td><td>${esc(x.detail)}</td></tr>`,
      ),
    ),
    button("关闭", "close"),
  );
}
async function bmcAddressPreview(serial) {
  const w = { resource: "bmc-address", serial };
  state.wizard = w;
  modal(
    "应用 BMC 地址",
    serial,
    '<div class="live-empty">核对当前地址、目标分配和 BMC 身份…</div>',
    button("关闭", "close"),
  );
  const r = await api("/api/devices/bmc-address/preview", { serial });
  if (state.wizard !== w) return;
  w.preview = r;
  modal(
    "应用 BMC 地址",
    serial,
    r.passed
      ? defs([
          ["当前地址", esc(r.current_ip)],
          ["规划地址", esc(r.planned_ip)],
          [
            "操作",
            r.current_ip === r.planned_ip
              ? "固定分配当前地址，BMC 仍使用 DHCP。"
              : "分配规划地址，并验证 BMC 身份。",
          ],
        ]) +
          `<label class="live-check"><input id="bmc-confirm" type="checkbox">确认更新 BMC 地址，不触发装机。</label>`
      : `<div class="live-error">${esc(r.detail)}</div><div class="live-note">请处理上述问题后重试。</div>`,
    button("关闭", "close") +
      (r.passed ? button("确认应用地址", "bmc-address-apply", true) : "") +
      '<div id="resource-error" class="live-error" role="alert"></div>',
  );
}
async function bmcAddressApply() {
  const w = state.wizard;
  if (!$("#bmc-confirm").checked) throw Error("请确认地址应用范围。");
  const r = await api("/api/devices/bmc-address/apply", {
    preflight_id: w.preview.id,
    confirm_serial: w.serial,
  });
  close();
  await load();
  toast([bmcAddressLabel(r.status), r.detail].filter(Boolean).join("："));
}
async function bmcAddressVerify(serial) {
  const r = await api("/api/devices/bmc-address/verify", { serial });
  await load();
  toast([bmcAddressLabel(r.status), r.detail].filter(Boolean).join("："));
}

function nicRow(n = {}, i = 0) {
  let html = renderNicFields(n, i);
  const bindings = state.wizard?.row?.intent?.network_bindings || {};
  const wanted = n.role === "host_bmc" ? "UNDERLAY" : "HOST_INBAND";
  const networks =
    state.networks?.networks.filter(
      (x) => x.segment_type === wanted && x.name !== "static-assignments",
    ) || [];
  const value =
    bindings[n.mac_address] ||
    networks.find(
      (x) =>
        n.fixed_ip && x.prefixes.some((p) => inPrefix(n.fixed_ip, p.prefix)),
    )?.id ||
    "";
  return html.replace(
    '<div class="live-editor-grid">',
    '<div class="live-editor-grid">' +
      selectField(
        "nic-network-" + i,
        "关联子网",
        [
          ["", "选择 NICo 已有子网"],
          ...networks.map((x) => [
            x.id,
            x.name + " · " + x.prefixes.map((p) => p.prefix).join(","),
          ]),
        ],
        value,
      ),
  );
}
function inPrefix(ip, cidr) {
  const num = (s) =>
    s.split(".").reduce((a, v) => (a * 256 + Number(v)) >>> 0, 0);
  const [base, bits] = cidr.split("/");
  if (!ip || ip.includes(":") || !bits) return false;
  const mask =
    Number(bits) === 0 ? 0 : (0xffffffff << (32 - Number(bits))) >>> 0;
  return (num(ip) & mask) === (num(base) & mask);
}
async function deviceDialog(id) {
  await Promise.allSettled([loadNetworks(), loadOS()]);
  state.networks ||= { networks: [] };
  state.osLibrary ||= { operating_systems: [] };
  renderDevicePlanDialog(id);
  if (!state.wizard.nics.some((n) => n.role === "host_bmc")) {
    const r = state.wizard.row || {};
    state.wizard.nics.push({
      role: "host_bmc",
      mac_address: r.bmc_mac_address,
      ip_allocation: r.bmc_ip_allocation,
    });
    $("#nic-list").innerHTML = state.wizard.nics.map(nicRow).join("");
  }
  const row = state.wizard.row;
  if (row) {
    const bmc = row.bmc_address || {};
    const bmcIndex = state.wizard.nics.findIndex((n) => n.role === "host_bmc");
    const bmcNetworks = state.networks.networks.filter(
      (n) => n.segment_type === "UNDERLAY" && n.name !== "static-assignments",
    );
    const bmcNetwork =
      row.intent?.network_bindings?.[row.bmc_mac_address] ||
      bmcNetworks.find((n) =>
        n.prefixes.some((p) => inPrefix(row.bmc_ip_address, p.prefix)),
      )?.id ||
      "";
    $("#dev-bmc-allocation")
      .closest("label")
      .insertAdjacentHTML(
        "afterend",
        selectField(
          "dev-bmc-network",
          "BMC 规划子网",
          [
            ["", "选择已准备的 BMC 子网"],
            ...bmcNetworks.map((n) => [
              n.id,
              n.name + " · " + n.prefixes.map((p) => p.prefix).join(","),
            ]),
          ],
          bmcNetwork,
        ),
      );
    $("#dev-bmc-ip").insertAdjacentHTML(
      "beforebegin",
      `<span class="live-small">当前地址 ${esc(row.bmc_ip || "暂无地址")}${bmc.status && !["unverified", "verified"].includes(bmc.status) ? " · " + esc(bmcAddressLabel(bmc.status)) : ""}</span>`,
    );
    $("#dev-bmc-ip").insertAdjacentHTML(
      "afterend",
      button(
        "使用当前地址",
        "bmc-use-current",
        false,
        `data-ip="${esc(row.bmc_ip || "")}" ${row.bmc_ip ? "" : "disabled"}`,
      ),
    );
    state.wizard.nics.forEach((n, i) => {
      if (n.role === "host_bmc") $(`[data-nic="${i}"]`).hidden = true;
    });
  }
  if (!row)
    $("#dev-bmc-allocation")
      .closest("label")
      .insertAdjacentHTML(
        "afterend",
        selectField(
          "dev-bmc-network",
          "BMC 规划子网",
          [
            ["", "稍后选择"],
            ...state.networks.networks
              .filter(
                (n) =>
                  n.segment_type === "UNDERLAY" &&
                  n.name !== "static-assignments",
              )
              .map((n) => [n.id, n.name]),
          ],
          "",
        ),
      );
  const intent = { ...(state.wizard.row?.intent || {}) };
  if (!intent.hostname && row?.serial)
    intent.hostname = (
      "host-" +
      row.serial
        .toLowerCase()
        .replace(/[^a-z0-9-]/g, "-")
        .replace(/^-+|-+$/g, "")
        .slice(0, 43) +
      "-" +
      row.id.slice(0, 8)
    ).slice(0, 63);
  const profiles = state.resources.first_install_profiles || [];
  const os = state.osLibrary.operating_systems.filter(
    (o) => o.status === "registered" && o.native?.is_active,
  );
  $("#resource-error").insertAdjacentHTML(
    "beforebegin",
    installIntentEditor(intent, profiles, os),
  );
  const retainOption = (selector, value, label) => {
    if (value && selector) {
      if (![...selector.options].some((o) => o.value === value))
        selector.add(new Option(label, value));
      selector.value = value;
    }
  };
  retainOption(
    $("#intent-profile"),
    intent.profile_id,
    "原规划方案（暂不可读取）",
  );
  retainOption($("#intent-os"), intent.os_id, "原规划 OS（暂不可用）");
  state.wizard.nics.forEach((n, i) =>
    retainOption(
      $("#nic-network-" + i),
      intent.network_bindings?.[n.mac_address?.toLowerCase()],
      "原规划子网（暂不可读取）",
    ),
  );
  retainOption(
    $("#dev-bmc-network"),
    intent.network_bindings?.[row?.bmc_mac_address?.toLowerCase()],
    "原规划 BMC 子网（暂不可读取）",
  );
  const list = $("#nic-list"),
    section = list.closest("section");
  section.querySelector("h3").textContent = "其他网卡";
  const details = document.createElement("details");
  details.id = "all-nics";
  details.innerHTML = `<summary>全部网卡（${state.wizard.nics.filter((n) => n.role !== "host_bmc").length} 个主机接口）</summary>`;
  section.insertBefore(details, list);
  details.append(list);
  section.querySelector('[data-live="nic-add"]') &&
    details.append(section.querySelector('[data-live="nic-add"]'));
  wrapNicDetails();
  const primary =
    state.wizard.nics.find((n) => n.role === "host" && n.primary)
      ?.mac_address || "";
  const main = document.createElement("section");
  main.className = "subsection";
  main.innerHTML =
    '<h3>主机管理与启动口</h3><div class="live-editor-grid">' +
    selectField(
      "dev-primary-mac",
      "启动网卡 MAC",
      [
        ["", "稍后选择"],
        ...state.wizard.nics
          .filter((n) => n.role !== "host_bmc")
          .map((n) => [
            n.mac_address,
            n.mac_address + " · " + nicSource(n.mac_address),
          ]),
      ],
      primary,
    ) +
    inputField("dev-host-ip", "管理 IP", "") +
    selectField(
      "dev-host-network",
      "管理子网",
      [
        ["", "稍后选择"],
        ...state.networks.networks
          .filter(
            (n) =>
              n.segment_type === "HOST_INBAND" &&
              n.name !== "static-assignments",
          )
          .map((n) => [
            n.id,
            n.name + " · " + n.prefixes.map((p) => p.prefix).join(","),
          ]),
      ],
      "",
    ) +
    '</div><p class="live-small">选择用于网络引导及 OS 管理的网卡。</p>';
  section.before(main);
  loadPrimaryPlan();
  const install = $("#intent-hostname").closest("section");
  $("#intent-enable").checked = true;
  main.after(install);
  refreshIntentDefaults();
  const top = $(".modal-body > .live-editor-grid");
  const identity = document.createElement("section");
  identity.className = "subsection";
  identity.innerHTML = '<h3>设备信息</h3><div class="live-editor-grid"></div>';
  const bmcSection = document.createElement("section");
  bmcSection.className = "subsection";
  bmcSection.innerHTML =
    '<h3>BMC 地址与登录</h3><div class="live-editor-grid"></div>';
  for (const id of ["dev-serial", "dev-name", "dev-rack", "dev-mac"]) {
    const label = $("#" + id)?.closest("label");
    if (label) identity.querySelector("div").append(label);
  }
  for (const id of [
    "dev-user",
    "dev-password",
    "dev-bmc-ip",
    "dev-bmc-allocation",
    "dev-bmc-network",
  ]) {
    const label = $("#" + id)?.closest("label");
    if (label) bmcSection.querySelector("div").append(label);
  }
  if (top) {
    top.before(identity, bmcSection);
    if (!top.children.length) top.remove();
  }
  $("#live-dialog-title").textContent = row ? "编辑设备规划" : "新增设备规划";
  $("#resource-error").before(
    Object.assign(document.createElement("p"), {
      className: "live-small",
      textContent: "保存规划，在安装时应用。BMC 改址需单独执行。",
    }),
  );
}
function intentRequest(w, m) {
  const bindings = {};
  w.nics.forEach((n, i) => {
    const mac = $("#nic-mac-" + i)
      ?.value.trim()
      .toLowerCase();
    const key = $("#nic-network-" + i)?.value;
    if (mac && key && !$("#nic-remove-" + i)?.checked) bindings[mac] = key;
  });
  const intent = {
    hostname: $("#intent-hostname").value.trim(),
    profile_id: $("#intent-profile").value,
    os_id: $("#intent-os").value,
    username: $("#intent-user").value.trim(),
    login_mode: $("#intent-mode").value,
    password: $("#intent-password").value,
    network_bindings: bindings,
  };
  return {
    serial: m.chassis_serial_number,
    revision: w.row?.intent?.revision || "",
    intent,
  };
}
async function validateIntentForDevice(w, m) {
  await api("/api/devices/installation-config/validate", {
    ...intentRequest(w, m),
    machine: m,
  });
}
async function saveIntentForDevice(w, m) {
  try {
    await api("/api/devices/installation-config", intentRequest(w, m));
  } catch (error) {
    const data = await api("/api/resources");
    const current = data.devices.find(
      (d) => d.serial === m.chassis_serial_number,
    );
    if (current) w.row = current;
    throw Error(
      "NICo 设备声明已保存；安装配置保存失败：" +
        error.message +
        "。请检查后重新保存。",
    );
  }
}
observeUI(
  "change",
  "management.js",
  (e) => {
    if (e.target.id === "candidate-all") {
      document
        .querySelectorAll(
          "[data-candidate-network]:not([hidden]) input[name=candidate]",
        )
        .forEach((c) => (c.checked = e.target.checked));
      state.candidateSelection = selectedCandidates();
    }
    if (e.target.name === "plan-device")
      state.planSelection = [
        ...document.querySelectorAll("input[name=plan-device]:checked"),
      ].map((c) => c.value);
    if (e.target.name === "candidate")
      state.candidateSelection = selectedCandidates();
    if (e.target.id === "candidate-network") {
      state.candidateNetwork = e.target.value;
      document.querySelectorAll("[data-candidate-network]").forEach((r) => {
        r.hidden =
          !!e.target.value && r.dataset.candidateNetwork !== e.target.value;
        if (r.hidden) r.querySelector("input").checked = false;
      });
      state.candidateSelection = selectedCandidates();
    }
    const match = /^nic-network-(\d+)$/.exec(e.target.id);
    if (match) {
      const i = match[1],
        n = state.networks.networks.find((n) => n.id === e.target.value);
      if (n?.prefixes.length === 1) {
        const p = n.prefixes[0],
          bits = Number(p.prefix.split("/")[1]),
          mask = bits === 0 ? 0 : (0xffffffff << (32 - bits)) >>> 0;
        $("#nic-mask-" + i).value = [24, 16, 8, 0]
          .map((s) => (mask >>> s) & 255)
          .join(".");
        $("#nic-gateway-" + i).value = p.gateway || "";
        $("#nic-segment-" + i).value = String(
          { HOST_INBAND: 3, UNDERLAY: 2, ADMIN: 1, TENANT: 0 }[n.segment_type],
        );
      }
    }
  },
  false,
);
registerActions(
  "management.js",
  [
    "os-upload",
    "os-resume",
    "os-detail",
    "os-refresh",
    "os-upload-start",
    "os-import",
    "os-import-start",
    "os-recover",
    "os-cancel",
    "os-register",
    "os-activate",
    "device-managed",
    "device-pending",
    "candidate-refresh",
    "bmc-use-current",
    "bmc-address-preview",
    "bmc-address-apply",
    "bmc-address-verify",
    "candidate-auth",
    "candidate-auth-submit",
    "candidate-enroll",
    "candidate-enroll-submit",
  ],
  async (e) => {
    const el = e.target.closest("[data-live]");
    if (!el || el.disabled) return;
    const action = el.dataset.live;
    try {
      if (action === "os-upload" || action === "os-resume")
        return uploadDialog(el.dataset.id);
      if (action === "os-detail") return osDetail(el.dataset.id);
      if (action === "os-refresh") {
        await loadOS();
        render();
        return;
      }
      if (action === "os-upload-start") return busy(uploadISO);
      if (action === "os-import") return await osImportDialog();
      if (action === "os-import-start") return busy(importISO);
      if (action === "os-recover" || action === "os-cancel") {
        const o = state.osLibrary.operating_systems.find(
          (o) => o.id === el.dataset.id,
        );
        if (
          action === "os-cancel" &&
          !confirm("取消此版本并删除已准备的文件？源 ISO 保留。")
        )
          return;
        el.disabled = true;
        await api("/api/operating-systems/" + action.slice(3), {
          id: o.id,
          revision: o.revision,
        });
        await loadOS();
        render();
        return;
      }
      if (action === "os-register") {
        const o = state.osLibrary.operating_systems.find(
          (o) => o.id === el.dataset.id,
        );
        el.disabled = true;
        await api("/api/operating-systems/register", {
          id: o.id,
          revision: o.revision,
        });
        await loadOS();
        render();
        return;
      }
      if (action === "os-activate") {
        const o = state.osLibrary.operating_systems.find(
          (o) => o.id === el.dataset.id,
        );
        el.disabled = true;
        await api("/api/operating-systems/activate", {
          id: o.id,
          active: !o.native.is_active,
        });
        await loadOS();
        render();
        return;
      }
      if (action === "device-managed") {
        state.deviceView = "managed";
        state.candidateNetwork = "";
        state.candidateSelection = [];
        state.planSelection = [];
        render();
        return;
      }
      if (action === "device-pending") {
        state.deviceView = "pending";
        render();
        return;
      }
      if (action === "candidate-refresh") {
        state.deviceView = "pending";
        await loadCandidates();
        render();
        return;
      }
      if (action === "bmc-use-current") {
        $("#dev-bmc-ip").value = el.dataset.ip;
        $("#dev-bmc-allocation").value = "Fixed";
        return;
      }
      if (action === "bmc-address-preview")
        return await bmcAddressPreview(el.dataset.serial);
      if (action === "bmc-address-apply") return busy(bmcAddressApply);
      if (action === "bmc-address-verify")
        return busy(() => bmcAddressVerify(el.dataset.serial));
      if (action === "candidate-auth") return candidateAuthDialog();
      if (action === "candidate-auth-submit")
        return busy(authenticateCandidates);
      if (action === "candidate-enroll") return await candidateEnrollDialog();
      if (action === "candidate-enroll-submit") return busy(enrollCandidates);
    } catch (error) {
      el.disabled = false;
      toast(error.message);
    }
  },
);
let osPolling = false;
registerPoller(
  "management.js",
  ["os"],
  async () => {
    if (!state.csrf || state.page !== "os" || state.wizard || osPolling) return;
    const pending = state.osLibrary?.operating_systems.some((o) =>
      ["uploading", "importing", "preparing", "registering"].includes(o.status),
    );
    if (!pending) return;
    osPolling = true;
    try {
      await readSection("os", sectionReads.os);
    } finally {
      osPolling = false;
    }
  },
  5000,
);

function nicSource(mac) {
  const source = state.wizard?.row?.inventory_sources?.[mac?.toLowerCase()];
  return source?.source === "bmc"
    ? "BMC 发现"
    : source?.source === "csv"
      ? "CSV 导入"
      : source?.source === "manual"
        ? "手工添加"
        : "已声明 · 来源待核对";
}
function wrapNicDetails() {
  document.querySelectorAll("#nic-list [data-nic]").forEach((el) => {
    const index = Number(el.dataset.nic),
      nic = state.wizard.nics[index];
    if (nic.role === "host_bmc") {
      el.hidden = true;
      return;
    }
    if (el.parentElement.tagName === "DETAILS" || el.hidden) return;
    const d = document.createElement("details");
    d.className = "nic-detail";
    d.innerHTML = `<summary>${esc(nic.mac_address || "新接口")} · ${esc(nicSource(nic.mac_address))}</summary>`;
    el.before(d);
    d.append(el);
  });
}
function loadPrimaryPlan() {
  const mac = $("#dev-primary-mac")?.value,
    index = state.wizard.nics.findIndex((n) => n.mac_address === mac);
  $("#dev-host-ip").value = index >= 0 ? $("#nic-ip-" + index).value : "";
  const key = index >= 0 ? $("#nic-network-" + index).value : "";
  if (key && ![...$("#dev-host-network").options].some((o) => o.value === key))
    $("#dev-host-network").add(new Option("原规划子网（暂不可读取）", key));
  $("#dev-host-network").value = key;
  $("#dev-host-ip").disabled = index < 0;
  $("#dev-host-network").disabled = index < 0;
}
function syncPrimaryPlan() {
  const mac = $("#dev-primary-mac")?.value;
  state.wizard.nics.forEach((n, i) => {
    if (n.role === "host_bmc") return;
    $("#nic-primary-" + i).checked = n.mac_address === mac;
    if (n.mac_address === mac) {
      $("#nic-ip-" + i).value = $("#dev-host-ip").value.trim();
      $("#nic-network-" + i).value = $("#dev-host-network").value;
      if ($("#dev-host-ip").value.trim())
        $("#nic-allocation-" + i).value = "fixed";
    }
  });
}
observeUI(
  "input",
  "management.js",
  (e) => {
    if (state.wizard?.nics && e.target.id === "dev-host-ip") syncPrimaryPlan();
  },
  false,
);
observeUI(
  "change",
  "management.js",
  (e) => {
    if (!state.wizard?.nics) return;
    if (e.target.id === "dev-primary-mac") {
      loadPrimaryPlan();
      syncPrimaryPlan();
    }
    if (e.target.id === "dev-host-network") {
      syncPrimaryPlan();
      const i = state.wizard.nics.findIndex(
        (n) => n.mac_address === $("#dev-primary-mac").value,
      );
      if (i >= 0) {
        $("#nic-network-" + i).value = e.target.value;
        $("#nic-network-" + i).dispatchEvent(
          new Event("change", { bubbles: true }),
        );
      }
    }
    if (e.target.id.startsWith("nic-mac-")) {
      const index = Number(e.target.id.slice(8)),
        nic = state.wizard.nics[index],
        previous = nic.mac_address;
      nic.mac_address = e.target.value.trim();
      const selector = $("#dev-primary-mac");
      let option = [...selector.options].find((o) => o.value === previous);
      if (option) {
        option.value = nic.mac_address;
        option.textContent = nic.mac_address + " · 手工规划";
      } else if (nic.mac_address)
        selector.add(
          new Option(nic.mac_address + " · 手工规划", nic.mac_address),
        );
    }
    if (e.target.id.startsWith("nic-primary-")) {
      const index = Number(e.target.id.slice(12)),
        nic = state.wizard.nics[index];
      if (e.target.checked) {
        $("#dev-primary-mac").value = nic.mac_address;
        state.wizard.nics.forEach((n, i) => {
          if (i !== index) $("#nic-primary-" + i).checked = false;
        });
      } else if ($("#dev-primary-mac").value === nic.mac_address)
        $("#dev-primary-mac").value = "";
      loadPrimaryPlan();
    }
    const match = e.target.id.match(/^nic-[a-z]+-(\d+)$/);
    if (
      match &&
      state.wizard.nics[Number(match[1])]?.mac_address ===
        $("#dev-primary-mac").value
    )
      loadPrimaryPlan();
  },
  false,
);

function addNic() {
  appendNic();
  wrapNicDetails();
}
async function saveDevice() {
  const returnTo = state.installReviewReturn;
  const w = state.wizard;
  syncPrimaryPlan();
  if (["Dynamic", "Retained"].includes($("#dev-bmc-allocation").value))
    $("#dev-bmc-ip").value = "";
  w.nics.forEach((n, i) => {
    if (n.role === "host_bmc") {
      $("#nic-mac-" + i).value = $("#dev-mac").value.trim();
      const policy = $("#dev-bmc-allocation").value.toLowerCase(),
        ip = $("#dev-bmc-ip").value.trim();
      $("#nic-allocation-" + i).value = [
        "fixed",
        "dynamic",
        "retained",
      ].includes(policy)
        ? policy
        : "";
      $("#nic-ip-" + i).value =
        policy === "fixed" || policy === "auto" ? ip : "";
      $("#nic-primary-" + i).checked = false;
      if ($("#dev-bmc-network"))
        $("#nic-network-" + i).value = $("#dev-bmc-network").value;
    }
  });
  const result = await persistDevicePlan(
    returnTo
      ? () => {
          state.wizard = returnTo;
          returnTo.step = 2;
          returnTo.check = null;
          returnTo.checkError = null;
          returnTo.checking = true;
          batchWizard();
        }
      : null,
  );
  if (returnTo && state.wizard === returnTo) {
    returnTo.checking = false;
    await restoreInstallReview(returnTo);
  }
  return result;
}
