"use strict";
/* 机柜、NVLink 域两个列表页。设备页面在 trays.js，任务在 tasks.js，机柜详情在 rack.js。 */

/* 清单核对只是提示：NICo 的机柜状态机不看它，只看就绪的交换机数量是否达到机柜规格。 */
const checkBadge = (r) => { const n = DB.absent(r).length + DB.misplaced(r).length;
  return !r.trays.some((t) => t.matched) ? badge("等待设备出现", "gray") : !r.admit ? badge("待确认接入", "blue") + (n ? `<span class="cell-sub">${n} 项差异</span>` : "") : n ? badge(n + " 项差异", "amber") : badge("与清单一致", "green"); };
const members = (r) => `计算托盘 ${r.trays.filter((t) => t.type === "compute").length} · 交换机 ${r.trays.filter((t) => t.type === "switch").length} · 供电框 ${r.trays.filter((t) => t.type === "power_shelf").length}`;
const taskStatus = (t) => badge(t.status, t.status === "已完成" ? "green" : /已终止|失败/.test(t.status) ? "red" : "amber");
const taskStage = (t) => { const cur = t.stages.find((s) => s.s === "run" || s.s === "fail"); return cur ? cur.n : t.status === "已完成" ? "完成" : "等待执行"; };
const bringStage = (r) => (r.bring && r.bring.stages.find((s) => s.s === "run" || s.s === "fail")) || null;
const rackStateCell = (r) => (r.state ? stateBadge(r.state) + `<span class="cell-sub">自 ${r.stateSince}</span>` : badge("尚未建立", "gray") + `<span class="cell-sub">只在清单里</span>`);

registerPage("racks", {
  module: "racks", title: "机柜管理",
  render() {
    const trays = DB.trays();
    return heading("机柜管理", "查看每个机柜的 NICo 状态、健康和成员设备，并发起电源和固件操作。", button("刷新数据", "refresh")) +
      `<div ${fp(1)}>${summary([["机柜", S.racks.length], ["就绪", S.racks.filter((r) => r.state === "Ready").length], ["需要处理", S.racks.filter(rackNeedsAttention).length], ["设备就绪", `${trays.filter((t) => /Ready$/.test(t.state)).length}<small>/ ${trays.length}</small>`], ["进行中的任务", S.racks.filter(DB.busy).length]])}</div>` +
      `<div ${fp(2)}>${table(["机柜", "NICo 状态", "健康", "机柜规格", "成员设备", "清单核对", "实例", "进行中", "操作"], S.racks.map((r) =>
        `<tr class="row-link" data-go="rack/${r.id}"><td><strong>${r.id}</strong><span class="cell-sub">${esc(r.location)}</span></td><td ${fp(3)}>${rackStateCell(r)}</td><td>${healthBadge(rackHealth(r))}</td><td>${code(r.profile)}</td><td>${members(r)}<span class="cell-sub">就绪 ${DB.ready(r)} / ${r.trays.length}</span></td><td ${fp(4)}>${checkBadge(r)}</td><td>${DB.rackInstances(r.id).length}</td><td ${fp(5)}>${DB.busy(r) ? badge(r.task.label + " · " + taskStage(r.task), "blue") : bringStage(r) && r.state !== "Error" ? badge("NICo 上线 · " + bringStage(r).n, "blue") : "—"}</td><td>${button("详情", "noop", false, `data-go="rack/${r.id}"`)}</td></tr>`))}</div>` +
      note("新机柜不在这里创建。在“设备清单”导入到货清单后，机柜先以“尚未建立”出现在这里；设备匹配上清单、你在机柜详情里确认接入之后，NICo 才接管设备并建立机柜对象。");
  },
  spec: {
    purpose: "机柜是默认的操作单位。本页回答每个机柜处在流程的哪一步、有没有需要处理的问题。",
    entry: "运维 → 机柜管理（默认首页）", design: "5 整体操作运维流程；6.3 机柜与设备", existing: "设备管理 → 机柜（列与状态用词沿用）；机柜拓扑的统计条并入",
    points: [
      { n: 1, name: "统计条", kind: "调整", desc: "机柜数、就绪数、需要处理、设备就绪、进行中的任务。取代机柜拓扑页的设备数量统计。" },
      { n: 2, name: "机柜表", kind: "调整", desc: "机柜、NICo 状态、健康、机柜规格、成员设备沿用现有机柜页；列表同时包含清单里还没有 NICo 对象的机柜。点击整行进入机柜详情。" },
      { n: 3, name: "NICo 状态", kind: "沿用", desc: "显示状态机的状态原文和进入时间，不翻译、不另起状态名。还没有 NICo 对象的机柜显示“尚未建立”。" },
      { n: 4, name: "清单核对", kind: "新增", desc: "等待设备出现、待确认接入、N 项差异、与清单一致。差异包括清单里没出现的设备和槽位不一致的设备。" },
      { n: 5, name: "进行中", kind: "新增", desc: "NICo 正在自动上线时显示所在阶段；有电源或固件任务时显示任务及其步骤。同一机柜同时只有一个任务。" },
    ],
    fields: [["NICo 状态", "NICo Core", "Discovering、Maintenance（带阶段）、Validating、Ready、Error、Deleting；没有对象时为“尚未建立”"], ["机柜规格", "NICo Core", "由清单里的机柜拓扑和厂商推导"], ["成员设备", "清单 + NICo", "三类设备的数量与就绪数"], ["清单核对", "清单 + NICo", "清单里有、但还没有设备读出这个序列号的行数，加上实测槽位与清单不同的台数"], ["实例", "NICo Core", "机柜上已交付的实例数"]],
    rules: ["“需要处理”只用 NICo 的信号：状态为 Error、有整柜泄漏、成员设备有严重告警。", "清单里的机柜都出现在这里，不论 NICo 里有没有对象。"],
  },
});

