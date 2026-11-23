// 从页面脚本里的 spec 生成 page-spec.zh-CN.md（页面功能说明）。页面说明只有一个来源：pages/*.js。
// 界面是简体中文，页面说明随界面只有简体中文。
// 用法：node tools/build-spec.mjs
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const html = fs.readFileSync(path.join(root, "index.html"), "utf8");
const scripts = [...html.matchAll(/<script src="([^"]+)"/g)].map((m) => m[1]).filter((s) => s !== "main.js");
const ctx = vm.createContext({ console, setInterval, clearInterval, setTimeout });
for (const s of scripts) { ctx.__file = s; vm.runInContext(fs.readFileSync(path.join(root, s), "utf8"), ctx, { filename: s }); }
const { pages, map, nav } = vm.runInContext("({ pages: pagesByNav().map((p) => Object.assign(p, { name: pageName(p), group: navPath(p)[0] || '—', calls: pageCalls(p).map((x) => ({ use: x.use, id: x.id, name: x.call ? x.call.name : x.id, surface: x.call ? x.call.surface : '未定义', write: !!(x.call && x.call.write), cli: x.call ? x.call.cli : '' })), chain: pageResources(p).map((r) => r.name) })), map: EXISTING_MAP, nav: NAV.map(([g, items]) => [g, items.map(([id, kids]) => MODULE_LABEL[id] + (kids ? '（子菜单：' + kids.map((k) => MODULE_LABEL[k]).join('、') + '）' : '')).join('；')]) })", ctx);

const cell = (v) => String(v ?? "").replace(/\|/g, "\\|").replace(/\n/g, " ");
const tbl = (head, rows) => [`| ${head.join(" | ")} |`, `| ${head.map(() => "---").join(" | ")} |`, ...rows.map((r) => `| ${r.map(cell).join(" | ")} |`)].join("\n");
const points = pages.flatMap((p) => p.spec.points), count = (k) => points.filter((x) => x.kind === k).length;

let out = `# 整机柜运维前端页面功能说明\n\n[设计稿说明](README.zh-CN.md) · [设计文档](../README.zh-CN.md)\n\n本文件由 \`tools/build-spec.mjs\` 从页面脚本生成，不要直接修改。页面与说明写在同一个文件里，改页面时一起改。\n\n` +
  `共 ${pages.length} 个页面、${points.length} 个功能点：沿用 ${count("沿用")}，调整 ${count("调整")}，新增 ${count("新增")}。“沿用”指与现有产品页面一致，“调整”指在现有基础上修改，“新增”指现有产品没有。\n\n` +
  `## 左侧菜单\n\n${tbl(["分组", "菜单项"], nav)}\n\n机柜是关联与汇总视图；设备按类型各有自己的入口，不需要先进机柜。\n\n## 页面清单\n\n${tbl(["菜单分组", "页面", "入口", "功能点"], pages.map((p) => [p.group, p.name.split(" › ").slice(1).join(" › ") || p.name, p.spec.entry, p.spec.points.length]))}\n\n` +
  `## 现有页面去向\n\n${tbl(["现有页面", "新页面", "变化"], map)}\n`;
for (const p of pages) {
  const s = p.spec;
  out += `\n## ${p.name}\n\n${s.purpose}\n\n- 入口：${s.entry}\n- 设计章节：${s.design}\n- 现有页面：${s.existing}\n- 脚本：\`${p.file}\`，路由 \`#${p.id}\`\n\n` +
    `### 功能点\n\n${tbl(["编号", "功能点", "类型", "说明"], s.points.map((x) => [x.n, x.name, x.kind, x.desc]))}\n`;
  if (s.fields) out += `\n### 字段\n\n${tbl(["字段", "来源", "说明"], s.fields)}\n`;
  if (s.rules) out += `\n### 规则与门控\n\n${s.rules.map((r) => `- ${r}`).join("\n")}\n`;
  if (p.calls.length) out += `\n### NICo 接口\n\n${tbl(["用途", "接口", "类型", "命令行"], p.calls.map((x) => [x.use, "`" + x.name + "`", x.surface + (x.write ? " · 写" : " · 读"), x.cli ? "`" + x.cli + "`" : "—"]))}\n\n前置资源（按准备顺序）：${p.chain.join(" → ") || "—"}\n`;
  for (const d of s.dialogs || []) out += `\n### 弹窗：${d.name}\n\n${d.desc}\n${d.fields ? "\n" + tbl(["输入", "必填", "说明"], d.fields) + "\n" : ""}`;
}
fs.writeFileSync(path.join(root, "page-spec.zh-CN.md"), out);

