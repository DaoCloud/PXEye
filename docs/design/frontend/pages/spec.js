"use strict";
/* 全部页面说明：把每个页面随身携带的 spec 汇总成一份文档。tools/build-spec.mjs 用同一份数据生成 Markdown。 */

const EXISTING_MAP = [
  ["总览 → 机柜拓扑", "机柜管理 → 机柜详情 → 设备（机柜立面）", "卡片视图改为按槽位排列的立面；统计并入机柜列表"],
  ["装机 → 安装任务", "交付 → 安装任务", "表格与任务详情不变；“新建安装任务”改为“机柜交付”向导"],
  ["资源 → 设备管理 → 设备规划", "接入 → 设备清单 → 期望清单", "输入改为覆盖三类设备的整表；配置对比沿用"],
  ["资源 → 设备管理 → 发现设备 / 纳管设备", "接入 → 设备发现；机柜管理 → 机柜详情 → 对账", "整机柜由 NICo 按清单自动发现并接管，不再逐台确认纳管；发现进度跨机柜可查"],
  ["设备管理 → 服务器 / 交换机 / 供电框", "设备管理 → 计算托盘 / 交换机 / 供电框", "仍是三个独立的子菜单；地址与固件版本直接在表里，行上增加电源快捷入口"],
  ["设备管理 → 告警", "健康告警", "范围增加机柜级告警"],
  ["设备管理 → 布线、发现诊断", "接入 → 设备发现；机柜管理 → 机柜详情 → 对账", "探测结果、错误码和处理建议并入设备发现；接线不符作为对账问题出现"],
  ["设备管理 → 机柜", "机柜管理、机柜详情", "详情弹窗扩展为页面；“机柜维护”拆成单一动作"],
  ["设备管理 → 操作记录", "运维 → 操作审计", "增加任务列，可跳到任务"],
  ["资源 → 实例管理", "交付 → 实例管理", "增加机柜和租户"],
  ["资源 → 操作系统；配置 → 安装方案", "配置 → 安装方案", "合并；去掉逐机覆盖"],
  ["资源 → 网络管理", "接入 → 网络规划 → 子网 / 地址分配", "增加用途和规划检查；地址分配由弹窗扩展为页签"],
  ["配置 → 站点设置", "配置 → 站点设置 → 站点概况；接入 → 网络规划 → DHCP 服务", "增加依赖组件及其未就绪时的影响；引导网络移到 DHCP 服务，并增加按子网的中继状态"],
  ["配置 → NICo 集群", "配置 → 站点设置 → 控制面", "服务表加入 Flow 与 RMS"],
  ["（无）", "设备管理（总览）、设备管理 → DPU、NVLink 域管理、运维任务、设备清单 → 版本记录、固件基线、机柜交付", "新增页面"],
];
function specSection(p) {
  const s = p.spec, name = pageName(p);
  return `<section id="spec-${p.id.replace("/", "-")}"><h2>${esc(name)}　<a class="link-button" data-go="${p.id === "rack" ? "rack/RACK-A01" : p.id}">打开页面</a></h2><p class="live-small">${esc(s.purpose)}</p>
    ${defs([["入口", esc(s.entry)], ["设计章节", esc(s.design)], ["现有页面", esc(s.existing)]])}
    <h3>功能点</h3><table><thead><tr><th>编号</th><th>功能点</th><th>类型</th><th>说明</th></tr></thead><tbody>${s.points.map((x) => `<tr><td><span class="pin">${x.n}</span></td><td><b>${esc(x.name)}</b></td><td><span class="kind ${KIND[x.kind]}">${x.kind}</span></td><td>${esc(x.desc)}</td></tr>`).join("")}</tbody></table>
    ${s.fields ? `<h3>字段</h3><table><thead><tr><th>字段</th><th>来源</th><th>说明</th></tr></thead><tbody>${s.fields.map((f) => `<tr><td><b>${esc(f[0])}</b></td><td>${esc(f[1])}</td><td>${esc(f[2] || "")}</td></tr>`).join("")}</tbody></table>` : ""}
    ${s.rules ? `<h3>规则与门控</h3><ul>${s.rules.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>` : ""}
    ${s.calls && s.calls.length ? `<h3>NICo 接口</h3><table><thead><tr><th>用途</th><th>接口</th><th>类型</th><th>命令行</th></tr></thead><tbody>${pageCalls(p).map((x) => `<tr><td>${esc(x.use)}</td><td class="live-code">${esc(x.call ? x.call.name : x.id)}</td><td>${x.call ? esc(x.call.surface) + (x.call.write ? " · 写" : " · 读") : "未定义"}</td><td class="live-code">${esc(x.call && x.call.cli ? x.call.cli : "—")}</td></tr>`).join("")}</tbody></table><h3>前置资源（按准备顺序）</h3><p class="live-small">${pageResources(p).map((r) => esc(r.name)).join(" → ") || "—"}</p>` : ""}
    ${(s.dialogs || []).map((d) => `<h3>弹窗：${esc(d.name)}</h3><p class="live-small">${esc(d.desc)}</p>${d.fields ? `<table><thead><tr><th>输入</th><th>必填</th><th>说明</th></tr></thead><tbody>${d.fields.map((f) => `<tr><td><b>${esc(f[0])}</b></td><td>${esc(f[1])}</td><td>${esc(f[2] || "")}</td></tr>`).join("")}</tbody></table>` : ""}`).join("")}</section>`;
}
registerPage("spec", {
  title: "全部页面说明",
  render() {
    const pages = pagesByNav(), points = pages.flatMap((p) => p.spec.points), count = (k) => points.filter((x) => x.kind === k).length;
    return `<div class="spec-doc">` + heading("全部页面说明", "每个页面的定位、功能点、字段、规则和弹窗。内容与页面写在同一个文件里，这里是汇总。", button("打印 / 另存为 PDF", "spec-print")) +
      summary([["页面", pages.length], ["功能点", points.length], ["沿用", count("沿用")], ["调整", count("调整")], ["新增", count("新增")]]) +
      `<section><h2>页面清单</h2>${table(["菜单分组", "页面", "入口", "功能点"], pages.map((p) => `<tr><td>${navPath(p)[0] || "—"}</td><td><a class="link-button" href="#spec-${p.id.replace("/", "-")}" data-anchor="spec-${p.id.replace("/", "-")}">${esc(navPath(p).slice(1).concat(p.tab || (p.crumb ? [p.title] : [])).join(" › "))}</a></td><td>${esc(p.spec.entry)}</td><td>${p.spec.points.length}</td></tr>`))}</section>
       <section><h2>现有页面去向</h2>${table(["现有页面", "新页面", "变化"], EXISTING_MAP.map((r) => `<tr><td>${esc(r[0])}</td><td><b>${esc(r[1])}</b></td><td>${esc(r[2])}</td></tr>`))}</section>` +
      pages.map(specSection).join("") + `</div>`;
  },
});
registerAction("spec-print", () => window.print());

/* 接口契约：资源依赖、接口清单和缺口。数据在 contract.js，各页面在 spec.calls 里声明自己用到的接口。 */
const CALL_AREAS = ["站点与依赖", "网络与地址", "设备清单", "设备发现", "机柜与 NVLink 域", "设备读取", "设备操作", "机柜级任务", "交付与实例", "健康"];
registerPage("contract", {
  title: "接口契约",
  render() {
    const order = resourceChain(NICO_RESOURCES.map((r) => r.id)), problems = contractProblems();
    const names = (ids) => (ids || []).map((id) => (resourceById(id) || { name: id }).name).join("、") || "—";
    const users = (id) => callUsers(id).map((p) => `<a class="link-button" data-go="${p.id === "rack" ? "rack/RACK-A01" : p.id}">${esc(p.tab || p.title)}</a>`).join("　") || "—";
    const callTable = (list) => table(["接口 / 命令行", "请求参数", "用到的字段", "前置资源", "执行方", "使用的页面", "证据"], list.map((c) =>
      `<tr><td><strong class="live-code">${esc(c.name)}</strong><span class="cell-sub">${surfaceBadge(c)}</span>${c.cli ? `<span class="cell-sub guide-cli live-code">${esc(c.cli)}</span>` : ""}${c.note ? `<span class="cell-sub">${esc(c.note)}</span>` : ""}</td><td>${esc(c.request || "—")}</td><td>${esc((c.fields || []).join("、") || "—")}</td><td>${names(c.requires)}</td><td>${esc(c.executedBy || "Core")}</td><td>${users(c.id)}</td><td>${badge(c.evidence || "定义", c.evidence === "现场" ? "green" : c.evidence === "模拟" ? "blue" : "gray")}${c.used ? `<span class="cell-sub">${badge("现有产品已调用", "blue")}</span>` : ""}<span class="cell-sub live-code">${esc(c.source || "")}</span></td></tr>`));
    return `<div class="spec-doc contract-doc">` + heading("接口契约", "每个页面调用 NICo 的哪些接口、对应什么命令行、用到哪些字段，以及要让页面有数据必须先准备好哪些资源。", button("打印 / 另存为 PDF", "spec-print")) +
      note(`接口、参数和字段取自 NICo 源码 <b>${CONTRACT_SOURCE.repo}</b> 的提交 <span class="live-code">${CONTRACT_SOURCE.commit}</span>（${CONTRACT_SOURCE.version}）。“证据”一列说明核对到了哪一步：定义 = 只读过源码；模拟 = 在模拟环境调用过；现场 = 在真实整机柜环境核对过。目前全部是“定义”。标有“现有产品已调用”的接口在主线产品里已经有调用代码，其余是整机柜方向新增的。`) +
      summary([["资源", NICO_RESOURCES.length], ["接口", NICO_CALLS.length], ["其中写操作", NICO_CALLS.filter((c) => c.write).length], ["现有产品已调用", NICO_CALLS.filter((c) => c.used).length], ["缺口", CONTRACT_GAPS.length], ["自检问题", problems.length]]) +
      `<section><h2>资源依赖与准备顺序</h2><p class="live-small">按“先准备的在前”排列。一个页面要有数据，它用到的接口的全部前置资源都要先就位。</p>${table(["顺序", "资源", "NICo 对象", "怎么得到", "依赖", "没有真实整机柜时", "出处"], order.map((r, i) => `<tr><td>${i + 1}</td><td><strong>${esc(r.name)}</strong>${r.note ? `<span class="cell-sub">${esc(r.note)}</span>` : ""}</td><td>${code(r.object || "—")}</td><td>${esc(r.createdBy)}</td><td>${names(r.requires)}</td><td>${badge(PREP_LABEL[r.prep] || r.prep, { direct: "green", config: "green", derived: "blue", simulator: "amber", hardware: "red" }[r.prep] || "gray")}${r.prepNote ? `<span class="cell-sub">${esc(r.prepNote)}</span>` : ""}</td><td>${code(r.source || "")}</td></tr>`))}</section>` +
      CALL_AREAS.map((area) => { const list = NICO_CALLS.filter((c) => c.area === area); return list.length ? `<section class="call-table"><h2>接口：${area}</h2>${callTable(list)}</section>` : ""; }).join("") +
      (NICO_CALLS.some((c) => !CALL_AREAS.includes(c.area)) ? `<section><h2>接口：其他</h2>${callTable(NICO_CALLS.filter((c) => !CALL_AREAS.includes(c.area)))}</section>` : "") +
      `<section><h2>缺口：设计需要、NICo 没有直接提供</h2>${table(["设计需要", "涉及页面", "源码里的情况", "可选的处理", "出处"], CONTRACT_GAPS.map((g) => `<tr><td><strong>${esc(g.need)}</strong></td><td>${esc((g.pages || []).join("、"))}</td><td>${esc(g.finding)}</td><td>${esc(g.options)}</td><td>${code(g.source || "")}</td></tr>`), "没有记录缺口。")}</section>` +
      `<section><h2>不调用 NICo 的页面</h2><p>${pagesByNav().filter((p) => !pageCalls(p).length).map((p) => esc(pageName(p))).join("、") || "没有"}。这些页面的数据由平台自己保存。</p></section>` +
      (problems.length ? `<section><h2>自检问题</h2><ul>${problems.map((p) => `<li>${esc(p)}</li>`).join("")}</ul></section>` : "") + `</div>`;
  },
});

