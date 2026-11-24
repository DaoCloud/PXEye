"use strict";
/* 示例数据与模拟引擎。全部为编写的占位数据：序列号 DEMO-…，MAC 02:…，地址取自 192.0.2.0/24、198.51.100.0/24 与 203.0.113.0/24。
   真实实现中，这些数据来自 NICo Core（读取、设备声明、机柜状态机与单设备操作）和 NICo REST / Flow（机柜级电源与固件任务）；
   到货清单、凭据的暂存和设备身份读取是平台自己的数据。 */

/* 机柜规格由机柜拓扑和机柜厂商推导；规格本身和它的成员数量是站点配置。 */
const TOPOLOGY = "gb200_nvl72r1_c2g4", RACK_VENDOR = "Wiwynn";
const PROFILE = "GB200_NVL72R1_C2G4_WIWYNN";
const PROFILE_NEED = { compute: 18, switch: 9, power_shelf: 8 };
const TYPE_LABEL = { compute: "计算托盘", switch: "交换机", power_shelf: "供电框" };
/* 设备是基础对象，机柜是叠在上面的一层：服务器可以不属于任何机柜。机柜里的服务器就是计算托盘。 */
const typeLabel = (t) => (t.type === "compute" && !t.rack ? "服务器" : TYPE_LABEL[t.type]);
const placeText = (t) => (t.rack ? `${t.rack} / 槽位 ${String(t.slot).padStart(2, "0")}` : "未分配机柜");
/* 新机柜上线有两条线：bringup_task 是人提交的上线任务（上电并放行计算托盘的接管）；bringup 是交换机就绪后 NICo 的机柜状态机自己走的维护阶段。
   其余是 Flow 任务的步骤：会中断业务的任务先等受影响的主机就绪，再按站点规则展开。 */
const STAGES = {
  bringup_task: ["供电框上电", "计算托盘上电并放行接管", "计算托盘固件", "交换机上电", "核对交换机固件", "计算托盘重启"],
  bringup: ["固件升级", "NVOS 更新", "上电顺序", "配置 NMX-C 集群", "机柜校验"],
  power_off: ["等待主机就绪", "计算托盘下电", "交换机下电", "供电框下电"],
  power_on: ["供电框上电", "交换机上电", "计算托盘上电"],
  power_cycle: ["等待主机就绪", "计算托盘下电", "交换机下电", "供电框下电", "供电框上电", "交换机上电", "计算托盘上电"],
  force_off: ["全部设备强制下电"],
  firmware: ["等待主机就绪", "计算托盘固件", "交换机固件"],
  tray_power: ["执行电源动作"],
  tray_firmware: ["更新组件固件"],
};
/* 机柜状态机各阶段对应的状态原文。 */
const BRINGUP_STATE = { 固件升级: "Maintenance(FirmwareUpgrade)", "NVOS 更新": "Maintenance(NVOSUpdate)", 上电顺序: "Maintenance(PowerSequence)", "配置 NMX-C 集群": "Maintenance(ConfigureNmxCluster)", 机柜校验: "Validating" };
/* 固件基线：只列 NICo 能读回并比对的部件，加上只能下发、不能读回的 NVOS 目标版本。 */
const BASELINES = [
  { id: "GB200-NVL72 2026.11", profile: PROFILE, released: "2026-11-10", note: "当前推荐", parts: { "计算托盘 BMC": "25.11.2", "计算托盘 UEFI": "2.19.0", "交换机 BMC": "25.11.1" }, nvos: "25.02.4012" },
  { id: "GB200-NVL72 2026.10", profile: PROFILE, released: "2026-10-08", note: "上一版", parts: { "计算托盘 BMC": "25.10.4", "计算托盘 UEFI": "2.18.1", "交换机 BMC": "25.10.2" }, nvos: "25.02.3004" },
];
/* 网络用途：每类设备的每种接口必须落在一个已规划的子网里。需要的地址数按接口算，不按设备算。 */
const NET_ROLES = [
  { id: "oob", label: "带外管理", devices: "计算托盘 BMC、交换机 BMC、供电框 PMC、DPU BMC", kind: "Underlay", perRack: 35 + 36 },
  { id: "nvos", label: "交换机系统管理", devices: "交换机 NVOS 管理口", kind: "Underlay", perRack: 18 },
  { id: "host", label: "主机管理", devices: "计算托盘主机网口：引导、装机与系统管理", kind: "HostInband", perRack: 18 },
];
const pad2 = (n) => String(n).padStart(2, "0");
const hex2 = (n) => n.toString(16).padStart(2, "0");
const slotType = (s) => (s <= 4 || s >= 32 ? "power_shelf" : s >= 15 && s <= 23 ? "switch" : "compute");
const nowText = () => "2026-11-24 " + new Date().toTimeString().slice(0, 5);

