"use strict";
let hardwareTimer = null;
function stopHardwarePolling() {
  clearTimeout(hardwareTimer);
  hardwareTimer = null;
}
async function deviceDetail(serial, tab = "overview") {
  stopHardwarePolling();
  const w = {
    resource: "device-detail",
    serial,
    tab,
    hardware: null,
    loading: true,
  };
  state.wizard = w;
  modal(
    "设备详情",
    serial,
    '<div class="live-empty">正在读取设备信息…</div>',
    button("关闭", "close"),
  );
  await readDeviceHardware(w);
}
async function readDeviceHardware(w) {
  if (w.loading && w.hardware) return;
  w.loading = true;
  const scroll = $(".modal-body")?.scrollTop || 0;
  try {
    const data = await api(
      "/api/devices/" + encodeURIComponent(w.serial) + "/hardware",
    );
    if (state.wizard !== w) return;
    w.hardware = data;
    w.error = null;
    w.check = null;
    renderDeviceDetail(w, scroll);
    if (data.auto_refresh) {
      hardwareTimer = setTimeout(() => {
        if (state.wizard === w) readDeviceHardware(w);
      }, 10000);
    }
  } catch (e) {
    if (state.wizard === w) {
      w.error = e.message;
      renderDeviceDetail(w, scroll);
    }
  } finally {
    w.loading = false;
  }
}
function deviceInterfaceTable(device, hardware, observed = []) {
  const ports = new Map(
    [...(hardware?.nics || []), ...observed]
      .filter((n) => n.mac || n.mac_address)
      .map((n) => [(n.mac || n.mac_address).toLowerCase(), n]),
  );
  const planned = (device.interfaces || []).filter(
    (n) => ["host", "unspecified", 0, 1].includes(n.role ?? "host"),
  );
  for (const nic of planned) {
    const mac = nic.mac_address?.toLowerCase();
    if (mac && !ports.has(mac)) ports.set(mac, { mac });
  }
  ports.delete(device.bmc_mac_address?.toLowerCase());
  return '<section class="subsection"><h3>设备网卡列表</h3>' + table(
    ["MAC / 型号", "PCIe 地址", "用途", "规划 IP", "所属子网", "网关"],
    [...ports.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([mac, port]) => {
      const nic = planned.find((n) => n.mac_address?.toLowerCase() === mac),
        binding = device.intent?.network_bindings?.[mac],
        network = state.networks?.networks.find((n) => n.id === binding),
        subnet = network?.prefixes.map((p) => p.prefix).join(", ") ||
          (nic?.fixed_mask ? `掩码 ${nic.fixed_mask}` : "");
      return `<tr><td>${esc(mac)}${port.model || port.name ? `<span class="live-small">${esc(port.model || port.name)}</span>` : ""}</td><td>${esc(port.pci_address || "")}${port.pci_note ? `<span class="live-small">${esc(port.pci_note)}</span>` : ""}</td><td>${nic?.primary ? "启动 / 管理口" : "主机接口"}</td><td>${esc(nic?.fixed_ip || "")}</td><td>${esc(subnet)}</td><td>${esc(nic?.fixed_gateway || "")}</td></tr>`;
    }),
  ) + '<p class="live-small">IP 为已保存的设备配置，下次安装时生效。PCIe 地址来自硬件回报，未获取或映射不唯一时留空。</p></section>';
}
function renderDeviceDetail(w, scroll = 0) {
  if (state.wizard !== w) return;
  const d = state.resources.devices.find((d) => d.serial === w.serial),
    h = w.hardware;
  const tabs = `<div class="live-tabs" role="tablist">${button("概览", "device-detail-tab", w.tab === "overview", 'data-tab="overview"')}${button("硬件信息", "device-detail-tab", w.tab === "hardware", 'data-tab="hardware"')}</div>`;
  let body = tabs;
  if (!h) {
    body += `<div class="live-error">${esc(w.error || "读取失败，请稍后重新打开设备详情。")}</div>`;
    modal("设备详情", w.serial, body, button("关闭", "close"));
    return;
  }
  body += `<p class="live-small">硬件信息更新时间：${h.hardware_read_at ? when(h.hardware_read_at) : "暂无"}</p>`;
  if (h.error || w.error)
    body += `<div class="live-error">${esc(w.error || (typeof h.error === "string" && h.error) || "NICo返回接入失败，请查看错误信息。")}</div>`;
  if (w.tab === "overview") {
    body += defs([
      ["设备SN", esc(w.serial)],
      [
        "名称 / 位置",
        esc(
          [d.metadata?.name, d.metadata?.rack].filter(Boolean).join(" / ") ||
            "未填写",
        ),
      ],
      ["当前 BMC", bmcLink(h.bmc_ip || d.bmc_ip)],
      [
        "主机接入",
        h.machine_id && h.identity_matches
          ? "已按硬件身份关联"
          : "尚未关联可核对的 NICo 主机",
      ],
      [
        "硬件",
        h.hardware && h.available && h.identity_matches
          ? esc(h.hardware.architecture || "架构未回报") +
            " · " +
            h.hardware.nics.length +
            " 个网卡 · " +
            h.hardware.disks.length +
            " 块盘"
          : "等待 Scout 回报",
      ],
      [
        "安装规划",
        esc(d.intent?.hostname || "hostname未设置") +
          " · " +
          esc(
            d.planning_missing?.length
              ? "待补充 " + d.planning_missing.join("、")
              : "已保存",
          ),
      ],
    ]);
  } else {
    if (h.hardware) {
      const f = h.hardware;
      body += defs([
        ["CPU架构", esc(f.architecture || "未回报")],
        ...(f.cpus.length
          ? [
              [
                "CPU",
                f.cpus
                  .map(
                    (c) =>
                      esc(c.model || "型号未提供") +
                      " · " +
                      esc(c.sockets ?? "—") +
                      " 路 / " +
                      esc(c.cores ?? "—") +
                      " 核 / " +
                      esc(c.threads ?? "—") +
                      " 线程",
                  )
                  .join("<br>"),
              ],
            ]
          : []),
        ...(f.memory_mb
          ? [["内存", (f.memory_mb / 1024).toLocaleString() + " GiB"]]
          : []),
      ]);
      body +=
        '<section class="subsection"><h3>磁盘</h3>' +
        table(
          ["型号", "序列号", "容量", "规划用途"],
          f.disks.map(
            (disk) =>
              `<tr><td>${esc(disk.model || "未回报")}</td><td>${esc(disk.serial || "无可用序列号")}</td><td>${disk.size_mb ? (disk.size_mb / 1024).toFixed(1) + " GiB" : "Scout未提供"}</td><td>${disk.serial && disk.serial === d.intent?.disk_serial ? "规划系统盘" : "—"}</td></tr>`,
          ),
        ) +
        "</section>";
      if (h.changes.length || h.conflicts.length)
        body += `<section class="subsection"><h3>硬件与规划变更</h3>${[...h.changes, ...h.conflicts].map((x) => `<p>${esc(x)}</p>`).join("")}<p class="live-small">请核对差异并更新设备规划。</p></section>`;
    } else
      body +=
        '<div class="live-empty">暂无硬件信息。主机进入 Scout 后可采集网卡和磁盘。</div>';
  }
  body += deviceInterfaceTable(d, h.hardware, h.nics);
  if (h.can_prepare && !w.check)
    body += button("检查接入条件", "hardware-check", false);
  if (w.check) {
    const c = w.check.checks[0];
    body +=
      '<section class="subsection"><h3>启动接入条件</h3>' +
      table(
        ["项目", "结果"],
        c.items
          .filter((i) => i.key !== "scout")
          .map(
            (i) =>
              `<tr><td>${esc(i.label)}</td><td>${i.status === "pass" ? "✓ " : ""}${esc(i.detail)}</td></tr>`,
          ),
      ) +
      (w.check.passed
        ? `<div class="live-note live-warning">将启动 ${esc(w.serial)} 进入 Scout，并执行站点配置的磁盘清理、凭据及 BIOS / 固件配置。</div><label class="live-check"><input id="hardware-cleanup" type="checkbox">允许清理本机全部磁盘（含非系统盘，清单待核对）。</label>${button("启动硬件接入", "hardware-start", true)}`
        : `<div class="live-note">${esc(c.next_action)}</div>`) +
      "</section>";
  }
  const foot =
    (state.installReviewReturn
      ? button("返回安装核对", "return-install-review")
      : "") + button("关闭", "close");
  modal("设备详情", w.serial, body, foot);
  $(".modal-body").scrollTop = scroll;
}
async function openReferencedPlan(id, mac) {
  stopHardwarePolling();
  const current = state.wizard;
  if (current?.resource === "batch") state.installReviewReturn = current;
  await deviceDialog(id);
  if (mac) {
    const w = state.wizard;
    if (!w.nics.some((n) => n.mac_address?.toLowerCase() === mac)) {
      w.nics.push({ role: "host", mac_address: mac, primary: false });
      $("#nic-list").innerHTML = w.nics.map(nicRow).join("");
      wrapNicDetails();
      $("#dev-primary-mac").add(new Option(mac, mac));
    }
    $("#dev-primary-mac").value = mac;
    $("#dev-primary-mac").dispatchEvent(new Event("change", { bubbles: true }));
  }
  if (state.installReviewReturn) {
    const back = document.querySelector('.modal-footer [data-live="close"]');
    if (back) {
      back.dataset.live = "return-install-review";
      back.textContent = "返回安装核对";
    }
  }
}
function restoreInstallReview(returnTo = state.installReviewReturn) {
  const w = returnTo;
  if (!w) return;
  state.installReviewReturn = null;
  state.wizard = w;
  w.check = null;
  w.checkError = null;
  w.checking = false;
  w.step = 2;
  w.entries = w.selected.map((serial) => {
    const d = state.resources.devices.find((d) => d.serial === serial);
    return {
      serial,
      hostname: d.intent?.hostname || "",
      disk_serial: d.intent?.disk_serial || null,
      bmc_choice: "require_planned",
    };
  });
  w.profile_id =
    state.resources.devices.find((d) => d.serial === w.selected[0])?.intent
      ?.profile_id || "";
  batchWizard();
  return batchCheck();
}
registerHook("modalClosed", stopHardwarePolling);
function discoveryDialog(serial) {
  return deviceDetail(serial, "hardware");
}
registerActions(
  "hardware.js",
  [
    "device-detail",
    "device-detail-tab",
    "device-detail-plan",
    "hardware-check",
    "hardware-start",
    "return-install-review",
  ],
  async (e) => {
    const b = e.target.closest("[data-live]");
    if (!b || b.disabled) return;
    const w = state.wizard;
    try {
      switch (b.dataset.live) {
        case "device-detail":
          return await deviceDetail(b.dataset.serial);
        case "device-detail-tab":
          w.tab = b.dataset.tab;
          return renderDeviceDetail(w);
        case "device-detail-plan":
          return await openReferencedPlan(b.dataset.id);
        case "hardware-check":
          b.disabled = true;
          w.check = await api("/api/devices/admission-preview", {
            serials: [w.serial],
          });
          if (state.wizard === w) renderDeviceDetail(w);
          return;
        case "hardware-start":
          if (!$("#hardware-cleanup")?.checked)
            throw Error("请确认全部磁盘的接入清理范围。");
          b.disabled = true;
          const r = await api("/api/devices/admit-batch", {
            preflight_id: w.check.id,
            confirm_serials: [w.serial],
            confirm_ingestion: true,
            cleanup_scope: "all_disks",
          });
          w.check = null;
          await readDeviceHardware(w);
          if (r.status !== "accepted")
            toast("接入请求结果需要核对，请查看设备状态。");
          return;
        case "return-install-review":
          return restoreInstallReview();
      }
    } catch (error) {
      b.disabled = false;
      toast(error.message);
    }
  },
);
