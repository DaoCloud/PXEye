"use strict";
/* 设计稿运行时。写法对齐产品的 shared/live.js 与 shared/ui_runtime.js：
   - 页面用 registerPage 注册，一个页面只有一个注册归属；
   - 操作用 registerAction 注册，页面里的按钮通过 data-live="<操作名>" 触发；
   - heading / button / badge / table / defs / modal 的签名与产出的类名和产品一致。
   与产品不同的只有两点：数据来自 data.js 的示例数据；每个页面带一份 spec（页面说明）。 */

const $ = (s) => document.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

/* ---------- 与产品一致的页面构造函数 ---------- */
const button = (text, action, primary = false, extra = "") => `<button class="button ${primary ? "primary" : ""}" data-live="${action}" ${extra}>${esc(text)}</button>`;
const badge = (text, color = "gray") => `<span class="status ${color}">${esc(text)}</span>`;
const table = (heads, rows, empty = "暂无记录") =>
  `<div class="live-table-wrap"><table class="live-table"><thead><tr>${heads.map((x) => `<th>${esc(x)}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table>${rows.length ? "" : `<div class="live-empty">${esc(empty)}</div>`}</div>`;
const defs = (rows) => `<dl class="live-def">${rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join("")}</dl>`;
const heading = (name, description, actions = "") => `<div class="live-heading"><div><h1 tabindex="-1">${esc(name)}</h1><p>${esc(description)}</p></div><div class="live-tools">${actions}</div></div>`;
const note = (html, kind = "") => `<div class="live-note ${kind === "warning" ? "live-warning" : kind === "error" ? "live-error" : ""}">${html}</div>`;
const code = (v) => `<span class="live-code">${esc(v)}</span>`;
const summary = (items) => `<div class="summary-strip device-status-summary cols-${items.length}">${items.map(([k, v]) => `<div><small>${esc(k)}</small><strong>${v}</strong></div>`).join("")}</div>`;
const selectField = (key, label, options, value) =>
  `<label>${esc(label)}<select class="input" data-filter="${key}">${options.map(([v, t]) => `<option value="${esc(v)}" ${String(value ?? "") === String(v) ? "selected" : ""}>${esc(t)}</option>`).join("")}</select></label>`;
const searchField = (key, label, value, placeholder) => `<label>${esc(label)}<input class="input" type="search" data-filter="${key}" value="${esc(value || "")}" placeholder="${esc(placeholder || "")}"></label>`;

/* 页面功能点锚点：fp(3) 给元素打上编号，标注模式下显示，与页面说明里的功能点一一对应。 */
const fp = (n) => `data-fp="${n}"`;

/* 写操作按钮：只读角色、依赖组件缺失或业务门控不满足时禁用，并在 title 里写明原因。
   admin: true 的操作只有管理角色可用（站点、网络、安装方案）；其余写操作需要操作或管理角色。 */
function act(text, action, { primary = false, gate = "", extra = "", compact = false, admin = false } = {}) {
  const reason = S.role === "只读" ? "只读角色不能执行操作" : admin && S.role !== "管理" ? "需要管理角色：站点与共享档案由管理角色维护" : gate;
  return `<button class="button ${primary ? "primary" : ""} ${compact ? "compact" : ""}" data-live="${action}" ${extra} ${reason ? `disabled title="${esc(reason)}"` : ""}>${esc(text)}</button>`;
}

/* ---------- 状态显示：页面显示 NICo 的状态原文，颜色只表达类别 ---------- */
function stateBadge(text) {
  if (!text) return badge("未发现", "gray");
  const color = /^(Ready|Assigned\/Ready|已完成|Running|已发布)$/.test(text) ? "green" : /Error|Failed|失败|不符|已终止|Degraded/.test(text) ? "red" : /Created|未报告|草稿|Off/.test(text) ? "gray" : "blue";
  return badge(text, color);
}
/* 电源显示：NICo 回报 On / Off，界面显示开机 / 关机；没有回报显示未报告。 */
const powerText = (v) => ({ On: "开机", Off: "关机" })[v] || "未报告";
const healthBadge = (h) => ({ ok: badge("正常", "green"), warn: badge("告警", "amber"), bad: badge("严重", "red"), none: badge("未报告", "gray") })[h];
function rackHealth(r) {
  if (r.state === "Created") return "none";
  const alerts = DB.alerts().filter((a) => a.rack === r.id);
  return alerts.some((a) => a.block) ? "bad" : alerts.length ? "warn" : "ok";
}
const rackNeedsAttention = (r) => DB.blockers(r).length > 0 || r.state === "Error" || rackHealth(r) === "bad";
const readyCount = (r, type) => { const list = r.trays.filter((t) => !type || t.type === type); return `${list.filter((t) => /Ready$/.test(t.state)).length}<small>/ ${list.length}</small>`; };

/* ---------- 注册表 ---------- */
const PAGES = {}, PAGE_ORDER = [], ACTIONS = {};
/* 左侧菜单：按“对象直达”组织。每个菜单项是一个入口（nav id），可以带子菜单。
   机柜是关联与汇总视图；设备按类型各有自己的入口，不需要先进机柜。 */
const NAV = [
  ["运维", [["racks"], ["domains"], ["devices", ["compute", "switch", "power_shelf", "dpu"]], ["health"], ["tasks"], ["audit"]]],
  ["交付", [["delivery"], ["installs"], ["instances"]]],
  ["接入", [["network"], ["inventory"], ["discovery"]]],
  ["配置", [["site"], ["baselines"], ["os"]]],
];
/* 菜单名用四个字的正式名称，与主分支的“设备管理”“实例管理”“站点设置”“安装任务”同一规格；子菜单是设备类型名。页面标题与菜单名一致。 */
const MODULE_LABEL = { racks: "机柜管理", domains: "NVLink 域管理", devices: "设备管理", compute: "计算托盘", switch: "交换机", power_shelf: "供电框", dpu: "DPU", health: "健康告警", tasks: "运维任务", audit: "操作审计", delivery: "机柜交付", installs: "安装任务", instances: "实例管理", site: "站点设置", network: "网络规划", inventory: "设备清单", discovery: "设备发现", baselines: "固件基线", os: "安装方案" };
const MODULE_ROUTE = { compute: "devices/compute", switch: "devices/switch", power_shelf: "devices/power-shelf", dpu: "devices/dpu", installs: "delivery/installs", instances: "delivery/instances", os: "os-templates" };
const MODULE_PARENT = {}; NAV.forEach(([, items]) => items.forEach(([id, kids]) => (kids || []).forEach((k) => (MODULE_PARENT[k] = id))));
const navRoute = (id) => MODULE_ROUTE[id] || id;
/* 带说明的页面，按菜单顺序排列。 */
const pagesByNav = () => NAV.flatMap(([, items]) => items.flatMap(([id, kids]) => [id, ...(kids || [])])).flatMap((m) => PAGE_ORDER.map((id) => PAGES[id]).filter((p) => p.module === m && p.spec));
const pageName = (p) => [...navPath(p), ...(p.tab ? [p.tab] : []), ...(p.crumb ? [p.title] : [])].join(" › ") || p.title;
/* 页面在菜单中的完整位置，用于面包屑和页面说明。 */
function navPath(page) {
  if (!page.module) return [];
  const group = NAV.find(([, items]) => items.some(([id, kids]) => id === page.module || (kids || []).includes(page.module)))[0];
  return [group, ...(MODULE_PARENT[page.module] ? [MODULE_LABEL[MODULE_PARENT[page.module]]] : []), MODULE_LABEL[page.module]];
}
/* def: { module, tab, title, render(arg), spec } —— module 是所属菜单项；tab 是同一菜单项下的页签名（只有站点和清单使用）。 */
function registerPage(id, def) { if (PAGES[id]) throw new Error("duplicate page " + id); def.id = id; def.file = typeof document !== "undefined" && document.currentScript ? document.currentScript.getAttribute("src") : globalThis.__file || ""; PAGES[id] = def; PAGE_ORDER.push(id); }
function registerAction(name, fn) { if (ACTIONS[name]) throw new Error("duplicate action " + name); ACTIONS[name] = fn; }

/* ---------- 路由 ---------- */
function route() {
  const hash = (typeof location === "undefined" ? "" : location.hash.slice(1)) || "racks";
  if (PAGES[hash]) return { id: hash, arg: "" };
  const i = hash.indexOf("/");
  const id = i < 0 ? hash : hash.slice(0, i);
  return PAGES[id] ? { id, arg: decodeURIComponent(hash.slice(i + 1)) } : { id: "racks", arg: "" };
}
function go(hash) { if (location.hash.slice(1) === hash) render(); else location.hash = hash; }
const view = (key, fallback) => (S.view[key] === undefined ? fallback : S.view[key]);

function moduleTabs(module, current) {
  const tabs = PAGE_ORDER.map((id) => PAGES[id]).filter((p) => p.module === module && p.tab);
  if (tabs.length < 2) return "";
  return `<div class="live-tabs" role="tablist">${tabs.map((p) => `<button class="button ${p.id === current ? "primary" : ""}" role="tab" aria-selected="${p.id === current}" data-go="${p.id}">${esc(p.tab)}</button>`).join("")}</div>`;
}

function render() {
  const { id, arg } = route(), page = PAGES[id], alerts = DB.alerts();
  document.body.classList.toggle("annotate", !!S.view.annotate);
  document.body.classList.toggle("guide-open", S.view.guide !== false);
  document.body.classList.toggle("guide-wide", S.view.guide !== false && !!S.view.guideWide);
  /* 菜单上的数字都表示“需要关注的数量”，不是总数。 */
  const count = { racks: S.racks.filter(rackNeedsAttention).length, health: alerts.length, tasks: S.racks.filter(DB.busy).length, devices: DB.trays().filter(DB.needsAttention).length };
  /* 子菜单可折叠：点父级文字进入父级页面并展开，点箭头只切换折叠。进入子菜单里的页面时自动展开；
     折叠后如果当前页面在子菜单里，父级显示为选中。 */
  if (S.view.lastPage !== id) { S.view.lastPage = id; if (MODULE_PARENT[page.module]) S.view["nav:" + MODULE_PARENT[page.module]] = true; }
  const open = (pid) => view("nav:" + pid, pid === "devices");
  const label = (id) => `<span>${MODULE_LABEL[id]}</span>${count[id] ? `<span class="nav-count">${count[id]}</span>` : ""}`;
  const item = (id, sub) => `<button class="nav-item ${sub ? "nav-sub" : ""} ${page.module === id ? "active" : ""}" data-go="${navRoute(id)}">${label(id)}</button>`;
  const parent = (id, kids) => `<div class="nav-parent ${open(id) ? "open" : ""}"><button class="nav-item ${page.module === id || (!open(id) && kids.includes(page.module)) ? "active" : ""}" data-go="${navRoute(id)}" data-nav-open="${id}">${label(id)}</button>` +
    `<button class="nav-toggle" data-design="nav-toggle" data-id="${id}" aria-expanded="${open(id)}" aria-label="${open(id) ? "收起" : "展开"}${MODULE_LABEL[id]}子菜单">${CHEVRON}</button></div>` +
    `<div class="nav-children" ${open(id) ? "" : "hidden"}>${kids.map((k) => item(k, true)).join("")}</div>`;
  $("#navigation").innerHTML = NAV.map(([group, items]) => `<div class="nav-group"><div class="nav-label">${group}</div>${items.map(([id, kids]) => (kids ? parent(id, kids) : item(id))).join("")}</div>`).join("");
  const path = navPath(page), leaf = page.crumb ? page.crumb(arg) : page.tab || "";
  $("#breadcrumb").innerHTML = `<span>基础设施</span>` + path.slice(1).map((p, i, list) => `<span>/</span>` + (i === list.length - 1 && !leaf ? `<strong>${esc(p)}</strong>` : `<span>${esc(p)}</span>`)).join("") + (leaf ? `<span>/</span><strong>${esc(leaf)}</strong>` : path.length ? "" : `<span>/</span><strong>${esc(page.title)}</strong>`);
  $("#operator").textContent = `${S.role}角色 · 已登录`;
  $("#design-topbar").innerHTML =
    `<span class="design-tag">设计稿 · 示例数据</span>` +
    `<label>角色 <select data-design="role">${["只读", "操作", "管理"].map((r) => `<option ${S.role === r ? "selected" : ""}>${r}</option>`).join("")}</select></label>` +
    `<button class="button compact ${S.view.annotate ? "primary" : ""}" data-design="annotate">功能点标注</button>` +
    `<button class="button compact ${S.view.guide !== false ? "primary" : ""}" data-design="guide">页面说明</button>` +
    `<button class="button compact" data-go="spec">全部页面说明</button>`;
  $("#main").innerHTML = (page.tab && page.module ? moduleTabs(page.module, id) : "") + page.render(arg);
  renderGuide(page, arg);
}

/* ---------- 弹窗与抽屉（类名与产品一致） ---------- */
const CHEVRON = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M9 6l6 6-6 6"/></svg>`;
const CLOSE_ICON = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true" focusable="false"><path d="M6 6l12 12M18 6L6 18"/></svg>`;
function modal(title, sub, body, foot, { drawer = false, wide = true } = {}) {
  S.view.modal = true;
  $(".app-shell").inert = true;
  $("#overlay-root").innerHTML = `<div class="overlay-backdrop ${drawer ? "drawer-side" : ""}"><section class="modal ${drawer ? "drawer" : wide ? "wide" : ""}" role="dialog" aria-modal="true" aria-labelledby="live-dialog-title"><header class="modal-header"><div><h2 id="live-dialog-title">${esc(title)}</h2><p>${esc(sub)}</p></div><button class="icon-button live-close" data-live="close" aria-label="关闭">${CLOSE_ICON}</button></header><div class="modal-body">${body}</div>${foot ? `<footer class="modal-footer"><span></span><div class="actions">${foot}</div></footer>` : ""}</section></div>`;
  $("#overlay-root button:not([disabled]):not(.live-close),#overlay-root input")?.focus();
}
function closeModal() { S.view.modal = false; $("#overlay-root").innerHTML = ""; $(".app-shell").inert = false; }
function toast(text) { const el = $("#toast"); el.textContent = text; el.classList.add("visible"); clearTimeout(toast.timer); toast.timer = setTimeout(() => el.classList.remove("visible"), 3200); }
const field = (label, control, hint = "") => `<label class="form-field"><span>${esc(label)}</span>${control}${hint ? `<small class="muted">${esc(hint)}</small>` : ""}</label>`;

