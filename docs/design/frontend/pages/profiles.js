"use strict";
/* 配置：操作时可以选择的档案（固件基线、安装方案），以及全部写操作的审计。 */

registerPage("baselines", {
  module: "baselines", title: "固件基线",
  render() {
    return heading("固件基线", "固件基线是绑定机柜规格的一组版本。固件更新只能选择基线，不能填写任意版本。", button("刷新数据", "refresh")) +
      `<div ${fp(1)}>${table(["固件基线", "机柜规格", "发布日期", "使用中的机柜", "版本不同的设备", "操作"], BASELINES.map((b, i) => `<tr><td><strong>${b.id}</strong><span class="cell-sub">${b.note}</span></td><td>${code(b.profile)}</td><td>${code(b.released)}</td><td>${S.racks.filter((r) => r.baseline === b.id).map((r) => `<a class="link-button" data-go="rack/${r.id}">${r.id}</a>`).join("　") || "—"}</td><td ${fp(2)}>${i === 0 ? DB.trays().filter((t) => t.type !== "power_shelf" && DB.drift(t)).length + " 台与此基线不同" : "—"}</td><td>${button("查看", "baseline-view", false, `data-id="${b.id}"`)}</td></tr>`))}</div>` +
      `<div ${fp(3)}>${note("基线对应站点为每个机柜规格配置的固件清单，在这里只读。固件的实际更新在“机柜管理”里发起。NICo 只能判断设备的版本和基线是否相同，不能判断高低；选择旧基线就是降级。")}</div>`;
  },
  spec: {
    purpose: "把固件版本从操作参数里拿出来，变成可审计的档案。操作人只选基线。", entry: "配置 → 固件基线", design: "6.6 档案与审计；10 非功能设计（固件基线的来源）", existing: "新增页面。现有服务器运行状态里的“固件”表是实际版本的来源",
    points: [
      { n: 1, name: "基线列表", kind: "新增", desc: "基线、适用的机柜规格、发布日期、使用中的机柜。" },
      { n: 2, name: "偏差统计", kind: "新增", desc: "版本与推荐基线不同的设备数量，对应设备页的“固件与基线不同”筛选。" },
      { n: 3, name: "只读说明", kind: "新增", desc: "基线在这里只读；更新固件从机柜发起。" },
    ],
    fields: [["固件基线", "站点为机柜规格配置的固件清单", "计算托盘的 BMC 和 UEFI、交换机的 BMC，以及 NVOS 的目标版本"], ["版本不同的设备", "设备实际版本对比推荐基线", "只比较 NICo 读得到的部件：NVOS 和供电框没有可读的版本"]],
    rules: ["固件只在两种时候更新：新机柜上线（机柜规格配了固件清单时），和人提交固件更新。平时不会自动更新，版本不同只标出来。", "提交固件更新时，版本已经与所选基线相同的设备会跳过。", "没有为某个机柜规格配置固件清单时，这个规格的机柜上线时不会更新固件。"],
    dialogs: [{ name: "基线详情", desc: "列出基线包含的部件和版本。" }],
  },
});
registerAction("baseline-view", ({ id }) => { const b = DB.baseline(id); modal(b.id, `固件基线 · ${b.profile}`, table(["部件", "版本", "能否读回"], Object.entries(b.parts).map(([k, v]) => `<tr><td>${k}</td><td>${code(v)}</td><td>可以，用于比对</td></tr>`).concat([`<tr><td>NVOS</td><td>${code(b.nvos)}</td><td>不能：只在机柜上线时下发，NICo 读不到已安装的版本</td></tr>`])), button("关闭", "close", true), { wide: false }); });

registerPage("os-templates", {
  module: "os", title: "安装方案",
  render() {
    return heading("安装方案", "设置 OS、系统盘、分区和默认登录配置值。交付时只选择已发布的方案。", button("刷新数据", "refresh") + act("新建方案", "os-new", { primary: true, admin: true })) +
      `<div ${fp(1)}>${table(["名称 / 版本", "默认系统 / 安装器", "分区 / 默认登录配置", "状态 / 引用", "操作"], S.osTemplates.map((o) => `<tr><td><strong>${o.id}</strong><span class="cell-sub">v1</span></td><td>Ubuntu Server 24.04 · ${o.arch}<span class="cell-sub">autoinstall</span></td><td>${o.disk}<span class="cell-sub">${o.login}</span></td><td ${fp(2)}>${stateBadge(o.state)}<span class="cell-sub">${o.used} 个实例引用</span></td><td><div class="inline-actions">${button(o.state === "草稿" ? "编辑草稿" : "查看", "os-view")}${button("复制", "os-view")}${o.state === "草稿" ? "" : button("新版本", "os-view")}</div></td></tr>`))}</div>` +
      `<div ${fp(3)}>${note("整机柜的计算托盘同质，默认不需要逐机配置。主机名和地址由 NICo 按清单分配，不在方案里填写。")}</div>`;
  },
  spec: {
    purpose: "可复用的系统安装配置。合并现有的操作系统材料和安装方案，交付时只需选一个方案。", entry: "配置 → 安装方案", design: "6.6 档案与审计", existing: "安装方案页（表头、状态、行操作沿用）与操作系统页（ISO 与 OS 版本）合并",
    points: [
      { n: 1, name: "方案列表", kind: "沿用", desc: "名称 / 版本、默认系统 / 安装器、分区 / 默认登录配置、状态 / 引用、操作，与安装方案页一致。" },
      { n: 2, name: "状态 / 引用", kind: "沿用", desc: "草稿、已发布、已停用。已发布的版本只读，修改要建新版本。" },
      { n: 3, name: "不做逐机配置", kind: "调整", desc: "去掉设备覆盖设置和逐机网卡规划：整机柜的托盘同质，主机名和地址来自清单。" },
    ],
    rules: ["新建和发布方案需要管理角色。", "交付只能选择已发布的方案。", "编辑弹窗沿用安装方案的基本信息、系统盘选择、分区布局、默认登录配置、安装验收。"],
  },
});
["os-new", "os-view"].forEach((a) => registerAction(a, () => toast("沿用现有的安装方案弹窗，设计稿不重复展示")));

