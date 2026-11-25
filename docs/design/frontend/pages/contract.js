"use strict";
/* 实现参考版才加载的内容：接口契约页、页面说明面板里的“NICo 接口”和“前置资源”、顶栏的入口。
   数据全部在 contract.js。对外版（index.html）不加载这两个文件。 */
DESIGN_EXT.topbar.push(`<button class="button compact" data-go="contract">接口契约</button>`, `<span class="design-tag">实现参考版</span>`);
DESIGN_EXT.guide.push((page) => contractHtml(page));

const LEVEL_KIND = { 必需: "keep", 整机柜: "change", 可选: "new" };
/* 页面说明面板：当前页面用到的 NICo 接口，以及要让它有数据必须先具备的资源。 */
const surfaceBadge = (c) => `<span class="kind ${c.write ? "change" : "keep"}">${esc(c.surface)} · ${c.write ? "写" : "读"}</span>`;
const API_KIND = { 沿用: "keep", 扩展: "change", 新增: "new" };
const platformHtml = (page) => { const apis = platformApis(page.id); return apis.length ? `<h3>平台后端接口</h3><p class="live-small">沿用 = 和现有产品一样；扩展 = 接口不变，多了字段或范围；新增 = 现有产品没有。</p>${apis.map((a) => `<div class="guide-call"><b>${esc(a.use)}</b><div class="live-code">${a.method} ${esc(a.path)}</div><span class="kind ${API_KIND[a.status]}">${a.status}</span>${a.change ? `<div class="guide-cli">${esc(a.change)}</div>` : ""}</div>`).join("")}` : ""; };
function contractHtml(page) {
  const list = pageCalls(page), chain = pageResources(page);
  if (!list.length) return platformHtml(page) + `<h3>NICo 接口</h3><p>这个页面不调用 NICo，数据由平台自己保存。</p>`;
  const parts = pageComponents(page);
  return platformHtml(page) + `<h3>需要的组件</h3><p>${parts.map((k) => `<b>${esc(k.name)}</b><span class="kind ${LEVEL_KIND[k.level]}">${esc(k.level)}</span>`).join("　")}</p>
    <h3>NICo 接口</h3>${list.map((x) => x.call
      ? `<div class="guide-call"><b>${esc(x.use)}</b><div class="live-code">${esc(x.call.name)}</div>${surfaceBadge(x.call)}${x.call.cli ? `<div class="guide-cli live-code">${esc(x.call.cli)}</div>` : ""}</div>`
      : `<div class="guide-call"><b>${esc(x.use)}</b><div class="live-code">${esc(x.id)}</div><span class="kind new">契约中未定义</span></div>`).join("")}
    ${chain.length ? `<h3>前置资源（按准备顺序）</h3><ol class="guide-chain">${chain.map((r) => `<li><b>${esc(r.name)}</b><span class="kind keep">${esc(PREP_LABEL[r.prep] || r.prep)}</span><p>${esc(r.createdBy)}</p></li>`).join("")}</ol>` : ""}
    <p style="margin-top:10px"><a class="link-button" data-go="contract">查看完整的接口契约</a></p>`;
}

