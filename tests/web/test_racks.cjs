// 机柜 page: state text and the maintenance form rules, without a browser.
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "../../src/pxeye/web/pages/racks.js"),
  "utf8",
);
const sandbox = {
  module: { exports: {} },
  state: {},
  sectionReads: {},
  registerPage() {},
  registerActions() {},
  observeUI() {},
  registerHook() {},
  deviceStatusAddNavChild() {},
};
vm.runInNewContext(source, sandbox);
const {
  racksStateText,
  racksStateTone,
  racksMaintenanceParams,
  racksMaintenanceSummary,
} = sandbox.module.exports;

assert.equal(racksStateText(""), "未报告");
assert.equal(racksStateText("Ready"), "Ready");
assert.equal(
  racksStateText("Maintenance/FirmwareUpgrade/Start"),
  "Maintenance（FirmwareUpgrade/Start）",
);
assert.equal(racksStateTone({ state: "" }), "gray");
assert.equal(racksStateTone({ state: "Ready", lifecycle: {} }), "green");
assert.equal(racksStateTone({ state: "Error/x", lifecycle: {} }), "red");
assert.equal(
  racksStateTone({ state: "Ready", lifecycle: { outcome: "error" } }),
  "red",
);
assert.equal(
  racksStateTone({ state: "Validating", lifecycle: { above_sla: true } }),
  "amber",
);

const fail = (form, text) =>
  assert.throws(() => racksMaintenanceParams(form), { message: text });
fail({ activities: [] }, "请至少选择一个维护项目。");
fail({ activities: ["nvos_update"] }, "固件升级和 NVOS 更新需要 SOT JSON。");
fail(
  { activities: ["firmware_upgrade"], sot: "{" },
  "SOT JSON 不是有效的 JSON。",
);
fail(
  { activities: ["power_sequence"], scope: "devices" },
  "请至少选择一台设备，或改为整个机柜。",
);

// Whole rack: no id lists; SOT only with the activities that need it.
assert.deepEqual(
  JSON.parse(
    JSON.stringify(
      racksMaintenanceParams({
        scope: "rack",
        activities: ["power_sequence"],
        sot: "{}",
        components: "BMC",
        reason: "  ",
      }),
    ),
  ),
  { activities: ["power_sequence"] },
);
const params = racksMaintenanceParams({
  scope: "devices",
  activities: ["firmware_upgrade", "configure_nmx_cluster"],
  sot: ' {"a": 1} ',
  components: "BMC, CPLD，HMC",
  force: true,
  machines: ["m1"],
  switches: [],
  power_shelves: ["p1"],
  reason: "CHG-1",
});
assert.deepEqual(JSON.parse(JSON.stringify(params)), {
  activities: ["firmware_upgrade", "configure_nmx_cluster"],
  sot_json: '{"a": 1}',
  components: ["BMC", "CPLD", "HMC"],
  force_update: true,
  machine_ids: ["m1"],
  power_shelf_ids: ["p1"],
  reason: "CHG-1",
});
const summary = racksMaintenanceSummary(params);
assert.equal(summary.activities, "固件升级、NVLink 集群配置");
assert.equal(summary.scope, "所选设备：计算主机 1 · 交换机 0 · 供电框 1");
assert.equal(
  racksMaintenanceSummary({ activities: ["nvos_update"] }).scope,
  "整个机柜",
);
console.log("racks page: ok");
