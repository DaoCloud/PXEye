"use strict";
const topologyKinds = {
  server: "服务器",
  switch: "交换机",
  power_shelf: "供电框",
  dpu: "DPU",
  other: "其他设备",
};
const topologyIcon = (kind) =>
  `<img class="topology-icon" src="/icons/${kind === "rack" ? "building-warehouse" : kind === "server" ? "server-2" : kind === "switch" ? "network" : kind === "power_shelf" ? "bolt" : kind === "dpu" ? "cpu" : "server-2"}.svg" alt="">`;
const topologyRackName = (id) =>
  id === "unassigned"
    ? "未分配机柜"
    : /^([0-9a-f]{8}-){1}/i.test(id)
      ? "Rack · " + id.slice(0, 8)
      : id;
function topologyInPrefix(ip, cidr) {
  const parts = (value) => value.split(".").map(Number);
  try {
    const [base, bitsText] = cidr.split("/"),
      bits = Number(bitsText),
      a = parts(ip),
      b = parts(base);
    if (a.length !== 4 || b.length !== 4 || bits < 0 || bits > 32) return false;
    const ai = a.reduce((n, x) => (n * 256 + x) >>> 0, 0),
      bi = b.reduce((n, x) => (n * 256 + x) >>> 0, 0),
      mask = bits === 0 ? 0 : (0xffffffff << (32 - bits)) >>> 0;
    return (ai & mask) === (bi & mask);
  } catch {
    return false;
  }
}
function topologyNetworks(device) {
  const networks = new Map(
    (state.networks?.networks || []).map((n) => [n.id, n]),
  );
  return device.ports.flatMap((port) => {
    const observed = port.observed || [];
    if (observed.length)
      return observed.map((row) => ({
        name: row.network_name || "未匹配子网",
        prefix: (networks.get(row.network_id)?.prefixes || [])
          .map((p) => p.prefix)
          .join(" / "),
        address: (row.addresses || []).join(", ") || port.target_ip || "待分配",
        role: port.role_label,
        mac: port.mac_address,
      }));
    const target = port.target_ip || "";
    const network = [...networks.values()].find(
      (n) =>
        target && n.prefixes?.some((p) => topologyInPrefix(target, p.prefix)),
    );
    return [
      {
        name: network?.name || "未关联子网",
        prefix: network?.prefixes?.map((p) => p.prefix).join(" / ") || "",
        address: target || "待分配",
        role: port.role_label,
        mac: port.mac_address,
      },
    ];
  });
}
function topologyStatus(device) {
  if (device.status === "managed" || device.status === "server")
    return ["已纳管", "ok"];
  if (device.status === "declared") return ["已声明", "planned"];
  return ["待完善", "muted"];
}
function topologyPortAddress(port) {
  const current = (port?.observed || [])
    .flatMap((row) => row.addresses || [])
    .find(Boolean);
  return current || port?.target_ip || "—";
}
function topologyPower(device) {
  const value = String(device.power_state ?? "")
    .toLowerCase()
    .replaceAll("_", "");
  if (value === "on" || value === "0") return ["on", "开机"];
  if (value === "off" || value === "1") return ["off", "关机"];
  return ["unknown", "电源状态未知"];
}
function topologyDevice(device) {
  const dpus = device.ports.filter((p) => p.role?.startsWith("dpu_"));
  const bmc = device.ports.find((p) =>
    ["host_bmc", "switch_bmc", "dpu_bmc", "pmc"].includes(p.role),
  );
  const management = device.ports.find((p) =>
    ["host", "nvos", "dpu_os"].includes(p.role),
  );
  const [powerClass, powerLabel] = topologyPower(device),
    powerTime = device.power_state_updated_at
      ? ` · ${new Date(device.power_state_updated_at).toLocaleString("zh-CN")}`
      : "";
  return `<button class="topology-device topology-${esc(device.kind)}" data-topology-device="${esc(device.id)}" type="button" draggable="${state.topologyEditing ? "true" : "false"}">
   <span class="topology-device-icon">${topologyIcon(device.kind)}</span>
   <span class="topology-device-main"><strong>${esc(device.serial || device.name || topologyKinds[device.kind] || "设备")}</strong><span class="topology-device-facts"><small><i>BMC 地址</i><b>${esc(topologyPortAddress(bmc))}</b></small><small><i>管理地址</i><b>${esc(topologyPortAddress(management))}</b></small></span></span>
   ${dpus.length ? `<span class="topology-dpu-count">${topologyIcon("dpu")} ${dpus.length} DPU</span>` : ""}
   <span class="topology-power ${powerClass}" title="${esc(powerLabel + powerTime)}" aria-label="${esc(powerLabel)}"></span>
 </button>`;
}
function topologyOrdered(rackId, zone, rows) {
  const rack = (state.topologyLayout?.racks || []).find(
      (row) => row.rack_id === rackId,
    ),
    order = rack?.zones?.[zone] || [],
    positions = new Map(order.map((id, index) => [id, index]));
  return rows
    .map((row, index) => ({ row, index }))
    .sort(
      (a, b) =>
        (positions.has(a.row.id)
          ? positions.get(a.row.id)
          : order.length + a.index) -
        (positions.has(b.row.id)
          ? positions.get(b.row.id)
          : order.length + b.index),
    )
    .map((item) => item.row);
}
function topologyRack(rackId, devices) {
  const switches = topologyOrdered(
      rackId,
      "network",
      devices.filter((d) => d.kind === "switch"),
    ),
    servers = topologyOrdered(
      rackId,
      "compute",
      devices.filter((d) => d.kind === "server"),
    ),
    power = topologyOrdered(
      rackId,
      "power",
      devices.filter((d) => d.kind === "power_shelf"),
    ),
    other = topologyOrdered(
      rackId,
      "other",
      devices.filter(
        (d) => !["switch", "server", "power_shelf"].includes(d.kind),
      ),
    );
  const section = (kind, name, rows) =>
    rows.length
      ? `<section class="rack-zone rack-zone-${kind}"><header><span>${esc(name)}</span><b>${rows.length}</b></header><div class="rack-device-grid" data-topology-rack="${esc(rackId)}" data-topology-zone="${kind}">${rows.map(topologyDevice).join("")}</div></section>`
      : "";
  return `<article class="rack-card">
  <header class="rack-header"><div class="rack-title">${topologyIcon("rack")}<div><h2>${esc(topologyRackName(rackId))}</h2><span>${rackId === "unassigned" ? "设备尚未关联 Rack" : esc(rackId)}</span></div></div><div class="rack-count"><strong>${devices.length}</strong><span>设备</span></div></header>
  <div class="rack-frame"><div class="rack-units">${section("network", "网络与交换", switches)}${section("compute", "计算托盘", servers)}${section("other", "其他设备", other)}${section("power", "供电", power)}</div></div>
 </article>`;
}
function topologyPage() {
  const devices = state.equipment?.devices || [];
  const racks = [
    ...new Set(devices.map((d) => d.rack_id || "unassigned")),
  ].sort((a, b) =>
    a === "unassigned"
      ? 1
      : b === "unassigned"
        ? -1
        : String(a).localeCompare(String(b)),
  );
  const grouped = new Map();
  for (const d of devices) {
    const key = d.rack_id || "unassigned";
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key).push(d);
  }
  const count = (kind) =>
    devices.filter((d) =>
      kind === "dpu"
        ? d.ports.some((p) => p.role?.startsWith("dpu_"))
        : d.kind === kind,
    ).length;
  const actions = state.topologyEditing
    ? button("取消", "topology-cancel") +
      button("恢复自动排列", "topology-reset") +
      button("保存布局", "topology-save", true)
    : button("刷新拓扑", "topology-refresh") +
      button("编辑布局", "topology-edit", true);
  let body = heading("机柜拓扑", "按 Rack 查看设备及管理地址。", actions);
  body += `<section class="topology-summary"><div><span>Rack</span><strong>${racks.filter((x) => x !== "unassigned").length}</strong></div><div><span>服务器</span><strong>${count("server")}</strong></div><div><span>DPU 节点</span><strong>${count("dpu")}</strong></div><div><span>交换机</span><strong>${count("switch")}</strong></div><div><span>供电框</span><strong>${count("power_shelf")}</strong></div></section>`;
  body += `<div class="topology-note ${state.topologyEditing ? "editing" : ""}"><img src="/icons/building-warehouse.svg" alt="">${state.topologyEditing ? "拖动设备调整同一分区内的顺序，服务器按从左到右、从上到下排列。" : "这是按 NICo Rack 归属生成的逻辑拓扑。当前数据没有 U 位信息，因此不推测设备的物理高度和安装位置。"}</div>`;
  body += grouped.size
    ? `<div class="rack-grid">${[...grouped].map(([id, rows]) => topologyRack(id, rows)).join("")}</div>`
    : `<div class="topology-empty"><img src="/icons/building-warehouse.svg" alt=""><strong>暂无机柜设备</strong><span>请先在设备规划中关联 Rack。</span></div>`;
  return body;
}
function topologyLayoutFromPage() {
  const racks = new Map();
  document
    .querySelectorAll(".rack-device-grid[data-topology-rack]")
    .forEach((grid) => {
      const rackId = grid.dataset.topologyRack;
      if (!racks.has(rackId))
        racks.set(rackId, {
          rack_id: rackId,
          zones: { network: [], compute: [], other: [], power: [] },
        });
      racks.get(rackId).zones[grid.dataset.topologyZone] = [
        ...grid.querySelectorAll("[data-topology-device]"),
      ].map((row) => row.dataset.topologyDevice);
    });
  return { racks: [...racks.values()] };
}
let topologyDragged = null,
  topologyDragGrid = null;