/* 清单里的一行，依次经过三个标记：matched 读到身份并对上清单；declared 已纳管（声明写进 NICo，计算托盘带暂停标记，不上电）；
   state 有值表示上线后 NICo 已接管并建立设备对象。MAC 和地址在机柜接电后从 DHCP 得到。 */
function makeTray(rackId, n, slot, discovered, baseline) {
  const type = slotType(slot), key = { compute: "C", switch: "S", power_shelf: "P" }[type];
  const serial = `DEMO-${key}-${rackId.slice(-3)}-${pad2(slot)}`;
  const tray = {
    id: `${rackId}/${pad2(slot)}`, rack: rackId, n, slot, type, serial, matched: discovered, declared: discovered, seenSlot: discovered && type !== "power_shelf" ? slot : 0,
    model: discovered ? { compute: "GB200 Compute Tray", switch: "NVLink Switch Tray", power_shelf: "Power Shelf" }[type] : "",
    bmcMac: "", bmcIp: "", addrMode: type === "compute" ? "保留" : "动态分配",
    state: discovered ? "Ready" : "", reason: "", health: discovered ? "ok" : "none", alerts: [], power: discovered ? "On" : "",
    baseline: discovered ? baseline : "", maintenance: "", quarantine: "", instance: "", lastSeen: discovered ? "2026-11-24 08:00" : "",
    history: discovered ? [["2026-11-02 09:41", type === "compute" ? "HostInit/Discovered" : "Initializing"], ["2026-11-02 10:30", "Ready"]] : [],
  };
  if (type === "compute") Object.assign(tray, { cfg: { host: "", os: "", disk: "", mip: "" }, arch: "aarch64", disks: ["nvme0n1 · 480 GB", "nvme1n1 · 1.92 TB"], hostMac: "", hostIp: "", nics: [], hardware: { CPU: "2 × Grace 72C", GPU: "4 × GB200", 内存: "960 GiB", 系统盘: "1 × 480 GB NVMe", 数据盘: "1 × 1.92 TB NVMe", 网卡: "2 × BlueField-3（网卡模式）" }, sku: "gb200-compute-c2g4",
    lldp: [{ port: "eno1", sw: "mgmt-leaf-" + pad2(n), remote: "swp" + slot }, { port: "p0", sw: "spine-" + pad2(n) + "a", remote: "Ethernet" + slot }] });
  if (type === "switch") Object.assign(tray, { nvos: [], primary: slot === 15, fabricManager: discovered ? "OK" : "" });
  if (discovered) assignAddresses(tray);
  return tray;
}
/* 设备通电后从 DHCP 得到的 MAC 和地址。 */
function assignAddresses(t) {
  const n = t.n, s = t.slot, base = (n - 1) * 80, host = (n - 1) * 40 + s + 10;
  t.bmcMac = `02:00:${pad2(n)}:00:00:${hex2(s)}`; t.bmcIp = `192.0.2.${base + s + 10}`;
  if (t.type === "compute") {
    const c = s <= 14 ? s - 5 : s - 24 + 10;
    t.hostMac = `02:10:${pad2(n)}:00:00:${hex2(s)}`; t.hostIp = `198.51.100.${host}`;
    /* 管理地址是设备规划时定下的，和这个网口的 MAC 对应；NICo 按它分配。 */
    if (!t.cfg.mip) t.cfg.mip = t.hostIp;
    t.nics = [1, 2].map((i) => ({ name: "BlueField-3 · " + i, serial: `DEMO-D-${t.rack.slice(-3)}-${pad2(s)}${i}`, part: "900-9D3B6-00CV-AA0", fw: "32.45.1020", policy: "nic", mode: "Nic", mac: `02:3${i}:${pad2(n)}:00:00:${hex2(s)}`, ip: `192.0.2.${base + 45 + c * 2 + i}` }));
  }
  if (t.type === "switch") t.nvos = [0, 1].map((i) => ({ mac: `02:2${i}:${pad2(n)}:00:00:${hex2(s)}`, ip: `203.0.113.${(n - 1) * 40 + (s - 15) * 2 + i + 11}`, primary: i === 0, name: "eth" + i }));
}
/* 不属于机柜的服务器：没有槽位，没有上线这一步。纳管后不上电；第一次装系统时由 NICo 上电接管。
   stage：ready 已接管；held 已纳管、还没有接管；matched 已匹配清单、还没有纳管。 */
