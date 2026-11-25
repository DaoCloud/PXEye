"use strict";
/* 设备发现：流程和现有产品的“发现设备”一致，页面只是换了样式。
   设备接电后 BMC 从 DHCP 拿到地址，出现在这里的列表里，这时平台不知道它是哪台设备。
   人输入 BMC 的用户名和口令“获取设备信息”（单台，或多台共用一组凭据），平台读出类型、序列号和型号；
   核对之后“加入纳管设备”。服务器纳管时把声明写进 NICo，带暂停标记，不上电；交换机和供电框先在平台本地纳管。
   规划里的管理口和 BMC 规划地址不在这里用：纳管之后到设备管理里“一键匹配”。 */

/* 从接电到装好系统的全过程：每一步由谁触发、设备上发生什么。 */
const DISCOVERY_STEPS = [
  ["设备接电", "现场", "BMC 待机通电并申请地址，NICo DHCP 从带外地址池分配。设备本身不开机", "这时拿到的是地址池里的任意一个地址"],
  ["获取设备信息", "人，单台或批量", "输入 BMC 的用户名和口令，平台登录一次 BMC，读出类型、序列号和型号", "只读，不改设备"],
  ["加入纳管设备", "人，单台或批量", "服务器的声明写进 NICo，带暂停标记；交换机和供电框先在平台本地纳管", "不上电、不改 BIOS、不动磁盘、不装系统"],
  ["一键匹配", "人，在设备管理里", "把规划里的管理口、BMC 规划地址、机柜和槽位写进已纳管设备的配置", "只写平台本地，不动设备"],
  ["登记机柜", "人，每个机柜一次", "机柜声明写入 NICo；本柜已纳管的交换机和供电框同步为 NICo 声明。这一步是整机柜才有的", "不上电"],
  ["开始上线", "人，每个机柜一次。不属于机柜的服务器没有这一步", "上线任务按顺序上电：供电框、计算托盘、交换机；放行计算托盘后 NICo 接管它。交换机就绪后 NICo 自动做机柜维护", "设备会上电和重启；按站点策略可能清理全部磁盘"],
  ["装系统", "人", "在“安装任务”里选设备、核对配置、检查并确认。不属于机柜的服务器在这时才由 NICo 上电接管", "这一步才写系统盘"],
];
const EP_KIND = { compute: "服务器", switch: "交换机", power_shelf: "供电框" };
const epGet = (id) => S.endpoints.find((e) => e.id === id);
/* 读到的序列号在规划里对应哪一行。 */
const epPlan = (e) => (e.identity ? DB.trays().find((t) => t.serial === e.identity.serial && !t.noPlan) : null);
const epInfoCell = (e) => { const t = epPlan(e);
  return e.identity ? `${code(e.identity.serial)}<span class="cell-sub">${EP_KIND[e.identity.kind]} · ${esc(e.identity.model)}</span><span class="cell-sub">${t ? (t.rack ? `规划：${t.rack} 槽位 ${pad2(t.slot)}` : "规划：未分配机柜") : "规划里没有这个序列号"}</span>`
    : e.failed ? `<span class="live-error">${esc(e.failed)}</span>` : `<span class="muted">待获取</span>`; };

