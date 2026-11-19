"""Rack unit (U) positions of servers, kept by PXEye.

NICo Core has no position for a general server, so the operator records one per
serial number. The rack column of the import is only compared with the rack the
device already has in device management; the rack itself is never written here,
and nothing is written to Core.
"""

import csv
import io

HEADERS = (("serial", "rack", "unit"), ("serial", "rack", "unit", "height"))
MAX_ROWS = 2000
MAX_UNIT = 60


class RackUnitsInvalid(Exception):
    def __init__(self, errors):
        super().__init__("U 位数据有误，未保存。")
        self.errors = errors


def _number(text, line, field, errors):
    text = (text or "").strip()
    if not text.isdigit() or not 1 <= int(text) <= MAX_UNIT:
        errors.append(
            {"line": line, "field": field, "message": f"应为 1 到 {MAX_UNIT} 之间的整数。"}
        )
        return None
    return int(text)


def parse(text):
    """Return positions from `serial,rack,unit[,height]` CSV, or raise with every error."""
    if not isinstance(text, str):
        raise RackUnitsInvalid([{"line": 0, "field": "csv", "message": "缺少 CSV 文本。"}])
    rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))
    numbered = [(n, row) for n, row in enumerate(rows, 1) if any(cell.strip() for cell in row)]
    if not numbered:
        return []
    line, header = numbered[0]
    header = tuple(cell.strip().lower() for cell in header)
    if header not in HEADERS:
        raise RackUnitsInvalid(
            [
                {
                    "line": line,
                    "field": "header",
                    "message": "表头应为 serial,rack,unit 或 serial,rack,unit,height。",
                }
            ]
        )
    body = numbered[1:]
    if len(body) > MAX_ROWS:
        raise RackUnitsInvalid(
            [{"line": 0, "field": "csv", "message": f"最多 {MAX_ROWS} 行，当前 {len(body)} 行。"}]
        )
    errors, positions, seen, lines = [], [], {}, {}
    for line, row in body:
        if len(row) != len(header):
            errors.append(
                {
                    "line": line,
                    "field": "csv",
                    "message": f"应有 {len(header)} 列，当前 {len(row)} 列。",
                }
            )
            continue
        serial, rack = row[0].strip(), row[1].strip()
        if not serial:
            errors.append({"line": line, "field": "serial", "message": "序列号不能为空。"})
        elif serial in seen:
            errors.append(
                {"line": line, "field": "serial", "message": f"与第 {seen[serial]} 行序列号重复。"}
            )
        else:
            seen[serial] = line
        unit = _number(row[2], line, "unit", errors)
        height = _number(row[3], line, "height", errors) if len(row) == 4 else 1
        if unit is not None and height is not None and unit + height - 1 > MAX_UNIT:
            errors.append(
                {"line": line, "field": "height", "message": f"占用范围超过 U{MAX_UNIT}。"}
            )
        elif serial and unit is not None and height is not None:
            lines[len(positions)] = line
            positions.append({"serial": serial, "rack": rack, "unit": unit, "height": height})
    for i, a in enumerate(positions):
        for j, b in enumerate(positions[:i]):
            if (
                a["rack"]
                and a["rack"] == b["rack"]
                and a["unit"] <= b["unit"] + b["height"] - 1
                and b["unit"] <= a["unit"] + a["height"] - 1
            ):
                errors.append(
                    {
                        "line": lines[i],
                        "field": "unit",
                        "message": f"与 {b['serial']}（第 {lines[j]} 行）在同一机柜中位置重叠。",
                    }
                )
                break
    if errors:
        raise RackUnitsInvalid(sorted(errors, key=lambda e: e["line"]))
    return positions


def to_csv(positions):
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(HEADERS[1])
    for p in positions:
        writer.writerow([p["serial"], p["rack"], p["unit"], p["height"]])
    return out.getvalue()


def view(saved, devices):
    """Saved positions, compared with the devices device management lists."""
    racks = {d.get("serial"): d.get("rack_id") or "" for d in devices if d.get("serial")}
    positions = saved.get("positions", [])
    return {
        "positions": positions,
        "csv": to_csv(positions),
        "revision": saved.get("revision", ""),
        "updated": saved.get("updated"),
        "mismatches": [
            {"serial": p["serial"], "recorded_rack": p["rack"], "device_rack": racks[p["serial"]]}
            for p in positions
            if p["serial"] in racks and p["rack"] != racks[p["serial"]]
        ],
        "unknown": [p["serial"] for p in positions if p["serial"] not in racks],
    }


def devices(app):
    """The device list device management shows, read through its own services."""
    snapshot = app.management_addresses.snapshot()
    return [d for d in app.equipment.view(snapshot)["devices"] if not d.get("address_only")]


def save(app, body):
    """Validate and store an import; returns (status, payload)."""
    if not isinstance(body, dict) or set(body) != {"csv", "revision"}:
        return 400, {
            "error": "请求字段无效，请刷新后核对。",
            "code": "INVALID_FIELDS",
            "errors": [],
        }
    try:
        positions = parse(body["csv"])
    except RackUnitsInvalid as error:
        return 400, {"error": str(error), "code": "RACK_UNITS_INVALID", "errors": error.errors}
    saved = app.store.save_rack_units(positions, str(body["revision"] or ""))
    if saved is None:
        return 409, {
            "error": "U 位已被他人修改，请关闭后重新打开再导入。",
            "code": "RACK_UNITS_CONFLICT",
            "errors": [],
        }
    return 200, view(saved, devices(app))