/* 所有写操作共用的确认弹窗：只显示对象、动作、受影响的实例、将经过的阶段；输入只有原因（和高风险时的对象确认）。 */
function confirmOperation({ title, target, action, instances = 0, stages = [], extra = "", high = false, confirmText = "", why = "", submit = "提交", run }) {
  const facts = [["对象", `<b>${esc(target)}</b>`], ["动作", esc(action)], ["受影响的实例", instances ? `<b style="color:var(--red)">${instances} 个</b>` : "0 个"]];
  if (stages.length) facts.push(["将经过的阶段", esc(stages.join(" → "))]);
  modal(title, stages.length ? "确认后提交为一个任务。顺序、超时和重试由站点规则决定。" : "确认后立即执行，并读回结果。",
    `<div class="confirm-facts">${defs(facts)}</div>${extra}<div class="live-form">${field("原因", `<input class="input" id="op-why" value="${esc(why)}" placeholder="工单号或原因">`)}${high ? field(`高风险操作：输入 ${confirmText} 以确认`, `<input class="input live-code" id="op-confirm" autocomplete="off">`) : ""}</div>`,
    button("取消", "close") + `<button class="button ${high ? "danger" : "primary"}" data-live="op-submit">${esc(submit)}</button>`, { wide: false });
  confirmOperation.pending = () => {
    const reason = $("#op-why").value.trim();
    if (!reason) return toast("请填写原因");
    if (high && $("#op-confirm").value.trim() !== confirmText) return toast("输入的内容与对象不一致");
    const picked = $("#op-pick") ? $("#op-pick").value : "";
    closeModal(); run(reason, picked); render();
  };
}
registerAction("close", closeModal);
registerAction("op-submit", () => confirmOperation.pending && confirmOperation.pending());
registerAction("refresh", () => { toast("已重新读取 NICo 的状态"); render(); });