// ---- 接口契约：interface-contract.zh-CN.md（给人看）和 contract.json（给采集工具读） ----
const c = vm.runInContext(`({ source: CONTRACT_SOURCE, prep: PREP_LABEL, areas: CALL_AREAS, problems: contractProblems(),
  resources: resourceChain(NICO_RESOURCES.map((r) => r.id)).map((r) => Object.assign({}, r, { requiresNames: (r.requires || []).map((id) => (resourceById(id) || { name: id }).name) })),
  calls: NICO_CALLS.map((x) => Object.assign({}, x, { requiresNames: (x.requires || []).map((id) => (resourceById(id) || { name: id }).name), pages: callUsers(x.id).map((p) => pageName(p)) })),
  gaps: CONTRACT_GAPS })`, ctx);
const code = (v) => (v ? "`" + v + "`" : "—");
let doc = `# 整机柜运维接口契约\n\n[设计稿说明](README.zh-CN.md) · [页面功能说明](page-spec.zh-CN.md) · [设计文档](../README.zh-CN.md)\n\n本文件由 \`tools/build-spec.mjs\` 从 \`contract.js\` 和各页面脚本生成，不要直接修改。\n\n` +
  `每个页面调用 NICo 的哪些接口、对应什么命令行、用到哪些字段，以及要让页面有数据必须先准备好哪些资源。接口、参数和字段取自 NICo 源码 \`${c.source.repo}\` 的提交 \`${c.source.commit}\`（${c.source.version}）。${c.source.note}\n\n` +
  `证据等级：**定义** = 只读过源码里的定义；**模拟** = 在模拟环境里调用过；**现场** = 在真实整机柜环境核对过。共 ${c.resources.length} 个资源、${c.calls.length} 个接口（其中写操作 ${c.calls.filter((x) => x.write).length} 个，现有产品已调用 ${c.calls.filter((x) => x.used).length} 个）、${c.gaps.length} 个缺口。\n\n` +
  `## 各页面的接口数与前置资源\n\n${tbl(["页面", "读", "写", "前置资源（按准备顺序）"], pages.map((p) => [p.name, p.calls.filter((x) => !x.write).length, p.calls.filter((x) => x.write).length, p.calls.length ? p.chain.join(" → ") || "—" : "不调用 NICo，数据由平台自己保存"]))}\n\n每个页面具体用到哪些接口，见[页面功能说明](page-spec.zh-CN.md)里各页的“NICo 接口”一节。\n\n` +
  `## 资源依赖与准备顺序\n\n按“先准备的在前”排列。一个页面要有数据，它用到的接口的全部前置资源都要先就位。\n\n${tbl(["顺序", "资源", "NICo 对象", "怎么得到", "依赖", "没有真实整机柜时", "说明", "出处"], c.resources.map((r, i) => [i + 1, r.name, code(r.object), r.createdBy, r.requiresNames.join("、") || "—", (c.prep[r.prep] || r.prep) + (r.prepNote ? "：" + r.prepNote : ""), r.note || "", code(r.source)]))}\n`;
for (const area of [...c.areas, "其他"]) {
  const list = c.calls.filter((x) => (area === "其他" ? !c.areas.includes(x.area) : x.area === area));
  if (list.length) doc += `\n## 接口：${area}\n\n${tbl(["接口", "类型", "命令行", "请求参数", "用到的字段", "前置资源", "执行方", "使用的页面", "证据", "说明", "出处"], list.map((x) => [code(x.name), x.surface + (x.write ? " · 写" : " · 读"), code(x.cli), x.request || "—", (x.fields || []).join("、") || "—", x.requiresNames.join("、") || "—", x.executedBy || "Core", x.pages.join("；") || "—", (x.evidence || "定义") + (x.used ? "；现有产品已调用" : ""), x.note || "", code(x.source)]))}\n`;
}
doc += `\n## 缺口：设计需要、NICo 没有直接提供\n\n${c.gaps.length ? tbl(["设计需要", "涉及页面", "源码里的情况", "可选的处理", "出处"], c.gaps.map((g) => [g.need, (g.pages || []).join("、"), g.finding, g.options, code(g.source)])) : "没有记录缺口。"}\n`;
if (c.problems.length) doc += `\n## 自检问题\n\n${c.problems.map((p) => `- ${p}`).join("\n")}\n`;
fs.writeFileSync(path.join(root, "interface-contract.zh-CN.md"), doc);
fs.writeFileSync(path.join(root, "contract.json"), JSON.stringify({ source: c.source, resources: c.resources, calls: c.calls, gaps: c.gaps }, null, 2) + "\n");
console.log(`契约：资源 ${c.resources.length}，接口 ${c.calls.length}，缺口 ${c.gaps.length}，自检问题 ${c.problems.length} → interface-contract.zh-CN.md、contract.json`);
console.log(`页面 ${pages.length}，功能点 ${points.length}（沿用 ${count("沿用")} / 调整 ${count("调整")} / 新增 ${count("新增")}） → page-spec.zh-CN.md`);