function makeServer(i, stage) {
  const ready = stage === "ready";
  return { id: "SRV/" + pad2(i), rack: "", n: 0, slot: 0, type: "compute", arch: "x86_64", serial: "DEMO-H-00" + pad2(i), matched: true, declared: stage !== "matched", seenSlot: 0, model: "GPU Server 8G",
    bmcMac: `02:00:0f:00:00:${hex2(i)}`, bmcIp: `192.0.2.${241 + i}`, addrMode: "保留", state: ready ? "Ready" : "", reason: "", health: ready ? "ok" : "none", alerts: [], power: ready ? "On" : "",
    baseline: "", maintenance: "", quarantine: "", instance: "", lastSeen: "2026-11-24 08:00", history: ready ? [["2026-11-18 10:02", "HostInit/Discovered"], ["2026-11-18 10:40", "Ready"]] : [],
    hostMac: `02:10:0f:00:00:${hex2(i)}`, hostIp: ready ? `198.51.100.${200 + i}` : "", cfg: { host: "", os: "", disk: "", mip: `198.51.100.${200 + i}` }, nics: [], sku: "gpu-server-8g", disks: ["nvme0n1 · 480 GB", "nvme1n1 · 3.84 TB", "nvme2n1 · 3.84 TB"],
    hardware: { CPU: "2 × 64C x86_64", GPU: "8 × GPU", 内存: "1 TiB", 系统盘: "1 × 480 GB NVMe", 数据盘: "2 × 3.84 TB NVMe", 网卡: "2 × 25GbE" }, lldp: [{ port: "eno1", sw: "mgmt-leaf-09", remote: "swp" + i }] };
}
/* 服务器被 NICo 接管之后的样子。 */
function takeOverServer(t) { Object.assign(t, { declared: true, state: "Ready", health: "ok", power: "On", hostIp: t.hostIp || t.cfg.mip || `198.51.100.${200 + +t.id.slice(-2)}`, lastSeen: nowText(), history: [[nowText(), "HostInit/Discovered"], [nowText(), "Ready"]] }); }
function makeRack(id, n, discovered, baseline, location) {
  const trays = []; for (let s = 1; s <= 35; s++) trays.push(makeTray(id, n, s, discovered, baseline));
  /* state 为空表示 NICo 里还没有这个机柜的对象：机柜只在清单里。 */
  return { id, n, domain: "NVL-" + id.slice(-3), topology: TOPOLOGY, vendor: RACK_VENDOR, profile: PROFILE, location, admit: discovered, admitAt: discovered ? "2026-11-02 09:30" : "", up: discovered, state: discovered ? "Ready" : "", stateSince: discovered ? "2026-11-02 15:02" : "", reason: "",
    baseline: discovered ? baseline : "", trays, tasks: [], task: null, bring: null,
    history: discovered ? [["2026-11-02 09:40", "Discovering"], ["2026-11-02 11:05", "Maintenance(FirmwareUpgrade)"], ["2026-11-02 11:06", "Maintenance(NVOSUpdate)"], ["2026-11-02 11:07", "Maintenance(PowerSequence)"], ["2026-11-02 11:20", "Maintenance(ConfigureNmxCluster)"], ["2026-11-02 14:31", "Validating"], ["2026-11-02 15:02", "Ready"]] : [] };
}
/* 一个 NVL72 机柜就是一个 NVLink 域。域有两个编号：机柜组编号（清单里的）和 NMX-C 回报的域编号。 */
const makeDomain = (r, formed) => ({ id: r.domain, rack: r.id, topology: r.topology, uuid: formed ? `7f3a${pad2(r.n)}c2-0000-4000-8000-0000000000${pad2(r.n)}` : "", nmxc: formed ? "ok" : "", health: formed ? "ok" : "none", partitions: [] });

