"use strict";
/* 示例数据与模拟引擎。全部为编写的占位数据：序列号 DEMO-…，MAC 02:…，地址取自 192.0.2.0/24 与 198.51.100.0/24。
   真实实现中，这些数据来自 NICo Core（读取与单设备操作）和 NICo REST / Flow（机柜级任务）。 */

const PROFILE = "GB200_NVL72R1_C2G4";
const TYPE_LABEL = { compute: "计算托盘", switch: "交换机", power_shelf: "供电框" };
const STAGES = {
  bringup: ["固件升级", "NVOS 更新", "NMX-C 配置", "机柜校验"],
  power_off: ["计算托盘下电", "交换机 下电", "供电框下电"],
  power_on: ["供电框上电", "等待托盘出现", "泄漏检查", "交换机 上电", "计算托盘上电"],
  power_cycle: ["计算托盘下电", "交换机 下电", "交换机 上电", "计算托盘上电"],
  firmware: ["等待主机就绪", "供电框固件", "交换机 固件", "计算托盘固件", "版本校验"],
  tray_power: ["检查实例与任务", "执行电源动作", "读回电源状态"],
  tray_firmware: ["等待主机就绪", "更新组件固件", "版本校验"],
  decommission: ["确认无实例", "释放与清理", "退役", "移出期望清单"],
};
const BASELINES = [
  { id: "GB200-NVL72 2026.11", profile: PROFILE, released: "2026-11-10", note: "当前推荐", parts: { "计算托盘 BMC": "25.11.2", "计算托盘 UEFI": "2.19.0", "BlueField-3": "32.45.1020", "交换机 BMC": "25.11.1", NVOS: "25.02.4012", "供电框 PMC": "1.9.3" } },
  { id: "GB200-NVL72 2026.10", profile: PROFILE, released: "2026-10-08", note: "上一版", parts: { "计算托盘 BMC": "25.10.4", "计算托盘 UEFI": "2.18.1", "BlueField-3": "32.44.1036", "交换机 BMC": "25.10.2", NVOS: "25.02.3004", "供电框 PMC": "1.9.1" } },
];
/* 网络用途：每类设备的每种接口必须落在一个已规划的子网里。导入设备清单前要先规划好。 */
const NET_ROLES = [
  { id: "oob", label: "带外管理", devices: "计算托盘 BMC、交换机 BMC、供电框 PMC", kind: "Underlay", demand: () => DB.trays().length },
  { id: "nvos", label: "交换机系统管理", devices: "交换机 NVOS 管理口", kind: "Underlay", demand: () => DB.trays().filter((t) => t.type === "switch").length },
  { id: "host", label: "主机管理", devices: "计算托盘主机网口：引导、装机与系统管理", kind: "HostInband", demand: () => DB.trays().filter((t) => t.type === "compute").length },
];
const pad2 = (n) => String(n).padStart(2, "0");
const slotType = (s) => (s <= 4 || s >= 32 ? "power_shelf" : s >= 15 && s <= 23 ? "switch" : "compute");
const nowText = () => "2026-11-23 " + new Date().toTimeString().slice(0, 5);

