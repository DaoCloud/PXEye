"use strict";
/* 操作：机柜、NVLink 域、设备的写操作，以及它们共用的门控。
   规则（设计说明书第 8、9 章）：
   - 会跨多台设备排序的操作提交为 Flow 任务；单设备的状态类操作直接调用 Core 并读回。
   - 同一机柜同一时间只有一个进行中的任务。
   - 依赖组件缺失时操作不可用并说明原因；有泄漏告警的机柜拒绝上电。 */

/* 机柜级门控：返回不可用的原因，空字符串表示可用。 */
function rackGate(r, kind) {
  if (DB.busy(r)) return "该机柜有进行中的任务，同一机柜同时只能有一个任务";
  if (!S.flow && ["bringup", "power", "firmware", "decommission"].includes(kind)) return "Flow 未就绪，机柜级任务不可用";
  if (!S.rms && ["bringup", "power", "firmware"].includes(kind)) return "RMS 未就绪，电源与固件操作不可用";
  if (kind === "bringup") {
    if (r.state === "Created") return "等待通电与发现";
    if (DB.blockers(r).length) return `对账还有 ${DB.blockers(r).length} 项阻塞`;
    if (r.state === "Ready") return "机柜已就绪";
    if (["Maintenance", "Validating"].includes(r.state)) return "机柜正在上线或维护";
  }
  if (["power", "firmware"].includes(kind) && !["Ready", "Error"].includes(r.state)) return "机柜上线完成后可用";
  if (kind === "decommission" && DB.rackInstances(r.id).length) return "机柜上还有实例，先释放";
  return "";
}