function freshState() {
  const a01 = makeRack("RACK-A01", 1, true, BASELINES[0].id, "机房 1 · A 列 01");
  const a02 = makeRack("RACK-A02", 2, true, BASELINES[1].id, "机房 1 · A 列 02");
  const done = (id, kind, label, target, stages, at, reason) => ({ id, kind, label, target, stages: stages.map((n) => ({ n, s: "done" })), status: "已完成", by: "ops-01", at, end: at.slice(0, 11) + "13:48", reason });
  a01.tasks = [done("task-0039", "firmware", "固件更新 → " + BASELINES[0].id, "RACK-A01", STAGES.firmware, "2026-11-12 11:05", "升级到 11 月基线")];
  a02.tasks = [done("task-0041", "power", "机柜上电", "RACK-A02", STAGES.power_on, "2026-11-03 10:12", "计划停电后恢复")];
  const instances = [];
  const OS_ARM = "Ubuntu 24.04 ARM64 · 标准系统盘", OS_X86 = "Ubuntu 24.04 x86_64 · 标准系统盘";
  const installed = (t, host, os, at) => { t.state = "Assigned/Ready"; t.instance = "inst-" + host; instances.push({ id: t.instance, tray: t.id, rack: t.rack, host, os, state: "Ready", ip: t.hostIp, created: at }); return { tray: t.id, host, os, disk: "", s: "done" }; };
  const batchA01 = { id: "batch-006", at: "2026-11-04 16:20", by: "ops-01", why: "训练集群 A 装机", items: a01.trays.filter((t) => t.type === "compute").map((t, i) => installed(t, "train-a01-" + pad2(i + 1), OS_ARM, "2026-11-04 16:20")) };
  /* 不属于机柜的服务器：一台已装系统，一台已接管待装，一台已纳管还没有接管，一台刚匹配上清单。 */
  const pool = { id: "", pool: true, state: "", trays: [makeServer(1, "ready"), makeServer(2, "ready"), makeServer(3, "held"), makeServer(4, "matched")], tasks: [], task: null };
  const batchSrv = { id: "batch-007", at: "2026-11-18 11:05", by: "ops-02", why: "推理服务器装机", items: [installed(pool.trays[0], "infer-01", OS_X86, "2026-11-18 11:05")] };
  const sw = a01.trays.find((t) => t.slot === 18); sw.health = "warn"; sw.fabricManager = "UNKNOWN"; sw.alerts = [{ id: "SwitchUnreachable", target: sw.nvos[0].ip, msg: "NVOS 管理口不可达，Fabric Manager 状态读不到", since: "2026-11-21 03:14", cls: [] }];
  const mt = a02.trays.find((t) => t.slot === 27); mt.maintenance = "CHG-1042 更换风扇"; mt.health = "warn";
  mt.alerts = [{ id: "BmcSensor", target: "fan3", msg: "风扇 3 转速低于阈值", since: "2026-11-22 21:40", cls: [] }, { id: "Maintenance", target: "", msg: "维护标记：CHG-1042 更换风扇", since: "2026-11-22 21:55", cls: ["PreventAllocations"] }];
  /* 一台计算托盘换过盘：两块 NVMe 一样大，按方案的规则解析不出唯一的系统盘。用来演示安装条件检查不通过、逐台指定系统盘后通过。 */
  const odd = a02.trays.find((t) => t.slot === 29); odd.disks = ["nvme0n1 · 1.92 TB", "nvme1n1 · 1.92 TB"]; odd.hardware = { ...odd.hardware, 系统盘: "2 × 1.92 TB NVMe（换过盘）" }; delete odd.hardware.数据盘;
  /* 另一台的 BMC 第一次检查时超时：用来演示安装条件检查发现阻断项、重新检查后通过。 */
  a02.trays.find((t) => t.slot === 30).checkFlaky = 1;
  const d01 = makeDomain(a01, true), d02 = makeDomain(a02, true);
  d01.partitions = [{ id: "lp-train-a", name: "train-a", state: "Ready", physical: "nmx-part-0001", created: "2026-11-04 16:18" }];
  return {
    role: "操作", rms: true, flow: true, leak: false, taskSeq: 41, view: {}, guide: 1, currentSystems: {},
    racks: [a01, a02], pool, instances, installs: [batchSrv, batchA01], domains: [d01, d02],
    inventory: [{ v: 3, at: "2026-11-03 09:30", by: "ops-01", file: "arrival-2026-11-A.csv", note: "新增 RACK-A02（35 台）", why: "到货批次 2026-11-A" }, { v: 2, at: "2026-11-02 09:10", by: "ops-01", file: "arrival-2026-11-A.csv", note: "新增 RACK-A01（35 台）", why: "到货批次 2026-11-A" }],
    audit: [
      { at: "2026-11-22 21:55", by: "ops-02", obj: "RACK-A02 / 槽位 27", act: "设置维护标记", why: "CHG-1042 更换风扇", task: "—", res: "读回一致" },
      { at: "2026-11-12 11:05", by: "ops-01", obj: "RACK-A01", act: "固件更新 → " + BASELINES[0].id, why: "升级到 11 月基线", task: "task-0039", res: "成功，版本与基线相同" },
      { at: "2026-11-18 11:05", by: "ops-02", obj: "安装批次 batch-007", act: "新建安装任务（1 台）", why: "推理服务器装机", task: "—", res: "验收通过 1/1" },
      { at: "2026-11-04 16:20", by: "ops-01", obj: "安装批次 batch-006", act: "新建安装任务（18 台）", why: "训练集群 A 装机", task: "—", res: "验收通过 18/18" },
      { at: "2026-11-03 10:12", by: "ops-01", obj: "RACK-A02", act: "机柜上电", why: "计划停电后恢复", task: "task-0041", res: "成功，成员全部开机" },
    ],
    /* 子网：NICo 的网络段。capacity 为可分配地址数（去掉保留地址）。vlan 只是平台记的备注，NICo 不存。 */
    subnets: [
      { id: "net-oob", name: "oob-mgmt", role: "oob", kind: "Underlay", cidr: "192.0.2.0/24", gateway: "192.0.2.1", vlan: "401", pool: ["192.0.2.11", "192.0.2.250"], reserved: 10, capacity: 240, mtu: 1500, state: "READY" },
      { id: "net-nvos", name: "nvos-mgmt", role: "nvos", kind: "Underlay", cidr: "203.0.113.0/24", gateway: "203.0.113.1", vlan: "431", pool: ["203.0.113.11", "203.0.113.250"], reserved: 10, capacity: 240, mtu: 1500, state: "READY" },
      { id: "net-host", name: "host-inband", role: "host", kind: "HostInband", cidr: "198.51.100.0/24", gateway: "198.51.100.1", vlan: "301", pool: ["198.51.100.11", "198.51.100.250"], reserved: 10, capacity: 240, mtu: 9000, state: "READY" },
    ],
    /* 拿到了地址、但还没有归属的端点：认证失败、读不到身份，或读到的序列号不在清单里。 */
    endpoints: [{ id: "ep-0007", mac: "02:00:ee:00:00:07", ip: "192.0.2.247", subnet: "net-oob", seen: "2026-11-24 07:41", problem: "unlisted", type: "compute", serial: "DEMO-X-0007", model: "GB200 Compute Tray" }],
    osTemplates: [{ id: "Ubuntu 24.04 ARM64 · 标准系统盘", arch: "aarch64", disk: "容量最小的 NVMe，GPT / UEFI，ext4", login: "ubuntu + 公钥", state: "已发布", used: 18 }, { id: "Ubuntu 24.04 x86_64 · 标准系统盘", arch: "x86_64", disk: "容量最小的 NVMe，GPT / UEFI，ext4", login: "ubuntu + 公钥", state: "已发布", used: 1 }, { id: "Ubuntu 24.04 ARM64 · 大容量根分区", arch: "aarch64", disk: "容量最大的 NVMe，GPT / UEFI，XFS", login: "ubuntu + 公钥", state: "草稿", used: 0 }],
  };
}

