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
