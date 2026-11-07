"use strict";
const releaseLabels = {
  accepted: "回收请求已接受",
  unknown: "请求结果待核对",
  preparing: "实例已移除，设备准备中",
  needs_attention: "设备回收失败，需处理",
  completed: "回收完成",
};
const instanceButton = (text, action, id, extra = "") =>
  `<button class="button" data-instance-action="${action}" data-id="${esc(id)}" ${extra}>${esc(text)}</button>`;
async function loadInstances() {
  state.instances = await api("/api/instances");
}
function instanceOperationPending() {
  return Boolean(
    state.instances?.releases.some((r) => r.status !== "completed"),
  );
}
function instanceDisks(disks) {
  return table(
    ["磁盘序列号", "型号", "容量"],
    disks.map(
      (d) =>
        `<tr><td class="live-code">${esc(d.serial || "未回报")}</td><td>${esc(d.model || "未回报")}</td><td>${d.size_mb ? esc((d.size_mb / 1024).toFixed(1)) + " GiB" : "未回报"}</td></tr>`,
    ),
  );
}
function instanceMatches(i) {
  const query = (state.instanceQuery || "").trim().toLowerCase();
  return (
    !query ||
    [i.name, i.id, i.serial, i.hostname, ...i.addresses]
      .join(" ")
      .toLowerCase()
      .includes(query)
  );
}
function instancesPage() {
  const data = state.instances;
  let body = heading(
    "实例管理",
    "查看实例分配，删除实例并回收设备。",
    button("刷新数据", "refresh"),
  );
  if (!data) return body + '<div class="live-empty">正在读取 NICo 实例…</div>';
  if (data.warning) body += `<div class="live-note">${esc(data.warning)}</div>`;
  body += `<div class="live-tools"><label>搜索实例 <input class="input" id="instance-search" value="${esc(state.instanceQuery || "")}" placeholder="名称、ID、SN、主机名、IP" aria-label="搜索实例"></label><span class="live-small">${data.instances.length} 个当前实例 · 查询时间 ${when(data.checked_at)}</span></div>`;
  body += `<div id="instance-rows">${table(
    [
      "实例名称 / ID",
      "设备 SN / 主机名",
      "NICo 实例地址 / OS",
      "机器状态 / 回收进度",
      "操作",
    ],
    data.instances.map(
      (i) =>
        `<tr data-instance-row="${esc(i.id)}" ${instanceMatches(i) ? "" : "hidden"}><td><button class="link-button" data-instance-action="detail" data-id="${esc(i.id)}">${esc(i.name)}</button><span class="live-small live-code">${esc(i.id)}</span></td><td>${esc(i.serial || "尚未回报 SN")}<span class="live-small">${esc(i.hostname || "未配置")} · ${esc(i.hostname_source)}</span></td><td>${esc(i.addresses.join("、") || "尚未分配")}<span class="live-small">${esc(i.os_name)}</span></td><td>${esc(i.machine_state)}${i.release ? `<span class="live-small">${esc(releaseLabels[i.release.status])}</span>` : ""}</td><td>${instanceButton("详情", "detail", i.id)} ${instanceButton("删除（退租回收）", "delete", i.id, i.delete_allowed ? "" : `disabled title="${esc(i.delete_reason)}"`)}${i.delete_reason ? `<span class="live-small">${esc(i.delete_reason)}</span>` : ""}</td></tr>`,
    ),
  )}</div><div id="instance-no-match" class="live-empty" ${!data.instances.length || data.instances.some(instanceMatches) ? "hidden" : ""}>未找到匹配的实例。</div>`;
  if (data.releases.length)
    body += `<section class="subsection"><h2>回收记录</h2>${table(
      ["实例 / 设备", "提交时间", "进度", "操作"],
      data.releases.map(
        (r) =>
          `<tr><td>${esc(r.name)}<span class="live-small live-code">${esc(r.id)} · ${esc(r.serial)}</span></td><td>${when(r.requested_at)}</td><td>${badge(releaseLabels[r.status] || r.status, r.status === "needs_attention" ? "red" : r.status === "completed" ? "green" : "amber")}<span class="live-small">${esc(r.detail || r.machine_state || "")}</span></td><td>${instanceButton("查看记录", "detail", r.id)}</td></tr>`,
      ),
    )}</section>`;
  return (
    body +
    '<div class="live-note">删除实例可能重启设备并清理全部磁盘；回收完成前请勿使用设备。</div>'
  );
}
function releaseRecord(r) {
  return r
    ? defs([
        ["回收进度", esc(releaseLabels[r.status] || r.status)],
        ["说明", esc(r.detail)],
        ["提交时间 / 操作员", when(r.requested_at) + " / " + esc(r.actor)],
        ["最近查询", when(r.checked_at)],
        ["Machine 状态", esc(r.machine_state || "等待核对")],
      ])
    : "";
}
function instanceFacts(i) {
  return (
    defs([
      [
        "实例名称 / ID",
        esc(i.name) +
          '<span class="live-small live-code">' +
          esc(i.id) +
          "</span>",
      ],
      ["设备 SN", esc(i.serial || "尚未回报")],
      ["主机名", esc(i.hostname || "未配置") + " · " + esc(i.hostname_source)],
      [
        "实例地址 / OS",
        esc(i.addresses.join("、") || "尚未分配") + " / " + esc(i.os_name),
      ],
      ["Machine ID", `<span class="live-code">${esc(i.machine_id)}</span>`],
      ["Machine 状态", esc(i.machine_state)],
      ["租户", esc(i.tenant)],
      [
        "配置版本",
        Object.entries(i.versions)
          .filter(([, v]) => v)
          .map(
            ([k, v]) => `<span class="live-small">${esc(k)}: ${esc(v)}</span>`,
          )
          .join(""),
      ],
    ]) +
    `<section class="subsection"><h3>磁盘 · 最近 Scout 回报</h3><p class="live-small">最近采集记录；回收清理范围为本机全部磁盘。</p>${instanceDisks(i.disks)}</section>`
  );
}
async function instanceDialog(id, remove = false) {
  const w = { resource: remove ? "instance-release" : "instance-detail", id };
  state.wizard = w;
  state.detail = null;
  modal(
    remove ? "删除实例（退租回收）" : "实例详情",
    id,
    '<div class="live-empty">正在读取实例、设备信息及最近 Scout 磁盘清单…</div>',
    button("关闭", "close"),
  );
  let result;
  try {
    result = await api("/api/instances/" + encodeURIComponent(id));
  } catch (error) {
    if (state.wizard === w)
      modal(
        "实例读取失败",
        id,
        `<div class="live-error">${esc(error.message)}</div>`,
        instanceButton("重新读取", remove ? "delete" : "detail", id) +
          button("关闭", "close"),
      );
    return;
  }
  if (state.wizard !== w) return;
  const i = result.instance;
  w.instance = i;
  if (!i) {
    modal(
      "实例回收记录",
      id,
      releaseRecord(result.release) +
        instanceDisks(result.release?.disks || []),
      instanceButton("刷新记录", "detail", id) + button("关闭", "close"),
    );
    return;
  }
  let body =
      (remove
        ? defs([
            [
              "设备 SN / 主机名",
              esc(i.serial) + " / " + esc(i.hostname || "未配置"),
            ],
            [
              "实例名称 / ID",
              esc(i.name) +
                '<span class="live-small live-code">' +
                esc(i.id) +
                "</span>",
            ],
            [
              "实例地址 / 机器状态",
              esc(i.addresses.join("、") || "尚未分配") +
                " / " +
                esc(i.machine_state),
            ],
          ]) +
          `<section class="subsection"><h3>回收磁盘 · 最近 Scout 回报</h3>${instanceDisks(i.disks)}</section>`
        : instanceFacts(i)) + releaseRecord(result.release),
    foot = button("关闭", "close");
  if (remove && i.delete_allowed) {
    body =
      `<div class="live-note live-warning">删除将回收实例及关联资源，可能重启设备并清理全部磁盘。现有系统和数据可能丢失；设备规划与安装历史保留。</div>` +
      body +
      `<div class="live-form"><label for="instance-confirm-serial">输入设备 SN 确认范围<input class="input" id="instance-confirm-serial" autocomplete="off" placeholder="${esc(i.serial)}"></label><label class="live-check"><input type="checkbox" id="instance-confirm-cleanup">允许清理本机全部磁盘并回收实例资源。</label></div><div id="resource-error" class="live-error" role="alert"></div>`;
    foot =
      button("取消", "close") +
      instanceButton(
        "确认删除并回收",
        "submit",
        id,
        'id="instance-release-submit" disabled',
      );
  } else if (!i.delete_allowed) {
    body += `<div class="live-note">${esc(i.delete_reason)}</div>`;
    foot = instanceButton("刷新详情", "detail", id) + foot;
  } else foot = instanceButton("删除（退租回收）", "delete", id) + foot;
  modal(
    remove ? "删除实例（退租回收）" : "实例详情",
    i.serial || i.id,
    body,
    foot,
  );
}
function updateInstanceSubmit() {
  const b = $("#instance-release-submit");
  if (!b) return;
  b.disabled =
    Boolean(state.wizard?.sending) ||
    !(
      $("#instance-confirm-serial")?.value === state.wizard?.instance?.serial &&
      $("#instance-confirm-cleanup")?.checked
    );
}
async function submitInstanceRelease() {
  const w = state.wizard;
  if (w?.resource !== "instance-release" || w.sending) return;
  if (
    $("#instance-confirm-serial")?.value !== w.instance.serial ||
    !$("#instance-confirm-cleanup")?.checked
  )
    return;
  w.sending = true;
  updateInstanceSubmit();
  // Freeze the confirmation once submitted; timeout must never invite an automatic replay.
  $("#instance-confirm-serial").disabled = true;
  $("#instance-confirm-cleanup").disabled = true;
  try {
    const r = await api(
      "/api/instances/" + encodeURIComponent(w.id) + "/release",
      {
        revision: w.instance.revision,
        confirm_serial: w.instance.serial,
        confirm_cleanup: true,
      },
    );
    if (state.wizard === w) {
      modal(
        "实例回收进度",
        w.instance.serial,
        releaseRecord(r),
        instanceButton("查询回收进度", "detail", w.id) +
          button("关闭", "close"),
      );
    }
    await refreshPage("instances");
  } catch (error) {
    if (state.wizard === w)
      modal(
        "请核对回收结果",
        w.instance.serial,
        `<div class="live-error">${esc(error.message)}</div><p>请查询回收结果，避免重复删除。</p>`,
        instanceButton("查询当前结果", "detail", w.id) +
          button("关闭", "close"),
      );
  }
}
observeUI(
  "input",
  "instances.js",
  (e) => {
    if (e.target.id === "instance-search") {
      state.instanceQuery = e.target.value;
      document.querySelectorAll("[data-instance-row]").forEach((row) => {
        const i = state.instances.instances.find(
          (i) => i.id === row.dataset.instanceRow,
        );
        row.hidden = !instanceMatches(i);
      });
      $("#instance-no-match").hidden =
        !state.instances.instances.length ||
        state.instances.instances.some(instanceMatches);
    }
    updateInstanceSubmit();
  },
  false,
);
observeUI("change", "instances.js", updateInstanceSubmit, false);
observeUI(
  "click",
  "instances.js",
  async (e) => {
    const b = e.target.closest("[data-instance-action]");
    if (!b || b.disabled) return;
    try {
      if (b.dataset.instanceAction === "submit") await submitInstanceRelease();
      else
        await instanceDialog(
          b.dataset.id,
          b.dataset.instanceAction === "delete",
        );
    } catch (error) {
      toast(error.message);
    }
  },
  false,
);
