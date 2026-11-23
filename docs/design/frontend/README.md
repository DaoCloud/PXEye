# Whole-rack operations frontend design

**English** · [简体中文](README.zh-CN.md) · [Design documents](../README.md)

The frontend page design of PXEye for GB200 / GB300 whole racks. It is the reference for the frontend implementation: the pages can be clicked through, the styles and code conventions match the existing product, and every page carries its own description. All data is authored sample data; nothing connects to a site, and none of it is implemented functionality.

## Open it

In a checkout of the repository, open `docs/design/frontend/index.html` in a browser. No build or server is needed. The page links the product stylesheets under `src/pxeye/web/` directly, so it must be opened inside the repository; the directory cannot be copied elsewhere on its own.

## Where the page descriptions are

The description of each page (purpose, entry, feature points, fields, rules, dialogs) is the `spec` of that page's script, in the same file as its rendering code. It is shown in three ways from that single source:

| View | Where | Use |
| --- | --- | --- |
| The “页面说明” panel on the right | “页面说明” in the top bar, or the vertical strip on the right when the panel is collapsed | Read the description of the current page while clicking through. The panel can be collapsed, expanded and widened; it always pushes the page aside and never covers it |
| Numbered markers on the page | “功能点标注” in the top bar | The numbers match the feature points of the description; hovering a feature point highlights the page element |
| All page descriptions | “全部页面说明” in the top bar, or [page-spec.zh-CN.md](page-spec.zh-CN.md) | Review and printing |

`page-spec.zh-CN.md` is generated; do not edit it. After changing a page or its `spec`, regenerate it:

```bash
node docs/design/frontend/tools/build-spec.mjs
```

Feature point types: **沿用** (kept) is the same as the existing product page, **调整** (changed) modifies an existing one, **新增** (new) does not exist in the product. The interface is in Simplified Chinese, and so are the page descriptions that come with it.

## Left menu

The menu goes straight to objects: each device type has its own entry, with no need to enter a rack first; the rack is the view that relates and summarises devices. A menu item with a submenu can be collapsed: clicking the text opens the page and expands it, clicking the arrow only toggles it.

| Group | Menu items |
| --- | --- |
| 运维 (Operations) | 机柜管理; NVLink 域管理; 设备管理 (submenu: 计算托盘, 交换机, 供电框, DPU); 健康告警; 运维任务; 操作审计 |
| 交付 (Delivery) | 机柜交付; 安装任务; 实例管理 |
| 接入 (Onboarding) | 网络规划; 设备清单; 设备发现 |
| 配置 (Configuration) | 站点设置; 固件基线; 安装方案 |

The three onboarding items are in the order they are used: plan the subnets, import the device inventory, then watch device discovery after power-on. The inventory cannot be imported while the network plan check fails.

Menu names are formal four-character names, page titles equal the menu names, and submenu items are device type names. A number on a menu item is always the count that needs attention, not a total. First-level items keep the product's font size and spacing, with a darker colour and slightly heavier weight; submenu items are one size smaller and lighter.

## Wording

Interface text is Chinese throughout and does not join an English abbreviation with Chinese into one term. Fixed terms: 安装方案, 交换机, 机柜上线 (NICo's bringup), 就绪, 序列号, 开机 and 关机, 阻止分配. The three device types are collectively “设备”; “计算托盘” is only the name of one type.

Only two kinds of text stay in their original form: product and component names (NICo, NVLink, RMS, Flow, BMC, PMC, NVOS, DPU, Fabric Manager), and the state values reported by NICo state machines (such as Ready, Maintenance), which are shown verbatim by rule.

## Structure

| File | Content |
| --- | --- |
| `index.html` | The shell. Styles are linked from `styles.css`, `live.css` and `nico.css` under `src/pxeye/web/`; the design keeps no copy |
| `design.css` | Component styles added by the design and the annotation layer; move the component part into the product styles when implementing |
| `app.js` | Runtime: `registerPage` / `registerAction`, `heading` / `table` / `button` / `badge` / `modal`, with the same signatures and class names as the product's `shared/live.js` |
| `data.js` | Sample data and task simulation; replaced by the NICo Core and Flow interfaces when implementing |
| `pages/*.js` | Page scripts, each page with its `spec` |
| `pages/operations.js` | Write operations and gates for racks, NVLink domains and devices |
| `tools/build-spec.mjs` | Generates `page-spec.zh-CN.md` from the page scripts |

## Walkthrough

The “讲解与模拟” tab of the right panel has a ten-step walkthrough and a few simulation switches: power on and discover a new rack, leak alert, RMS unavailable, Flow unavailable, reset sample data. The top bar switches between three roles: read-only cannot run any operation; operator can run device, rack and delivery operations; administrator can also change the site, the network and installation profiles.
