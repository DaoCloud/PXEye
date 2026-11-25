"use strict";
/* 操作：机柜和设备的写操作，以及它们共用的门控。
   规则（设计说明书第 8、9 章）：
   - 机柜页只放 NICo 在机柜对象上定义的操作：上线、电源、固件、期望与实际校验、机柜维护（重新执行、终止）、删除机柜。
     “登记机柜”把机柜声明和成员关系写入 NICo：设备的纳管在设备发现里逐台或批量完成，机柜自身只有一条机柜声明。装系统是逐台机器的事，不是机柜的操作。
   - 交换机就绪后的机柜维护不是任务：它由 NICo 的机柜状态机自动进行。进行中可以终止，终止后机柜停在 Error；停在 Error 时提供“重新执行机柜维护”。
   - 会跨多台设备排序的电源和固件操作提交为 Flow 任务；单设备的状态类操作直接调用 Core 并读回。
   - 同一机柜同一时间只有一个进行中的任务。
   - 依赖组件缺失时操作不可用并说明原因；有整柜泄漏的机柜拒绝上电。 */

/* 机柜级门控：返回不可用的原因，空字符串表示可用。 */
function rackGate(r, kind) {
  if (kind === "bringup") return !r.admit ? "先登记机柜" : r.up ? "已经上线过" : DB.busy(r) ? "该机柜有进行中的任务" : !S.flow ? "Flow 未就绪，上线任务不可用" : !S.rms ? "RMS 未就绪，无法上电" : "";
  if (!r.state) return r.admit ? "机柜还没有上线" : "NICo 里还没有这个机柜的对象";
  if (DB.busy(r)) return "该机柜有进行中的任务，同一机柜同时只能有一个任务";
  if (kind === "remaint") return !S.rms ? "RMS 未就绪，机柜维护无法执行" : r.state !== "Error" ? "只在机柜停在 Error 时使用" : "";
  if (kind === "terminate") return /^Maintenance/.test(r.state) ? "" : "只在机柜处于维护阶段时可以终止";
  if (!S.flow && ["power", "firmware"].includes(kind)) return "Flow 未就绪，机柜级任务不可用";
  if (!S.rms && ["power", "firmware"].includes(kind)) return "RMS 未就绪，电源与固件操作不可用";
  if (["power", "firmware"].includes(kind) && !["Ready", "Error"].includes(r.state)) return "机柜正在上线，完成后可用";
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
/* 登记机柜：整柜新增的一步。设备的纳管在“设备发现”里逐台或批量完成，规划在“设备管理”里一键匹配进设备配置；
   这里把机柜声明写入 NICo，并把本柜已纳管、已匹配的成员带上机柜和槽位：交换机和供电框这时才同步为 NICo 声明。 */
registerAction("rack-admit", ({ id }) => {
  const r = DB.rack(id), got = DB.placed(r), by = (type) => got.filter((t) => t.type === type).length, loose = r.trays.filter((t) => t.declared && !t.placed).length, miss = r.trays.filter((t) => !t.declared).length;
  confirmOperation({ title: "登记机柜", target: id, action: `把机柜声明写入 NICo，并带上已纳管、已匹配规划的 ${got.length} 台成员`, stages: ["写入机柜声明", "同步交换机和供电框的声明", "更新计算托盘声明里的机柜和槽位"], why: "到货核对完成", submit: "登记机柜", sub: "登记只是把机柜和成员关系告诉 NICo：不上电、不动磁盘、不装系统。",
    extra: defs([["带上的成员", `${got.length} / ${r.trays.length} 台：计算托盘 ${by("compute")}、交换机 ${by("switch")} / ${PROFILE_NEED.switch}、供电框 ${by("power_shelf")}`], ["已纳管、还没有一键匹配", loose ? `${loose} 台，这次不带上；匹配之后会自动补进这个机柜` : "没有"], ["规划里有、还没有纳管", miss ? `${miss} 台，纳管并匹配之后会自动补进这个机柜` : "没有"], ["地址", "不变。按规划更新 BMC 地址在设备管理里另外做"]]) +
      doList(ADMIT_DO, ADMIT_NOT) + note("<b>交换机和供电框的 BMC 口令从这一步起由 NICo 接手</b>，规划里的出厂口令不再有效，平台也不再保存。计算托盘的口令在纳管时已经交给 NICo。要把设备交还，逐台退役。", "warning"),
    run: (why) => { admitRack(id); addAudit(id, "登记机柜", why, "—", `机柜声明已写入，带上 ${got.length} 台成员，设备未上电`); S.guide = Math.max(S.guide, 6); toast(`${id}：机柜已登记。下一步：开始上线`); } });
});
registerAction("rack-bringup", ({ id }) => {
  const r = DB.rack(id), n = DB.placed(r).length;
  confirmOperation({ title: "开始上线", target: id, action: `给已登记的 ${n} 台成员上电，并让 NICo 接管`, stages: STAGES.bringup_task, why: "新机柜上线", submit: "开始上线", high: true, confirmText: id, sub: "提交为一个上线任务。上线不装操作系统，装系统在“安装任务”里逐台确认。",
    extra: doList(UP_DO, UP_NOT) + note("<b>对设备的影响：</b>设备会上电并重启；计算托盘的 BIOS 设置会被修改并锁定；<b>按站点策略可能清理全部磁盘，包括非系统盘</b>；固件与期望版本不同时会被更新。主机管理地址在计算托盘第一次从网络启动时分配。", "warning") +
      note("任务完成后，交换机就绪数达到机柜规格要求时，NICo 自动开始机柜维护（固件升级、NVOS 更新、上电顺序、配置 NMX-C 集群、机柜校验）。这一段不是任务，顺序不能调整；进行中可以终止，终止后机柜停在 Error。全部完成后机柜状态为 Ready，柜里的计算托盘才能装系统。"),
    run: (why) => { bringUpRack(id, why); S.guide = Math.max(S.guide, 6); S.view["rackTab:" + id] = "tasks"; } });
});
registerAction("slot-fix", ({ id }) => {
  const t = DB.tray(id), r = DB.rack(t.rack), other = r.trays.find((x) => x.slot === t.seenSlot), from = t.slot;
  if (other && other.seenSlot === t.slot) { [t.slot, other.slot] = [other.slot, t.slot]; [t.id, other.id] = [other.id, t.id]; other.seenSlot = other.slot; other.simSlot = 0; } else t.slot = t.seenSlot;
  t.seenSlot = t.slot; t.simSlot = 0; r.trays.sort((a, b) => a.slot - b.slot);
  S.inventory.unshift({ v: S.inventory[0].v + 1, at: nowText(), by: "ops-01", file: "（更正槽位）", note: `${r.id} ${t.serial} 槽位 ${pad2(from)} 改为 ${pad2(t.slot)}`, why: "按实测槽位更正" });
  addAudit(`${r.id} / 槽位 ${pad2(t.slot)}`, "按实测更正清单", "实测槽位与清单不同", "—", "清单已更新"); toast("清单已按实测槽位更正"); render();
});
registerAction("rack-remaint", ({ id }) => {
  const r = DB.rack(id);
  confirmOperation({ title: "重新执行机柜维护", target: id, action: "让 NICo 从头再走一遍机柜维护的各个阶段", stages: STAGES.bringup, why: "故障原因已消除", submit: "重新执行",
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
    extra: baselinePicker(r.baseline) + readiness(r, "刷写固件") + note("版本已经与所选基线相同的设备会跳过。刷写完成后不会自动断电重启；需要重启才生效的部件，另外提交一次机柜重启。供电框的固件不在这个操作里。") + note("固件只在两种时候更新：新机柜上线时，和像现在这样由人提交。平时不会在后台自动更新，设备版本与基线不同只是标出来。"),
    run: (why, pick) => { startTask(id, "firmware", "固件更新 → " + pick, STAGES.firmware, { why, onDone: () => { r.baseline = pick; r.trays.forEach((t) => t.state && (t.baseline = pick)); }, readback: () => "版本与 " + pick + " 相同" }); S.view["rackTab:" + id] = "tasks"; } });
});
registerAction("rack-validate", ({ id }) => {
  const r = DB.rack(id), open = DB.absent(r).length;
  addAudit(id, "期望与实际校验", "例行核对", "—", open ? open + " 项差异" : "无差异");
  toast(open ? `校验完成：${open} 项差异，见清单核对` : "校验完成：期望与实际一致"); S.view["rackTab:" + id] = "check"; render();
});
/* 终止机柜维护：NICo 只在机柜处于维护阶段时接受。终止后机柜进入 Error，要人重新执行一次机柜维护。 */
registerAction("rack-terminate", ({ id }) => {
  const r = DB.rack(id), cur = r.bring && r.bring.stages.find((s) => s.s === "run");
  confirmOperation({ title: "终止机柜维护", target: id, action: "让 NICo 停止正在进行的机柜维护", why: "", submit: "终止维护", high: true, confirmText: id, sub: "终止后机柜进入 Error，不会自己恢复。",
    extra: defs([["当前阶段", cur ? esc(cur.n) : "—"], ["终止之后", "机柜状态变为 Error；要继续，重新执行机柜维护，从头再走一遍"]]) + note("NICo 会清理已经发给设备的请求。<b>已经在设备上开始的动作不保证能撤回</b>，例如正在刷写的固件；终止后以设备读回的状态为准。", "warning"),
    run: (why) => { if (r.bring && r.bring.timer) { clearInterval(r.bring.timer); r.bring.timer = 0; } if (cur) cur.s = "fail"; setRackState(r, "Error", "操作人终止了机柜维护"); addAudit(id, "终止机柜维护", why, "—", "读回 Error"); toast(`${id}：机柜维护已终止，机柜停在 Error`); } });
});
/* 删除机柜：NICo 只删除机柜对象，不检查也不处理成员设备。所以前提由平台检查：没有实例、成员设备都已逐台退役、没有进行中的任务。 */
function rackDeleteChecks(r) {
  const inst = DB.rackInstances(r.id).length, left = r.trays.filter((t) => t.state && !/Decommission/.test(t.state)).length;
  return [["机柜上没有实例", !inst, inst ? `还有 ${inst} 个实例，先在“实例管理”里删除` : "没有实例"], ["成员设备都已退役", !left, left ? `还有 ${left} 台设备在 NICo 里，先在“设备管理”里逐台退役` : "成员设备都已退役"], ["没有进行中的任务", !DB.busy(r), DB.busy(r) ? "有进行中的任务" : "没有"]];
}
registerAction("rack-delete", ({ id }) => {
  const r = DB.rack(id), checks = rackDeleteChecks(r), ok = checks.every((c) => c[1]);
  modal("删除机柜", id, `<div class="confirm-facts">${defs([["对象", `<b>${id}</b>`], ["动作", "删除 NICo 里的机柜对象和机柜声明，并从清单移除这个机柜"]])}</div>` +
    `<h3 class="section-title">删除前要满足</h3>` + table(["前提", "现在", "说明"], checks.map((c) => `<tr><td>${c[0]}</td><td>${c[1] ? badge("满足", "green") : badge("不满足", "red")}</td><td>${c[2]}</td></tr>`)) +
    note("<b>删除机柜不会替你处理成员设备。</b>NICo 只删除机柜对象：不给设备下电，不退役设备，也不检查柜里还有没有设备。所以要先逐台退役，再回到这里删除机柜。") +
    `<div class="live-form">${field("原因", `<input class="input" id="op-why" placeholder="工单号或原因">`)}${field(`高风险操作：输入 ${id} 以确认`, `<input class="input live-code" id="op-confirm" autocomplete="off">`)}</div>`,
    button("取消", "close") + `<button class="button danger" data-live="rack-delete-run" data-id="${id}" ${ok ? "" : 'disabled title="前提没有全部满足"'}>删除机柜</button>`, { wide: false });
});
registerAction("rack-delete-run", ({ id }) => {
  const why = $("#op-why").value.trim(); if (!why) return toast("请填写原因");
  if ($("#op-confirm").value.trim() !== id) return toast("输入的内容与对象不一致");
  closeModal(); S.domains = S.domains.filter((d) => d.rack !== id); S.racks = S.racks.filter((x) => x.id !== id);
  S.inventory.unshift({ v: S.inventory[0].v + 1, at: nowText(), by: "ops-01", file: "（删除机柜）", note: "移除 " + id, why });
  addAudit(id, "删除机柜", why, "—", "机柜对象已删除"); toast(id + " 已删除"); go("racks");
});
registerAction("task-cancel", ({ id }) => { cancelTask(id); render(); });
registerAction("discovery-rack", () => { closeModal(); go("discovery"); });

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
  { id: "decommission", label: "退役", types: ["compute", "switch", "power_shelf"], risk: "高", via: "Core", guard: (t) => (t.instance ? "这台设备上有实例，先删除实例" : !/Ready$/.test(t.state) ? "设备要在 Ready 状态" : t.type !== "compute" && DB.rack(t.rack).trays.some((x) => x.instance) ? "机柜上还有已分配的计算托盘，先删除实例" : ""), apply: (t) => { t.state = "Decommissioning"; t.health = "none"; }, readback: "已提交，设备进入退役流程；完成后在这里消失" },
];
/* 逐个目标的检查，对应现有产品的“服务端预览”：先让装机，再看生命周期状态。 */
function trayCheck(t, a) {
  if (!t.state || /Decommission/.test(t.state)) return "NICo 中没有可操作的对象";
  if (a.via === "Flow" && DB.busy(DB.rack(t.rack))) return "所在机柜有进行中的任务";
  if (a.rms && !S.rms) return "RMS 未就绪";
  if (a.via === "Flow" && !S.flow) return "Flow 未就绪";
  if (DB.installing(t) && a.risk !== "低") return "该设备有进行中的安装任务";
  return a.guard(t);
}
function trayOpDialog(ids, actionId) {
  const trays = ids.map(DB.tray), type = trays[0].type, options = TRAY_ACTIONS.filter((a) => a.types.includes(type)), a = options.find((x) => x.id === actionId) || options[0];
  const rows = trays.map((t) => { const why = trayCheck(t, a); return `<tr><td>${code(t.serial)}</td><td>${placeText(t)}</td><td>${stateBadge(t.state)}</td><td>${t.instance ? code(t.instance) : "—"}</td><td>${why ? badge("拒绝：" + why, "red") : badge("通过", "green")}</td></tr>`; });
  const pass = trays.filter((t) => !trayCheck(t, a)), affected = pass.filter((t) => t.instance).length + (type !== "compute" && a.risk === "高" ? new Set(pass.map((t) => t.rack)).size && [...new Set(pass.map((t) => t.rack))].reduce((n, r) => n + DB.rackInstances(r).length, 0) : 0);
  const high = a.risk === "高", confirmText = trays.length === 1 ? trays[0].serial : `${pass.length} 台`;
  const stages = a.via === "Flow" ? a.stages || STAGES.tray_power : [];
  modal(trays.length > 1 ? `批量操作（${trays.length} 台${type === "compute" ? "服务器" : TYPE_LABEL[type]}）` : `操作 ${trays[0].serial}`, "选对象，选动作，写原因。检查在提交时由服务端再执行一次。",
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
      startTask(rackId, "tray", `${a.label}（${mine.length} 台${typeLabel(mine[0])}）`, a.stages || STAGES.tray_power, { why, target: mine.length === 1 ? (rackId ? placeText(mine[0]) : mine[0].serial) : `${rackId || "未分配机柜"} / ${mine.length} 台`, onDone: () => mine.forEach((t) => a.apply(t, pick, why)), readback: () => a.readback });
    });
    toast(`已提交 ${new Set(pass.map((t) => t.rack)).size} 个任务`);
  } else {
    pass.forEach((t) => { a.apply(t, pick, why); addAudit(t.rack ? placeText(t) : t.serial, a.label, why, "—", a.unknown ? "未知：NICo 无读回方式，未自动重发" : a.readback); });
    toast(a.unknown ? `${a.label}已发送，结果未知` : `${a.label}完成，读回一致`);
  }
  S.view.checked = {}; S.guide = Math.max(S.guide, 10); render();
});

/* ---------- 模拟控制（只在设计稿中存在） ---------- */
registerAction("sim-discover", () => { if (simulateDiscovery("RACK-A03")) { S.guide = 4; S.view["rackTab:RACK-A03"] = "check"; toast("RACK-A03 已接电：34 个 BMC 拿到了地址，出现在设备发现里。下一步：获取设备信息，加入纳管设备"); go("discovery"); } });
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
registerAction("sim-reset", () => { DB.groups().forEach((r) => { if (r.task) clearInterval(r.task.timer); if (r.bring && r.bring.timer) clearInterval(r.bring.timer); }); S.installs.forEach((b) => b.timer && clearInterval(b.timer)); S.bmcJobs.forEach((j) => j.timer && clearInterval(j.timer)); const keep = Object.fromEntries(Object.entries(S.view).filter(([k]) => k.startsWith("nav:") || ["guide", "guideWide", "annotate", "guideTab", "lastPage"].includes(k))); S = freshState(); Object.assign(S.view, keep); go("racks"); toast("示例数据已重置"); });
