"""Pure helpers of the device operation dialog and the records page, run in Node."""

import json
import shutil
import subprocess
import unittest
from pathlib import Path

PAGES = Path(__file__).resolve().parents[2] / "src/pxeye/web/pages"

HARNESS = r"""
const vm = require("vm");
const fs = require("fs");
const noop = () => {};
const ctx = {
  state: {}, sectionReads: {}, registerPage: noop, registerActions: noop, observeUI: noop,
  registerHook: noop, deviceStatusAddNavChild: noop, window: { addEventListener: noop },
  document: { body: { classList: { contains: () => false } } },
  table: (h, rows) => rows.join(""), badge: (t) => t, esc: (x) => String(x),
  button: (t) => t, defs: () => "", heading: () => "", when: (t) => String(t),
};
vm.createContext(ctx);
for (const file of process.argv.slice(1, -1))
  vm.runInContext(fs.readFileSync(file, "utf8"), ctx);
const r = vm.runInContext(process.argv[process.argv.length - 1], ctx);
process.stdout.write(JSON.stringify(r === undefined ? null : r));
"""


def run(expr):
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node is not installed")
    files = [str(PAGES / "device_status.js"), str(PAGES / "rack_action_records.js")]
    out = subprocess.run(
        [node, "-e", HARNESS, *files, expr], capture_output=True, text=True, check=True
    )
    return json.loads(out.stdout)


CATALOG = """[
  {id: "power_on", kind: "machine", available: true, params: []},
  {id: "maintenance_enable", kind: "machine", available: true,
   params: [{name: "reference", label: "工单", type: "text", required: true}]},
  {id: "component_firmware_update_tray", kind: "machine", available: true, params: []},
  {id: "switch_reset", kind: "switch", available: true, params: []},
  {id: "rack_power_on", kind: "rack", available: false, params: []}
]"""

RACK = """{params: [
  {name: "activities", label: "维护项目", type: "multi", required: true,
   choices: ["firmware_upgrade", "power_sequence"]},
  {name: "sot_json", label: "SOT JSON", type: "json", required: false,
   required_with: ["firmware_upgrade"]},
  {name: "machine_ids", label: "机器", type: "list", required: false},
  {name: "force_update", label: "强制", type: "bool", required: false}]}"""


