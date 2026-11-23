"use strict";
/* 任务：跨机柜查看所有 Flow 任务。taskStatus / taskStage 定义在 racks.js。 */

registerPage("tasks", {
  module: "tasks", title: "运维任务",
  render() {
    const f = view("taskStatus", ""), list = DB.tasks().filter((t) => !f || t.status === f);
    return heading("运维任务", "查看机柜级操作提交的任务、阶段和结果。任务由 NICo Flow 按站点规则分阶段执行。", button("刷新数据", "refresh")) +
      `<div class="filter-bar" ${fp(1)}>${selectField("taskStatus", "状态", [["", "全部"], ["执行中", "执行中"], ["已完成", "已完成"], ["已终止", "已终止"]], f)}<span class="live-small">${list.length} 个任务</span></div>` +
      `<div ${fp(2)}>${table(["任务 / 创建时间", "对象", "操作", "阶段 / 状态", "操作者", "原因", "操作"], list.map((t) => { const rackId = t.target.split(" / ")[0]; return `<tr><td>${code(t.id)}<span class="cell-sub">${t.at}</span></td><td><strong>${esc(t.target)}</strong></td><td>${esc(t.label)}</td><td ${fp(3)}>${esc(taskStage(t))}<span class="cell-sub">${taskStatus(t)}</span></td><td>${t.by}</td><td>${esc(t.reason || "—")}</td><td><div class="inline-actions">${button("查看阶段", "task-open", false, `data-rack="${rackId}"`)}${t.status === "执行中" ? act("取消任务", "task-cancel", { extra: `data-id="${rackId}" ${fp(4)}`, compact: true }) : ""}</div></td></tr>`; }), "还没有任务。")}</div>` +
      note("任务在某个阶段失败或被取消后停止，已完成的硬件动作不会撤销。页面不提供一键回滚。");
  },
  spec: {
    purpose: "跨机柜查看所有 Flow 任务。任务是机柜级操作的唯一执行记录。", entry: "运维 → 运维任务", design: "6.3 机柜与设备（任务视图）；9 操作设计", existing: "新增页面。表头写法沿用安装任务页（任务 / 创建时间、阶段 / 状态）",
    points: [
      { n: 1, name: "状态筛选", kind: "新增", desc: "全部、执行中、已完成、已终止。" },
      { n: 2, name: "任务表", kind: "新增", desc: "任务编号、对象、操作、当前阶段、操作者和原因。" },
      { n: 3, name: "阶段 / 状态", kind: "沿用", desc: "写法与安装任务页一致：上面是当前阶段，下面是状态标签。" },
      { n: 4, name: "取消任务", kind: "新增", desc: "只对执行中的任务显示。取消后任务停在当前阶段，不回滚。" },
    ],
    rules: ["状态用词沿用安装任务：执行中、已完成、已终止。", "只读角色不能取消任务。"],
  },
});
registerAction("task-open", ({ rack }) => { S.view["rackTab:" + rack] = "tasks"; go("rack/" + rack); });