registerPage("discovery", {
  module: "discovery", title: "设备发现",
  render() {
    const f = { net: view("dsNet", ""), st: view("dsSt", "") }, checked = S.view.epChecked || {}, open = view("dsWays", false);
    const list = S.endpoints.filter((e) => (!f.net || e.subnet === f.net) && (!f.st || (f.st === "todo" ? !e.identity : !!e.identity)));
    const picked = S.endpoints.filter((e) => checked[e.id]), ready = S.endpoints.filter((e) => e.identity);
    return heading("设备发现", "发现通过 DHCP 获取临时管理地址的设备。输入 BMC 的用户名和密码获取设备信息，核对后加入纳管设备。", button("刷新发现结果", "refresh") + button("查看 DHCP 服务", "noop", false, 'data-go="network/dhcp"')) +
      `<div ${fp(1)}>${summary([["发现的端点", S.endpoints.length], ["待获取设备信息", S.endpoints.filter((e) => !e.identity).length], ["已获取 · 待纳管", ready.length], ["已纳管设备", DB.trays().filter((t) => t.declared).length]])}</div>` +
      `<div class="filter-bar" ${fp(2)}>${selectField("dsNet", "发现子网", [["", "全部发现子网"], ...S.subnets.filter((n) => n.kind === "Underlay").map((n) => [n.id, n.name])], f.net)}${selectField("dsSt", "设备信息", [["", "全部"], ["todo", "待获取"], ["done", "已获取"]], f.st)}</div>` +
      `<div class="device-status-action-bar" ${fp(3)}>${act(`批量获取设备信息（${picked.filter((e) => !e.identity).length}）`, "ep-identify-many", { gate: picked.some((e) => !e.identity) ? "" : "先勾选待获取的端点" })}${act(`批量纳管（${picked.filter((e) => e.identity).length}）`, "ep-enroll-many", { gate: picked.some((e) => e.identity) ? "" : "先勾选已经获取到设备信息的端点" })}${button("全选当前列表", "ep-check-all")}${button("清空选择", "ep-check-none")}<span class="live-small">批量获取共用一组用户名和密码，一次最多 50 台，同时读取 4 台。</span></div>` +
      `<div ${fp(4)}>${table(["选择", "临时管理地址 / MAC", "来源子网 / 最近 DHCP", "设备信息", "操作"], list.map((e) => `<tr><td><input type="checkbox" data-ep-check="${e.id}" ${checked[e.id] ? "checked" : ""} aria-label="选择 ${e.ip}"></td><td>${code(e.ip)}<span class="cell-sub live-code">${e.mac}</span></td><td>${subnetLink(e.subnet)}<span class="cell-sub">最近 DHCP ${e.seen}</span></td><td ${fp(5)}>${epInfoCell(e)}</td>
        <td><div class="inline-actions">${e.identity ? act("确认设备信息", "ep-confirm", { primary: true, compact: true, extra: `data-id="${e.id}"` }) : act("获取设备信息", "ep-identify", { compact: true, extra: `data-id="${e.id}"` })}</div></td></tr>`), "当前没有待处理的端点：拿到地址的设备都已经纳管。新设备接电后会出现在这里。")}</div>` +
      `<section class="live-card" ${fp(6)}><div class="live-heading" style="margin-bottom:${open ? 14 : 0}px"><div><h2 style="margin:0">从接电到装好系统：每一步谁触发、设备上发生什么</h2></div><div class="live-tools">${button(open ? "收起" : "展开", "discovery-ways")}</div></div>${open ? table(["步骤", "谁触发", "发生什么", "对设备的影响"], DISCOVERY_STEPS.map((w, i) => `<tr><td><strong>${i + 1}. ${w[0]}</strong></td><td>${w[1]}</td><td>${w[2]}</td><td>${w[3]}</td></tr>`)) : ""}</section>` +
      note("这里只列出拿到了地址、还没有归属的端点。纳管之后设备到“设备管理”里：在那里“一键匹配”规划、更新 BMC 地址、做系统配置。读到的序列号不在规划里也可以纳管，它会成为一台没有规划的设备。");
  },
  spec: {
    purpose: "把通电的设备认出来并纳管。流程沿用现有产品的“发现设备”：人输入凭据获取设备信息，核对后加入纳管设备。平台不自动读取，也不自动纳管。",
    entry: "接入 → 设备发现", design: "5 整体操作运维流程（P5 识别、P6 纳管）；6.3 机柜与设备", existing: "设备管理 → 发现设备。列表、获取设备信息、批量获取、确认设备信息、加入纳管设备都沿用；只换了页面样式，并在设备信息里多显示一行“规划里对应哪个机柜和槽位”",
    points: [
      { n: 1, name: "统计条", kind: "调整", desc: "发现的端点、待获取设备信息、已获取待纳管、已纳管设备。" },
      { n: 2, name: "筛选", kind: "沿用", desc: "按发现子网筛选；增加按是否已获取设备信息筛选。切换发现子网不保留跨子网的选择。" },
      { n: 3, name: "批量操作", kind: "沿用", desc: "勾选端点后“批量获取设备信息”：只填一组共用的用户名和密码，一次最多 50 台，同时读取 4 台。获取到之后可以“批量纳管”。" },
      { n: 4, name: "端点列表", kind: "沿用", desc: "临时管理地址 / MAC、来源子网 / 最近 DHCP、设备信息、操作，与现有页面一致。列表只包含拿到了地址、还没有归属的带外接口。" },
      { n: 5, name: "设备信息", kind: "调整", desc: "没有获取时显示“待获取”；认证失败时显示原因；获取到之后显示序列号、类型和型号。多显示一行：这个序列号在规划里对应哪个机柜和槽位，或“规划里没有这个序列号”。" },
      { n: 6, name: "全过程说明", kind: "新增", desc: "从设备接电到装好系统的七步，每一步写明谁触发、发生什么、对设备有什么影响。默认折叠。" },
    ],
    fields: [["临时管理地址 / MAC", "NICo DHCP", "设备接电时从带外地址池拿到的地址，是地址池里的任意一个"], ["来源子网 / 最近 DHCP", "NICo", "带外管理子网，以及最近一次申请地址的时间"], ["设备信息", "平台读取设备的 BMC", "类型、序列号、型号。用人输入的凭据读取"], ["规划", "设备规划", "按读到的序列号去规划里找；只是提示，不影响能不能纳管"]],
    rules: ["获取设备信息只读设备，不写 NICo，也不改设备。", "平台不自动读取设备信息，也不逐组尝试口令：用哪组凭据由人给出。认证失败的端点，换一组凭据再单独获取。", "批量获取一次 1–50 台，同时读取 4 台；归属有冲突或没有可用地址的端点不能选。", "获取到的设备信息 15 分钟内有效，过期后要重新获取才能纳管。", "加入纳管设备：服务器的声明写进 NICo，带暂停标记，NICo 不给它上电，也不接管；交换机和供电框先保存在平台本地，到“登记机柜”时才同步为 NICo 声明。", "读到的序列号不在规划里也可以纳管；它没有机柜和槽位，在设备清单里补上规划后再“一键匹配”。", "纳管不上电、不改 BIOS、不动磁盘、不装系统。"],
    dialogs: [
      { name: "获取设备信息", desc: "沿用现有弹窗：对一个端点输入 BMC 或 PMC 的用户名和密码，读取设备信息。", fields: [["临时管理地址", "是", "这个端点当前的地址"], ["BMC / PMC 用户名", "是", "1–16 个字符"], ["密码", "是", "1–20 个字符；只用于这次读取和随后的纳管"]] },
      { name: "批量获取设备信息", desc: "沿用现有弹窗：只填一组共用的用户名和密码，直接使用所选端点的当前地址。完成后列出每个端点的结果，可以对成功的“确认并纳管”。", fields: [["共用用户名", "是", ""], ["共用密码", "是", ""]] },
      { name: "确认设备信息", desc: "沿用现有弹窗：显示读到的类型、序列号、型号、BMC MAC 和临时地址，以及规划里对应的机柜和槽位；确认后“加入纳管设备”。", fields: [["加入纳管设备", "是", "服务器写入 NICo 声明并带暂停标记；交换机和供电框本地纳管"]] },
    ],
  },
});
registerAction("discovery-ways", () => { S.view.dsWays = !view("dsWays", false); render(); });
registerAction("ep-check-all", () => { const f = { net: view("dsNet", ""), st: view("dsSt", "") }; S.view.epChecked = Object.fromEntries(S.endpoints.filter((e) => (!f.net || e.subnet === f.net) && (!f.st || (f.st === "todo" ? !e.identity : !!e.identity))).slice(0, 50).map((e) => [e.id, true])); render(); });
registerAction("ep-check-none", () => { S.view.epChecked = {}; render(); });
/* 模拟用的凭据：填的密码是 other 开头就当作另一组口令，其余当作批次里通用的那一组。 */
const epCred = (pass) => (/^other/.test(pass) ? "other" : "shared");
registerAction("ep-identify", ({ id }) => { const e = epGet(id);
  modal("获取设备信息", "只读取设备信息，不改设备", `<div class="live-form">${field("临时管理地址", `<input class="input live-code" value="${e.ip}" readonly>`, `MAC ${e.mac}`)}${field("BMC / PMC 用户名", `<input class="input" id="ep-user" value="admin" maxlength="16">`)}${field("密码", `<input class="input" type="password" id="ep-pass" maxlength="20" autocomplete="off">`, e.failed ? "上一次认证失败，换一组凭据再试" : "")}</div>`,
    button("取消", "close") + button("获取设备信息", "ep-identify-run", true, `data-id="${id}"`), { wide: false }); });
