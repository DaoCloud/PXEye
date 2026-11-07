"""Validate rack presentation order without changing infrastructure resources."""


def normalize_topology_layout(app, body):
    racks = body.get("racks")
    if not isinstance(racks, list) or len(racks) > 200:
        raise ValueError("机柜布局格式无效。")
    snapshot = app.management_addresses.snapshot()
    devices = app.equipment.view(snapshot).get("devices", [])
    current = {str(row.get("id")): row for row in devices if row.get("id")}
    kind_zone = {"switch": "network", "server": "compute", "power_shelf": "power"}
    zones_allowed = ("network", "compute", "other", "power")
    result, seen, rack_ids = [], set(), set()
    for rack in racks:
        if not isinstance(rack, dict) or not isinstance(rack.get("rack_id"), str):
            raise ValueError("机柜布局格式无效。")
        rack_id = rack["rack_id"].strip()
        if not rack_id or len(rack_id) > 256 or rack_id in rack_ids:
            raise ValueError("机柜标识无效或重复。")
        rack_ids.add(rack_id)
        zones = rack.get("zones")
        if not isinstance(zones, dict) or any(key not in zones_allowed for key in zones):
            raise ValueError("设备分区无效。")
        normalized = {}
        for zone in zones_allowed:
            ids = zones.get(zone, [])
            if not isinstance(ids, list) or len(ids) > 500:
                raise ValueError("设备顺序格式无效。")
            normalized[zone] = []
            for value in ids:
                if not isinstance(value, str) or not value or len(value) > 512 or value in seen:
                    raise ValueError("设备标识无效或重复。")
                device = current.get(value)
                expected_rack = str(device.get("rack_id") or "unassigned") if device else None
                expected_zone = kind_zone.get(device.get("kind"), "other") if device else None
                if not device or expected_rack != rack_id or expected_zone != zone:
                    raise ValueError("设备或 Rack 已变化，请刷新拓扑后重新编辑。")
                seen.add(value)
                normalized[zone].append(value)
        result.append({"rack_id": rack_id, "zones": normalized})
    return {"racks": result}
