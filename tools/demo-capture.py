#!/usr/bin/env python3
"""Write a demo capture: authored placeholder data for every rack operations page.

Nothing here comes from a site. A stand-in NICo Core answers from the tables below,
and tools/core-capture.py runs against it in-process, exactly as at a site, so the
result is an ordinary capture that tools/core-replay.py serves without any Core:

    python3 tools/demo-capture.py > demo.json
    PYTHONPATH=src python3 tools/core-replay.py serve demo.json --writable

The site is named "演示站点（示例数据）" and the document carries "demo": true. Serials
are DEMO-…, MAC addresses are locally administered (02:…), addresses come from the
documentation ranges 192.0.2.0/24 and 198.51.100.0/24. Keep the generated file out of
the repository like any other capture.

What the data shows, on purpose:

- 2 racks (DEMO-R01, DEMO-R02) and 8 servers: Ready; Assigned/Ready; Failed/NVMECleanFailed
  with outcome ERROR past its time limit; HostInit/WaitingForDiscovery past its time limit;
  HostInit/WaitingForLockdown in transition; one declared server Core has not created
  (DEMO-SRV-007); one server without a rack (DEMO-SRV-008). Two servers have a DPU.
- Health alerts on 3 servers: PoweredOff (PreventAllocations, Hardware), FanSpeed,
  Temperature on a GPU target. A health warning on one NVLink switch.
- LLDP to two leaf switches: demo-leaf-a sends its name and MED inventory and port names;
  the other sends only its chassis MAC and MAC port ids (named by the switch labels). Two
  servers report the same port of demo-leaf-a (a conflict). DEMO-SRV-004 reports no LLDP.
- Switch labels include one switch no server hears (unmatched). Rack units cover every
  server of DEMO-R01; DEMO-SRV-006 is recorded in DEMO-R01 although declared in DEMO-R02
  (a mismatch).
- Site exploration: successful BMC reports, and three NICO-SITEEXPLORER-101 refusals. No
  authentication failure: its error code has not been observed at a site, so none is made up.
"""

import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
SITE = "演示站点（示例数据）"
CORE_URL = "https://core.demo.invalid:1079"
BASE = datetime(2026, 11, 18, 1, 0, tzinfo=timezone.utc)


def at(minutes, micro=0):
    return (
        (BASE + timedelta(minutes=minutes, microseconds=micro)).isoformat().replace("+00:00", "Z")
    )


def mid(n, kind="h"):
    return f"fm100{kind}demo{n:04d}" + "0" * 36


# ---------------------------------------------------------------- servers
# n, rack, state, outcome, reason, above sla, alerts, lldp key, dpu, gpu, core machine
SERVERS = [
    (1, "DEMO-R01", "Ready", None, "", False, [], "a1", True, True, True),
    (2, "DEMO-R01", "Assigned/Ready", None, "", False, ["PoweredOff"], "a2", False, True, True),
    (
        3,
        "DEMO-R01",
        "Failed/NVMECleanFailed",
        "ERROR",
        "the object is in the state for longer than defined by the SLA",
        True,
        ["FanSpeed"],
        "b3",
        False,
        False,
        True,
    ),
    (
        4,
        "DEMO-R01",
        "HostInit/WaitingForDiscovery",
        None,
        "",
        True,
        [],
        None,
        False,
        False,
        True,
    ),
    (
        5,
        "DEMO-R02",
        "HostInit/WaitingForLockdown",
        "TRANSITION",
        "waiting for lockdown to be applied",
        False,
        ["Temperature"],
        "mix5",
        True,
        True,
        True,
    ),
    (6, "DEMO-R02", "Ready", None, "", False, [], "mix6", False, False, True),
    (7, "DEMO-R02", None, None, "", False, [], None, False, False, False),
    (8, "", "Ready", None, "", False, [], "b8", False, False, True),
]


def serial(n):
    return f"DEMO-SRV-{n:03d}"


def bmc_mac(n):
    return f"02:00:5e:10:00:{n:02x}"


def bmc_ip(n):
    return f"192.0.2.{10 + n}"


def host_mac(n, port):
    return f"02:00:5e:20:{n:02x}:{port:02x}"


LEAF_A = {"mac": "02:de:00:00:0a:01", "name": "demo-leaf-a"}
LEAF_B = {"mac": "02:de:00:00:0b:01"}
LEAF_C = "02:de:00:00:0c:01"  # labelled, heard by nobody