observeUI(
  "dragstart",
  "topology.js",
  (e) => {
    const device = e.target.closest("[data-topology-device]");
    if (!state.topologyEditing || !device) return e.preventDefault();
    topologyDragged = device;
    topologyDragGrid = device.closest(".rack-device-grid");
    device.classList.add("dragging");
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", device.dataset.topologyDevice);
  },
  false,
);
observeUI(
  "dragover",
  "topology.js",
  (e) => {
    const grid = e.target.closest(".rack-device-grid");
    if (!state.topologyEditing || !topologyDragged || grid !== topologyDragGrid)
      return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    const target = e.target.closest("[data-topology-device]");
    if (!target || target === topologyDragged) {
      if (!target) grid.append(topologyDragged);
      return;
    }
    const rect = target.getBoundingClientRect(),
      sameRow =
        Math.abs(topologyDragged.getBoundingClientRect().top - rect.top) <
        rect.height / 2,
      before = sameRow
        ? e.clientX < rect.left + rect.width / 2
        : e.clientY < rect.top + rect.height / 2;
    grid.insertBefore(topologyDragged, before ? target : target.nextSibling);
  },
  false,
);
observeUI(
  "drop",
  "topology.js",
  (e) => {
    if (
      state.topologyEditing &&
      e.target.closest(".rack-device-grid") === topologyDragGrid
    )
      e.preventDefault();
  },
  false,
);
observeUI(
  "dragend",
  "topology.js",
  () => {
    topologyDragged?.classList.remove("dragging");
    topologyDragged = null;
    topologyDragGrid = null;
  },
  false,
);
registerActions(
  "topology.js",
  [
    "topology-refresh",
    "topology-edit",
    "topology-cancel",
    "topology-save",
    "topology-reset",
  ],
  async (e) => {
    const action = e.target.closest('[data-live^="topology-"]');
    if (!action) return;
    try {
      if (action.dataset.live === "topology-refresh") {
        await refreshPage("topology");
        return toast("机柜拓扑已刷新。");
      }
      if (action.dataset.live === "topology-edit") {
        state.topologyEditing = true;
        return render();
      }
      if (action.dataset.live === "topology-cancel") {
        state.topologyEditing = false;
        return render();
      }
      if (action.dataset.live === "topology-save") {
        action.disabled = true;
        state.topologyLayout = await api(
          "/api/topology-layout",
          topologyLayoutFromPage(),
        );
        state.topologyEditing = false;
        render();
        return toast("机柜布局已保存。");
      }
      if (action.dataset.live === "topology-reset") {
        action.disabled = true;
        state.topologyLayout = await api("/api/topology-layout", { racks: [] });
        state.topologyEditing = false;
        render();
        return toast("已恢复自动排列。");
      }
    } catch (error) {
      action.disabled = false;
      toast(error.message);
    }
  },
);

observeUI("click", "topology-device", async (e) => {
  const device = e.target.closest("[data-topology-device]");
  if (device) {
    if (state.topologyEditing) return;
    const d = state.equipment?.devices.find(
      (x) => x.id === device.dataset.topologyDevice,
    );
    if (d?.kind === "server") return deviceDetail(d.serial);
    if (d) return equipmentDetail(d.id);
  }
});
