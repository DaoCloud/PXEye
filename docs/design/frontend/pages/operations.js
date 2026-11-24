"use strict";
/* 操作：机柜和设备的写操作，以及它们共用的门控。
   规则（设计说明书第 8、9 章）：
   - 新机柜要人“确认接入”：确认之前平台只读设备，确认之后才写入 NICo。
   - 机柜上线不是操作：确认接入后它由 NICo 的机柜状态机自动进行。页面只在它停在 Error 时提供“重新执行机柜维护”。
   - 会跨多台设备排序的电源和固件操作提交为 Flow 任务；单设备的状态类操作直接调用 Core 并读回。
   - 同一机柜同一时间只有一个进行中的任务。
   - 依赖组件缺失时操作不可用并说明原因；有整柜泄漏的机柜拒绝上电。 */

/* 机柜级门控：返回不可用的原因，空字符串表示可用。 */
function rackGate(r, kind) {
  if (!r.state) return "NICo 里还没有这个机柜的对象";
  if (DB.busy(r)) return "该机柜有进行中的任务，同一机柜同时只能有一个任务";
  if (kind === "remaint") return !S.rms ? "RMS 未就绪，机柜维护无法执行" : r.state !== "Error" ? "只在机柜停在 Error 时使用" : "";
  if (!S.flow && ["power", "firmware", "decommission"].includes(kind)) return "Flow 未就绪，机柜级任务不可用";
  if (!S.rms && ["power", "firmware"].includes(kind)) return "RMS 未就绪，电源与固件操作不可用";
  if (["power", "firmware"].includes(kind) && !["Ready", "Error"].includes(r.state)) return "NICo 正在上线，完成后可用";
  if (kind === "decommission" && DB.rackInstances(r.id).length) return "机柜上还有实例，先释放";
  return "";
}
/* 任务什么时候真正开始：会中断业务的任务先做就绪检查。把现在的检查结果和提交后的过程写在确认页上。 */
function readiness(r, what) {
  const n = DB.rackInstances(r.id).length, total = r.trays.filter((t) => t.type === "compute" && t.state).length;
  return `<div class="live-card" style="margin:14px 0 0"><h3 style="margin:0 0 8px">提交后的过程</h3><ol class="live-small" style="margin:0;padding-left:18px">
    <li><b>等待主机就绪。</b>任务先检查这个机柜的主机能不能被操作，每 5 秒查一次，最多等 30 分钟。${n ? `<b style="color:var(--red)">现在 ${total} 台里有 ${n} 台不满足：已分配给实例。</b>实例不释放，任务会一直等到超时后失败。` : `现在 ${total} 台全部满足，<b>提交后立即开始</b>。`}</li>
    <li><b>${what}。</b>按下面的步骤逐类设备执行，每一步由硬件后端完成。</li>
    <li><b>读回结果。</b>任务轮询每台设备的状态，直到成功、失败或超时；失败时停在那一步。</li></ol></div>`;
}
const RULE_NOTE = "顺序、等待时间和重试由站点的操作规则决定；站点没有自定义规则时使用 NICo 内置的默认规则。这里不填写。";

