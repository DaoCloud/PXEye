"use strict";
/* 页面脚本全部加载后启动。锚点链接在“全部页面说明”里滚动到对应章节，不改变路由。 */
document.addEventListener("click", (e) => {
  const a = e.target.closest("[data-anchor]");
  if (a) { e.preventDefault(); document.getElementById(a.dataset.anchor)?.scrollIntoView({ behavior: "smooth", block: "start" }); }
});
boot();
