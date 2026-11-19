"""What NICo site exploration found at each BMC address it probed.

Core's GetSiteExplorationReport carries, for every explored address, either the error of
the last attempt or a full Redfish inventory. Diagnosing why a device was not discovered
needs only the summary: the address, what answered, the error and its mitigation. The
inventory itself stays in Core; the firmware dialog of a server reads it per machine.
This module only reads and keeps no state.
"""

import json
import time


def duration_seconds(value):
    """Core renders a protobuf Duration as text such as ``"10.003920396s"``."""
    if not isinstance(value, str) or not value.endswith("s"):
        return None
    try:
        return float(value[:-1])
    except ValueError:
        return None


def error_type(value):
    """The error is a JSON document with a ``Type``; anything else is kept as given."""
    if not isinstance(value, str) or not value.strip():
        return ""
    try:
        parsed = json.loads(value)
    except ValueError:
        return value.strip()
    if isinstance(parsed, dict) and isinstance(parsed.get("Type"), str):
        return parsed["Type"]
    return value.strip()


def first_system(report):
    return next(
        (
            s
            for s in report.get("systems") or []
            if isinstance(s, dict) and (s.get("serialNumber") or s.get("model"))
        ),
        {},
    )


def endpoint(row, managed):
    report = row.get("report") if isinstance(row.get("report"), dict) else {}
    schema = report.get("lastExplorationErrorSchema")
    schema = schema if isinstance(schema, dict) else {}
    raw_error = report.get("lastExplorationError")
    failed = bool(schema or (isinstance(raw_error, str) and raw_error.strip()))
    system = {} if failed else first_system(report)
    address = row.get("address") or ""
    return {
        "address": address,
        "endpoint_type": report.get("endpointType") or "",
        "vendor": report.get("vendor") or "",
        "machine_id": report.get("machineId") or "",
        "preingestion_state": row.get("preingestionState") or "",
        "report_version": row.get("reportVersion") or "",
        "latency": report.get("lastExplorationLatency") or "",
        "latency_seconds": duration_seconds(report.get("lastExplorationLatency")),
        "failed": failed,
        "error": {
            "code": schema.get("errorCode") or "",
            "text": schema.get("text") or "",
            "mitigation": schema.get("mitigation") or "",
            "type": error_type(raw_error),
        }
        if failed
        else None,
        "managed_host": bool(address) and address in managed,
        "serial": system.get("serialNumber") or "",
        "model": system.get("model") or "",
        "last_redfish_bmc_reset": row.get("lastRedfishBmcReset") or "",
        "last_ipmitool_bmc_reset": row.get("lastIpmitoolBmcReset") or "",
        "last_redfish_reboot": row.get("lastRedfishReboot") or "",
        "last_redfish_powercycle": row.get("lastRedfishPowercycle") or "",
    }


def last_run(value):
    """The last site explorer run as Core gives it; counts arrive as int64 strings."""
    if not isinstance(value, dict) or not value:
        return None

    def count(key):
        try:
            return int(value.get(key) or 0)
        except (TypeError, ValueError):
            return None

    return {
        "started_at": value.get("startedAt") or "",
        "finished_at": value.get("finishedAt") or "",
        # Proto JSON omits false.
        "success": value.get("success") is True,
        "error": value.get("error") or "",
        "failure_category": value.get("failureCategory") or "",
        "explorations": count("endpointExplorations"),
        "succeeded": count("endpointExplorationsSuccess"),
        "failed": count("endpointExplorationsFailed"),
        "last_successful_finished_at": value.get("lastSuccessfulFinishedAt") or "",
        "last_failed_finished_at": value.get("lastFailedFinishedAt") or "",
    }


def exploration(adapter):
    """Summarise the site exploration report. Reads only."""
    response = adapter.rpc("GetSiteExplorationReport", {}) or {}
    managed = {
        host.get("hostBmcIp")
        for host in response.get("managedHosts") or []
        if isinstance(host, dict) and host.get("hostBmcIp")
    }
    endpoints = [
        endpoint(row, managed) for row in response.get("endpoints") or [] if isinstance(row, dict)
    ]
    # Failed first, then by address, so the page leads with what needs attention.
    endpoints.sort(key=lambda e: (not e["failed"], e["address"]))
    return {
        "observed_at": time.time(),
        "endpoints": endpoints,
        "last_run": last_run(response.get("lastRun")),
    }