let S = freshState();
const DB = {
  /* 不属于机柜的服务器放在 S.pool 里：它不是机柜，只是让“同一时间一个任务”这类按机柜的规则有地方落。 */
  rack: (id) => (id === "" ? S.pool : S.racks.find((r) => r.id === id)),
  groups: () => [...S.racks, S.pool],
  tray: (id) => DB.trays().find((t) => t.id === id),
  trays: () => DB.groups().flatMap((r) => r.trays),
  servers: () => S.pool.trays,
  /* 这台设备有没有还没装完的安装任务。 */
  installing: (t) => S.installs.some((b) => b.items.some((i) => i.tray === t.id && i.s !== "done")),
  domain: (id) => S.domains.find((d) => d.id === id),
  baseline: (id) => BASELINES.find((b) => b.id === id),
  busy: (r) => !!(r.task && r.task.status === "执行中"),
  tasks: () => DB.groups().flatMap((r) => r.tasks).sort((a, b) => (a.id < b.id ? 1 : -1)),
  rackInstances: (id) => S.instances.filter((i) => i.rack === id),
  subnet: (id) => S.subnets.find((n) => n.id === id),
  roleSubnets: (role) => S.subnets.filter((n) => n.role === role),
  ready: (r, type) => r.trays.filter((t) => (!type || t.type === type) && /Ready$/.test(t.state)).length,
  /* 清单与实物的差异：清单里有、但还没有任何设备读出这个序列号的行。只在机柜已有设备出现之后才算差异。 */
  absent: (r) => (r.trays.some((t) => t.matched) ? r.trays.filter((t) => !t.matched) : []),
  /* 槽位不一致：清单里写的槽位，和 NICo 接管设备后从硬件后端读到的槽位不同。上线之后才有。 */
  misplaced: (r) => r.trays.filter((t) => t.seenSlot && t.seenSlot !== t.slot),
  /* 机柜的电源：机柜对象没有电源状态，只能数成员。 */
  power(r) { const known = r.trays.filter((t) => t.state), on = known.filter((t) => t.power === "On").length; return { known: known.length, on, text: !known.length ? "未报告" : on === known.length ? "全部开机" : on === 0 ? "全部关机" : `${on} / ${known.length} 开机` }; },
  /* 设备的各个接口。地址分配和规划检查都按接口算。 */
  interfaces() {
    const out = [];
    DB.trays().filter((t) => t.bmcIp).forEach((t) => {
      const add = (role, iface, mac, ip, mode) => out.push({ tray: t, role, iface, mac, ip, mode, subnet: (DB.roleSubnets(role)[0] || {}).id || "" });
      add("oob", "BMC", t.bmcMac, t.bmcIp, t.addrMode);
      if (t.type === "switch") t.nvos.forEach((p) => add("nvos", `NVOS 管理口 ${p.name}${p.primary ? "（主）" : ""}`, p.mac, p.ip, "动态分配"));
      if (t.type === "compute") {
        if (t.hostIp) add("host", "主机管理口", t.hostMac, t.hostIp, "动态分配");
        t.nics.forEach((c) => add("oob", "DPU BMC " + c.name.slice(-1), c.mac, c.ip, "动态分配"));
      }
    });
    return out;
  },
  subnetUsed: (id) => DB.interfaces().filter((i) => i.subnet === id).length + S.endpoints.filter((e) => e.subnet === id).length,
  /* 规划检查：每种用途都有子网，且可分配地址不少于清单里全部机柜需要的数量。extra 是导入前预估要新增的机柜数。 */
  planChecks(extraRacks = 0) {
    return NET_ROLES.map((r) => { const nets = DB.roleSubnets(r.id), capacity = nets.reduce((n, x) => n + x.capacity, 0), need = r.perRack * (S.racks.length + extraRacks);
      return { role: r, nets, capacity, need, ok: nets.length > 0 && capacity >= need, reason: !nets.length ? "缺少子网" : capacity < need ? "地址不足" : "" }; });
  },
  planOk: (extraRacks) => DB.planChecks(extraRacks).every((c) => c.ok),
  /* 当前告警。编号和分类用 NICo 的原文：阻止分配只对它所在的那台主机生效；RackLeak 分类才是整柜泄漏。 */
  alerts() {
    const out = [];
    S.racks.forEach((r) => {
      const miss = {}; DB.absent(r).forEach((t) => (miss[t.type] = (miss[t.type] || 0) + 1));
      if (Object.keys(miss).length) out.push({ scope: "机柜", obj: r.id, rack: r.id, tray: "", id: "MissingRackComponent", target: "", msg: "成员数量少于机柜规格：" + Object.entries(miss).map(([k, v]) => `${TYPE_LABEL[k]}少 ${v} 台`).join("，"), since: r.stateSince || nowText(), cls: [] });
      if (S.leak === r.id) out.push({ scope: "机柜", obj: r.id, rack: r.id, tray: "", id: "RackLeakDetect", target: "", msg: "机柜级泄漏。NICo 已自动对整柜强制下电", since: S.leakAt, cls: ["RackLeak", "PreventAllocations"] });
      r.trays.forEach((t) => t.alerts.forEach((a) => out.push({ scope: TYPE_LABEL[t.type], obj: `${r.id} / 槽位 ${pad2(t.slot)}`, rack: r.id, tray: t.id, id: a.id, target: a.target || "", msg: a.msg, since: a.since, cls: a.cls || [] })));
    });
    S.pool.trays.forEach((t) => t.alerts.forEach((a) => out.push({ scope: "服务器", obj: t.serial, rack: "", tray: t.id, id: a.id, target: a.target || "", msg: a.msg, since: a.since, cls: a.cls || [] })));
    return out;
  },
  /* 整柜泄漏：只认 RackLeak 分类。一台设备的维护标记或告警不代表整柜有问题。 */
  leak: (rackId) => S.leak === rackId,
  blocked: (t) => t.alerts.some((a) => (a.cls || []).includes("PreventAllocations")),
  /* 纳管后、上线前：声明已写入，NICo 还没有建立设备对象。 */
  held: (t) => t.declared && !t.state,
  /* “需要处理”只用 NICo 的信号：状态机处理失败、存在健康告警。 */
  needsAttention: (t) => !!t.state && (t.health === "bad" || t.health === "warn" || /Failed|Error|失败/.test(t.state)),
  /* 固件偏差：设备实际所在的基线不是当前推荐基线。NICo 只能判断版本是否相同，不能判断高低。 */
  drift: (t) => !!t.baseline && t.baseline !== BASELINES[0].id,
};

