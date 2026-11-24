"use strict";
/* 任务：跨机柜查看所有 Flow 任务。taskStatus / taskStage 定义在 racks.js。
   任务的对象、操作、操作者和原因是平台提交时记下的；NICo 的任务只带编号、状态、规则和各步骤的结果。
   步骤的名称来自任务所用的操作规则。NICo 自动进行的机柜上线不是任务，不在这里。 */

registerPage("tasks", {
  module: "tasks", title: "运维任务",
  render() {
    const f = view("taskStatus", ""), list = DB.tasks().filter((t) => !f || t.status === f);
    return heading("运维任务", "查看机柜级电源和固件操作提交的任务、步骤和结果。任务由 NICo Flow 按站点的操作规则分步执行。", button("刷新数据", "refresh")) +
      `<div class="filter-bar" ${fp(1)}>${selectField("taskStatus", "状态", [["", "全部"], ["执行中", "执行中"], ["已完成", "已完成"], ["失败", "失败"], ["已终止", "已终止"]], f)}<span class="live-small">${list.length} 个任务</span></div>` +
      `<div ${fp(2)}>${table(["任务 / 起止时间", "对象", "操作", "步骤 / 状态", "操作者", "原因", "操作"], list.map((t) => { const rackId = t.target.split(" / ")[0]; return `<tr><td>${code(t.id)}<span class="cell-sub">${t.at}${t.end ? " 至 " + t.end.slice(11) : ""}</span></td><td><strong>${esc(t.target)}</strong></td><td>${esc(t.label)}</td><td ${fp(3)}>${esc(taskStage(t))}<span class="cell-sub">${taskStatus(t)}</span></td><td>${t.by}</td><td>${esc(t.reason || "—")}</td><td><div class="inline-actions">${button("查看步骤", "task-open", false, `data-rack="${rackId}"`)}${t.status === "执行中" ? act("取消任务", "task-cancel", { extra: `data-id="${rackId}" ${fp(4)}`, compact: true }) : ""}</div></td></tr>`; }), "还没有任务。")}</div>` +
      note("任务在某一步失败后停止。取消是尽力而为：还没开始的步骤不再执行，已经交给硬件后端的动作不会停。已完成的硬件动作不会撤销，页面不提供一键回滚。NICo 自动进行的机柜上线不是任务，进度在机柜详情里。");
  },
  spec: {
    purpose: "跨机柜查看所有 Flow 任务。任务是机柜级操作的唯一执行记录。", entry: "运维 → 运维任务", design: "6.3 机柜与设备（任务视图）；9 操作设计", existing: "新增页面。表头写法沿用安装任务页（任务 / 创建时间、阶段 / 状态）",
    points: [
      { n: 1, name: "状态筛选", kind: "新增", desc: "全部、执行中、已完成、失败、已终止。" },
      { n: 2, name: "任务表", kind: "新增", desc: "任务编号、起止时间、对象、操作、当前步骤、操作者和原因。NICo 自动提交的任务（例如泄漏时的强制下电）操作者显示为“NICo 自动”。" },
      { n: 3, name: "阶段 / 状态", kind: "沿用", desc: "写法与安装任务页一致：上面是当前步骤，下面是状态标签。" },
      { n: 4, name: "取消任务", kind: "新增", desc: "只对执行中的任务显示。取消后不再开始新的步骤；已经交给硬件后端的动作不会停，也不回滚。" },
    ],
    fields: [["对象 / 操作 / 操作者 / 原因", "平台提交任务时的记录", "NICo 的任务不带这几项。不是经平台提交的任务只显示 NICo 给出的描述"], ["步骤", "任务所用的操作规则 + NICo 的任务报告", "报告只有每一步的序号和结果，名称取自规则里这一步的设备类型和动作"], ["状态", "NICo 的任务状态", "执行中、已完成、失败、已终止"]],
    rules: ["状态用词沿用安装任务，另有“失败”。", "只读角色不能取消任务。"],
  },
});
registerAction("task-open", ({ rack }) => { S.view["rackTab:" + rack] = "tasks"; go("rack/" + rack); });