/* ---------- 机柜操作 ---------- */
registerAction("rack-admit", ({ id }) => {
  const r = DB.rack(id), got = r.trays.filter((t) => t.matched), sw = got.filter((t) => t.type === "switch").length, diff = DB.absent(r).length + DB.misplaced(r).length;
  confirmOperation({ title: "确认接入", target: id, action: `把已匹配的 ${got.length} 台设备写入 NICo`, stages: ["写入声明", "NICo 探测并接管", "交换机就绪后自动上线"], why: "到货核对完成", submit: "确认接入", sub: "这是新机柜唯一需要人点头的一步。确认之前平台只读设备，不写 NICo。",
    extra: defs([["已匹配", `${got.length} / ${r.trays.length} 台，其中交换机 ${sw} / ${PROFILE_NEED.switch}`], ["清单核对的差异", diff ? `${diff} 项，确认后仍可处理` : "没有"], ["待处理的端点", S.endpoints.length ? `${S.endpoints.length} 个，确认后匹配上的会自动写入` : "没有"]]) +
      note(`<b>确认后不能撤回。</b>NICo 接管设备时会轮换设备口令；交换机就绪后自动开始上线，依次是固件升级、NVOS 更新、上电顺序、配置 NMX-C 集群、机柜校验，开始后不能取消。${sw < PROFILE_NEED.switch ? `<br><b>现在交换机只匹配上 ${sw} 台，不到 ${PROFILE_NEED.switch} 台：确认后设备会被接管，但上线要等交换机到齐才开始。</b>` : ""}`, "warning"),
    run: (why) => { admitRack(id); addAudit(id, "确认接入", why, "—", `${got.length} 台已写入 NICo`); S.guide = Math.max(S.guide, 5); toast(`${id}：已写入 NICo，等待 NICo 接管和上线`); } });
});
registerAction("slot-fix", ({ id }) => {
  const t = DB.tray(id), r = DB.rack(t.rack), other = r.trays.find((x) => x.slot === t.seenSlot), from = t.slot;
  if (other && other.seenSlot === t.slot) { [t.slot, other.slot] = [other.slot, t.slot]; [t.id, other.id] = [other.id, t.id]; other.seenSlot = other.slot; } else t.slot = t.seenSlot;
  t.seenSlot = t.slot; r.trays.sort((a, b) => a.slot - b.slot);
  S.inventory.unshift({ v: S.inventory[0].v + 1, at: nowText(), by: "ops-01", file: "（更正槽位）", note: `${r.id} ${t.serial} 槽位 ${pad2(from)} 改为 ${pad2(t.slot)}`, why: "按实测槽位更正" });
  addAudit(`${r.id} / 槽位 ${pad2(t.slot)}`, "按实测更正清单", "实测槽位与清单不同", "—", "清单已更新"); toast("清单已按实测槽位更正"); render();
});
registerAction("rack-remaint", ({ id }) => {
  const r = DB.rack(id);
  confirmOperation({ title: "重新执行机柜维护", target: id, action: "让 NICo 从头再走一遍上线的各个阶段", stages: STAGES.bringup, why: "故障原因已消除", submit: "重新执行",
    extra: note("机柜停在 Error 后不会自己恢复。重新执行前先确认上次失败的原因已经消除：" + esc(r.reason || "见状态历史") + "。"),
    run: (why) => { addAudit(id, "重新执行机柜维护", why, "—", "已提交，机柜离开 Error"); setRackState(r, "Maintenance(FirmwareUpgrade)"); r.bring = null; coreBringup(r); } });
});
registerAction("rack-power", ({ id }) => {
  const r = DB.rack(id), p = DB.power(r), allOn = p.on === p.known, allOff = p.on === 0;
  const opt = (v, name, text, checked) => `<label><input type="radio" name="power" value="${v}" ${checked ? "checked" : ""}> <b>${name}</b><small>${text}</small></label>`;
  modal("机柜电源", `${id} 成员电源：${p.text}`,
    `<div class="choice-cards">${allOff ? "" : opt("off", "下电", "计算托盘 → 交换机 → 供电框", allOn)}${allOff ? "" : opt("cycle", "重启", "按下电顺序全部断电，再按上电顺序全部上电，包括供电框", false)}${allOn ? "" : opt("on", "上电", "供电框 → 交换机 → 计算托盘", allOff)}</div>
     ${!allOn && !allOff ? note("成员的电源状态不一致。提交前先确认要的是上电还是下电。", "warning") : ""}${note(RULE_NOTE)}`,
    button("取消", "close") + button("下一步", "rack-power-next", true, `data-id="${id}"`), { wide: false });
});
registerAction("rack-power-next", ({ id }) => {
  const r = DB.rack(id), picked = document.querySelector("[name=power]:checked"), n = DB.rackInstances(id).length;
  if (!picked) return toast("先选择一个动作");
  const pick = picked.value;
  if (pick === "on" && DB.leak(id)) {
    return modal("上电被拒绝", id, note(`<b>${id} 有整柜泄漏告警。</b>有泄漏的机柜不能上电。请先由设施侧确认并清除告警；平台不提供跳过检查的入口。`, "error"), button("查看告警", "close-go", false, 'data-to="health"') + button("关闭", "close", true), { wide: false });
  }
  const cfg = { off: ["机柜下电", "正常下电", STAGES.power_off, "Off"], on: ["机柜上电", "上电", STAGES.power_on, "On"], cycle: ["机柜重启", "全部断电后重新上电", STAGES.power_cycle, "On"] }[pick];
  confirmOperation({ title: cfg[0], target: id, action: cfg[1], stages: cfg[2], instances: pick === "on" ? 0 : n, high: pick !== "on", confirmText: id, extra: pick === "on" ? "" : readiness(r, cfg[1]),
    run: (why) => { startTask(id, "power", cfg[0], cfg[2], { why, onDone: () => r.trays.forEach((t) => t.state && (t.power = cfg[3])), readback: () => "成员电源：" + DB.power(r).text }); S.view["rackTab:" + id] = "tasks"; } });
});
registerAction("close-go", ({ to }) => { closeModal(); go(to); });
const baselinePicker = (current) => `<div class="live-form">${field("固件基线", `<select class="input" id="op-pick">${BASELINES.map((b) => `<option ${b.id === BASELINES[0].id ? "selected" : ""}>${b.id}</option>`).join("")}</select>`, "只能选择基线，不能填写任意版本。当前：" + (current || "—"))}</div>`;
registerAction("rack-firmware", ({ id }) => {
  const r = DB.rack(id), n = DB.rackInstances(id).length;
  confirmOperation({ title: "固件更新", target: id, action: "按固件基线更新计算托盘和交换机", stages: STAGES.firmware, instances: n, high: n > 0, confirmText: id,
    extra: baselinePicker(r.baseline) + readiness(r, "刷写固件") + note("刷写完成后不会自动断电重启；需要重启才生效的部件，另外提交一次机柜重启。供电框的固件不在这个操作里。"),
    run: (why, pick) => { startTask(id, "firmware", "固件更新 → " + pick, STAGES.firmware, { why, onDone: () => { r.baseline = pick; r.trays.forEach((t) => t.state && (t.baseline = pick)); }, readback: () => "版本与 " + pick + " 相同" }); S.view["rackTab:" + id] = "tasks"; } });
});
registerAction("rack-validate", ({ id }) => {
  const r = DB.rack(id), open = DB.absent(r).length;
  addAudit(id, "期望与实际校验", "例行核对", "—", open ? open + " 项差异" : "无差异");
  toast(open ? `校验完成：${open} 项差异，见清单核对` : "校验完成：期望与实际一致"); S.view["rackTab:" + id] = "check"; render();
});
registerAction("rack-decommission", ({ id }) => {
  confirmOperation({ title: "机柜退役", target: id, action: "退役整柜并从清单移除", stages: STAGES.decommission, high: true, confirmText: id,
    run: (why) => startTask(id, "decommission", "机柜退役", STAGES.decommission, { why, onDone: () => { S.domains = S.domains.filter((d) => d.rack !== id); S.racks = S.racks.filter((x) => x.id !== id); S.inventory.unshift({ v: S.inventory[0].v + 1, at: nowText(), by: "ops-01", file: "（机柜退役）", note: "移除 " + id, why }); go("racks"); }, readback: () => "对象已退役" }) });
});
registerAction("task-cancel", ({ id }) => { cancelTask(id); render(); });
registerAction("discovery-rack", ({ rack }) => { S.view.dsRack = rack; S.view.dsRes = ""; go("discovery"); });