def leaf_a(n, port, switch_port):
    return {
        "macAddress": host_mac(n, port).upper(),
        "lldp": {
            "name": LEAF_A["name"],
            "description": "Demo Network OS, Version 0.0 (placeholder)",
            "localPort": f"ens{port + 1}f0np0",
            "idType": "mac",
            "idValue": LEAF_A["mac"],
            "remotePortType": "ifname",
            "remotePortValue": f"Ethernet1/{switch_port}",
            "medInventory": {
                "serial": "DEMO-SW-LEAF-A",
                "manufacturer": "DemoNet",
                "model": "DemoNet DS-4800",
            },
        },
    }


def leaf_b_port(switch_port):
    return f"02:de:00:00:0b:{0x10 + switch_port:02x}"


def leaf_b(n, port, switch_port):
    return {
        "macAddress": host_mac(n, port).upper(),
        "lldp": {
            "localPort": f"ens{port + 1}f1np1",
            "idType": "mac",
            "idValue": LEAF_B["mac"],
            "remotePortType": "mac",
            "remotePortValue": leaf_b_port(switch_port),
        },
    }


LLDP = {
    "a1": lambda n: [leaf_a(n, 0, 1), leaf_a(n, 1, 2), leaf_b(n, 2, 1), leaf_b(n, 3, 2)],
    "a2": lambda n: [leaf_a(n, 0, 3), leaf_a(n, 1, 4), leaf_b(n, 2, 3)],
    "b3": lambda n: [leaf_b(n, 0, 5), leaf_b(n, 1, 6)],
    # DEMO-SRV-005 and DEMO-SRV-006 both report Ethernet1/9: the deliberate conflict.
    "mix5": lambda n: [leaf_a(n, 0, 9), leaf_b(n, 1, 9), leaf_a(n, 2, 10)],
    "mix6": lambda n: [leaf_a(n, 0, 9), leaf_b(n, 1, 11)],
    "b8": lambda n: [leaf_b(n, 0, 12), leaf_b(n, 1, 13)],
}

ALERTS = {
    "PoweredOff": lambda n: {
        "id": "PoweredOff",
        "target": bmc_ip(n),
        "inAlertSince": at(1320, 242424),
        "message": 'System "1" power state is "Off"',
        "classifications": ["PreventAllocations", "Hardware"],
    },
    "FanSpeed": lambda n: {
        "id": "FanSpeed",
        "target": "Fan3",
        "inAlertSince": at(1260),
        "message": "Fan3 speed 1800 RPM is below the lower threshold 2400 RPM",
        "classifications": ["Hardware"],
    },
    "Temperature": lambda n: {
        "id": "Temperature",
        "target": "GPU3",
        "inAlertSince": at(1350),
        "message": "GPU3 temperature 87 C is above the warning threshold 85 C",
        "classifications": ["Hardware"],
    },
}


def capabilities(n, gpu):
    result = {
        "cpu": [{"name": "Demo CPU 64-Core", "count": 2, "vendor": "DemoChip"}],
        "memory": [{"name": "DDR5", "count": 16, "vendor": "DemoMem", "capacity": "64 GiB"}],
        "storage": [
            {"name": "DEMO NVMe 3.84TB", "count": 4, "vendor": "DemoDisk", "capacity": "3.84 TB"},
            {"name": "DEMO M.2 480GB", "count": 1, "vendor": "DemoDisk", "capacity": "480 GB"},
        ],
        "network": [{"name": "Demo 2x100GbE Adapter", "count": 2, "vendor": "DemoNIC"}],
    }
    if gpu:
        result["gpu"] = [
            {"name": "Demo GPU 80GB", "count": 8, "vendor": "DemoGPU", "capacity": "80 GiB"}
        ]
    return result