class ActionDialogTest(unittest.TestCase):
    def test_groups_by_kind(self):
        out = run(
            f"deviceStatusActionGrouped({CATALOG}, 'machine').map(([g, a]) => [g, a.map((x) => x.id)])"
        )
        self.assertEqual(
            out,
            [
                ["电源", ["power_on"]],
                ["维护与隔离", ["maintenance_enable"]],
                ["固件与其他", ["component_firmware_update_tray"]],
            ],
        )
        self.assertEqual(run(f"deviceStatusActionGrouped({CATALOG}, 'switch')[0][0]"), "复位")
        self.assertEqual(run(f"deviceStatusActionGrouped({CATALOG}, 'power_shelf')"), [])

    def test_required_param(self):
        expr = f"deviceStatusActionCollect({CATALOG}[1], {{reference: '  '}})"
        self.assertEqual(run(expr)["error"], "请填写工单。")
        expr = f"deviceStatusActionCollect({CATALOG}[1], {{reference: ' T-1 '}})"
        self.assertEqual(run(expr), {"params": {"reference": "T-1"}, "error": ""})

    def test_required_with_and_lists(self):
        out = run(f"deviceStatusActionCollect({RACK}, {{activities: ['firmware_upgrade']}})")
        self.assertEqual(out["error"], "所选维护项目需要SOT JSON。")
        out = run(
            f"deviceStatusActionCollect({RACK}, {{activities: ['power_sequence', 'bogus'], "
            "machine_ids: 'm1\\n m2 ,m3\\n', force_update: true})"
        )
        self.assertEqual(
            out["params"],
            {
                "activities": ["power_sequence"],
                "machine_ids": ["m1", "m2", "m3"],
                "force_update": True,
            },
        )
        out = run(
            f"deviceStatusActionCollect({RACK}, {{activities: ['firmware_upgrade'], sot_json: '{{x'}})"
        )
        self.assertEqual(out["error"], "SOT JSON不是有效的 JSON。")

    def test_high_risk_confirmation(self):
        preview = """{action: {needs_confirm_serial: true}, targets: [
          {target: "m1", serial: "SN1", eligible: true, confirm_with: "serial"},
          {target: "r1", serial: "", eligible: true, confirm_with: "id"},
          {target: "m3", serial: "SN3", eligible: false, confirm_with: "serial"}]}"""
        out = run(f"deviceStatusActionConfirm({preview}, {{m1: 'SN1', r1: 'x'}})")
        self.assertEqual(out["missing"], ["r1"])
        self.assertFalse(out["ready"])
        out = run(f"deviceStatusActionConfirm({preview}, {{m1: ' SN1 ', r1: 'r1', m3: 'SN3'}})")
        self.assertEqual(out["confirm"], {"m1": "SN1", "r1": "r1"})
        self.assertTrue(out["ready"])
        self.assertEqual(out["eligible"], 2)

    def test_low_risk_needs_no_typing_but_one_eligible(self):
        preview = "{action: {needs_confirm_serial: false}, targets: [{target: 'm1', eligible: %s}]}"
        self.assertTrue(run(f"deviceStatusActionConfirm({preview % 'true'}, {{}}).ready"))
        self.assertFalse(run(f"deviceStatusActionConfirm({preview % 'false'}, {{}}).ready"))

    def test_target_requires_core_object(self):
        self.assertIsNone(run("deviceStatusActionTarget({serial: 'S'}, null)"))
        self.assertEqual(
            run("deviceStatusActionTarget({serial: 'S', id: 'e1'}, {id: 'm1'})"),
            {"target": "m1", "serial": "S", "label": "S"},
        )

    def test_hidden_when_switch_off_or_read_only(self):
        self.assertFalse(run("state.rackActions = false; deviceStatusActionEnabled()"))
        self.assertTrue(run("state.rackActions = true; deviceStatusActionEnabled()"))
        expr = (
            "state.rackActions = true; document.body.classList.contains = () => true; "
            "deviceStatusActionEnabled()"
        )
        self.assertFalse(run(expr))


RECORDS = """[
  {id: "a", created: 10, action: "power_on", status: "succeeded", reason: "T-1",
   operator: "session:x@1", targets: [{target: "m1", serial: "SN1", name: "host-1"}]},
  {id: "b", created: 30, action: "force_off", status: "unknown", reason: "",
   operator: "session:x@1", targets: [{target: "m2", serial: "SN2", name: ""}]},
  {id: "c", created: 20, action: "power_on", status: "refused", reason: "",
   operator: "session:y@2", targets: [{target: "m2", serial: "SN2", name: ""}]}
]"""
CAT = "{actions: [{id: 'force_off', label: '强制关机'}]}"


class RecordsTest(unittest.TestCase):
    def ids(self, filters):
        return run(f"rackActionRecordsFilter({RECORDS}, {filters}, {CAT}).map((r) => r.id)")

    def test_newest_first(self):
        self.assertEqual(self.ids("{}"), ["b", "c", "a"])

    def test_filters(self):
        self.assertEqual(self.ids("{action: 'power_on'}"), ["c", "a"])
        self.assertEqual(self.ids("{status: 'unknown'}"), ["b"])
        self.assertEqual(self.ids("{search: 'sn2'}"), ["b", "c"])
        self.assertEqual(self.ids("{search: '强制'}"), ["b"])
        self.assertEqual(self.ids("{search: 'y@2', action: 'power_on'}"), ["c"])

    def test_label_falls_back_to_id(self):
        self.assertEqual(run(f"rackActionRecordsLabel('force_off', {CAT})"), "强制关机")
        self.assertEqual(run("rackActionRecordsLabel('x', null)"), "x")

    def test_disabled_without_switch(self):
        self.assertFalse(run("state.readiness = {rack_actions: false}; rackActionRecordsEnabled()"))
        self.assertTrue(run("state.readiness = {rack_actions: true}; rackActionRecordsEnabled()"))


if __name__ == "__main__":
    unittest.main()
