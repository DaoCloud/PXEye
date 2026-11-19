"""The alerts page, run in Node with stubbed page globals."""

import json
import shutil
import subprocess
import unittest
from pathlib import Path

PAGE = Path(__file__).resolve().parents[2] / "src/pxeye/web/pages/alerts.js"

HARNESS = r"""
const vm = require("vm");
const fs = require("fs");
const noop = () => {};
const esc = (x) => String(x ?? "");
const ctx = {
  state: {}, registerPage: noop, deviceStatusAddNavChild: noop, deviceStatusReload: noop,
  registerActions: noop, observeUI: noop, esc,
  deviceStatusPages: {
    servers: { kind: "server", label: "服务器", source: "servers" },
    switches: { kind: "switch", label: "交换机", source: "switches" },
    power_shelves: { kind: "power_shelf", label: "供电框", source: "power_shelves" },
  },
  deviceStatusHealth: {
    ok: ["正常", "green"], warning: ["告警", "amber"], alert: ["告警", "amber"],
    critical: ["严重", "red"], unknown: ["未报告", "gray"],
  },
  deviceStatusReported: (page, d) => ctx.state.deviceStatus[page.source][d.native_id] || null,
  deviceStatusTime: (t) => t || "—",
  eqAttr: (id) => `data-id="${id}"`,
  badge: (t) => `<b>${t}</b>`, button: (t, a) => `<button data-live="${a}">${t}</button>`,
  heading: (n) => `<h1>${n}</h1>`, table: (h, rows) => `<table>${rows.join("")}</table>`,
  selectField: (k) => `<select id="${k}"></select>`, inputField: (k) => `<input id="${k}">`,
  when: () => "T",
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


def alert(alert_id, since, *classifications):
    return {
        "id": alert_id,
        "target": "target-1",
        "message": "message",
        "since": since,
        "classifications": list(classifications),
    }


def reported(level, *alerts):
    return {"health": {"level": level, "alerts": list(alerts)}}


DEVICES = json.dumps(
    [
        ["servers", {"id": "d1", "serial": "SN-1"}, reported("alert", alert("PoweredOff", "2026-01-02T00:00:00Z", "PreventAllocations", "Hardware"))],
        ["servers", {"id": "d2", "serial": "SN-2"}, reported("alert", alert("PoweredOff", "2026-01-01T00:00:00Z", "PreventAllocations"), alert("Other", "", "Hardware"))],
        ["switches", {"id": "d3", "serial": "SN-3"}, reported("critical")],
        ["switches", {"id": "d4", "serial": "SN-4"}, reported("ok")],
        ["power_shelves", {"id": "d5", "serial": "SN-5"}, reported("unknown")],
        ["power_shelves", {"id": "d6", "serial": "SN-6"}, None],
    ]
)  # fmt: skip


def page_state(devices):
    """State for alertsRender: devices are [page, device, reported] triples."""
    rows = {"servers": {}, "switches": {}, "power_shelves": {}}
    equipment = []
    kinds = {"servers": "server", "switches": "switch", "power_shelves": "power_shelf"}
    for page, device, report in devices:
        device = dict(device, kind=kinds[page], native_id=device["id"])
        equipment.append(device)
        if report:
            rows[page][device["id"]] = report
    return json.dumps(
        {
            "rackOperations": True,
            "equipment": {"devices": equipment},
            "deviceStatus": dict(rows, observed_at=1, errors=[]),
        }
    )


class AlertsTest(unittest.TestCase):
    def test_entries_and_summary(self):
        expr = f"alertsSummary(alertsEntries({DEVICES}))"
        self.assertEqual(run(expr), {"alerts": 3, "devices": 3, "types": 2, "prevent": 2})

    def test_level_without_alerts_listed_once(self):
        expr = f"alertsEntries({DEVICES}).filter((e) => !e.alert).map((e) => [e.device.serial, e.level])"
        self.assertEqual(run(expr), [["SN-3", "critical"]])

    def test_grouping_and_earliest(self):
        expr = (
            f"((g) => Object.fromEntries(Object.entries(g).map(([k, v]) => "
            f"[k, [v.length, alertsEarliest(v)]])))(alertsGroups(alertsEntries({DEVICES})))"
        )
        self.assertEqual(
            run(expr),
            {
                "PoweredOff": [2, "2026-01-01T00:00:00Z"],
                "Other": [1, ""],
                "\u0000level": [1, ""],
            },
        )

    def test_filters(self):
        base = f"alertsEntries({DEVICES})"
        self.assertEqual(
            run(f"state.alertsFilters.kind = 'switches'; {base}.filter(alertsMatches).length"), 1
        )
        self.assertEqual(
            run(f"state.alertsFilters.classification = 'Hardware'; {base}.filter(alertsMatches).length"),
            2,
        )  # fmt: skip
        self.assertEqual(
            run(f"state.alertsFilters.search = 'sn-2'; {base}.filter(alertsMatches).length"), 2
        )

    def test_render_opens_status_dialog(self):
        expr = f"Object.assign(state, {page_state(json.loads(DEVICES))}); alertsRender()"
        html = run(expr)
        self.assertIn(
            'data-live="device-status-open" data-device-status="servers" data-id="d1"', html
        )
        self.assertIn("健康等级为严重但未报告告警项", html)
        self.assertIn("另有 1 台设备", html)
        html = run(expr.replace("alertsRender()", "state.alertsView = 'device'; alertsRender()"))
        self.assertIn('data-device-status="switches" data-id="d3"', html)

    def test_render_all_healthy(self):
        devices = json.loads(DEVICES)[3:]
        html = run(f"Object.assign(state, {page_state(devices)}); alertsRender()")
        self.assertIn("NICo 报告了 2 台设备的健康状态，均未报告告警，读取于 T", html)

    def test_gate_off(self):
        html = run("state.rackOperations = false; alertsRender()")
        self.assertIn("此页面未在当前站点启用", html)

    def test_read_error(self):
        html = run(
            "Object.assign(state, {rackOperations: true, equipment: {devices: []}, "
            "deviceStatus: null, readErrors: {deviceStatus: 'read failed'}}); alertsRender()"
        )
        self.assertIn('role="alert"', html)
        self.assertIn("read failed", html)


if __name__ == "__main__":
    unittest.main()