def machine(row):
    n, rack, state, outcome, reason, above, alerts, lldp, dpu, gpu, _ = row
    lifecycle = {"state": state, "version": f"V{n + 3}-T17950{n:02d}000000000"}
    if outcome:
        lifecycle["stateReason"] = {"outcome": outcome, "outcomeMsg": reason}
    lifecycle["sla"] = {
        "sla": "0s" if above else "1800s",
        **({"timeInStateAboveSla": True} if above else {}),
    }
    health = {"source": "aggregate-host-health", "observedAt": at(1430, 491614)}
    if alerts:
        health["alerts"] = [ALERTS[name](n) for name in alerts]
    status = {
        "lifecycle": lifecycle,
        "health": health,
        "capabilities": capabilities(n, gpu),
        "lastRebootTime": at(400 + n * 30, 473018),
        "lastScoutObservedVersion": "0.0.0-demo-0000000",
        "bmcStatus": {},
    }
    if lldp:
        status["lldpNeighbors"] = LLDP[lldp](n)
    if state.startswith("Failed"):
        status["failureDetails"] = "StateMachineArea(HostInit)/NVMECleanFailed"
    if dpu:
        status["associatedDpuMachineIds"] = [{"id": mid(n, "d")}]
    bmc = {"ip": bmc_ip(n), "mac": bmc_mac(n).upper()}
    result = {
        "id": {"id": mid(n)},
        "state": state,
        "machineType": "HOST",
        "bmcInfo": bmc,
        "bmc": bmc,
        "metadata": {"name": mid(n)},
        "placementInRack": {},
        "config": {"dpf": {}, **({"hwSku": "demo-gpu-8x"} if gpu else {})},
        "status": status,
    }
    if rack:
        result["rackId"] = {"value": rack}
    return result


def dpu_machine(n):
    bmc = {"ip": f"198.51.100.{10 + n}", "mac": f"02:00:5e:30:00:{n:02x}".upper()}
    return {
        "id": {"id": mid(n, "d")},
        "state": "Ready",
        "machineType": "DPU",
        "bmcInfo": bmc,
        "bmc": bmc,
        "metadata": {"name": mid(n, "d")},
        "config": {},
        "status": {
            "lifecycle": {"state": "Ready", "sla": {"sla": "0s"}},
            "health": {"source": "aggregate-dpu-health", "observedAt": at(1430)},
            "associatedHostMachineId": {"id": mid(n)},
            "capabilities": {"dpu": [{"name": "Demo DPU", "count": 1, "vendor": "DemoNIC"}]},
            "dpuAgentVersion": "0.0.0-demo",
        },
    }


MACHINES = [machine(row) for row in SERVERS if row[10]] + [
    dpu_machine(row[0]) for row in SERVERS if row[8]
]
MACHINE_IDS = [m["id"]["id"] for m in MACHINES]


def expected_machine(row):
    n, rack = row[0], row[1]
    result = {
        "bmc_mac_address": bmc_mac(n),
        "bmc_username": "demo",
        "bmc_password": "demo-placeholder",
        "bmc_ip_address": bmc_ip(n),
        "chassis_serial_number": serial(n),
        "metadata": {"name": f"demo-srv-{n:03d}", "labels": []},
        "host_nics": [
            {
                "mac_address": host_mac(n, 0),
                "role": 1,
                "primary": True,
                "ip_allocation": 2,
                "fixed_ip": f"198.51.100.{100 + n}",
                "fixed_mask": "255.255.255.0",
                "fixed_gateway": "198.51.100.1",
            }
        ],
    }
    if rack:
        result["rack_id"] = {"value": rack}
    return result


EXPECTED_MACHINES = {"expected_machines": [expected_machine(row) for row in SERVERS]}