/* ---------- 设备操作目录 ----------
   名称与现有产品的操作对话框一致。via: "Flow" 提交为任务；"Core" 立即执行并读回。 */
const TRAY_ACTIONS = [
  { id: "power-on", label: "上电", types: ["compute", "switch", "power_shelf"], risk: "中", via: "Flow", rms: true, guard: (t) => (t.power === "On" ? "已是开机状态" : DB.leak(t.rack) ? "机柜有整柜泄漏告警，拒绝上电" : ""), apply: (t) => (t.power = "On"), readback: "读回电源：开机" },
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
  { id: "decommission", label: "退役", types: ["switch", "power_shelf"], risk: "高", via: "Core", guard: (t) => (!/Ready$/.test(t.state) ? "设备要在 Ready 状态" : DB.rack(t.rack).trays.some((x) => x.instance) ? "机柜上还有已分配的计算托盘，先释放实例" : ""), apply: (t) => { t.state = "Decommissioning"; t.health = "none"; }, readback: "已提交，设备进入退役流程；完成后在这里消失" },
];
/* 逐个目标的检查，对应现有产品的“服务端预览”：先让装机，再看生命周期状态。 */
function trayCheck(t, a) {
  if (!t.state || /Decommission/.test(t.state)) return "NICo 中没有可操作的对象";
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
     <div class="confirm-facts" style="margin-top:14px">${defs([["执行路径", a.via === "Flow" ? "提交为任务，由 NICo 编排、硬件后端执行" : "立即执行，并读回结果"], ["受影响的实例", affected ? `<b style="color:var(--red)">${affected} 个</b>${type !== "compute" ? "（按整柜计算）" : ""}` : "0 个"], ...(stages.length ? [["将经过的步骤", esc(stages.join(" → "))]] : []), ...(a.unknown ? [["结果", "NICo 没有读回方式，结果记为未知，不自动重发"]] : [])])}</div>
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

/* ---------- 模拟控制（只在设计稿中存在） ---------- */
registerAction("sim-discover", () => { if (simulateDiscovery("RACK-A03")) { S.guide = 4; S.view["rackTab:RACK-A03"] = "check"; toast("RACK-A03 已通电：32 台匹配上清单，新增 2 个待处理的端点。确认接入后才写入 NICo"); go("discovery"); } });
/* 整柜泄漏：NICo 自动对整柜强制下电，页面只是如实显示。告警清除后设备保持关机。 */
registerAction("sim-leak", () => {
  const r = DB.rack("RACK-A01");
  if (S.leak) { S.leak = false; toast("泄漏告警已清除。设备保持关机，需要提交上电"); return render(); }
  S.leak = r.id; S.leakAt = nowText(); if (r.task && r.task.timer) clearInterval(r.task.timer);
  r.trays.forEach((t) => t.state && (t.power = "Off"));
  const t = { id: "task-" + String(++S.taskSeq).padStart(4, "0"), kind: "power", label: "强制下电（泄漏处理）", target: r.id, stages: STAGES.force_off.map((n) => ({ n, s: "done" })), status: "已完成", by: "NICo 自动", at: nowText(), end: nowText(), reason: "机柜级泄漏" };
  r.tasks.unshift(t); r.task = t; addAudit(r.id, t.label, t.reason, t.id, "成员全部关机").by = "NICo 自动";
  toast("RACK-A01 发生整柜泄漏：NICo 已自动强制下电"); render();
});
registerAction("sim-rms", () => { S.rms = !S.rms; toast(S.rms ? "RMS 已恢复" : "RMS 不可用：电源与固件操作被禁用"); render(); });
registerAction("sim-flow", () => { S.flow = !S.flow; toast(S.flow ? "Flow 已恢复" : "Flow 不可用：机柜级任务被禁用"); render(); });
registerAction("sim-reset", () => { S.racks.forEach((r) => { if (r.task) clearInterval(r.task.timer); if (r.bring && r.bring.timer) clearInterval(r.bring.timer); }); const keep = Object.fromEntries(Object.entries(S.view).filter(([k]) => k.startsWith("nav:") || ["guide", "guideWide", "annotate", "guideTab", "lastPage"].includes(k))); S = freshState(); Object.assign(S.view, keep); go("racks"); toast("示例数据已重置"); });