function addAudit(obj, act, why, task, res) { S.audit.unshift({ at: nowText(), by: "ops-01", obj, act, why: why || "—", task: task || "—", res }); return S.audit[0]; }

/* 模拟 Flow 任务：按规则的步骤推进。真实实现中任务由 Flow 持久化，页面只轮询任务状态。 */
function startTask(rackId, kind, label, stages, opts = {}) {
  const r = DB.rack(rackId);
  const t = { id: "task-" + String(++S.taskSeq).padStart(4, "0"), rack: rackId, kind, label, target: opts.target || rackId, stages: stages.map((n) => ({ n, s: "wait" })), status: "执行中", by: opts.by || "ops-01", at: nowText(), end: "", reason: opts.why || "" };
  r.task = t; r.tasks.unshift(t);
  const rec = addAudit(t.target, label, opts.why, t.id, "已提交"); rec.by = t.by;
  t.timer = setInterval(() => {
    const cur = t.stages.find((s) => s.s === "run"); if (cur) cur.s = "done";
    const next = t.stages.find((s) => s.s === "wait");
    if (next) { next.s = "run"; if (opts.onStage) opts.onStage(next.n); }
    else { clearInterval(t.timer); t.status = "已完成"; t.end = nowText(); if (opts.onDone) opts.onDone(); rec.res = "成功，" + (opts.readback ? opts.readback() : "读回 " + r.state); if (window.toast) toast(`${t.target}：${label} 完成`); }
    if (window.render) render();
  }, 1200);
  return t;
}
/* 取消是尽力而为：还没开始的步骤不再执行，已经交给硬件后端的动作不会停。 */
function cancelTask(rackId) {
  const r = DB.rack(rackId), t = r.task; if (!t || t.status !== "执行中") return;
  clearInterval(t.timer); t.status = "已终止"; t.end = nowText(); const cur = t.stages.find((s) => s.s === "run"); if (cur) cur.s = "fail";
  addAudit(t.target, "取消任务", "操作人取消", t.id, "已请求终止；已交给硬件后端的动作不会停止");
}
function setRackState(r, st, reason = "") { r.state = st; r.reason = reason; r.stateSince = nowText(); r.history.push([nowText(), st]); }