registerPage("domains", {
  module: "domains", title: "NVLink 域管理",
  render() {
    const parts = S.domains.flatMap((d) => d.partitions.map((p) => ({ d, p })));
    const nmxc = (d) => ({ ok: badge("连通", "green"), bad: badge("不可达", "red") })[d.nmxc] || badge("未报告", "gray");
    const fm = (r) => { const sw = r.trays.filter((t) => t.type === "switch"); return `${sw.filter((t) => t.fabricManager === "OK").length}<small class="muted"> / ${sw.length}</small>`; };
    return heading("NVLink 域管理", "一个 NVL72 机柜是一个 NVLink 域。这里查看每个域的 NMX-C 是否连通、域的健康，以及域里的 NVLink 分区。", button("刷新数据", "refresh")) +
      `<div ${fp(1)}>${summary([["NVLink 域", S.domains.length], ["NMX-C 连通", S.domains.filter((d) => d.nmxc === "ok").length], ["未形成", S.domains.filter((d) => !d.uuid).length], ["逻辑分区", parts.length]])}</div>` +
      `<div ${fp(2)}>${table(["NVLink 域 / 拓扑", "机柜", "NMX-C 域编号", "NMX-C", "域健康", "Fabric Manager 正常的交换机", "逻辑分区"], S.domains.map((d) => { const r = DB.rack(d.rack);
        return `<tr><td><strong>${d.id}</strong><span class="cell-sub live-code">${d.topology}</span></td><td><a class="link-button" data-go="rack/${d.rack}">${d.rack}</a><span class="cell-sub">${r.state ? r.state : "尚未建立"}</span></td><td ${fp(3)}>${d.uuid ? code(d.uuid) : `<span class="muted">机柜上线后由 NMX-C 回报</span>`}</td><td>${nmxc(d)}</td><td>${healthBadge(d.health)}</td><td>${r.state ? fm(r) : "—"}</td><td>${d.partitions.length}</td></tr>`; }))}</div>` +
      `<h2 class="section-title">NVLink 分区</h2><div ${fp(4)}>${table(["逻辑分区", "NVLink 域", "租户", "状态", "NMX 分区", "创建时间"], parts.map(({ d, p }) => `<tr><td><strong>${esc(p.name)}</strong><span class="cell-sub live-code">${p.id}</span></td><td>${d.id}</td><td>${esc(p.tenant)}</td><td>${stateBadge(p.state)}</td><td>${code(p.physical)}</td><td>${code(p.created)}</td></tr>`), "还没有分区。分区在交付时按租户建立。")}</div>` +
      `<div ${fp(5)}>${note("<b>这一页只读，三样东西各有来处。</b>NVLink 域：按到货清单里的机柜自动声明，不需要人维护；机柜上线配置好 NMX-C 集群后才算形成。逻辑分区：由租户在交付时建立和删除。NMX 分区：第一个实例加入逻辑分区时由 NICo 自动建立。没有划进逻辑分区的 GPU，只能和同一个计算托盘里的 GPU 共享内存。更换计算托盘之前，要先把它的 GPU 从分区里移出。")}</div>`;
  },
  spec: {
    purpose: "NVLink 域的状态页：域有没有形成、NMX-C 是否连通、域里划了哪些分区、分给了谁。",
    entry: "运维 → NVLink 域管理", design: "6.3 机柜与设备；6.6 交付（NVLink 分区）", existing: "新增页面。现有交换机详情里的“NVLink 域”字段是它的来源",
    points: [
      { n: 1, name: "统计条", kind: "新增", desc: "域的数量、NMX-C 连通的数量、还没有形成的数量、逻辑分区数。" },
      { n: 2, name: "域列表", kind: "新增", desc: "域和拓扑、所属机柜、NMX-C 是否连通、域健康、Fabric Manager 正常的交换机数、分区数。机柜可点击进入详情。" },
      { n: 3, name: "NMX-C 域编号", kind: "新增", desc: "域有两个编号：清单里的机柜组编号，和机柜上线后 NMX-C 回报的域编号。两个都显示，后者没有回报时说明原因。" },
      { n: 4, name: "NVLink 分区", kind: "新增", desc: "逻辑分区的名称、所在的域、租户、状态和对应的 NMX 分区。" },
      { n: 5, name: "谁来维护", kind: "新增", desc: "说明域、逻辑分区和 NMX 分区各由谁建立：域按清单自动声明，逻辑分区由租户在交付时建立，NMX 分区由 NICo 自动建立。本页只读。" },
    ],
    fields: [["NVLink 域", "清单", "机柜组编号，一个 NVL72 机柜一个"], ["NMX-C 域编号", "NICo Core", "交换机和计算托盘回报的域编号；机柜上线配置好 NMX-C 集群后才有"], ["NMX-C", "NICo 机柜健康", "连通、不可达、未报告"], ["域健康", "NICo Core", "按 NMX-C 域编号记录的健康报告"], ["Fabric Manager", "NICo Core", "交换机回报的 OK、NOT_OK、UNKNOWN 里 OK 的台数"], ["逻辑分区 / 租户 / 状态", "NICo Core", "分区名称、租户的组织、分区的状态"], ["NMX 分区", "NICo Core", "逻辑分区在 NMX-C 上对应的分区"]],
    rules: ["页面只读。域不需要人维护；分区在交付里建立，不在这里。", "没有域级的电源和固件操作：一个域就是一个机柜。", "NICo 没有启用 NVLink 分区时，分区表为空。"],
  },
});
