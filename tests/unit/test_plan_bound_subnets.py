"""A bound subnet is the only source of a planned host port's mask and gateway."""

import unittest

from pxeye.services.device_plans import DevicePlans

HOST, BMC = "02:00:00:00:01:01", "02:00:00:00:00:01"
INBAND = {
    "id": "inband",
    "segment_type": "HOST_INBAND",
    "prefixes": [{"prefix": "192.0.2.0/24", "gateway": "192.0.2.1"}],
}


class Networks:
    def __init__(self, networks=None, error=None):
        self.rows, self.error, self.calls = networks or [], error, 0

    def networks(self):
        self.calls += 1
        if self.error:
            raise self.error
        return self.rows


def plans(resources):
    service = DevicePlans.__new__(DevicePlans)
    service.resources = resources
    return service


def record(bindings=None, **host):
    nic = {
        "mac_address": HOST,
        "role": "host",
        "primary": True,
        "ip_allocation": "fixed",
        "fixed_ip": "192.0.2.10",
        "fixed_mask": "255.255.255.0",
        "fixed_gateway": "192.0.2.1",
    } | host
    return {
        "machine": {
            "interfaces": [
                nic,
                {"mac_address": BMC, "role": "host_bmc", "fixed_ip": "198.51.100.10"},
            ]
        },
        "intent": {"network_bindings": {HOST.upper(): "inband"} if bindings is None else bindings},
    }


class BoundSubnetTests(unittest.TestCase):
    def test_declared_mask_and_gateway_are_replaced_by_the_subnet(self):
        # A declaration made outside the console can carry a wider mask than the subnet.
        plan = record(fixed_mask="255.255.0.0", fixed_gateway="192.0.2.254")
        plans(Networks([INBAND])).follow_bound_subnets(plan)
        host, bmc = plan["machine"]["interfaces"]
        self.assertEqual(
            (host["fixed_mask"], host["fixed_gateway"]), ("255.255.255.0", "192.0.2.1")
        )
        self.assertEqual(bmc, {"mac_address": BMC, "role": "host_bmc", "fixed_ip": "198.51.100.10"})

    def test_subnet_without_gateway_clears_the_planned_gateway(self):
        plan = record()
        network = INBAND | {"prefixes": [{"prefix": "192.0.2.0/24"}]}
        plans(Networks([network])).follow_bound_subnets(plan)
        self.assertNotIn("fixed_gateway", plan["machine"]["interfaces"][0])

    def test_address_outside_the_bound_subnet_is_rejected(self):
        plan = record(fixed_ip="203.0.113.10", fixed_gateway="203.0.113.1")
        with self.assertRaisesRegex(ValueError, HOST + " 的规划 IP 不属于所选子网"):
            plans(Networks([INBAND])).follow_bound_subnets(plan)

    def test_unbound_ports_do_not_read_networks(self):
        resources = Networks(error=AssertionError("networks must not be read"))
        plan = record(bindings={}, fixed_mask="255.255.0.0")
        plans(resources).follow_bound_subnets(plan)
        self.assertEqual(resources.calls, 0)
        self.assertEqual(plan["machine"]["interfaces"][0]["fixed_mask"], "255.255.0.0")

    def test_plan_is_kept_as_entered_while_core_is_unreachable(self):
        plan = record(fixed_mask="255.255.0.0")
        plans(Networks(error=RuntimeError("offline"))).follow_bound_subnets(plan)
        self.assertEqual(plan["machine"]["interfaces"][0]["fixed_mask"], "255.255.0.0")

    def test_port_without_planned_address_or_known_subnet_is_left_alone(self):
        plan = record(bindings={HOST: "deleted-subnet"}, fixed_mask="255.255.0.0")
        plans(Networks([INBAND])).follow_bound_subnets(plan)
        self.assertEqual(plan["machine"]["interfaces"][0]["fixed_mask"], "255.255.0.0")
        plan = record(fixed_ip="", fixed_mask="")
        plans(Networks([INBAND])).follow_bound_subnets(plan)
        self.assertEqual(plan["machine"]["interfaces"][0]["fixed_mask"], "")


if __name__ == "__main__":
    unittest.main()