/* 接口契约页：资源依赖、接口清单、各页面的对照和缺口。 */
const CALL_AREAS = ["站点与依赖", "网络与地址", "设备清单", "设备发现", "机柜与 NVLink 域", "设备读取", "设备操作", "机柜级任务", "交付与实例", "健康"];
registerPage("contract", {
  title: "接口契约", guideNote: "这个页面是接口契约的汇总。每个页面用到的接口在各自的页面说明里。",
  render() {
    const order = resourceChain(NICO_RESOURCES.map((r) => r.id)), problems = contractProblems();
    const names = (ids) => (ids || []).map((id) => (resourceById(id) || { name: id }).name).join("、") || "—";
    const users = (id) => callUsers(id).map((p) => `<a class="link-button" data-go="${p.id === "rack" ? "rack/RACK-A01" : p.id}">${esc(p.tab || p.title)}</a>`).join("　") || "—";
    const callTable = (list) => table(["接口 / 命令行", "请求参数", "用到的字段", "前置资源", "执行方", "使用的页面", "证据"], list.map((c) =>
      `<tr><td><strong class="live-code">${esc(c.name)}</strong><span class="cell-sub">${surfaceBadge(c)}</span>${c.cli ? `<span class="cell-sub guide-cli live-code">${esc(c.cli)}</span>` : ""}${c.note ? `<span class="cell-sub">${esc(c.note)}</span>` : ""}</td><td>${esc(c.request || "—")}</td><td>${esc((c.fields || []).join("、") || "—")}</td><td>${names(c.requires)}</td><td>${esc(c.executedBy || "Core")}</td><td>${users(c.id)}</td><td>${badge(c.evidence || "定义", { 现场: "green", 模拟: "blue", 调用: "amber" }[c.evidence] || "gray")}${c.observed ? `<span class="cell-sub">${esc(c.observed)}</span>` : ""}${c.used ? `<span class="cell-sub">${badge("现有产品已调用", "blue")}</span>` : ""}<span class="cell-sub live-code">${esc(c.source || "")}</span></td></tr>`));
    return `<div class="spec-doc contract-doc">` + heading("接口契约", "每个页面调用 NICo 的哪些接口、对应什么命令行、用到哪些字段，以及要让页面有数据必须先准备好哪些资源。", button("打印 / 另存为 PDF", "spec-print")) +
      note(`接口、参数和字段取自 NICo 源码 <b>${CONTRACT_SOURCE.repo}</b> 的提交 <span class="live-code">${CONTRACT_SOURCE.commit}</span>（${CONTRACT_SOURCE.version}）。“证据”一列说明核对到了哪一步：定义 = 只读过源码；调用 = 在没有整机柜硬件的 NICo 环境里实际调用过，下面写着看到了什么；模拟 = 在模拟整机柜的环境里调用过；现场 = 在真实整机柜环境核对过。${CONTRACT_SOURCE.tested}标有“现有产品已调用”的接口在主线产品里已经有调用代码，其余是整机柜方向新增的。`) +
      summary([["组件", NICO_COMPONENTS.length], ["资源", NICO_RESOURCES.length], ["接口", NICO_CALLS.length], ["其中写操作", NICO_CALLS.filter((c) => c.write).length], ["实际调用过", NICO_CALLS.filter((c) => c.evidence && c.evidence !== "定义").length], ["现有产品已调用", NICO_CALLS.filter((c) => c.used).length], ["缺口", CONTRACT_GAPS.length], ["自检问题", problems.length]]) +
      `<section><h2>组件：功能需要部署什么</h2><p class="live-small">一个接口需要某个组件，是由它的类型、执行方和前置资源推出来的。“必需”是任何功能都需要；“整机柜”是机柜级功能需要；“可选”缺了只影响一部分信息。</p>${table(["组件", "工作负载", "级别", "提供什么", "部署方式", "缺失时", "接口数", "依赖它的页面"], NICO_COMPONENTS.map((k) => `<tr><td><strong>${esc(k.name)}</strong><span class="cell-sub live-code">${esc(k.source || "")}</span></td><td>${esc(k.workload)}</td><td>${badge(k.level, { 必需: "green", 整机柜: "blue", 可选: "gray" }[k.level])}</td><td>${esc(k.provides)}</td><td>${esc(k.deploy || "—")}</td><td>${esc(k.missing)}</td><td>${componentCalls(k).length}</td><td>${k.id === "core" ? "全部调用 NICo 的页面" : componentPages(k).map((p) => `<a class="link-button" data-go="${p.id === "rack" ? "rack/RACK-A01" : p.id}">${esc(p.tab || p.title)}</a>`).join("　") || "—"}</td></tr>`))}</section>` +
      `<section><h2>资源依赖与准备顺序</h2><p class="live-small">按“先准备的在前”排列。一个页面要有数据，它用到的接口的全部前置资源都要先就位。</p>${table(["顺序", "资源", "NICo 对象", "怎么得到", "依赖", "没有真实整机柜时", "出处"], order.map((r, i) => `<tr><td>${i + 1}</td><td><strong>${esc(r.name)}</strong>${r.note ? `<span class="cell-sub">${esc(r.note)}</span>` : ""}</td><td>${code(r.object || "—")}</td><td>${esc(r.createdBy)}</td><td>${names(r.requires)}</td><td>${badge(PREP_LABEL[r.prep] || r.prep, { direct: "green", config: "green", derived: "blue", simulator: "amber", hardware: "red" }[r.prep] || "gray")}${r.prepNote ? `<span class="cell-sub">${esc(r.prepNote)}</span>` : ""}</td><td>${code(r.source || "")}</td></tr>`))}</section>` +
      CALL_AREAS.map((area) => { const list = NICO_CALLS.filter((c) => c.area === area); return list.length ? `<section class="call-table"><h2>接口：${area}</h2>${callTable(list)}</section>` : ""; }).join("") +
      (NICO_CALLS.some((c) => !CALL_AREAS.includes(c.area)) ? `<section><h2>接口：其他</h2>${callTable(NICO_CALLS.filter((c) => !CALL_AREAS.includes(c.area)))}</section>` : "") +
      `<section><h2>各页面用到的接口</h2>${table(["页面", "需要的组件", "读", "写", "接口与用途"], pagesByNav().map((p) => { const list = pageCalls(p); return `<tr><td><a class="link-button" data-go="${p.id === "rack" ? "rack/RACK-A01" : p.id}">${esc(pageName(p))}</a></td><td>${pageComponents(p).map((k) => esc(k.name)).join("、") || "—"}</td><td>${list.filter((x) => x.call && !x.call.write).length}</td><td>${list.filter((x) => x.call && x.call.write).length}</td><td>${list.length ? list.map((x) => `${esc(x.use)}：<span class="live-code">${esc(x.call ? x.call.name : x.id)}</span>`).join("<br>") : "不调用 NICo，数据由平台自己保存"}</td></tr>`; }))}</section>` +
      `<section><h2>平台后端接口：沿用现有产品的哪些，新增哪些</h2><p class="live-small">设备导入、设备发现、系统配置、装系统这四段沿用现有产品的流程和接口；整机柜只追加字段，或新增机柜这一层的接口。沿用 ${PLATFORM_APIS.filter((a) => a.status === "沿用").length} 个，扩展 ${PLATFORM_APIS.filter((a) => a.status === "扩展").length} 个，新增 ${PLATFORM_APIS.filter((a) => a.status === "新增").length} 个。</p>${table(["页面", "接口", "与现有产品的关系", "用途", "变化"], PLATFORM_APIS.map((a) => `<tr><td>${esc(pageName(PAGES[a.page]))}</td><td><span class="live-code">${a.method} ${esc(a.path)}</span></td><td><span class="kind ${API_KIND[a.status]}">${a.status}</span></td><td>${esc(a.use)}</td><td>${esc(a.change || "—")}</td></tr>`))}</section>` +
      `<section><h2>缺口：设计需要、NICo 没有直接提供</h2>${table(["设计需要", "涉及页面", "源码里的情况", "可选的处理", "出处"], CONTRACT_GAPS.map((g) => `<tr><td><strong>${esc(g.need)}</strong></td><td>${esc((g.pages || []).join("、"))}</td><td>${esc(g.finding)}</td><td>${esc(g.options)}</td><td>${code(g.source || "")}</td></tr>`), "没有记录缺口。")}</section>` +
      (problems.length ? `<section><h2>自检问题</h2><ul>${problems.map((p) => `<li>${esc(p)}</li>`).join("")}</ul></section>` : "") + `</div>`;
  },
});

