"use strict";
// Which switch port each server interface is plugged into, as NICo Scout heard
// it over LLDP. It shows what was observed: there is no intended cabling to
// compare against yet, so nothing here is judged right or wrong except a port
// reported by more than one interface.
state.cablingFilters = { switch: "", search: "" };
const cablingPage = deviceStatusPages.servers;
// Every observed link, joined to the console's device and its Core machine.
function cablingLinks(servers) {
  return servers.flatMap(([d, reported]) =>
    (Array.isArray(reported?.lldp) ? reported.lldp : []).map((n) => ({
      device: d,
      reported,
      neighbor: n,
      switchKey: n.switch_id || n.switch || n.switch_serial || "",
    })),
  );
}
const cablingPortKey = (link) =>
  `${link.switchKey}\u0000${link.neighbor.remote_port || ""}`;
function cablingConflicts(links) {
  const seen = {};
  for (const link of links)
    if (link.switchKey && link.neighbor.remote_port)
      (seen[cablingPortKey(link)] ||= new Set()).add(
        `${link.device.serial}\u0000${link.neighbor.mac_address || link.neighbor.local_port}`,
      );
  return new Set(
    Object.entries(seen)
      .filter(([, sources]) => sources.size > 1)
      .map(([key]) => key),
  );
}
function cablingMatches(link) {
  const f = state.cablingFilters,
    n = link.neighbor,
    d = link.device;
  return (
    (!f.switch || link.switchKey === f.switch) &&
    (!f.search ||
      [
        d.serial,
        d.name,
        n.switch,
        n.switch_id,
        n.switch_serial,
        n.remote_port,
        n.local_port,
        n.mac_address,
      ]
        .join(" ")
        .toLowerCase()
        .includes(f.search.toLowerCase()))
  );
}
function cablingRow(link, conflict) {
  const d = link.device,
    n = link.neighbor,
    rack = d.rack_id || link.reported?.rack_id;
  return `<tr><td><span class="live-code">${esc(n.remote_port || "—")}</span>${n.remote_port_type ? `<span class="live-small">${esc(n.remote_port_type)}</span>` : ""}${conflict ? badge("端口冲突", "red") + '<span class="live-small">同一端口被多个网口报告</span>' : ""}</td><td><button class="link-button" data-live="device-detail" data-serial="${esc(d.serial)}">${esc(d.name || d.serial)}</button><span class="live-small">${esc(d.serial)}</span></td><td>${esc(n.local_port || "—")}<span class="live-small live-code">${esc(n.mac_address || "")}</span></td><td>${esc(rack || "—")}</td></tr>`;
}
function cablingSwitchBlock(key, links, conflicts) {
  const first = links[0].neighbor,
    title = first.switch || first.switch_id || "未报告名称的交换机",
    detail = [
      first.switch && first.switch_id ? first.switch_id : "",
      first.switch_model,
      first.switch_serial ? `SN ${first.switch_serial}` : "",
    ].filter(Boolean);
  const rows = [...links]
    .sort((a, b) =>
      String(a.neighbor.remote_port || "").localeCompare(
        String(b.neighbor.remote_port || ""),
        undefined,
        { numeric: true },
      ),
    )
    .map((link) => cablingRow(link, conflicts.has(cablingPortKey(link))));
  return `<h3 style="margin: 20px 0 8px">${esc(title)}<span class="live-small">${esc(detail.join(" · "))}${detail.length ? " · " : ""}${links.length} 个网口</span></h3>${table(["交换机端口", "服务器", "服务器网口", "机柜"], rows)}`;
}
function cablingRender() {
  let body = heading(
    "布线",
    "按交换机查看服务器网口的实际连接，来自服务器发现时采集的 LLDP。",
    button("刷新数据", "cabling-refresh"),
  );
  if (!state.rackOperations)
    return body + '<div class="live-empty">此页面未在当前站点启用。</div>';
  const reports = state.deviceStatus,
    errors = [
      state.readErrors?.equipment,
      state.readErrors?.deviceStatus,
      ...(reports?.errors || []),
    ].filter(Boolean);
  if (errors.length)
    body += `<div class="live-error" role="alert">${esc([...new Set(errors)].join("；"))}</div>`;
  if (!state.equipment || !reports)
    return (
      body +
      (errors.length
        ? ""
        : '<div class="live-empty">正在读取设备与 LLDP 数据…</div>')
    );
  const servers = (state.equipment.devices || [])
      .filter((d) => d.kind === "server" && !d.address_only)
      .map((d) => [d, deviceStatusReported(cablingPage, d)]),
    links = cablingLinks(servers),
    conflicts = cablingConflicts(links),
    noMachine = servers.filter(([, i]) => !i).map(([d]) => d),
    noLldp = servers
      .filter(([, i]) => i && !(Array.isArray(i.lldp) && i.lldp.length))
      .map(([d]) => d),
    switches = {};
  for (const link of links) (switches[link.switchKey] ||= []).push(link);
  const names = (list) => list.map((d) => esc(d.name || d.serial)).join("、");
  const notes =
    (noLldp.length
      ? `<div class="live-note">${noLldp.length} 台服务器在 NICo 中有机器对象但没有 LLDP 数据：${names(noLldp)}。</div>`
      : "") +
    (noMachine.length
      ? `<div class="live-note">${noMachine.length} 台服务器 NICo 尚未建立设备对象，没有 LLDP 数据：${names(noMachine)}。</div>`
      : "");
  if (!links.length)
    return (
      body +
      '<div class="live-note">还没有任何服务器的 LLDP 数据。LLDP 邻居由 NICo Scout 在服务器上运行时采集（服务器发现阶段）；服务器完成发现后，这里会按交换机显示它的网口连接。</div>' +
      notes
    );
  const f = state.cablingFilters;
  if (f.switch && !switches[f.switch]) f.switch = "";
  const ports = new Set(links.map(cablingPortKey)).size;
  body += `<div class="summary-strip device-status-summary"><div><small>交换机</small><strong>${Object.keys(switches).length}</strong></div><div><small>已连接网口</small><strong>${links.length}</strong></div><div><small>没有 LLDP 数据的服务器</small><strong>${noLldp.length + noMachine.length}</strong></div><div><small>端口冲突</small><strong>${conflicts.size}</strong></div></div>`;
  if (conflicts.size)
    body += `<div class="live-note live-warning">${conflicts.size} 个交换机端口被多个服务器网口报告，已在表中标红；请核对实际接线或交换机端口配置。</div>`;
  body += `<div class="equipment-device-filters">${selectField(
    "cabling-filter-switch",
    "交换机",
    [
      ["", "全部交换机"],
      ...Object.entries(switches).map(([key, list]) => [
        key,
        list[0].neighbor.switch || key || "未报告名称",
      ]),
    ],
    f.switch,
  )}${inputField("cabling-filter-search", "搜索服务器、交换机、端口或 MAC", f.search)}</div>`;
  const blocks = Object.entries(switches)
    .map(([key, list]) => [key, list.filter(cablingMatches)])
    .filter(([, list]) => list.length)
    .map(([key, list]) => cablingSwitchBlock(key, list, conflicts));
  body += blocks.length
    ? blocks.join("")
    : '<div class="live-empty">没有符合筛选条件的连接。</div>';
  return (
    body +
    notes +
    `<p class="live-small">此页显示观测到的连接，不是与布线规划的比对。LLDP 由 NICo Scout 在服务器上采集，读取于 ${esc(when(reports.observed_at))}；${ports} 个不同的交换机端口。端口按交换机报告的原样显示，类型为 mac 时端口值是交换机端口的 MAC 地址。</p>`
  );
}
registerPage("cabling", cablingRender);
deviceStatusAddNavChild("cabling", "布线", deviceStatusReload);
registerActions("cabling.js", ["cabling-refresh"], async (e) => {
  const el = e.target.closest('[data-live="cabling-refresh"]');
  if (!el || el.disabled) return;
  await deviceStatusReload();
});
observeUI(
  "change",
  "cabling.js",
  (e) => {
    if (e.target.id === "cabling-filter-switch") {
      state.cablingFilters.switch = e.target.value;
      render();
    }
  },
  false,
);
observeUI(
  "input",
  "cabling.js",
  (e) => {
    if (e.target.id === "cabling-filter-search") {
      const position = e.target.selectionStart;
      state.cablingFilters.search = e.target.value;
      render();
      $("#cabling-filter-search").focus();
      $("#cabling-filter-search").setSelectionRange(position, position);
    }
  },
  false,
);