registerAction("ep-identify-run", ({ id }) => {
  const e = epGet(id); if (!$("#ep-user").value.trim() || !$("#ep-pass").value) return toast("用户名和密码都要填写");
  const ok = identifyEndpoint(e, epCred($("#ep-pass").value)); closeModal(); S.guide = Math.max(S.guide, 4);
  if (!ok) { toast(`${e.ip}：认证失败`); return render(); }
  render(); ACTIONS["ep-confirm"]({ id });
});
registerAction("ep-identify-many", () => {
  const list = S.endpoints.filter((e) => (S.view.epChecked || {})[e.id] && !e.identity);
  if (!list.length) return toast("先勾选待获取的端点");
  if (list.length > 50) return toast("一次最多 50 台");
  modal("批量获取设备信息", `已选择 ${list.length} 个端点`, `<p class="wiz-lead-note">只填一组共用的用户名和密码，直接使用所选端点的当前管理地址。口令不同的设备会显示认证失败，之后单独获取。</p><div class="live-form">${field("共用用户名", `<input class="input" id="ep-user" value="admin" maxlength="16">`)}${field("共用密码", `<input class="input" type="password" id="ep-pass" maxlength="20" autocomplete="off">`)}</div>`,
    button("取消", "close") + button("批量获取设备信息", "ep-identify-many-run", true), { wide: false });
});
registerAction("ep-identify-many-run", () => {
  if (!$("#ep-user").value.trim() || !$("#ep-pass").value) return toast("用户名和密码都要填写");
  const cred = epCred($("#ep-pass").value), list = S.endpoints.filter((e) => (S.view.epChecked || {})[e.id] && !e.identity), rows = list.map((e) => ({ e, ok: identifyEndpoint(e, cred) }));
  S.view.epResult = rows.map((r) => r.e.id); S.guide = Math.max(S.guide, 4); render(); epResultDialog();
});
function epResultDialog() {
  const rows = (S.view.epResult || []).map(epGet).filter(Boolean), ok = rows.filter((e) => e.identity);
  modal("获取结果", `成功 ${ok.length} / ${rows.length}`, table(["临时管理地址 / MAC", "结果", "设备信息"], rows.map((e) => `<tr><td>${code(e.ip)}<span class="cell-sub live-code">${e.mac}</span></td><td>${e.identity ? badge("已获取", "green") : badge("失败", "red")}</td><td>${epInfoCell(e)}</td></tr>`)) +
    (rows.length > ok.length ? note("认证失败的端点留在列表里：换一组凭据，在那一行上单独“获取设备信息”。", "warning") : ""),
    button("关闭", "close") + act(`确认并纳管（${ok.length}）`, "ep-enroll-result", { primary: true, gate: ok.length ? "" : "没有获取成功的端点" }));
}
/* 纳管的影响说明：服务器和交换机、供电框不一样。 */
const enrollNote = (list) => { const srv = list.filter((e) => e.identity.kind === "compute").length, other = list.length - srv;
  return `<div class="live-note"><b>加入纳管设备会做什么：</b>${srv ? `${srv} 台服务器的声明写进 NICo，带暂停标记，NICo 不给它上电，也不接管。` : ""}${other ? `${other} 台交换机和供电框先保存在平台本地；登记机柜时才同步为 NICo 声明。` : ""}不上电、不改 BIOS、不动磁盘、不装系统。</div>`; };