function makeTray(rackId, n, slot, discovered, baseline) {
  const type = slotType(slot), key = { compute: "C", switch: "S", power_shelf: "P" }[type];
  const serial = `DEMO-${key}-${rackId.slice(-3)}-${pad2(slot)}`;
  const tray = {
    id: `${rackId}/${pad2(slot)}`, rack: rackId, slot, type, serial, actualSerial: discovered ? serial : "",
    vendor: type === "power_shelf" ? "LiteOn" : "NVIDIA", model: { compute: "GB200 Compute Tray", switch: "NVLink Switch Tray", power_shelf: "33kW Power Shelf" }[type],
    bmcMac: `02:00:${pad2(n)}:00:00:${slot.toString(16).padStart(2, "0")}`, bmcIp: `192.0.2.${(n - 1) * 40 + slot + 10}`,
    state: discovered ? "Ready" : "", reason: "", health: discovered ? "ok" : "none", alerts: [], power: discovered ? "On" : "",
    baseline: discovered ? baseline : "", maintenance: "", quarantine: "", instance: "", lastSeen: discovered ? "2026-11-23 08:00" : "",
    history: discovered ? [["2026-11-02 09:20", "Created"], ["2026-11-02 09:41", type === "compute" ? "HostInit/Discovered" : "Initializing"], ["2026-11-02 10:30", "Ready"]] : [],
  };
  if (type === "compute") Object.assign(tray, {
    hostMac: `02:10:${pad2(n)}:00:00:${slot.toString(16).padStart(2, "0")}`, hostIp: `198.51.100.${(n - 1) * 40 + slot + 10}`,
    hardware: { CPU: "2 × Grace 72C", GPU: "4 × GB200", 内存: "960 GiB", 系统盘: "2 × 1.92 TB NVMe" }, sku: "gb200-compute-c2g4",
    dpus: [0, 1].map((i) => ({ id: `${serial}-DPU${i + 1}`, serial: `DEMO-D-${rackId.slice(-3)}-${pad2(slot)}${i + 1}`, state: discovered ? "Ready" : "", mode: "DPU", fw: "32.44.1036" })),
    lldp: [{ port: "eno1", sw: "mgmt-leaf-" + pad2(n), remote: "swp" + slot }, { port: "p0", sw: "spine-" + pad2(n) + "a", remote: "Ethernet" + slot }],
  });
  if (type === "switch") Object.assign(tray, { nvosIp: `203.0.113.${(n - 1) * 40 + slot + 10}`, nvosMac: `02:20:${pad2(n)}:00:00:${slot.toString(16).padStart(2, "0")}`, primary: slot === 15, fabricManager: discovered ? "Running" : "", nmxc: slot === 15 });
  if (type === "power_shelf") Object.assign(tray, { capacity: 33000, voltage: 54, psu: "6 / 6" });
  return tray;
}
function makeRack(id, n, domain, discovered, baseline, location) {
  const trays = []; for (let s = 1; s <= 35; s++) trays.push(makeTray(id, n, s, discovered, baseline));
  return { id, n, domain, profile: PROFILE, location, state: discovered ? "Ready" : "Created", stateSince: discovered ? "2026-11-02 15:02" : nowText(), power: discovered ? "On" : "",
    baseline: discovered ? baseline : "", trays, issues: [], tasks: [], task: null,
    history: discovered ? [["2026-11-02 09:12", "Created"], ["2026-11-02 09:40", "Discovering"], ["2026-11-02 11:05", "Maintenance"], ["2026-11-02 14:31", "Validating"], ["2026-11-02 15:02", "Ready"]] : [[nowText(), "Created"]] };
}

