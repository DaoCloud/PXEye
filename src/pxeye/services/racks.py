"""机柜: the rack objects NICo Core keeps for declared whole racks. Reads only.

The list is the one the rack-actions feature builds; this module serves it behind
``rack_operations`` alone and adds the per-rack state and health histories.
"""

import re
import time

from pxeye.services.device_status import record_time, state_timeline

RACK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")


def enabled(config):
    return config.get("rack_operations") is True


def view(adapter):
    from pxeye.services.rack_actions import racks

    return racks(adapter)


def _records(response, rack_id):
    histories = (response or {}).get("histories") or {}
    entry = histories.get(rack_id) if isinstance(histories, dict) else None
    return [r for r in (entry or {}).get("records") or [] if isinstance(r, dict)]


def history(adapter, rack_id):
    """State timeline and health observations of one rack; each read may fail alone."""
    if not isinstance(rack_id, str) or not RACK_ID.fullmatch(rack_id):
        raise ValueError("机柜 ID 格式不正确。")
    now = time.time()
    result = {"observed_at": now, "states": [], "health": [], "errors": []}
    try:
        response = adapter.rpc("FindRackStateHistories", {"rackIds": [{"id": rack_id}]})
        result["states"] = state_timeline(_records(response, rack_id), now)
    except Exception:  # noqa: BLE001 - say which read is missing
        result["errors"].append("NICo 未返回机柜状态历史。")
    try:
        response = adapter.rpc("FindRackHealthHistories", {"rackIds": [{"id": rack_id}]})
        observed = []
        for record in _records(response, rack_id):
            moment = record_time(record.get("time"))
            if moment is None:
                continue
            report = record.get("health") if isinstance(record.get("health"), dict) else {}
            alerts = [
                {
                    "id": str(a.get("id") or ""),
                    "target": str(a.get("target") or ""),
                    "message": str(a.get("message") or ""),
                }
                for a in report.get("alerts") or []
                if isinstance(a, dict)
            ]
            observed.append((moment, {"time": record.get("time"), "alerts": alerts}))
        observed.sort(key=lambda item: item[0], reverse=True)
        result["health"] = [item for _, item in observed[:50]]
    except Exception:  # noqa: BLE001
        result["errors"].append("NICo 未返回机柜健康历史。")
    return result