registerPage("audit", {
  module: "audit", title: "操作审计",
  render() {
    const f = { act: view("auAct", ""), res: view("auRes", ""), q: view("auQ", "").toLowerCase() };
    const kind = (a) => (/未知/.test(a.res) ? "结果未知" : /失败|已终止|拒绝/.test(a.res) ? "失败 / 未执行" : /已提交|已接受/.test(a.res) ? "已发送" : "已完成");
    const color = { 已完成: "green", 结果未知: "amber", "失败 / 未执行": "red", 已发送: "amber" };
    const list = S.audit.filter((a) => (!f.act || a.act.startsWith(f.act)) && (!f.res || kind(a) === f.res) && (!f.q || [a.obj, a.act, a.why, a.by, a.task].join(" ").toLowerCase().includes(f.q)));
    const acts = [...new Set(S.audit.map((a) => a.act.split(/[ ：→（]/)[0]))];
    return heading("操作审计", "查看对机柜和设备执行过的操作、原因、任务和读回结果。", button("刷新数据", "refresh")) +
      `<div ${fp(1)}>${summary([["记录总数", S.audit.length], ["已完成", S.audit.filter((a) => kind(a) === "已完成").length], ["结果未知", S.audit.filter((a) => ["结果未知", "已发送"].includes(kind(a))).length], ["失败 / 未执行", S.audit.filter((a) => kind(a) === "失败 / 未执行").length]])}</div>` +
      `<div class="filter-bar" ${fp(2)}>${selectField("auAct", "操作", [["", "全部操作"], ...acts.map((a) => [a, a])], f.act)}${selectField("auRes", "结果", [["", "全部"], ["已发送", "已发送"], ["已完成", "已完成"], ["结果未知", "结果未知"], ["失败 / 未执行", "失败 / 未执行"]], f.res)}${searchField("auQ", "搜索", view("auQ", ""), "对象、原因、任务或操作者")}</div>` +
      `<div ${fp(3)}>${table(["时间", "操作", "对象", "操作者", "原因", "任务", "结果", "读回"], list.map((a) => `<tr><td>${code(a.at)}</td><td>${esc(a.act)}</td><td><strong>${esc(a.obj)}</strong></td><td>${a.by}</td><td>${esc(a.why)}</td><td>${a.task === "—" ? "—" : /^task-/.test(a.task) ? `<a class="link-button" data-live="audit-task" data-task="${a.task}">${code(a.task)}</a>` : code(a.task)}</td><td ${fp(4)}>${badge(kind(a), color[kind(a)])}</td><td>${esc(a.res)}</td></tr>`), "还没有操作记录。")}</div>` +
      `<p class="live-small">共 ${S.audit.length} 条，最新在前。记录只追加、不删除；“结果未知”表示 NICo 没有读回方式或请求结果无法确认，平台不会自动重发。</p>`;
  },
  spec: {
    purpose: "谁在什么时候、因为什么、对什么做了什么，结果如何。每次写操作都在这里留一条。", entry: "运维 → 操作审计", design: "6.6 档案与审计；9 操作设计；12 验收原则（可审计）", existing: "设备管理 → 操作记录。统计条、筛选、表头和结果用词沿用，增加“任务”列",
    points: [
      { n: 1, name: "统计条", kind: "沿用", desc: "记录总数、已完成、结果未知、失败 / 未执行。" },
      { n: 2, name: "筛选", kind: "沿用", desc: "操作、结果和搜索。" },
      { n: 3, name: "记录表", kind: "调整", desc: "时间、操作、对象、操作者、原因、结果沿用；“NICo 消息”换成“任务”和“读回”，因为机柜级操作的执行记录在任务里。点击任务编号打开该任务的阶段。" },
      { n: 4, name: "结果", kind: "沿用", desc: "已发送、已完成、结果未知、失败 / 未执行。结果未知时不自动重发。" },
    ],
    fields: [["操作者", "站点身份系统", "接入身份系统后记录到人"], ["任务", "NICo Flow", "机柜级操作对应的任务编号；单设备操作为“—”"], ["读回", "NICo Core", "执行后读回的状态"]],
    rules: ["记录只追加，不能删除。", "导入清单、更换托盘、交付和回收也写入审计。"],
  },
});
registerAction("audit-task", ({ task }) => { const r = S.racks.find((x) => x.tasks.some((t) => t.id === task)); if (!r) return toast("这个任务所在的机柜已退役"); S.view["rackTab:" + r.id] = "tasks"; go("rack/" + r.id); });
