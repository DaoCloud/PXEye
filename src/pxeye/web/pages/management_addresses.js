"use strict";
const addressRoles = {
  host_bmc: "主机 BMC",
  host: "主机管理 / 引导",
  dpu_bmc: "DPU BMC",
  dpu_os: "DPU OS",
  switch_bmc: "交换机 BMC",
  pmc: "供电框 PMC",
  nvos: "NVOS",
  unknown: "未知接口",
};
const addressRows = () =>
  state.equipment?.management_addresses?.interfaces || [];
const addressAttr = (id) => `data-interface-id="${esc(id)}"`;
function addressScope(deviceIds) {
  return addressRows().filter(
    (a) => !deviceIds?.length || deviceIds.includes(a.device_id),
  );
}
const addressNetworkPolicy = (value) =>
  ({ DYNAMIC: "动态分配", RESERVED: "仅预留", UNKNOWN: "策略未知" })[value] ||
  value ||
  "策略未知";
function addressTable(rows) {
  return table(
    [
      "设备 / SN",
      "接口 / MAC",
      "当前分配 → 规划 IP",
      "子网方案 / 范围",
      "操作",
    ],
    rows.map(
      (a) =>
        `<tr><td>${esc(a.address_name || a.serial || "待识别")}<span class="live-small">${esc(equipmentKinds[a.address_kind || a.kind] || "其他设备")}</span></td><td>${esc(a.role_label)}<span class="live-small">${esc(a.mac_address)}</span></td><td>${esc(a.addresses.join(", ") || "未分配")}<span class="live-small">${esc(a.target_ip || "未规划")}</span></td><td>${esc(a.network_name || "未匹配子网")}<span class="live-small">${esc(addressNetworkPolicy(a.network_allocation_strategy))}</span><span class="live-small live-code">${esc((a.network_prefixes || []).join(", ") || "范围未提供")}</span></td><td>${button("规划地址", "address-edit", false, addressAttr(a.interface_id))}</td></tr>`,
    ),
  );
}

function addressDialog(deviceIds) {
  const rows = addressScope(deviceIds);
  state.wizard = { resource: "address-list", deviceIds };
  modal(
    "管理地址",
    "按接口维护地址规划",
    addressTable(rows) + eqError(),
    button("关闭", "close"),
  );
}
function addressEdit(iid) {
  const row = addressRows().find((a) => a.interface_id === iid);
  if (!row) throw Error("接口已变化，请刷新。");
  const device = state.resources?.devices.find((d) => d.serial === row.serial);
  const networkId =
    device?.intent?.network_bindings?.[row.mac_address?.toLowerCase()];
  const network = state.networks?.networks.find((n) => n.id === networkId);
  const subnet = networkId
    ? network?.prefixes.map((p) => p.prefix).join(", ") || "待配置"
    : (row.network_prefixes || []).join(", ") || "待配置";
  state.wizard = { resource: "address-edit", row };
  modal(
    "规划管理地址",
    row.serial || row.mac_address,
    `<div class="live-editor-grid">${eqText("address-name", "设备名称", row.address_name || "")}${eqText("address-serial", "设备 SN", row.serial || "", row.serial ? "readonly" : "")}${selectField(
      "eq-address-kind",
      "设备类型",
      Object.entries(equipmentKinds)
        .filter(([k]) => k !== "unknown")
        .concat([["unknown", "待识别"]]),
      row.address_kind || row.kind,
    )}${selectField("eq-address-role", "接口角色", Object.entries(addressRoles), row.role)}${eqText("address-mac", "接口 MAC", row.mac_address, "readonly")}${eqText("address-network", "管理子网", subnet, "readonly")}${eqText("address-current", "当前 IPv4", row.addresses.join(", "), "readonly")}${eqText("address-target", "规划 IPv4", row.target_ip || row.addresses[0] || "")}${eqText("address-user", "此接口 BMC / PMC 用户名")}${eqText("address-password", row.credential_present ? "密码（留空保留）" : "此接口 BMC / PMC 密码", "", 'type="password" autocomplete="new-password"')}</div><div class="live-note">保存地址规划。BMC / PMC 地址在设备管理执行更新；LOM 地址由安装任务应用。</div>` +
      eqError(),
    button("取消", "close") + button("保存规划", "address-save", true),
  );
}
async function addressSave() {
  const row = state.wizard.row,
    r = await api("/api/equipment/address-save", {
      interface_id: row.interface_id,
      revision: row.address_revision || "",
      mac_address: row.mac_address,
      target_ip: $("#eq-address-target").value.trim(),
      name: $("#eq-address-name").value.trim(),
      serial: $("#eq-address-serial").value.trim(),
      kind: $("#eq-address-kind").value,
      role: $("#eq-address-role").value,
      username: $("#eq-address-user").value,
      password: $("#eq-address-password").value,
    });
  close();
  await equipmentReload();
  toast(r.detail);
}
registerActions(
  "management_addresses.js",
  ["address-device", "address-endpoint", "address-edit", "address-save"],
  async (e) => {
    const b = e.target.closest('[data-live^="address-"]');
    if (!b || b.disabled) return;
    try {
      switch (b.dataset.live) {
        case "address-device":
          return addressDialog([b.dataset.id]);
        case "address-endpoint":
          return addressEdit(b.dataset.interfaceId);
        case "address-edit":
          return addressEdit(b.dataset.interfaceId);
        case "address-save":
          return await busy(addressSave);
      }
    } catch (error) {
      const target = $("#resource-error");
      if (target) target.textContent = error.message;
      else toast(error.message);
    }
  },
);