# ------------------------------------------------- NVLink switches, power shelf
NVSWITCHES = [
    {
        "id": {"value": "demo-nvsw-0001"},
        "isPrimary": True,
        "rackId": {"value": "DEMO-R01"},
        "placementInRack": {"slotNumber": 20},
        "nvlinkDomainUuid": {"value": "00000000-0000-4000-8000-00000000d001"},
        "config": {"enableNmxc": True},
        "metadata": {"name": "demo-nvsw-1"},
        "bmcInfo": {
            "ip": "192.0.2.41",
            "mac": "02:00:5e:40:00:01",
            "firmwareVersion": "0.0.1-demo",
        },
        "status": {
            "lifecycle": {"state": "Ready"},
            "controllerState": "ready",
            "healthStatus": "ok",
            "health": {"source": "switch-health", "observedAt": at(1430)},
            "powerState": "on",
            "serialNumber": "DEMO-NVSW-001",
            "fabricManagerStatus": "running",
            "fabricManagerStatusDetails": {"fabricManagerState": "FABRIC_MANAGER_STATE_OK"},
            "nvosPorts": [
                {
                    "mac": "02:00:5e:41:00:01",
                    "isPrimary": True,
                    "addresses": [{"address": "198.51.100.41"}],
                },
                {"mac": "02:00:5e:41:00:02", "servicePort": True},
            ],
        },
    },
    {
        "id": {"value": "demo-nvsw-0002"},
        "rackId": {"value": "DEMO-R01"},
        "placementInRack": {"slotNumber": 21},
        "nvlinkDomainUuid": {"value": "00000000-0000-4000-8000-00000000d001"},
        "config": {},
        "metadata": {"name": "demo-nvsw-2"},
        "bmcInfo": {
            "ip": "192.0.2.42",
            "mac": "02:00:5e:40:00:02",
            "firmwareVersion": "0.0.1-demo",
        },
        "status": {
            "lifecycle": {"state": "Ready"},
            "controllerState": "ready",
            "healthStatus": "warning",
            "health": {
                "source": "switch-health",
                "observedAt": at(1430),
                "alerts": [
                    {
                        "id": "PowerSupply",
                        "target": "PSU2",
                        "message": "PSU2 is not present",
                        "inAlertSince": at(1200),
                        "classifications": [],
                    }
                ],
            },
            "powerState": "on",
            "serialNumber": "DEMO-NVSW-002",
            "fabricManagerStatus": "degraded",
            "fabricManagerStatusDetails": {
                "fabricManagerState": "FABRIC_MANAGER_STATE_NOT_OK",
                "reason": "NMX-C has not reported for 10 minutes",
            },
            "nvosPorts": [
                {
                    "mac": "02:00:5e:41:00:03",
                    "isPrimary": True,
                    "addresses": [{"address": "198.51.100.42"}],
                }
            ],
        },
    },
]
EXPECTED_SWITCHES = [
    {
        "bmcMacAddress": s["bmcInfo"]["mac"],
        "bmcIpAddress": s["bmcInfo"]["ip"],
        "bmcUsername": "demo",
        "bmcPassword": "demo-placeholder",
        "nvosIpAddress": s["status"]["nvosPorts"][0]["addresses"][0]["address"],
        "switchSerialNumber": s["status"]["serialNumber"],
        "metadata": {"name": s["metadata"]["name"]},
        "rackId": s["rackId"],
        "nvosInterfaces": [
            {"macAddress": p["mac"], "isPrimary": p.get("isPrimary", False)}
            for p in s["status"]["nvosPorts"][:1]
        ],
    }
    for s in NVSWITCHES
]
SHELVES = [
    {
        "id": {"value": "demo-pshelf-0001"},
        "rackId": {"value": "DEMO-R02"},
        "placementInRack": {"slotNumber": 1},
        "metadata": {"name": "demo-pshelf-1"},
        "config": {"capacity": 33000, "voltage": 48},
        "bmcInfo": {
            "ip": "192.0.2.51",
            "mac": "02:00:5e:50:00:01",
            "firmwareVersion": "0.0.1-demo",
        },
        "status": {
            "lifecycle": {"state": "Ready"},
            "controllerState": "ready",
            "healthStatus": "ok",
            "health": {"source": "power-shelf-health", "observedAt": at(1430)},
            "powerState": "on",
            "serialNumber": "DEMO-PSHELF-001",
        },
    }
]
EXPECTED_SHELVES = [
    {
        "bmcMacAddress": s["bmcInfo"]["mac"],
        "bmcIpAddress": s["bmcInfo"]["ip"],
        "bmcUsername": "demo",
        "bmcPassword": "demo-placeholder",
        "shelfSerialNumber": s["status"]["serialNumber"],
        "metadata": {"name": s["metadata"]["name"]},
        "rackId": s["rackId"],
    }
    for s in SHELVES
]

# ------------------------------------------------------------- interfaces, power
INTERFACES = [
    {
        "id": {"value": f"00000000-0000-4000-8000-0000000b{m['id']['id'][10:14]}"},
        "macAddress": m["bmc"]["mac"],
        "address": [m["bmc"]["ip"]],
        "machineId": {"id": m["id"]["id"]},
        "isBmc": True,
    }
    for m in MACHINES
] + [
    {
        "id": {"value": f"00000000-0000-4000-8000-0000000a{m['id']['id'][10:14]}"},
        "macAddress": host_mac(int(m["id"]["id"][10:14]), 0).upper(),
        "address": [f"198.51.100.{100 + int(m['id']['id'][10:14])}"],
        "machineId": {"id": m["id"]["id"]},
        "primaryInterface": True,
    }
    for m in MACHINES
    if m["machineType"] == "HOST"
]
POWER = {
    "response": [
        {
            "hostId": {"id": m["id"]["id"]},
            "actualStateUpdatedAt": at(1320),
            **({"actualState": "Off"} if m["id"]["id"] == mid(2) else {}),
        }
        for m in MACHINES
        if m["machineType"] == "HOST"
    ]
}

