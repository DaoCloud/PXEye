#!/usr/bin/env python3
"""Convert a host CSV to the Core admin CLI's expected_machines JSON file.

Each CSV row becomes one Core ExpectedMachineJson object (NICo e703126e4).
Official optional fields are copied only when supplied; arrays/objects use JSON cells.
No API requests, network configuration or machine operations are performed.
"""

import argparse
import csv
import json
import os
from pathlib import Path
import re


REQUIRED_FIELDS = ("bmc_mac_address", "bmc_username", "bmc_password", "chassis_serial_number")
STRING_FIELDS = {"sku_id", "rack_id", "bmc_ip_address", "server_name"}
BOOL_FIELDS = {"default_pause_ingestion_and_poweron", "dpf_enabled", "bmc_retain_credentials"}
JSON_FIELDS = {
    "fallback_dpu_serial_numbers": list,
    "metadata": dict,
    "interfaces": list,
    "host_nics": list,  # Official compatibility alias of interfaces.
    "host_lifecycle_profile": dict,
}
POLICY_FIELDS = {"dpu_policy", "dpu_mode"}  # dpu_mode is the official legacy key.
OPTIONAL_FIELDS = (
    STRING_FIELDS | BOOL_FIELDS | set(JSON_FIELDS) | POLICY_FIELDS | {"id", "bmc_ip_allocation"}
)
POLICIES = {
    "unspecified",
    "Unspecified",
    "DpuModeUnspecified",
    "dpu_mode_unspecified",
    "DPU_MODE_UNSPECIFIED",
    "manage",
    "DpuMode",
    "dpu_mode",
    "DPU_MODE",
    "nic",
    "UseAsNic",
    "use_as_nic",
    "USE_AS_NIC",
    "NicMode",
    "nic_mode",
    "NIC_MODE",
    "ignore",
    "NoDpu",
    "no_dpu",
    "NO_DPU",
}


def json_cell(raw, field, line):
    def reject_constant(value):
        raise ValueError("non-JSON constant")

    def unique_keys(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate key")
            value[key] = item
        return value

    try:
        return json.loads(raw, parse_constant=reject_constant, object_pairs_hook=unique_keys)
    except ValueError:
        # Never include cell content or JSON decoder context in errors.
        raise ValueError(f"CSV line {line}: invalid JSON in {field}") from None


def optional_value(field, raw, line):
    text = raw.strip()
    if text == "null":
        return None
    if field in STRING_FIELDS:
        # An explicit JSON string allows empty strings or a literal "null".
        value = json_cell(text, field, line) if text.startswith('"') else raw
        valid = isinstance(value, str)
    elif field in BOOL_FIELDS:
        value = json_cell(text, field, line)
        valid = type(value) is bool
    elif field in JSON_FIELDS:
        value = json_cell(text, field, line)
        valid = isinstance(value, JSON_FIELDS[field])
        if field == "fallback_dpu_serial_numbers" and valid:
            valid = all(isinstance(item, str) for item in value)
        if field in {"interfaces", "host_nics"} and valid:
            valid = all(isinstance(item, dict) for item in value)
    elif field == "id":
        value = json_cell(text, field, line) if text.startswith(("{", '"')) else text
        valid = isinstance(value, str) or (
            isinstance(value, dict) and set(value) == {"value"} and isinstance(value["value"], str)
        )
    elif field in POLICY_FIELDS:
        value = int(text) if text in {"0", "1", "2", "3"} else text
        valid = type(value) is int or value in POLICIES
    else:  # Core's BmcIpAllocationType JSON enum.
        value = text
        valid = value in {"Unspecified", "Auto", "Dynamic", "Fixed", "Retained"}
    if not valid:
        raise ValueError(f"CSV line {line}: invalid type or value for {field}")
    return value


def convert(source):
    reader = csv.DictReader(source, strict=True)
    headers = reader.fieldnames or []
    if (
        len(headers) != len(set(headers))
        or not set(REQUIRED_FIELDS) <= set(headers)
        or set(headers) - set(REQUIRED_FIELDS) - OPTIONAL_FIELDS
    ):
        raise ValueError(
            "CSV must contain the four required BMC/serial fields and only "
            "official Core ExpectedMachineJson field names"
        )
    if "interfaces" in headers and "host_nics" in headers:
        raise ValueError("use either interfaces or its legacy alias host_nics, not both")

    machines = []
    seen_macs, seen_serials = set(), set()
    for row in reader:
        line = reader.line_num
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f"CSV line {line}: wrong number of columns")
        machine = {key: row[key] for key in REQUIRED_FIELDS}
        # Credentials must survive CSV quoting without stripping or interpolation.
        machine["bmc_mac_address"] = machine["bmc_mac_address"].strip().replace("-", ":").upper()
        machine["chassis_serial_number"] = machine["chassis_serial_number"].strip()
        # Pinned Core e703126e4 serial validator and PostgreSQL varchar lengths.
        if not re.fullmatch(r"[A-Za-z0-9_-]{4,32}", machine["chassis_serial_number"]):
            raise ValueError(
                f"CSV line {line}: chassis_serial_number requires 4-32 ASCII letters/digits/-/_"
            )
        for field, maximum in (("bmc_username", 16), ("bmc_password", 20)):
            if len(machine[field]) > maximum:
                raise ValueError(
                    f"CSV line {line}: {field} exceeds Core limit of {maximum} characters"
                )
        if any(not value for value in machine.values()):
            raise ValueError(f"CSV line {line}: required field is empty")
        if not re.fullmatch(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}", machine["bmc_mac_address"]):
            raise ValueError(f"CSV line {line}: invalid BMC MAC address")
        for field in headers:
            if field in OPTIONAL_FIELDS and row[field].strip():
                machine[field] = optional_value(field, row[field], line)
        if machine["bmc_mac_address"] in seen_macs:
            raise ValueError(f"CSV line {line}: duplicate BMC MAC address")
        if machine["chassis_serial_number"] in seen_serials:
            raise ValueError(f"CSV line {line}: duplicate chassis serial number")
        seen_macs.add(machine["bmc_mac_address"])
        seen_serials.add(machine["chassis_serial_number"])
        machines.append(machine)
    if not machines:
        raise ValueError("CSV contains no machines")
    return {"expected_machines": machines}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="UTF-8 CSV; a BOM is accepted")
    parser.add_argument("--output", type=Path, help="new JSON file, created with mode 0600")
    parser.add_argument("--check-only", action="store_true", help="validate without writing a file")
    args = parser.parse_args()
    if args.output is None and not args.check_only:
        parser.error("--output is required unless --check-only is used")

    try:
        with args.input.open(encoding="utf-8-sig", newline="") as source:
            manifest = convert(source)
    except ValueError as error:
        # Decode errors can contain input bytes, including secrets.
        if isinstance(error, UnicodeError):
            parser.exit(1, "CSV error: input must be UTF-8\n")
        parser.exit(1, f"CSV error: {error}\n")
    except csv.Error:
        parser.exit(1, "CSV error: invalid CSV quoting or record\n")
    except OSError:
        parser.exit(1, "CSV error: cannot read input file\n")

    if not args.check_only:
        try:
            fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                json.dump(manifest, output, ensure_ascii=False, indent=2)
                output.write("\n")
        except FileExistsError:
            parser.exit(1, "Output error: file already exists; choose a new output file\n")
        except OSError:
            parser.exit(1, "Output error: cannot write JSON file\n")
    count = len(manifest["expected_machines"])
    print(
        f"Validated {count} machines; "
        + ("no file written." if args.check_only else "JSON written (0600).")
    )


if __name__ == "__main__":
    main()