registerAction("ep-confirm", ({ id }) => { const e = epGet(id), t = epPlan(e);
  modal("确认设备信息", e.ip, `<div class="confirm-facts">${defs([["设备类型", EP_KIND[e.identity.kind]], ["序列号", code(e.identity.serial)], ["型号", esc(e.identity.model)], [e.identity.kind === "power_shelf" ? "PMC MAC" : "BMC MAC", code(e.mac)], ["临时管理地址", code(e.ip)], ["规划", t ? (t.rack ? `${t.rack} 槽位 ${pad2(t.slot)}` : "未分配机柜") : `<span class="live-error">规划里没有这个序列号</span>。可以先纳管，之后在设备清单里补上规划`]])}</div>` + enrollNote([e]),
    button("取消", "close") + act("加入纳管设备", "ep-enroll", { primary: true, extra: `data-id="${id}"` }), { wide: false }); });
function epEnroll(list) {
  const done = list.map(enrollEndpoint); S.view.epChecked = {}; S.view.epResult = [];
  addAudit(done.length === 1 ? done[0].serial : `${done.length} 台设备`, "加入纳管设备", "—", "—", "已纳管，设备未上电"); S.guide = Math.max(S.guide, 5); closeModal();
  toast(`${done.length} 台设备已纳管。下一步：到设备管理里“一键匹配”规划`); render();
}
registerAction("ep-enroll", ({ id }) => epEnroll([epGet(id)]));
registerAction("ep-enroll-result", () => epEnroll((S.view.epResult || []).map(epGet).filter((e) => e && e.identity)));
registerAction("ep-enroll-many", () => {
  const list = S.endpoints.filter((e) => (S.view.epChecked || {})[e.id] && e.identity); if (!list.length) return toast("先勾选已经获取到设备信息的端点");
  modal("批量纳管", `已选择 ${list.length} 台已经获取到设备信息的设备`, table(["临时管理地址", "设备信息"], list.slice(0, 12).map((e) => `<tr><td>${code(e.ip)}</td><td>${epInfoCell(e)}</td></tr>`)) + (list.length > 12 ? `<p class="live-small">显示前 12 台，共 ${list.length} 台。</p>` : "") + enrollNote(list),
    button("取消", "close") + act(`加入纳管设备（${list.length}）`, "ep-enroll-many-run", { primary: true }));
});
registerAction("ep-enroll-many-run", () => epEnroll(S.endpoints.filter((e) => (S.view.epChecked || {})[e.id] && e.identity)));