function freshState() {
  const a01 = makeRack("RACK-A01", 1, "NVL-D01", true, BASELINES[0].id, "机房 1 · A 列 01");
  const a02 = makeRack("RACK-A02", 2, "NVL-D01", true, BASELINES[1].id, "机房 1 · A 列 02");
  const done = (label, stages, at) => ({ id: "", kind: "bringup", label, target: "", stages: stages.map((n) => ({ n, s: "done" })), status: "已完成", by: "ops-01", at, reason: "新机柜上线" });
  a01.tasks = [Object.assign(done("机柜上线", STAGES.bringup, "2026-11-02 11:05"), { id: "task-0039", target: "RACK-A01" })];
  a02.tasks = [Object.assign(done("机柜上线", STAGES.bringup, "2026-11-03 10:12"), { id: "task-0041", target: "RACK-A02" })];
  const instances = [];
  a01.trays.filter((t) => t.type === "compute").forEach((t, i) => { t.state = "Assigned/Ready"; t.instance = "inst-a01-" + pad2(i + 1); instances.push({ id: t.instance, tray: t.id, rack: "RACK-A01", host: "train-a01-" + pad2(i + 1), os: "Ubuntu 24.04 ARM64", tenant: "训练集群 A", state: "Ready", ip: t.hostIp, created: "2026-11-04 16:20" }); });
  const sw = a01.trays.find((t) => t.slot === 18); sw.health = "warn"; sw.fabricManager = "Degraded"; sw.alerts = [{ id: "FabricManagerDegraded", msg: "Fabric Manager 状态降级", since: "2026-11-21 03:14", block: false }];
  const mt = a02.trays.find((t) => t.slot === 27); mt.maintenance = "CHG-1042 更换风扇"; mt.health = "warn"; mt.alerts = [{ id: "FanSpeedLow", msg: "风扇 3 转速低于阈值", since: "2026-11-22 21:40", block: false }];
  return {
    role: "操作", rms: true, flow: true, leak: false, taskSeq: 41, view: {}, guide: 1,
    racks: [a01, a02], instances, deliveries: [],
    domains: [{ id: "NVL-D01", topology: "gb200_nvl72r1_c2g4", racks: ["RACK-A01", "RACK-A02"], health: "ok", partitions: 1 }],
    inventory: [{ v: 3, at: "2026-11-03 09:30", by: "ops-01", file: "arrival-2026-11-A.csv", note: "新增 RACK-A02（35 台）", why: "到货批次 2026-11-A" }, { v: 2, at: "2026-11-02 09:10", by: "ops-01", file: "arrival-2026-11-A.csv", note: "新增 RACK-A01（35 台）", why: "到货批次 2026-11-A" }],
    audit: [
      { at: "2026-11-22 21:55", by: "ops-02", obj: "RACK-A02 / 槽位 27", act: "设置维护标记", why: "CHG-1042 更换风扇", task: "—", res: "读回一致" },
      { at: "2026-11-04 16:20", by: "ops-01", obj: "RACK-A01", act: "交付：装机并验收", why: "交付训练集群 A", task: "—", res: "验收通过 18/18" },
      { at: "2026-11-03 10:12", by: "ops-01", obj: "RACK-A02", act: "开始上线", why: "新机柜上线", task: "task-0041", res: "成功，读回 Ready" },
      { at: "2026-11-02 11:05", by: "ops-01", obj: "RACK-A01", act: "开始上线", why: "新机柜上线", task: "task-0039", res: "成功，读回 Ready" },
    ],
    rollouts: [],
    /* 子网：NICo 的网络段。capacity 为可分配地址数（去掉保留地址）。 */
    subnets: [
      { id: "net-oob", name: "oob-mgmt", role: "oob", kind: "Underlay", cidr: "192.0.2.0/24", gateway: "192.0.2.1", vlan: "401", policy: "动态分配", pool: ["192.0.2.11", "192.0.2.250"], reserved: 10, capacity: 240, mtu: 1500, state: "READY", relayLast: "2026-11-23 08:00", relay24h: 1840 },
      { id: "net-nvos", name: "nvos-mgmt", role: "nvos", kind: "Underlay", cidr: "203.0.113.0/24", gateway: "203.0.113.1", vlan: "431", policy: "动态分配", pool: ["203.0.113.11", "203.0.113.250"], reserved: 10, capacity: 240, mtu: 1500, state: "READY", relayLast: "2026-11-23 08:00", relay24h: 216 },
      { id: "net-host", name: "host-inband", role: "host", kind: "HostInband", cidr: "198.51.100.0/24", gateway: "198.51.100.1", vlan: "301", policy: "动态分配", pool: ["198.51.100.11", "198.51.100.250"], reserved: 10, capacity: 240, mtu: 9000, state: "READY", relayLast: "2026-11-23 07:58", relay24h: 432 },
    ],
    /* DHCP 观察到、但不在设备清单里的端点。 */
    unexpected: [{ mac: "02:00:ee:00:00:07", ip: "192.0.2.247", subnet: "net-oob", seen: "2026-11-23 07:41", info: "BMC 报告序列号 DEMO-X-0007，型号 GB200 Compute Tray" }],
    osTemplates: [{ id: "Ubuntu 24.04 ARM64 · 标准系统盘", arch: "aarch64", disk: "唯一匹配的 NVMe，GPT / UEFI，ext4", login: "ubuntu + 公钥", state: "已发布", used: 18 }, { id: "Ubuntu 24.04 ARM64 · 大容量根分区", arch: "aarch64", disk: "容量最大的 NVMe，GPT / UEFI，XFS", login: "ubuntu + 公钥", state: "草稿", used: 0 }],
    tenants: ["训练集群 A（NVKE）", "推理集群 B（NVKE）"],
  };
}