/* 模拟 Core 的机柜状态机：就绪的交换机数达到机柜规格要求后自动进入上线，逐个阶段推进；任何阶段失败进入 Error，并停在那里。 */
function coreBringup(r) {
  if (r.bring && r.bring.timer) clearInterval(r.bring.timer);
  if (DB.ready(r, "switch") < PROFILE_NEED.switch) return false;
  r.bring = { stages: STAGES.bringup.map((n) => ({ n, s: "wait" })), timer: 0 };
  r.bring.timer = setInterval(() => {
    const b = r.bring, cur = b.stages.find((s) => s.s === "run"); if (cur) cur.s = "done";
    const next = b.stages.find((s) => s.s === "wait");
    if (next && !S.rms && ["固件升级", "NVOS 更新", "上电顺序", "配置 NMX-C 集群"].includes(next.n)) { next.s = "fail"; clearInterval(b.timer); b.timer = 0; setRackState(r, "Error", "RMS 不可达：" + next.n + "无法执行"); }
    else if (next) { next.s = "run"; if (r.state !== BRINGUP_STATE[next.n]) setRackState(r, BRINGUP_STATE[next.n]); }
    else { clearInterval(b.timer); b.timer = 0; setRackState(r, "Ready"); r.baseline = BASELINES[0].id; r.trays.forEach((t) => t.state && (t.baseline = BASELINES[0].id)); const d = DB.domain(r.domain); Object.assign(d, makeDomain(r, true)); S.guide = Math.max(S.guide, 6); if (window.toast) toast(`${r.id}：NICo 已完成上线，机柜就绪`); }
    if (window.render) render();
  }, 1500);
  return true;
}

/* 模拟新机柜的三段：
   1. 机柜接电（simulateDiscovery）：BMC 拿到地址，平台读取身份并按序列号匹配清单。只读，不写 NICo。
      留下三种需要人处理的情况：一台交换机认证失败、一台计算托盘换了序列号、一个供电框没有申请地址。另有两台计算托盘插反了槽位，这要到上线之后才看得出来。
   2. 确认纳管（admitRack）：平台把声明写进 NICo。NICo 登录 BMC、轮换口令；计算托盘带暂停标记，不上电、不接管。
   3. 开始上线（bringUpRack）：人提交上线任务，按顺序上电并放行计算托盘；交换机就绪后 NICo 自动做机柜维护。 */