/* ---------- 机柜操作 ---------- */
registerAction("rack-bringup", ({ id }) => {
  const r = DB.rack(id);
  confirmOperation({ title: "开始上线", target: `${id}（${r.domain}）`, action: "机柜上线：固件、NVOS、NMX-C 配置与机柜校验", stages: STAGES.bringup, why: "新机柜上线",
    run: (why) => {
      setRackState(r, "Maintenance");
      startTask(id, "bringup", "机柜上线", STAGES.bringup, { why,
        onStage: (n) => { if (n === "机柜校验") setRackState(r, "Validating"); },
        onDone: () => { setRackState(r, "Ready"); r.power = "On"; r.baseline = BASELINES[0].id; r.trays.forEach((t) => (t.baseline = BASELINES[0].id)); S.guide = Math.max(S.guide, 6); } });
      S.view["rackTab:" + id] = "tasks";
    } });
});
registerAction("rack-power", ({ id }) => {
  const r = DB.rack(id), on = r.power === "On";
  modal("机柜电源", `${id} 当前电源：${powerText(r.power)}`,
    `<div class="choice-cards">${on
      ? `<label><input type="radio" name="power" value="off" checked> <b>下电</b><small>计算托盘 → 交换机 → 供电框</small></label><label><input type="radio" name="power" value="cycle"> <b>重启</b><small>正常重启柜内计算托盘与 交换机</small></label>`
      : `<label><input type="radio" name="power" value="on" checked> <b>上电</b><small>供电框 → 泄漏检查 → 交换机 → 计算托盘</small></label>`}</div>
     ${note("电源顺序、等待时间和重试属于站点规则 <b>" + (on ? "graceful-power-off" : "graceful-power-on") + "</b>，不在这里填写。")}`,
    button("取消", "close") + button("下一步", "rack-power-next", true, `data-id="${id}"`), { wide: false });
});
registerAction("rack-power-next", ({ id }) => {
  const r = DB.rack(id), pick = document.querySelector("[name=power]:checked").value, n = DB.rackInstances(id).length;
  if (pick === "on" && DB.preventAlloc(id) && S.leak) {
    return modal("上电被拒绝", id, note(`<b>${id} 有泄漏告警。</b>有泄漏告警的机柜不能上电。请先由设施侧确认并清除告警；平台不提供跳过检查的入口。`, "error"), button("查看告警", "close-go", false, 'data-to="health"') + button("关闭", "close", true), { wide: false });
  }
  const cfg = { off: ["机柜下电", "正常下电（Off）", STAGES.power_off, "Off"], on: ["机柜上电", "上电（On）", STAGES.power_on, "On"], cycle: ["机柜重启", "正常重启（Cycle）", STAGES.power_cycle, "On"] }[pick];
  confirmOperation({ title: cfg[0], target: `${id}（${r.domain}）`, action: cfg[1], stages: cfg[2], instances: pick === "on" ? 0 : n, high: pick !== "on", confirmText: id,
    run: (why) => { startTask(id, "power", cfg[0], cfg[2], { why, onDone: () => { r.power = cfg[3]; r.trays.forEach((t) => t.state && (t.power = cfg[3])); }, readback: () => "读回电源：" + powerText(cfg[3]) }); S.view["rackTab:" + id] = "tasks"; } });
});
registerAction("close-go", ({ to }) => { closeModal(); go(to); });
const baselinePicker = (current) => `<div class="live-form">${field("固件基线", `<select class="input" id="op-pick">${BASELINES.map((b) => `<option ${b.id === BASELINES[0].id ? "selected" : ""}>${b.id}</option>`).join("")}</select>`, "只能选择基线，不能填写任意版本。当前：" + (current || "—"))}</div>`;
registerAction("rack-firmware", ({ id }) => {
  const r = DB.rack(id), d = DB.domain(r.domain), n = DB.rackInstances(id).length;
  confirmOperation({ title: "固件更新", target: `${id}（${r.domain}）`, action: "按固件基线更新整柜", stages: STAGES.firmware, instances: n, high: n > 0, confirmText: id,
    extra: baselinePicker(r.baseline) + (d.racks.length > 1 ? note(`固件更新的推荐单位是 NVLink 域。<b>${d.id}</b> 还包含 ${d.racks.filter((x) => x !== id).join("、")}，只更新一个机柜会造成域内版本不一致。可在“NVLink 域管理”发起域级更新。`, "warning") : ""),
    run: (why, pick) => { startTask(id, "firmware", "固件更新 → " + pick, STAGES.firmware, { why, onDone: () => { r.baseline = pick; r.trays.forEach((t) => t.state && (t.baseline = pick)); }, readback: () => "版本符合 " + pick }); S.view["rackTab:" + id] = "tasks"; } });
});
registerAction("rack-validate", ({ id }) => {
  const r = DB.rack(id), open = r.issues.filter((i) => !i.done).length;
  addAudit(id, "期望与实际校验", "例行核对", "—", open ? open + " 项差异" : "无差异");
  toast(open ? `校验完成：${open} 项差异，见对账` : "校验完成：期望与实际一致"); S.view["rackTab:" + id] = "recon"; render();
});
registerAction("rack-decommission", ({ id }) => {
  confirmOperation({ title: "机柜退役", target: id, action: "退役整柜并从期望清单移除", stages: STAGES.decommission, high: true, confirmText: id,
    run: (why) => startTask(id, "decommission", "机柜退役", STAGES.decommission, { why, onDone: () => { const d = DB.domain(DB.rack(id).domain); d.racks = d.racks.filter((x) => x !== id); S.racks = S.racks.filter((x) => x.id !== id); S.inventory.unshift({ v: S.inventory[0].v + 1, at: nowText(), by: "ops-01", file: "（机柜退役）", note: "移除 " + id, why }); go("racks"); }, readback: () => "对象已退役" }) });
});
registerAction("task-cancel", ({ id }) => { cancelTask(id); render(); });

