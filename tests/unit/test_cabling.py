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
  sectionReads: {}, registerHook: noop, table: (h, rows) => rows.join(""), badge: (t) => t,
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


LABELS = """{switches: [
    {chassis_mac: "aa:bb:cc:00:00:01", name: "LEAF-A", model: "M-1", serial: "SN-SW1",
     management_ip: "192.0.2.10", rack: "R1"},
    {chassis_mac: "aa:bb:cc:00:00:09", name: "GHOST"}],
  ports: [{chassis_mac: "aa:bb:cc:00:00:01", port_id: "11:22:33:44:55:01", port_name: "Eth1/1"},
    {chassis_mac: "aa:bb:cc:00:00:01", port_id: "p-none", port_name: "X"}]}"""
LINK = (
    "{device: {serial: 'SN-A'}, reported: {}, switchKey: 'AA-BB-CC-00-00-01', neighbor: "
    "{switch_id: 'AA-BB-CC-00-00-01', switch: 'lldp-name', remote_port: '11:22:33:44:55:01', "
    "remote_port_type: 'mac'}}"
)


class CablingLabelTest(unittest.TestCase):
    def test_switch_title_uses_label(self):
        out = run(f"cablingSwitchTitle({LINK}.neighbor, cablingLabelIndex({LABELS}))")
        self.assertEqual(out["title"], "LEAF-A")
        self.assertIn("LLDP lldp-name AA-BB-CC-00-00-01", out["detail"])
        self.assertIn("管理 IP 192.0.2.10", out["detail"])

    def test_switch_title_without_label(self):
        out = run(f"cablingSwitchTitle({LINK}.neighbor, cablingLabelIndex(null))")
        self.assertEqual(out["title"], "lldp-name")

    def test_port_name_first(self):
        html = run(f"cablingRow({LINK}, false, cablingLabelIndex({LABELS}))")
        self.assertLess(html.index("Eth1/1"), html.index("11:22:33:44:55:01"))
        plain = run(f"cablingRow({LINK}, false)")
        self.assertNotIn("Eth1/1", plain)

    def test_counts_unmatched(self):
        out = run(f"cablingLabelCounts([{LINK}], {LABELS})")
        self.assertEqual(
            out, {"switches": 1, "switchesUnmatched": 1, "ports": 1, "portsUnmatched": 1}
        )

    def test_csv_round_trip_quotes(self):
        out = run(
            "cablingCsv(cablingPortColumns, [{chassis_mac: 'm', port_id: 'a,b', port_name: 'q\"'}])"
        )
        self.assertEqual(out, 'chassis_mac,port_id,port_name\nm,"a,b","q"""')
        self.assertEqual(run("cablingCsv(cablingPortColumns, [])"), "")


if __name__ == "__main__":
    unittest.main()