# ------------------------------------------------------------ per machine records
STEPS = [
    ('{"state": "created"}', 0),
    ('{"state": "configureastra", "configure_astra_state": {"state": "enablenics"}}', 0.01),
    ('{"state": "dpudiscoveringstate", "dpu_states": {"states": {}}}', 0.3),
    (
        '{"state": "hostinit", "machine_state": {"state": "waitingforplatformconfiguration", '
        '"retry_count": 0}}',
        0.5,
    ),
    (
        '{"state": "hostinit", "machine_state": {"state": "uefisetup", "uefi_setup_info": '
        '{"uefi_setup_state": {"state": "powercyclehost"}}}}',
        420,
    ),
    (
        '{"state": "hostinit", "machine_state": {"state": "waitingforlockdown", "lockdown_info": '
        '{"mode": "enable", "state": "setlockdown"}}}',
        440,
    ),
    (
        '{"state": "bomvalidating", "bom_validating_state": {"MatchingSku": '
        '{"reboot_retry_count": null, "machine_validation_context": "Discovery"}}}',
        470,
    ),
    (
        '{"state": "validation", "validation_state": {"validation_type": "machinevalidation"}}',
        475,
    ),
    (
        '{"state": "hostinit", "machine_state": {"state": "discovered", "skip_reboot_wait": true}}',
        520,
    ),
    ('{"state": "ready"}', 525),
]
TAIL = {
    "Assigned/Ready": [('{"state": "assigned", "instance_state": {"state": "ready"}}', 900)],
    "Failed/NVMECleanFailed": [
        ('{"state": "assigned", "instance_state": {"state": "ready"}}', 900),
        ('{"state": "failed", "failure": {"state": "nvmecleanfailed"}}', 1180),
    ],
    "HostInit/WaitingForDiscovery": None,
    "HostInit/WaitingForLockdown": None,
}


def history(machine_id):
    row = next((m for m in MACHINES if m["id"]["id"] == machine_id), None)
    if row is None:
        return {}
    n = int(machine_id[10:14])
    state = row["state"]
    steps = STEPS
    if TAIL.get(state, []) is None:
        cut = 4 if state.endswith("Discovery") else 6
        steps = STEPS[:cut]
        if state.endswith("Discovery"):
            steps = steps[:3] + [
                ('{"state": "hostinit", "machine_state": {"state": "waitingfordiscovery"}}', 30)
            ]
    else:
        steps = steps + (TAIL.get(state) or [])
    if row["machineType"] == "DPU":
        steps = [
            STEPS[0],
            ('{"state": "dpuinit", "dpu_state": {"state": "init"}}', 0.2),
            ('{"state": "ready"}', 60),
        ]
    records = [
        {
            "event": event,
            "time": at(n * 7 + minutes, 328564 + i),
            "version": f"V{i + 2}-T179501{n:02d}{i:02d}000000",
        }
        for i, (event, minutes) in enumerate(steps)
    ]
    return {"histories": {machine_id: {"records": records}}}


def health_history(machine_id):
    row = next((m for m in MACHINES if m["id"]["id"] == machine_id), None)
    if row is None:
        return {}
    alerts = (row["status"].get("health") or {}).get("alerts") or []
    ok = lambda minutes: {  # noqa: E731
        "health": {"source": "aggregate-host-health", "observedAt": at(minutes)},
        "time": at(minutes, 3000),
    }
    records = [ok(60), ok(600)]
    if alerts:
        first = [dict(a, inAlertSince=at(700)) for a in alerts]
        records.append(
            {
                "health": {
                    "source": "aggregate-host-health",
                    "observedAt": at(700),
                    "alerts": first,
                },
                "time": at(700, 3000),
            }
        )
        records.append(ok(760))  # it cleared …
        records.append(
            {  # … and came back
                "health": {
                    "source": "aggregate-host-health",
                    "observedAt": at(1430),
                    "alerts": alerts,
                },
                "time": at(1430, 3000),
            }
        )
    else:
        records.append(ok(1430))
    return {"histories": {machine_id: {"records": records}}}


def validation_runs(machine_id):
    n = int(machine_id[10:14])
    runs = [
        {
            "validationId": {"value": f"00000000-0000-4000-8000-0000000c{n:04d}"},
            "machineId": {"id": machine_id},
            "startTime": at(n * 7 + 475),
            "endTime": at(n * 7 + 475, 998424),
            "name": "Test_" + machine_id[:40],
            "context": "Discovery",
            "status": {"completed": "Skipped"},
            "durationToComplete": "0s",
        }
    ]
    if machine_id in (mid(1), mid(3)):
        runs.append(
            {
                "validationId": {"value": f"00000000-0000-4000-8000-0000000d{n:04d}"},
                "machineId": {"id": machine_id},
                "startTime": at(1000),
                "endTime": at(1012),
                "name": "OnDemand_" + machine_id[:36],
                "context": "OnDemand",
                "status": {"completed": "Failed", "total": 2, "completedTests": 2},
                "durationToComplete": "720s",
            }
        )
    return {"runs": runs}