/* ---------- 页面说明面板 ---------- */
const KIND = { 沿用: "keep", 调整: "change", 新增: "new" };
function specHtml(spec) {
  const points = (list) => list.map((p) => `<div class="guide-point" data-point="${p.n}"><span class="pin">${p.n}</span><div><b>${esc(p.name)}</b><span class="kind ${KIND[p.kind] || "keep"}">${esc(p.kind || "沿用")}</span><p>${esc(p.desc)}</p></div></div>`).join("");
  return `<h3>页面定位</h3><p>${esc(spec.purpose)}</p>
    <dl style="margin-top:10px"><dt>入口</dt><dd>${esc(spec.entry)}</dd><dt>设计章节</dt><dd>${esc(spec.design)}</dd><dt>现有页面</dt><dd>${esc(spec.existing)}</dd></dl>
    <h3>功能点</h3>${points(spec.points)}
    ${spec.fields ? `<h3>字段</h3><table class="guide-table"><thead><tr><th>字段</th><th>来源</th><th>说明</th></tr></thead><tbody>${spec.fields.map((f) => `<tr><td><b>${esc(f[0])}</b></td><td>${esc(f[1])}</td><td>${esc(f[2] || "")}</td></tr>`).join("")}</tbody></table>` : ""}
    ${spec.rules ? `<h3>规则与门控</h3><ul>${spec.rules.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>` : ""}
    ${(spec.dialogs || []).map((d) => `<h3>弹窗：${esc(d.name)}</h3><p>${esc(d.desc)}</p>${d.fields ? `<table class="guide-table" style="margin-top:6px"><thead><tr><th>输入</th><th>必填</th><th>说明</th></tr></thead><tbody>${d.fields.map((f) => `<tr><td><b>${esc(f[0])}</b></td><td>${esc(f[1])}</td><td>${esc(f[2] || "")}</td></tr>`).join("")}</tbody></table>` : ""}`).join("")}`;
}
const GUIDE_STEPS = [
  ["站点设置", "检查依赖组件是否就绪", "site"], ["网络规划", "规划各类设备的网段与 DHCP 地址池", "network"], ["设备清单", "导入到货清单，确认差异", "inventory"],
  ["设备发现", "模拟通电后查看发现进度与失败原因", "discovery"], ["机柜上线", "处理对账问题，提交任务并跟踪阶段", "rack/RACK-A03"], ["机柜交付", "按机柜装机或交给上层平台", "delivery"],
  ["健康告警", "告警与阻止分配", "health"], ["设备管理", "从菜单直接进入交换机：看地址、固件，上下电", "devices/switch"], ["NVLink 域管理", "域级固件与分阶段发布", "domains"], ["操作审计", "每次操作的记录", "audit"],
];
function renderGuide(page, arg) {
  const tab = view("guideTab", "spec"), a03 = DB.rack("RACK-A03");
  const sim = `<h3>讲解主线</h3><ol class="guide-steps">${GUIDE_STEPS.map(([t, d, h], i) => `<li class="${S.guide === i + 1 ? "now" : ""}" data-guide="${i + 1}" data-go="${h}">${i + 1}. ${t}<small>${d}</small></li>`).join("")}</ol>
    <h3>模拟现场与 NICo 的变化</h3><div class="guide-sim">
      <button class="button compact" data-live="sim-discover" ${a03 && a03.state === "Created" ? "" : `disabled title="${a03 ? "已发现" : "先导入清单"}"`}>通电并发现 RACK-A03</button>
      <button class="button compact" data-live="sim-leak">${S.leak ? "清除泄漏告警" : "触发泄漏告警"}</button>
      <button class="button compact" data-live="sim-rms">${S.rms ? "RMS 不可用" : "恢复 RMS"}</button>
      <button class="button compact" data-live="sim-flow">${S.flow ? "Flow 不可用" : "恢复 Flow"}</button>
      <button class="button compact" data-live="sim-reset">重置示例数据</button></div>
    <p class="muted" style="margin-top:12px">任务进度用定时器模拟，每个阶段约一秒，不代表真实耗时。</p>`;
  const name = page.crumb ? page.crumb(arg) : page.tab || page.title;
  if (S.view.guide === false) { $("#guide").innerHTML = `<button class="guide-handle" data-design="guide" aria-label="展开页面说明" title="展开页面说明">${CHEVRON}<span>页面说明</span></button>`; return; }
  $("#guide").innerHTML = `<div class="guide-head"><div class="guide-title"><div><h2>${esc(name)}</h2><p>${navPath(page).join(" › ") || "汇总"} · 页面说明随页面一起维护</p></div>
      <div class="guide-tools"><button class="button compact" data-design="guide-wide">${S.view.guideWide ? "恢复宽度" : "加宽"}</button><button class="button compact" data-design="guide">收起</button></div></div>
    <div class="guide-tabs"><button class="${tab === "spec" ? "active" : ""}" data-design="guide-spec">页面说明</button><button class="${tab === "demo" ? "active" : ""}" data-design="guide-demo">讲解与模拟</button></div></div>
    <div class="guide-body">${tab === "spec" ? (page.spec ? specHtml(page.spec) : "<p>这个页面是全部页面说明的汇总。</p>") : sim}</div>`;
}

/* ---------- 事件 ---------- */
function boot() {
  document.addEventListener("click", (e) => {
    const point = e.target.closest("[data-guide]"); if (point) S.guide = +point.dataset.guide;
    const design = e.target.closest("[data-design]");
    if (design && design.tagName === "BUTTON") {
      const k = design.dataset.design;
      if (k === "annotate") S.view.annotate = !S.view.annotate;
      if (k === "guide") S.view.guide = S.view.guide === false;
      if (k === "guide-spec") S.view.guideTab = "spec";
      if (k === "guide-demo") S.view.guideTab = "demo";
      if (k === "guide-wide") S.view.guideWide = !S.view.guideWide;
      if (k === "nav-toggle") S.view["nav:" + design.dataset.id] = !view("nav:" + design.dataset.id, design.dataset.id === "devices");
      return render();
    }
    const nav = e.target.closest("[data-go]");
    if (nav && nav.dataset.navOpen) S.view["nav:" + nav.dataset.navOpen] = true;
    if (nav) { if (S.view.modal) closeModal(); return go(nav.dataset.go); }
    const live = e.target.closest("[data-live]");
    if (live && !live.disabled) { const fn = ACTIONS[live.dataset.live]; if (fn) fn(live.dataset, live); else toast("设计稿未实现这个操作：" + live.dataset.live); }
  });
  document.addEventListener("change", (e) => {
    if (e.target.dataset.design === "role") { S.role = e.target.value; return render(); }
    if (e.target.dataset.filter && e.target.tagName === "SELECT") { S.view[e.target.dataset.filter] = e.target.value; render(); }
    if (e.target.dataset.check) { const set = (S.view.checked = S.view.checked || {}); set[e.target.dataset.check] = e.target.checked; render(); }
  });
  document.addEventListener("input", (e) => {
    if (e.target.dataset.filter && e.target.tagName === "INPUT") {
      const key = e.target.dataset.filter, pos = e.target.selectionStart; S.view[key] = e.target.value; render();
      const again = document.querySelector(`[data-filter="${key}"]`); if (again) { again.focus(); again.setSelectionRange(pos, pos); }
    }
  });
  document.addEventListener("mouseover", (e) => {
    const p = e.target.closest(".guide-point"); document.querySelectorAll(".fp-hot").forEach((el) => el.classList.remove("fp-hot"));
    if (p) document.querySelectorAll(`#main [data-fp="${p.dataset.point}"]`).forEach((el) => { el.classList.add("fp-hot"); });
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && S.view.modal) closeModal(); });
  window.addEventListener("hashchange", () => { if (S.view.modal) closeModal(); render(); });
  if (innerWidth < 1180) S.view.guide = false;
  render();
}
