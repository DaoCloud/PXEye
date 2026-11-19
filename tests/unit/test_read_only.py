"""A read-only observer must refuse every write before anything is sent."""

import unittest

from pxeye import read_only
from pxeye.clients.core import CoreClient
from pxeye.clients.errors import ReadOnlyModeError
from pxeye.clients.redfish import RedfishClient
from pxeye.clients.ssh import SSHClient

OBSERVER, OPERATOR = {"read_only": True}, {}


class Transport(CoreClient, RedfishClient, SSHClient):
    def __init__(self, config):
        self.config = config

    def check_core_certificate(self):
        raise AssertionError("a refused call must not reach the transport")


class ReadOnlyTests(unittest.TestCase):
    def test_only_an_explicit_true_enables_the_mode(self):
        self.assertTrue(read_only.enabled(OBSERVER))
        for value in ("true", 1, None):
            self.assertFalse(read_only.enabled({"read_only": value}))
        self.assertFalse(read_only.enabled(OPERATOR))

    def test_observer_accepts_sign_in_and_no_other_command(self):
        self.assertTrue(read_only.command_allowed(OBSERVER, "/api/login"))
        for path in ("/api/tasks", "/api/site", "/api/installer-events", "/api/devices/admit"):
            self.assertFalse(read_only.command_allowed(OBSERVER, path))
            self.assertTrue(read_only.command_allowed(OPERATOR, path))

    def test_core_reads_pass_and_writes_or_unknown_methods_are_refused(self):
        for method in ("FindInterfaces", "GetHostBootIntent", "DetermineMachineIngestionState"):
            read_only.require_rpc(OBSERVER, method)
        for method in ("AllocateInstance", "PatchExpectedMachines", "SetHostBootIntent", "New"):
            with self.assertRaises(ReadOnlyModeError):
                read_only.require_rpc(OBSERVER, method)
            read_only.require_rpc(OPERATOR, method)
        read_only.require_cli(OBSERVER, ["machine", "show", "--hosts"])
        for args in (["machine", "reboot", "--machine", "m"], ["machine"], []):
            with self.assertRaises(ReadOnlyModeError):
                read_only.require_cli(OBSERVER, args)

    def test_clients_refuse_before_touching_the_network(self):
        observer = Transport(OBSERVER)
        with self.assertRaises(ReadOnlyModeError):
            observer.rpc("AllocateInstance", {})
        with self.assertRaises(ReadOnlyModeError):
            observer.core(["machine", "reboot", "--machine", "m"])
        credential = {"username": "u", "password": "p"}
        for method in ("PATCH", "POST"):
            with self.assertRaises(ReadOnlyModeError):
                observer.redfish_request(
                    "192.0.2.1", "/redfish/v1/Systems", credential, method=method
                )
        with self.assertRaises(ReadOnlyModeError):
            observer.ssh({}, "true")
        self.assertTrue(ReadOnlyModeError.request_not_sent)


if __name__ == "__main__":
    unittest.main()