/* ---------- 对账问题的处理 ---------- */
registerAction("issue-fix", ({ id, issue }) => {
  const r = DB.rack(id), i = r.issues.find((x) => x.k === issue);
  const finish = (res, patch) => { resolveIssue(id, issue, patch); addAudit(`${id} / 槽位 ${pad2(i.slot)}`, i.action, i.title, "—", res); if (!DB.blockers(r).length) S.guide = Math.max(S.guide, 5); render(); toast("已处理：" + i.title); };
  if (issue !== "serial") return finish("读回一致");
  modal("更换设备", "按实物更新期望清单，NICo 会重新发现该槽位。",
    `${defs([["对象", `${id} 槽位 ${pad2(i.slot)}（${TYPE_LABEL[i.type]}）`], ["清单中的序列号", code(i.expect)], ["实测序列号", code(i.actual)]])}
     <div class="live-form" style="margin-top:16px">${field("新序列号", `<input class="input live-code" id="rp-serial" value="${esc(i.actual)}">`)}${field("新 BMC MAC", `<input class="input live-code" id="rp-mac" value="02:00:03:00:00:99">`)}${field("原因", `<input class="input" id="rp-why" value="出厂替换件，与出货单核对一致">`)}</div>`,
    button("取消", "close") + button("更新清单", "issue-replace", true, `data-id="${id}"`), { wide: false });
});
registerAction("issue-replace", ({ id }) => {
  const r = DB.rack(id), i = r.issues.find((x) => x.k === "serial"), serial = $("#rp-serial").value.trim(), mac = $("#rp-mac").value.trim(), why = $("#rp-why").value.trim();
  if (!serial || !mac || !why) return toast("序列号、BMC MAC 和原因都要填写");
  S.inventory.unshift({ v: S.inventory[0].v + 1, at: nowText(), by: "ops-01", file: "（更换设备）", note: `${id} 槽位 ${pad2(i.slot)} 序列号改为 ${serial}`, why });
  closeModal(); resolveIssue(id, "serial", { serial, bmcMac: mac }); addAudit(`${id} / 槽位 ${pad2(i.slot)}`, "更换设备", why, "—", "清单已更新，读回一致");
  if (!DB.blockers(r).length) S.guide = Math.max(S.guide, 5); render(); toast("清单已更新，设备重新发现");
});

/* ---------- 设备操作目录 ----------
   名称与现有产品的操作对话框一致。via: "Flow" 提交为任务；"Core" 立即执行并读回。 */