def validation_results(machine_id):
    n = int(machine_id[10:14])
    if machine_id not in (mid(1), mid(3)):
        return {}
    vid = {"value": f"00000000-0000-4000-8000-0000000d{n:04d}"}
    return {
        "results": [
            {
                "validationId": vid,
                "testId": "forge_CPUTestShort",
                "name": "CPUTestShort",
                "description": "Short CPU stress test",
                "context": "OnDemand",
                "command": "/opt/forge/cpu-test.sh",
                "args": "--short",
                "startTime": at(1000),
                "endTime": at(1005),
                "stdOut": "cpu test passed: 128 threads, 300 s",
            },
            {
                "validationId": vid,
                "testId": "forge_NvmeCheck",
                "name": "NvmeCheck",
                "description": "Check if all NVMe drives are writeable",
                "context": "OnDemand",
                "command": "/opt/forge/check-nvme-drives.sh",
                "exitCode": 1,
                "startTime": at(1005),
                "endTime": at(1012),
                "stdOut": "checking /dev/nvme0n1 … ok\nchecking /dev/nvme3n1 …",
                "stdErr": "/dev/nvme3n1: write failed: Input/output error",
            },
        ]
    }


FIRMWARE = [
    ("BMC-Primary", "Management controller firmware (primary).", "1.20", "2026-03-01T00:00:00Z"),
    ("BMC-Backup", "Management controller firmware (backup).", "1.18", "2026-01-10T00:00:00Z"),
    ("UEFI", "System firmware.", "2.04", "2026-02-15T00:00:00Z"),
    ("LXPM", "Provisioning manager firmware.", "2.04", "2026-02-01T00:00:00Z"),
    ("Ob_7.Bundle", "Onboard SSATA controller firmware.", "", None),
    ("Ob_6.Bundle", "Onboard SATA controller firmware.", "", None),
    ("Ob_1.Bundle", "Onboard LOM firmware.", "1.2890.0", None),
    ("Slot_2.Bundle", "Demo 2x100GbE adapter firmware.", "16.35.1012", "2025-11-29T00:00:00Z"),
    ("Slot_4.Bundle", "Demo RAID adapter firmware.", "3832", "2025-12-30T00:00:00Z"),
    ("Disk1", "Firmware of a disk behind a RAID or NVMe controller.", "DEM1", None),
    ("Disk2", "Firmware of a disk behind a RAID or NVMe controller.", "DEM1", None),
    ("Disk3", "Firmware of a disk behind a RAID or NVMe controller.", "DEM2", None),
    ("Disk4", "Firmware of a disk behind a RAID or NVMe controller.", "", None),
    ("PSU1", "Power supply firmware.", "2.61", None),
    ("PSU2", "Power supply firmware.", "2.61", None),
]


def bmc_report(n, machine_id=None):
    report = {
        "endpointType": "Bmc",
        "lastExplorationLatency": f"{12 + n}.918380638s",
        "vendor": "demovendor",
        "systems": [
            {
                "id": "1",
                "manufacturer": "DemoVendor",
                "model": "Demo Server X1",
                "serialNumber": serial(n),
                "ethernetInterfaces": [
                    {"id": "NIC1", "macAddress": host_mac(n, 0).upper(), "linkStatus": "LinkUp"}
                ],
            }
        ],
        "chassis": [
            {
                "id": "1",
                "model": "DEMO-X1-CTO",
                "partNumber": "DEMO-PN-0001",
                "serialNumber": serial(n),
                "manufacturer": "DemoVendor",
            }
        ],
        "service": [
            {
                "id": "FirmwareInventory",
                "inventories": [
                    {"id": i, "description": d, "version": v, **({"releaseDate": r} if r else {})}
                    for i, d, v, r in FIRMWARE
                ],
            }
        ],
        "machineSetupStatus": {"isDone": True},
        "secureBootStatus": {},
        "lockdownStatus": {
            "message": "kcs=false, firmware_rollback=Disabled, ethernet_over_usb=Disabled"
        },
    }
    if machine_id:
        report["machineId"] = machine_id
    return report