let S = freshState();
const DB = {
  rack: (id) => S.racks.find((r) => r.id === id),
  tray: (id) => S.racks.flatMap((r) => r.trays).find((t) => t.id === id),
  trays: () => S.racks.flatMap((r) => r.trays),
  domain: (id) => S.domains.find((d) => d.id === id),
  baseline: (id) => BASELINES.find((b) => b.id === id),
  blockers: (r) => r.issues.filter((i) => i.block && !i.done),
  busy: (r) => !!(r.task && r.task.status === "执行中"),
  tasks: () => S.racks.flatMap((r) => r.tasks).sort((a, b) => (a.id < b.id ? 1 : -1)),
  rackInstances: (id) => S.instances.filter((i) => i.rack === id),
  subnet: (id) => S.subnets.find((n) => n.id === id),
  roleSubnets: (role) => S.subnets.filter((n) => n.role === role),
  /* 设备的各个接口：带外管理口、交换机系统管理口、主机管理口。地址分配和设备发现都从这里来。 */
  interfaces() {
    const out = [];
    DB.trays().forEach((t) => {
      const add = (role, iface, mac, ip) => out.push({ tray: t, role, iface, mac, ip, subnet: (DB.roleSubnets(role)[0] || {}).id || "", leased: !!t.state && t.state !== "未发现" });
      add("oob", t.type === "power_shelf" ? "PMC" : "BMC", t.bmcMac, t.bmcIp);
      if (t.type === "switch") add("nvos", "NVOS 管理口", t.nvosMac, t.nvosIp);
      if (t.type === "compute") add("host", "主机管理口", t.hostMac, t.hostIp);
    });
    return out;
  },
  subnetUsed: (id) => DB.interfaces().filter((i) => i.subnet === id && i.leased).length,
  /* 规划检查：每种用途都有子网，且可分配地址不少于设备清单需要的数量。extra 用于导入前的预估。 */
  planChecks(extra = {}) {
    return NET_ROLES.map((r) => { const nets = DB.roleSubnets(r.id), capacity = nets.reduce((n, x) => n + x.capacity, 0), need = r.demand() + (extra[r.id] || 0);
      return { role: r, nets, capacity, need, ok: nets.length > 0 && capacity >= need, reason: !nets.length ? "缺少子网" : capacity < need ? "地址不足" : "" }; });
  },
  planOk: (extra) => DB.planChecks(extra).every((c) => c.ok),
  /* 当前告警：托盘告警 + 机柜级告警（成员未到齐、泄漏）。阻止分配的条目 block 为 true。 */
  alerts() {
    const out = [];
    S.racks.forEach((r) => {
      const open = r.issues.filter((i) => !i.done);
      if (open.length) out.push({ scope: "机柜", obj: r.id, rack: r.id, tray: "", id: "MissingRackComponent", msg: "机柜成员未到齐或不一致：" + open.map((i) => `槽位 ${i.slot} ${i.title}`).join("、"), since: r.stateSince, block: open.some((i) => i.block) });
      r.trays.forEach((t) => t.alerts.forEach((a) => out.push({ scope: TYPE_LABEL[t.type], obj: `${r.id} / 槽位 ${pad2(t.slot)}`, rack: r.id, tray: t.id, id: a.id, msg: a.msg, since: a.since, block: !!a.block })));
    });
    return out;
  },
  preventAlloc: (rackId) => DB.alerts().some((a) => a.rack === rackId && a.block),
  /* “需要处理”只用 NICo 的信号：状态机处理失败、超出状态时限、存在健康告警。 */
  needsAttention: (t) => t.health === "bad" || t.health === "warn" || /Failed|不符|失败/.test(t.state) || (!t.state && DB.rack(t.rack).state !== "Created"),
  /* 固件偏差：托盘实际所在的基线不是当前推荐基线。 */
  drift: (t) => !!t.baseline && t.baseline !== BASELINES[0].id,
};

function addAudit(obj, act, why, task, res) { S.audit.unshift({ at: nowText(), by: "ops-01", obj, act, why: why || "—", task: task || "—", res }); return S.audit[0]; }