const TRAY_ACTIONS = [
  { id: "power-on", label: "上电", types: ["compute", "switch", "power_shelf"], risk: "中", via: "Flow", rms: true, guard: (t) => (t.power === "On" ? "已是开机状态" : S.leak && DB.preventAlloc(t.rack) ? "机柜有泄漏告警，拒绝上电" : ""), apply: (t) => (t.power = "On"), readback: "读回电源：开机" },
  { id: "power-off", label: "正常关机", types: ["compute", "switch", "power_shelf"], risk: "高", via: "Flow", rms: true, guard: (t) => (t.power !== "On" ? "已是关机状态" : ""), apply: (t) => (t.power = "Off"), readback: "读回电源：关机" },
  { id: "restart", label: "正常重启", types: ["compute", "switch"], risk: "高", via: "Flow", rms: true, guard: (t) => (t.power !== "On" ? "设备未开机" : ""), apply: () => {}, readback: "读回电源：开机" },
  { id: "firmware", label: "固件更新", types: ["compute", "switch"], risk: "高", via: "Flow", rms: true, pick: true, stages: STAGES.tray_firmware, guard: () => "", apply: (t, pick) => (t.baseline = pick), readback: "版本符合所选基线" },
  { id: "maint-on", label: "设置维护标记", types: ["compute"], risk: "低", via: "Core", guard: (t) => (t.maintenance ? "已有维护标记" : ""), apply: (t, _p, why) => (t.maintenance = why), readback: "读回维护标记" },
  { id: "maint-off", label: "清除维护标记", types: ["compute"], risk: "低", via: "Core", guard: (t) => (t.maintenance ? "" : "没有维护标记"), apply: (t) => (t.maintenance = ""), readback: "读回无维护标记" },
  { id: "quarantine-on", label: "隔离", types: ["compute"], risk: "高", via: "Core", guard: (t) => (t.quarantine ? "已隔离" : ""), apply: (t, _p, why) => (t.quarantine = why), readback: "读回隔离 BLOCK_ALL_TRAFFIC" },
  { id: "quarantine-off", label: "解除隔离", types: ["compute"], risk: "中", via: "Core", guard: (t) => (t.quarantine ? "" : "没有隔离"), apply: (t) => (t.quarantine = ""), readback: "读回未隔离" },
  { id: "validate", label: "按需硬件校验", types: ["compute"], risk: "高", via: "Core", guard: () => "", apply: (t) => t.history.push([nowText(), "Validation/Requested"]), readback: "已返回校验编号" },
  { id: "sku", label: "核对 SKU", types: ["compute"], risk: "低", via: "Core", guard: () => "", apply: () => {}, readback: "读回核对请求时间" },
  { id: "bmc-reset", label: "重启 BMC", types: ["compute", "switch"], risk: "中", via: "Core", guard: () => "", apply: () => {}, readback: "", unknown: true },
  { id: "decommission", label: "退役", types: ["switch", "power_shelf"], risk: "高", via: "Core", guard: () => "", apply: (t) => { t.state = "Decommissioned"; t.health = "none"; t.power = "Off"; }, readback: "读回已退役" },
];
/* 逐个目标的检查，对应现有产品的“服务端预览”：先让装机，再看生命周期状态。 */
function trayCheck(t, a) {
  if (!t.state || /未发现|探测失败|不符|Decommissioned/.test(t.state)) return "NICo 中没有可操作的对象";
  if (a.via === "Flow" && DB.busy(DB.rack(t.rack))) return "所在机柜有进行中的任务";
  if (a.rms && !S.rms) return "RMS 未就绪";
  if (a.via === "Flow" && !S.flow) return "Flow 未就绪";
  if (S.deliveries.some((d) => d.rack === t.rack && d.done < d.total) && a.risk !== "低") return "该设备有进行中的安装任务";
  return a.guard(t);
}
function trayOpDialog(ids, actionId) {
  const trays = ids.map(DB.tray), type = trays[0].type, options = TRAY_ACTIONS.filter((a) => a.types.includes(type)), a = options.find((x) => x.id === actionId) || options[0];
  const rows = trays.map((t) => { const why = trayCheck(t, a); return `<tr><td>${code(t.serial)}</td><td>${t.rack} / 槽位 ${pad2(t.slot)}</td><td>${stateBadge(t.state)}</td><td>${t.instance ? code(t.instance) : "—"}</td><td>${why ? badge("拒绝：" + why, "red") : badge("通过", "green")}</td></tr>`; });
  const pass = trays.filter((t) => !trayCheck(t, a)), affected = pass.filter((t) => t.instance).length + (type !== "compute" && a.risk === "高" ? new Set(pass.map((t) => t.rack)).size && [...new Set(pass.map((t) => t.rack))].reduce((n, r) => n + DB.rackInstances(r).length, 0) : 0);
  const high = a.risk === "高", confirmText = trays.length === 1 ? trays[0].serial : `${pass.length} 台`;
  const stages = a.via === "Flow" ? a.stages || STAGES.tray_power : [];
  modal(trays.length > 1 ? `批量操作（${trays.length} 台${TYPE_LABEL[type]}）` : `操作 ${trays[0].serial}`, "选对象，选动作，写原因。检查在提交时由服务端再执行一次。",
    `<div class="live-form">${field("动作", `<select class="input" id="tray-action" data-tray-action="${ids.join(",")}">${options.map((o) => `<option value="${o.id}" ${o.id === a.id ? "selected" : ""}>${o.label}（风险${o.risk}）</option>`).join("")}</select>`)}</div>
     <div class="confirm-facts" style="margin-top:14px">${defs([["执行路径", a.via === "Flow" ? "提交为任务，由 NICo 编排、硬件后端执行" : "立即执行，并读回结果"], ["受影响的实例", affected ? `<b style="color:var(--red)">${affected} 个</b>${type !== "compute" ? "（按整柜计算）" : ""}` : "0 个"], ...(stages.length ? [["将经过的阶段", esc(stages.join(" → "))]] : []), ...(a.unknown ? [["结果", "NICo 没有读回方式，结果记为未知，不自动重发"]] : [])])}</div>
     ${table(["序列号", "位置", "状态", "实例", "检查"], rows)}
     ${a.pick ? baselinePicker(trays[0].baseline) : ""}
     <div class="live-form">${field("原因", `<input class="input" id="op-why" placeholder="工单号或原因">`)}${high ? field(`高风险操作：输入 ${confirmText} 以确认`, `<input class="input live-code" id="op-confirm" autocomplete="off">`) : ""}</div>`,
    button("取消", "close") + `<button class="button ${high ? "danger" : "primary"}" data-live="tray-op-submit" data-ids="${ids.join(",")}" data-action="${a.id}" ${pass.length ? "" : "disabled title=\"没有通过检查的目标\""}>对 ${pass.length} 台执行</button>`);
  const select = $("#tray-action"); if (select) select.onchange = () => trayOpDialog(ids, select.value);
}
registerAction("tray-op", ({ id, action }) => trayOpDialog([id], action));
registerAction("tray-batch", () => {
  const current = (PAGES[route().id] || {}).module, ids = Object.keys(S.view.checked || {}).filter((k) => S.view.checked[k] && DB.tray(k) && DB.tray(k).type === current);
  if (!ids.length) return toast("先勾选设备");
  if (ids.length > 10) return toast("一次最多 10 台");
  if (new Set(ids.map((i) => DB.tray(i).type)).size > 1) return toast("批量操作只能选择同一类型的设备");
  trayOpDialog(ids);
});
registerAction("tray-op-submit", ({ ids, action }) => {
  const a = TRAY_ACTIONS.find((x) => x.id === action), trays = ids.split(",").map(DB.tray), pass = trays.filter((t) => !trayCheck(t, a));
  const why = $("#op-why").value.trim(), pick = $("#op-pick") ? $("#op-pick").value : "", confirmText = trays.length === 1 ? trays[0].serial : `${pass.length} 台`;
  if (!why) return toast("请填写原因");
  if (a.risk === "高" && $("#op-confirm").value.trim() !== confirmText) return toast("输入的内容与对象不一致");
  closeModal();
  if (a.via === "Flow") {
    /* Flow 按机柜拆分任务：每个机柜一个任务。 */
    [...new Set(pass.map((t) => t.rack))].forEach((rackId) => {
      const mine = pass.filter((t) => t.rack === rackId);
      startTask(rackId, "tray", `${a.label}（${mine.length} 台${TYPE_LABEL[mine[0].type]}）`, a.stages || STAGES.tray_power, { why, target: mine.length === 1 ? `${rackId} / 槽位 ${pad2(mine[0].slot)}` : `${rackId} / ${mine.length} 台`, onDone: () => mine.forEach((t) => a.apply(t, pick, why)), readback: () => a.readback });
    });
    toast(`已提交 ${new Set(pass.map((t) => t.rack)).size} 个任务`);
  } else {
    pass.forEach((t) => { a.apply(t, pick, why); addAudit(`${t.rack} / 槽位 ${pad2(t.slot)}`, a.label, why, "—", a.unknown ? "未知：NICo 无读回方式，未自动重发" : a.readback); });
    toast(a.unknown ? `${a.label}已发送，结果未知` : `${a.label}完成，读回一致`);
  }
  S.view.checked = {}; S.guide = Math.max(S.guide, 9); render();
});