def inventory(machine_id):
    if machine_id not in MACHINE_IDS or machine_id.startswith("fm100d"):
        return {}
    return {
        "entries": [
            {"result": {"componentId": machine_id}, "report": bmc_report(int(machine_id[10:14]))}
        ]
    }


def refused(address):
    return {
        "address": address,
        "report": {
            "endpointType": "Unknown",
            "lastExplorationError": json.dumps(
                {
                    "Type": "ConnectionRefused",
                    "Details": f"url: https://{address}/redfish/v1/Systems: connection refused",
                }
            ),
            "lastExplorationLatency": "10.003920396s",
            "lastExplorationErrorSchema": {
                "errorCode": "NICO-SITEEXPLORER-101",
                "mitigation": "Verify endpoint network reachability and that the BMC Redfish "
                "service is enabled.",
                "text": f'the connection to the endpoint was refused: "url: https://{address}"',
            },
        },
        "reportVersion": "V587-T1795081318788528",
        "preingestionState": "Initial",
        "lastRedfishBmcReset": "no timestamp available",
        "lastIpmitoolBmcReset": "no timestamp available",
        "lastRedfishReboot": "no timestamp available",
        "lastRedfishPowercycle": "no timestamp available",
    }


EXPLORED = [1, 2, 3, 5, 6, 8]
EXPLORATION = {
    "endpoints": [
        {
            "address": bmc_ip(n),
            "report": bmc_report(n),
            "reportVersion": f"V{40 + n}-T1795081318788528",
            "preingestionState": "Complete",
            "lastRedfishBmcReset": "no timestamp available",
            "lastIpmitoolBmcReset": "no timestamp available",
            "lastRedfishReboot": at(400 + n * 30),
            "lastRedfishPowercycle": "no timestamp available",
        }
        for n in EXPLORED
    ]
    + [refused(bmc_ip(4)), refused(bmc_ip(7)), refused("192.0.2.60")],
    "managedHosts": [{"hostBmcIp": bmc_ip(n)} for n in EXPLORED],
    "lastRun": {
        "startedAt": "2026-11-19T01:41:39.837154+00:00",
        "finishedAt": "2026-11-19T01:41:58.823616+00:00",
        "success": True,
        "endpointExplorations": "9",
        "endpointExplorationsSuccess": "6",
        "endpointExplorationsFailed": "3",
        "lastSuccessfulFinishedAt": "2026-11-19T01:41:58.823616+00:00",
        "lastFailedFinishedAt": "2026-11-18T12:50:28.293055+00:00",
    },
}

# Answers that do not depend on the request.
RPC = {
    "FindMachineIds": {"machineIds": [{"id": i} for i in MACHINE_IDS]},
    "FindMachinesByIds": {"machines": MACHINES},
    "FindSwitches": {"switches": NVSWITCHES},
    "FindPowerShelves": {"powerShelves": SHELVES},
    "GetAllExpectedSwitches": {"expectedSwitches": EXPECTED_SWITCHES},
    "GetAllExpectedPowerShelves": {"expectedPowerShelves": EXPECTED_SHELVES},
    "FindInterfaces": {"interfaces": INTERFACES},
    "GetPowerOptions": POWER,
    "GetSiteExplorationReport": EXPLORATION,
}
# Answers per machine, from the machine ID in the request.
PER_MACHINE = {
    "FindMachineStateHistories": history,
    "FindMachineHealthHistories": health_history,
    "GetMachineValidationRuns": validation_runs,
    "GetMachineValidationResults": validation_results,
    "GetComponentInventory": inventory,
}
CLI = {("expected-machine", "show"): EXPECTED_MACHINES}

# ------------------------------------------------------------- PXEye-local data
SWITCHES_CSV = (
    "chassis_mac,name,model,serial,management_ip,rack\n"
    f"{LEAF_B['mac']},demo-leaf-b,DemoNet DS-4800,DEMO-SW-LEAF-B,198.51.100.2,DEMO-R01\n"
    f"{LEAF_C},demo-leaf-c,DemoNet DS-4800,DEMO-SW-LEAF-C,198.51.100.3,DEMO-R02\n"
)
PORTS_CSV = "chassis_mac,port_id,port_name\n" + "".join(
    f"{LEAF_B['mac']},{leaf_b_port(p)},GE1/0/{p}\n" for p in range(1, 14)
)
RACK_UNITS_CSV = (
    "serial,rack,unit,height\n"
    "DEMO-SRV-001,DEMO-R01,38,2\n"
    "DEMO-SRV-002,DEMO-R01,36,2\n"
    "DEMO-SRV-003,DEMO-R01,34,2\n"
    "DEMO-SRV-004,DEMO-R01,32,2\n"
    "DEMO-SRV-005,DEMO-R02,30,2\n"
    "DEMO-SRV-006,DEMO-R01,20,2\n"
)