/* 模拟 Flow 任务：按阶段推进。真实实现中任务由 Flow 持久化，页面只轮询任务状态。 */
function startTask(rackId, kind, label, stages, opts = {}) {
  const r = DB.rack(rackId);
  const t = { id: "task-" + String(++S.taskSeq).padStart(4, "0"), kind, label, target: opts.target || rackId, stages: stages.map((n) => ({ n, s: "wait" })), status: "执行中", by: "ops-01", at: nowText(), reason: opts.why || "" };
  r.task = t; r.tasks.unshift(t);
  const rec = addAudit(t.target, label, opts.why, t.id, "已提交");
  t.timer = setInterval(() => {
    const cur = t.stages.find((s) => s.s === "run"); if (cur) cur.s = "done";
    const next = t.stages.find((s) => s.s === "wait");
    if (next) { next.s = "run"; if (opts.onStage) opts.onStage(next.n); }
    else { clearInterval(t.timer); t.status = "已完成"; if (opts.onDone) opts.onDone(); rec.res = "成功，" + (opts.readback ? opts.readback() : "读回 " + r.state); if (window.toast) toast(`${t.target}：${label} 完成`); }
    if (window.render) render();
  }, 1200);
  return t;
}
function cancelTask(rackId) {
  const r = DB.rack(rackId), t = r.task; if (!t || t.status !== "执行中") return;
  clearInterval(t.timer); t.status = "已终止"; const cur = t.stages.find((s) => s.s === "run"); if (cur) cur.s = "fail";
  if (["bringup", "firmware"].includes(t.kind)) { r.state = "Error"; r.stateSince = nowText(); r.history.push([nowText(), "Error"]); }
  addAudit(t.target, "取消任务", "操作人取消", t.id, "已终止，已完成的硬件动作不撤销");
}
function setRackState(r, st) { r.state = st; r.stateSince = nowText(); r.history.push([nowText(), st]); }

/* 模拟：新机柜通电后 NICo 自动发现，并产生三类对账问题。 */
function simulateDiscovery(rackId) {
  const r = DB.rack(rackId); if (!r || r.state !== "Created") return false;
  setRackState(r, "Discovering");
  r.trays.forEach((t) => { t.state = "Ready"; t.health = "ok"; t.power = "On"; t.actualSerial = t.serial; t.baseline = BASELINES[1].id; t.lastSeen = nowText(); t.history = [[nowText(), "Created"], [nowText(), "Ready"]]; if (t.dpus) t.dpus.forEach((d) => (d.state = "Ready")); if (t.type === "switch") t.fabricManager = "Running"; });
  const mark = (slot, state, health, reason) => { const t = r.trays.find((x) => x.slot === slot); t.state = state; t.health = health; t.reason = reason; t.baseline = ""; t.power = state ? t.power : ""; };
  mark(9, "序列号不符", "bad", "实测序列号与期望清单不一致"); mark(20, "", "none", ""); mark(33, "探测失败", "warn", "NICO-SITEEXPLORER-101：连接被拒绝");
  r.trays.find((x) => x.slot === 9).actualSerial = "DEMO-C-" + rackId.slice(-3) + "-99";
  r.issues = [
    { k: "serial", slot: 9, type: "compute", title: "序列号不符", detail: "实物与清单不一致，可能是出厂替换件", expect: r.trays[8].serial, actual: r.trays[8].actualSerial, block: true, action: "更换设备" },
    { k: "missing", slot: 20, type: "switch", title: "未发现", detail: "没有收到该 BMC 的 DHCP 请求；交换机就绪数 8/9，低于机柜规格要求", expect: r.trays[19].serial, actual: "—", block: true, action: "重新发现" },
    { k: "probe", slot: 33, type: "power_shelf", title: "探测失败", detail: "NICO-SITEEXPLORER-101：连接被拒绝。处理建议：检查 PMC 网络与出厂凭据", expect: r.trays[32].serial, actual: r.trays[32].bmcIp + " 无响应", block: false, action: "重新探测" },
    { k: "cable", slot: 26, type: "compute", title: "接线不符", detail: "网口 p0 的 LLDP 邻居端口与同机柜其他设备的规律不一致", expect: "Ethernet26", actual: "Ethernet28", block: false, action: "标记已核对" },
  ];
  return true;
}
function resolveIssue(rackId, key, patch) {
  const r = DB.rack(rackId), i = r.issues.find((x) => x.k === key), t = r.trays.find((x) => x.slot === i.slot);
  i.done = true; Object.assign(t, { state: "Ready", health: "ok", reason: "", power: "On", baseline: BASELINES[1].id, lastSeen: nowText() }, patch || {}); t.actualSerial = t.serial;
  if (t.type === "switch") t.fabricManager = "Running";
}
