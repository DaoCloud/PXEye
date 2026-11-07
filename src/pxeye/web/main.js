"use strict";
function tasksPage() {
  return (
    heading(
      "安装任务",
      "创建装机任务，查看进度、日志和结果。",
      button("刷新数据", "refresh") +
        button(
          "新建安装任务",
          "batch-new",
          true,
          state.resources ? "" : "disabled",
        ),
    ) +
    batchSummary() +
    `` +
    table(
      [
        "任务 / 创建时间",
        "设备 / 管理地址",
        "目标主机名",
        "阶段 / 状态",
        "BMC 控制台",
        "操作",
      ],
      taskRows(),
    )
  );
}
registerPage("topology", topologyPage);
registerPage("tasks", tasksPage);
registerPage("devices", devicePage);
registerPage("instances", instancesPage);
registerPage("os", osPage);
registerPage("network", networkPage);
registerPage("profiles", profilePage);
registerPage("site", sitePage);
observeUI("click", "navigation", async (e) => {
  const page = e.target.closest("[data-page]");
  if (page) {
    await navigate(page.dataset.page);
    return;
  }
  const task = e.target.closest("[data-task]");
  if (task) await detail(task.dataset.task);
});
startApplication();