def machine_in(body):
    """The machine ID of a per-machine request, in any of the request shapes."""
    text = json.dumps(body)
    return next((i for i in MACHINE_IDS if i in text), None) or (
        (body.get("machineIds") or [{}])[0].get("id")
        if isinstance(body.get("machineIds"), list)
        else None
    )


def stand_in_core():
    asked = set()

    def rpc(self, method, body):
        if method in PER_MACHINE:
            ident = machine_in(body or {})
            return copy.deepcopy(PER_MACHINE[method](ident) if ident else {})
        if method not in RPC:
            asked.add(method)
        return copy.deepcopy(RPC.get(method, {}))

    def cli(self, args, *, data=False):
        answer = CLI.get(tuple(args[:2]))
        if answer is None:
            asked.add("cli " + " ".join(args))
            return {} if data else ""
        return copy.deepcopy(answer)

    return rpc, cli, asked


def seed_local(data):
    from pxeye.persistence.store import get_store
    from pxeye.services import rack_units, switch_labels

    store = get_store(data / "console.sqlite3")
    switches, ports = switch_labels.parse({"switches_csv": SWITCHES_CSV, "ports_csv": PORTS_CSV})
    store.save_switch_labels(switches, ports, "")
    store.save_rack_units(rack_units.parse(RACK_UNITS_CSV), "")


def load(name):
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"), Path(__file__).with_name(f"{name}.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def capture():
    """Run tools/core-capture.py against the stand-in Core; returns the document."""
    from pxeye.clients.core import CoreClient
    from pxeye.deployment import kubernetes

    patched = [
        (CoreClient, "rpc"),
        (CoreClient, "core"),
        (CoreClient, "check_core_certificate"),
        (kubernetes.CurrentCluster, "request"),
    ]
    saved = [(owner, name, owner.__dict__[name]) for owner, name in patched]
    env = {k: os.environ.get(k) for k in ("CONSOLE_CONFIG", "CONSOLE_DATA", "CONSOLE_SECRETS")}
    work = Path(tempfile.mkdtemp(prefix="pxeye-demo-"))
    rpc, cli, asked = stand_in_core()
    try:
        CoreClient.rpc, CoreClient.core = rpc, cli
        CoreClient.check_core_certificate = lambda self: None

        def no_cluster(self, *args, **kwargs):
            raise kubernetes.ClusterError("demo: no Kubernetes")

        kubernetes.CurrentCluster.request = no_cluster
        data, secrets = work / "data", work / "secrets"
        (data / "config").mkdir(parents=True)
        secrets.mkdir()
        (secrets / "bootstrap-password").write_text("demo\n")
        (secrets / "auth.json").write_text(
            json.dumps({"password_sha256": hashlib.sha256(b"demo").hexdigest()})
        )
        for name in ("ca.crt", "client.crt", "client.key"):
            (secrets / name).write_text("demo")
        site = {
            "site": {"name": SITE, "namespace": "", "deployment": ""},
            "core_url": CORE_URL,
            "nico_deployment": {"enabled": False, "namespace": "demo"},
        }
        (work / "site.json").write_text(json.dumps(site, ensure_ascii=False))
        seed_local(data)
        os.environ.update(
            CONSOLE_CONFIG=str(work / "site.json"),
            CONSOLE_DATA=str(data),
            CONSOLE_SECRETS=str(secrets),
        )
        output, report = io.StringIO(), io.StringIO()
        code = 0
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(report):
            try:
                load("core-capture").main()
            except SystemExit as stop:
                code = stop.code
        document = json.loads(output.getvalue())
        document["demo"] = True
        return document, code, report.getvalue(), sorted(asked)
    finally:
        for owner, name, value in saved:
            setattr(owner, name, value)
        for k, v in env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(work, ignore_errors=True)


def main():
    document, code, report, asked = capture()
    # Keep the capture's own report; leave out the console's request log.
    sys.stderr.write("".join(line for line in report.splitlines(True) if not line.startswith("{")))
    if asked:
        print("answered empty: " + ", ".join(asked), file=sys.stderr)
    sys.stdout.write(json.dumps(document, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    sys.exit(code)


if __name__ == "__main__":
    main()
