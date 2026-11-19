"""Pure helpers of the cabling page, run in Node with stubbed page globals."""

import json
import shutil
import subprocess
import unittest
from pathlib import Path

PAGE = Path(__file__).resolve().parents[2] / "src/pxeye/web/pages/cabling.js"

HARNESS = r"""
const vm = require("vm");
const fs = require("fs");
const noop = () => {};
const ctx = {
  state: {}, deviceStatusPages: { servers: {} }, registerPage: noop,
  deviceStatusAddNavChild: noop, deviceStatusReload: noop, registerActions: noop, observeUI: noop,
  esc: (x) => String(x),
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), ctx);
const r = vm.runInContext(process.argv[2], ctx);
process.stdout.write(JSON.stringify(r));
"""


def run(expr):
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node is not installed")
    out = subprocess.run(
        [node, "-e", HARNESS, str(PAGE), expr],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(out.stdout)


SERVERS = """[
  [{serial: "SN-A"}, {lldp: [
    {switch_id: "sw-1", remote_port: "p1", local_port: "eth0", mac_address: "m-a0"},
    {switch_id: "sw-1", remote_port: "p1", local_port: "eth0", mac_address: "m-a0"},
    {switch_id: "sw-2", remote_port: "p9", local_port: "eth1", mac_address: "m-a1"}]}],
  [{serial: "SN-B"}, {lldp: [
    {switch_id: "sw-1", remote_port: "p1", local_port: "eth0", mac_address: "m-b0"},
    {switch_id: "sw-1", remote_port: "p2", local_port: "eth1", mac_address: "m-b1"}]}],
  [{serial: "SN-C"}, {}],
  [{serial: "SN-D"}, {lldp: []}],
  [{serial: "SN-E"}, null]
]"""


class CablingTest(unittest.TestCase):
    def test_conflicts(self):
        self.assertEqual(run(f"[...cablingConflicts(cablingLinks({SERVERS}))].length"), 1)

    def test_same_interface_twice_is_no_conflict(self):
        expr = f"[...cablingConflicts(cablingLinks({SERVERS}.slice(0, 1)))].length"
        self.assertEqual(run(expr), 0)

    def test_grouping_by_switch(self):
        expr = (
            "Object.fromEntries(Object.entries(cablingSwitches("
            f"cablingLinks({SERVERS}))).map(([k, v]) => [k, v.length]))"
        )
        self.assertEqual(run(expr), {"sw-1": 4, "sw-2": 1})

    def test_missing_split(self):
        expr = (
            f"(({{noLldp, noMachine}}) => [noLldp.map((d) => d.serial), "
            f"noMachine.map((d) => d.serial)])(cablingMissing({SERVERS}))"
        )
        self.assertEqual(run(expr), [["SN-C", "SN-D"], ["SN-E"]])

    def test_empty_input(self):
        self.assertEqual(run("cablingLinks([]).length"), 0)
        self.assertEqual(run("[...cablingConflicts([])].length"), 0)

    def test_name_limit(self):
        expr = "cablingNames(Array.from({length: 25}, (_, i) => ({serial: 'S' + i})))"
        text = run(expr)
        self.assertTrue(text.endswith("等 25 台"))
        self.assertNotIn("S20", text)
        self.assertEqual(run("cablingNames([{name: 'n1'}])"), "n1")


if __name__ == "__main__":
    unittest.main()