/* ---------- NVLink 域操作：域级固件按机柜分阶段发布 ---------- */
registerAction("domain-firmware", ({ id }) => {
  const d = DB.domain(id), racks = d.racks.map(DB.rack), n = racks.reduce((s, r) => s + DB.rackInstances(r.id).length, 0);
  const gate = racks.map((r) => rackGate(r, "firmware")).find(Boolean);
  if (gate) return toast("暂不可用：" + gate);
  confirmOperation({ title: "域级固件更新", target: `${id}（${d.racks.join("、")}）`, action: "分阶段发布：先一个机柜，成功后再更新其余机柜", stages: d.racks.map((r, i) => `第 ${i + 1} 批 ${r}`), instances: n, high: true, confirmText: id,
    extra: baselinePicker(racks.map((r) => r.baseline).join(" / ")) + note("每批并发 1 个机柜；任一机柜失败后自动停止后续批次。已完成的机柜不回滚。"),
    run: (why, pick) => {
      const ro = { id: "run-" + String(S.rollouts.length + 1).padStart(3, "0"), domain: id, baseline: pick, at: nowText(), by: "ops-01", why, phases: d.racks.map((r) => ({ rack: r, status: "等待" })), status: "执行中" };
      S.rollouts.unshift(ro); addAudit(id, "域级固件更新 → " + pick, why, ro.id, "已提交");
      const next = (i) => {
        if (i >= ro.phases.length) { ro.status = "已完成"; S.audit.find((a) => a.task === ro.id).res = "成功，域内版本一致"; toast(id + "：域级固件更新完成"); S.guide = Math.max(S.guide, 10); return render(); }
        const ph = ro.phases[i], r = DB.rack(ph.rack); ph.status = "执行中";
        startTask(ph.rack, "firmware", "固件更新 → " + pick, STAGES.firmware, { why: `${ro.id} 第 ${i + 1} 批`, onDone: () => { r.baseline = pick; r.trays.forEach((t) => t.state && (t.baseline = pick)); ph.status = "已完成"; setTimeout(() => next(i + 1), 300); }, readback: () => "版本符合 " + pick });
      };
      next(0);
    } });
});
registerAction("domain-power", ({ id }) => {
  const d = DB.domain(id), racks = d.racks.map(DB.rack), off = racks.every((r) => r.power === "On"), n = racks.reduce((sum, r) => sum + DB.rackInstances(r.id).length, 0);
  if (!off && racks.some((r) => S.leak && DB.preventAlloc(r.id))) return toast("域内有机柜存在泄漏告警，拒绝上电");
  const targets = off ? racks : racks.filter((r) => r.power !== "On"), stages = off ? STAGES.power_off : STAGES.power_on;
  confirmOperation({ title: off ? "域级下电" : "域级上电", target: `${id}（${targets.map((r) => r.id).join("、")}）`, action: off ? "逐个机柜正常下电" : "逐个机柜上电", stages: targets.map((r, i) => `第 ${i + 1} 个 ${r.id}`), instances: off ? n : 0, high: off, confirmText: id,
    extra: note(`每个机柜一个任务，前一个完成后才开始下一个。机柜内的顺序由站点规则 <b>${off ? "graceful-power-off" : "graceful-power-on"}</b> 决定。`),
    run: (why) => {
      const next = (i) => { if (i >= targets.length) return; const r = targets[i];
        startTask(r.id, "power", off ? "机柜下电" : "机柜上电", stages, { why: `${id} 域级电源 · ${why}`, onDone: () => { r.power = off ? "Off" : "On"; r.trays.forEach((t) => t.state && (t.power = r.power)); setTimeout(() => next(i + 1), 300); }, readback: () => "读回电源：" + (off ? "关机" : "开机") }); };
      next(0); go("tasks");
    } });
});

