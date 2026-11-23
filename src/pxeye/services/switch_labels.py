"""Switch names and panel port names provided by the site, stored locally.

LLDP often carries no switch name and identifies ports by MAC, so the cabling
page cannot say which physical switch or panel port a server is plugged into.
The site supplies two CSV tables (docs/archive/rack-operations-v1/field-survey/cabling.md section 4);
PXEye keeps them in its own database and only uses them for display. Nothing
here is written to NICo Core or to a switch.
"""

import csv
import io
import re

SWITCH_COLUMNS = ["chassis_mac", "name", "model", "serial", "management_ip", "rack"]
PORT_COLUMNS = ["chassis_mac", "port_id", "port_name"]
SWITCH_REQUIRED = ("chassis_mac", "name")
PORT_REQUIRED = ("chassis_mac", "port_id", "port_name")
MAX_ROWS = 2000
_MAC_HEX = re.compile(r"^[0-9a-f]{12}$")


class SwitchLabelsError(ValueError):
    def __init__(self, errors):
        super().__init__("交换机信息有误，未保存。")
        self.errors = errors


class SwitchLabelsConflict(ValueError):
    pass


def normalize_mac(value):
    """Return the lower-case colon form, or None when the value is not a MAC."""
    raw = re.sub(r"[:\-.]", "", str(value or "").strip().lower())
    if not _MAC_HEX.match(raw):
        return None
    return ":".join(raw[i : i + 2] for i in range(0, 12, 2))


def parse_table(text, columns, required, keys, table):
    """Parse one CSV table; returns (rows, errors). Empty text means an empty table."""
    errors = []
    if not isinstance(text, str):
        return [], [{"table": table, "line": 0, "field": "", "message": "请提交 CSV 文本。"}]
    if not text.strip():
        return [], []
    lines = list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))
    header = [c.strip() for c in lines[0]] if lines else []
    if header != columns:
        message = "表头必须为：" + ",".join(columns)
        return [], [{"table": table, "line": 1, "field": "", "message": message}]
    rows, seen = [], {}
    data = [(n, row) for n, row in enumerate(lines[1:], start=2) if any(c.strip() for c in row)]
    if len(data) > MAX_ROWS:
        message = f"行数超过上限 {MAX_ROWS}。"
        return [], [{"table": table, "line": 0, "field": "", "message": message}]
    for line, row in data:
        if len(row) != len(columns):
            errors.append(
                {
                    "table": table,
                    "line": line,
                    "field": "",
                    "message": f"应有 {len(columns)} 列，实际 {len(row)} 列。",
                }
            )
            continue
        item = {c: v.strip() for c, v in zip(columns, row)}
        bad = False
        for field in required:
            if not item[field]:
                errors.append({"table": table, "line": line, "field": field, "message": "必填。"})
                bad = True
        if item["chassis_mac"]:
            mac = normalize_mac(item["chassis_mac"])
            if mac is None:
                errors.append(
                    {
                        "table": table,
                        "line": line,
                        "field": "chassis_mac",
                        "message": "不是有效的 MAC 地址。",
                    }
                )
                bad = True
            else:
                item["chassis_mac"] = mac
        if bad:
            continue
        if "port_id" in item:
            # Same key form as the cabling page: MAC colon form, else case-insensitive.
            item["port_id"] = normalize_mac(item["port_id"]) or item["port_id"]
        key = tuple(item[k].lower() for k in keys)
        if key in seen:
            errors.append(
                {
                    "table": table,
                    "line": line,
                    "field": keys[-1],
                    "message": f"与第 {seen[key]} 行重复。",
                }
            )
            continue
        seen[key] = line
        rows.append(item)
    return rows, errors


def parse(body):
    """Validate a save request; raises SwitchLabelsError listing every problem."""
    if not isinstance(body, dict) or set(body) - {"switches_csv", "ports_csv", "revision"}:
        raise ValueError("无效请求。")
    switches, switch_errors = parse_table(
        body.get("switches_csv", ""), SWITCH_COLUMNS, SWITCH_REQUIRED, ("chassis_mac",), "switches"
    )
    ports, port_errors = parse_table(
        body.get("ports_csv", ""),
        PORT_COLUMNS,
        PORT_REQUIRED,
        ("chassis_mac", "port_id"),
        "ports",
    )
    if switch_errors or port_errors:
        raise SwitchLabelsError(switch_errors + port_errors)
    return switches, ports


def save(store, body):
    switches, ports = parse(body)
    revision = body.get("revision") or ""
    if not isinstance(revision, str):
        raise ValueError("无效请求。")
    saved = store.save_switch_labels(switches, ports, revision)
    if saved is None:
        raise SwitchLabelsConflict("交换机信息已被他人更新，请重新打开后再保存。")
    return saved