function matchTray(t) { assignAddresses(t); Object.assign(t, { matched: true, lastSeen: nowText(), model: { compute: "GB200 Compute Tray", switch: "NVLink Switch Tray", power_shelf: "Power Shelf" }[t.type] }); }
function declareTray(t) { if (!t.matched) matchTray(t); t.declared = true; }
function takeOver(t) {
  declareTray(t);
  /* 实测槽位是 NICo 接管设备之后向硬件后端查到的：计算托盘和交换机有，供电框没有。 */
  if (t.type !== "power_shelf") t.seenSlot = t.simSlot || t.slot;
  Object.assign(t, { state: "Ready", health: "ok", power: "On", baseline: BASELINES[1].id, lastSeen: nowText(), history: [[nowText(), t.type === "compute" ? "HostInit/Discovered" : "Initializing"], [nowText(), "Ready"]] });
  if (t.type === "switch") t.fabricManager = "UNKNOWN";
}
function simulateDiscovery(rackId) {
  const r = DB.rack(rackId); if (!r || r.trays.some((t) => t.matched)) return false;
  r.trays.filter((t) => ![9, 20, 33].includes(t.slot)).forEach(matchTray);
  const a = r.trays.find((t) => t.slot === 12), b = r.trays.find((t) => t.slot === 13); a.simSlot = 13; b.simSlot = 12;
  const n = r.n, ip = (s) => `192.0.2.${(n - 1) * 80 + s + 10}`, mac = (s) => `02:00:${pad2(n)}:00:00:${hex2(s)}`;
  S.endpoints.push({ id: "ep-" + rackId.slice(-3) + "-20", mac: mac(20), ip: ip(20), subnet: "net-oob", seen: nowText(), problem: "auth", type: "", serial: "", model: "", sim: rackId + "/20" });
  S.endpoints.push({ id: "ep-" + rackId.slice(-3) + "-09", mac: mac(9), ip: ip(9), subnet: "net-oob", seen: nowText(), problem: "unlisted", type: "compute", serial: "DEMO-C-" + rackId.slice(-3) + "-99", model: "GB200 Compute Tray", sim: rackId + "/09" });
  return true;
}
function admitRack(rackId) {
  const r = DB.rack(rackId); r.admit = true; r.admitAt = nowText();
  r.trays.filter((t) => t.matched && !t.declared).forEach(declareTray);
}
/* 上线任务：按步骤上电。交换机上电并就绪后，NICo 的机柜状态机自己开始维护。 */
function bringUpRack(rackId, why) {
  const r = DB.rack(rackId), of = (type) => r.trays.filter((t) => t.declared && t.type === type); r.up = true;
  setRackState(r, "Discovering");
  return startTask(rackId, "bringup", "机柜上线", STAGES.bringup_task, { why,
    onStage: (n) => {
      if (n === "供电框上电") of("power_shelf").forEach(takeOver);
      if (n === "计算托盘上电并放行接管") of("compute").forEach((t) => Object.assign(t, { state: "HostInit/WaitingForDiscovery", power: "On", health: "none", history: [[nowText(), "HostInit/WaitingForDiscovery"]] }));
      if (n === "交换机上电") of("switch").forEach((t) => Object.assign(t, { state: "Initializing", power: "On", health: "none", history: [[nowText(), "Initializing"]] }));
    },
    onDone: () => { r.trays.filter((t) => t.declared).forEach(takeOver); coreBringup(r); },
    readback: () => `成员电源：${DB.power(r).text}；交换机就绪 ${DB.ready(r, "switch")} / ${PROFILE_NEED.switch}` });
}
/* 一个端点匹配上清单里的一行之后：机柜还没纳管就只记为已匹配；已纳管就写入声明；机柜已经上线过的，纳管后直接上电接管。 */
function matchEndpoint(epId, trayId, patch) {
  const e = S.endpoints.find((x) => x.id === epId), t = DB.tray(trayId), r = DB.rack(t.rack);
  if (e) S.endpoints = S.endpoints.filter((x) => x.id !== epId);
  Object.assign(t, patch || {});
  if (!r.admit) return matchTray(t);
  if (!r.up || DB.busy(r)) return declareTray(t);
  takeOver(t);
  if (r.state === "Discovering" && !(r.bring && r.bring.timer)) coreBringup(r);
}