/* ---------- 模拟控制（只在设计稿中存在） ---------- */
registerAction("sim-discover", () => { if (simulateDiscovery("RACK-A03")) { S.guide = 4; S.view["rackTab:RACK-A03"] = "recon"; S.view.dsRack = "RACK-A03"; toast("RACK-A03：NICo 已发现 32/35 台设备"); go("discovery"); } });
registerAction("sim-leak", () => {
  S.leak = !S.leak; const t = DB.tray("RACK-A01/11");
  t.alerts = S.leak ? [{ id: "LeakDetected", msg: "托盘泄漏传感器报警（设施侧事件同时到达）", since: nowText(), block: true }] : []; t.health = S.leak ? "bad" : "ok";
  toast(S.leak ? "已触发泄漏告警（RACK-A01 槽位 11）" : "泄漏告警已清除"); render();
});
registerAction("sim-rms", () => { S.rms = !S.rms; toast(S.rms ? "RMS 已恢复" : "RMS 不可用：电源与固件操作被禁用"); render(); });
registerAction("sim-flow", () => { S.flow = !S.flow; toast(S.flow ? "Flow 已恢复" : "Flow 不可用：机柜级任务被禁用"); render(); });
registerAction("sim-reset", () => { S.racks.forEach((r) => r.task && clearInterval(r.task.timer)); const keep = Object.fromEntries(Object.entries(S.view).filter(([k]) => k.startsWith("nav:") || ["guide", "guideWide", "annotate", "guideTab", "lastPage"].includes(k))); S = freshState(); Object.assign(S.view, keep); go("racks"); toast("示例数据已重置"); });
