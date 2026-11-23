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
const { pages, map, nav } = vm.runInContext("({ pages: pagesByNav().map((p) => Object.assign(p, { name: pageName(p), group: navPath(p)[0] || '—' })), map: EXISTING_MAP, nav: NAV.map(([g, items]) => [g, items.map(([id, kids]) => MODULE_LABEL[id] + (kids ? '（子菜单：' + kids.map((k) => MODULE_LABEL[k]).join('、') + '）' : '')).join('；')]) })", ctx);

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
  for (const d of s.dialogs || []) out += `\n### 弹窗：${d.name}\n\n${d.desc}\n${d.fields ? "\n" + tbl(["输入", "必填", "说明"], d.fields) + "\n" : ""}`;
}
fs.writeFileSync(path.join(root, "page-spec.zh-CN.md"), out);
console.log(`页面 ${pages.length}，功能点 ${points.length}（沿用 ${count("沿用")} / 调整 ${count("调整")} / 新增 ${count("新增")}） → page-spec.zh-CN.md`);
