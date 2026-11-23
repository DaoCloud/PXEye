"use strict";
/* 健康：当前有什么问题、影响谁、去哪处理。沿用现有“告警”页，范围扩大到机柜级告警。 */

registerPage("health", {
  module: "health", title: "健康告警",
  render() {
    const f = { scope: view("hScope", ""), block: view("hBlock", ""), q: view("hQ", "").toLowerCase(), by: view("hBy", "alert") };
    const all = DB.alerts(), list = all.filter((a) => (!f.scope || a.scope === f.scope) && (!f.block || a.block) && (!f.q || [a.id, a.msg, a.obj].join(" ").toLowerCase().includes(f.q)));
    const target = (a) => (a.tray ? `<a class="link-button" data-live="tray-detail" data-id="${a.tray}">${esc(a.obj)}</a>` : `<a class="link-button" data-go="rack/${a.rack}">${esc(a.obj)}</a>`);
    const cls = (a) => (a.block ? badge("阻止分配", "red") : "");
    let body;
    if (!list.length) body = `<div class="live-card"><div class="live-empty">${all.length ? "没有符合筛选条件的告警。" : "NICo 报告了全部设备的健康状态，均未报告告警。"}</div></div>`;
    else if (f.by === "alert") {
      const groups = {}; list.forEach((a) => (groups[a.id] = groups[a.id] || []).push(a));
      body = Object.entries(groups).map(([id, items]) => `<section class="live-card"><h2>${code(id)}　<span class="live-small">${items.length} 个对象 · 最早开始于 ${items.map((a) => a.since).sort()[0]}</span>　${cls(items[0])}</h2>${table(["设备", "对象", "开始", "说明", "操作"], items.map((a) => `<tr><td>${a.scope}</td><td>${target(a)}</td><td>${code(a.since)}</td><td>${esc(a.msg)}</td><td>${button("去处理", "noop", false, `data-go="rack/${a.rack}"`)}</td></tr>`))}</section>`).join("");
    } else body = table(["设备", "对象", "告警", "开始", "说明", "操作"], list.map((a) => `<tr><td>${a.scope}</td><td>${target(a)}</td><td>${code(a.id)} ${cls(a)}</td><td>${code(a.since)}</td><td>${esc(a.msg)}</td><td>${button("去处理", "noop", false, `data-go="rack/${a.rack}"`)}</td></tr>`));
    const silent = S.racks.filter((r) => r.state === "Created");
    return heading("健康告警", "汇总 NICo 对机柜、计算托盘、交换机和供电框当前报告的健康告警，查看影响了哪些对象。", button("刷新数据", "refresh") + button("在监控系统中查看", "health-metrics", false, fp(6))) +
      `<div ${fp(1)}>${summary([["告警数", all.length], ["涉及对象", new Set(all.map((a) => a.obj)).size], ["告警类型", new Set(all.map((a) => a.id)).size], ["阻止分配", all.filter((a) => a.block).length]])}</div>` +
      `<div class="filter-bar" ${fp(2)}>${selectField("hScope", "设备类型", [["", "全部"], ["机柜", "机柜"], ["计算托盘", "计算托盘"], ["交换机", "交换机"], ["供电框", "供电框"]], f.scope)}${selectField("hBlock", "影响", [["", "全部"], ["1", "阻止分配"]], f.block)}${searchField("hQ", "搜索", view("hQ", ""), "告警、说明或对象")}
        <span class="live-tabs" style="border:0;margin:0;padding:0" ${fp(3)}>${button("按告警", "health-by", f.by === "alert", 'data-by="alert"')}${button("按设备", "health-by", f.by === "device", 'data-by="device"')}</span></div>` +
      `<div ${fp(4)}>${body}</div>` +
      (silent.length ? `<div ${fp(5)}>${note(`另有 ${silent.length} 个机柜（${silent.map((r) => r.id).join("、")}）NICo 尚未建立设备对象，没有健康数据，不计入告警。`)}</div>` : "") +
      note("泄漏告警同时来自托盘传感器和设施侧事件。断路器与冷却阀的联锁由 BMS 负责；平台只在检测到风险时拒绝上电和交付。");
  },
  spec: {
    purpose: "汇总当前的健康告警，标出会阻止交付的条目，并把人带到处理的地方。页面本身不做监控曲线。",
    entry: "运维 → 健康告警", design: "6.5 健康；10 非功能设计（安全联锁、可观测性）", existing: "设备管理 → 告警。统计条、筛选、按告警 / 按设备切换和表头沿用",
    points: [
      { n: 1, name: "统计条", kind: "沿用", desc: "告警数、涉及对象、告警类型、阻止分配。" },
      { n: 2, name: "筛选", kind: "调整", desc: "设备类型增加“机柜”；分类筛选简化为“影响：阻止分配”。" },
      { n: 3, name: "按告警 / 按设备", kind: "沿用", desc: "两种分组方式，切换不清除筛选。" },
      { n: 4, name: "告警列表", kind: "调整", desc: "对象可点击：设备打开运行状态，机柜进入机柜详情。每行增加“去处理”。" },
      { n: 5, name: "未报告说明", kind: "沿用", desc: "还没有 NICo 对象的机柜单独说明，不计入告警，也不显示为正常。" },
      { n: 6, name: "监控系统入口", kind: "新增", desc: "曲线、功率和温度跳转到监控系统的机柜面板，页面不重做。" },
    ],
    fields: [["告警", "NICo 健康报告", "探针 ID 原文"], ["阻止分配", "NICo 告警分类", "对应 NICo 的 PreventAllocations 分类；带这个分类的告警会阻止交付，泄漏告警还会拒绝上电"], ["机柜级告警", "NICo 机柜健康", "成员未到齐或不一致（MissingRackComponent）"]],
    rules: ["没有收到报告显示为未报告，不显示为正常。", "页面只读；确认、抑制和通知不在本阶段。"],
  },
});
registerAction("health-by", ({ by }) => { S.view.hBy = by; render(); });
registerAction("health-metrics", () => toast("设计稿不打开外部系统：这里跳转到监控系统的机柜面板"));
