"""Read-only observer mode: an instance that reads a site without changing it.

A second PXEye attached to a Core that another PXEye already operates must not
allocate, install, enroll or reconfigure anything. Per-device task exclusion
lives in each instance's own database, and discovery or machine-creation
switches are global to the Core, so two writers would not see each other.

The mode is enforced twice. The HTTP transport rejects every command except
sign-in, and the outbound clients refuse anything that is not a read. The
client check is deny-by-default: an unrecognised Core method is refused.
"""

from pxeye.clients.errors import ReadOnlyModeError

MESSAGE = "当前为只读观察实例，不执行写操作。"

# Core RPC naming is consistent: these prefixes never mutate state.
READ_RPC_PREFIXES = ("Find", "Get", "Determine")
# nico-admin-cli reads take the form `<resource> show ...`.
READ_CLI_VERBS = ("show",)
READ_REDFISH_METHODS = ("GET", "OPTIONS")
# The only command an observer accepts: it creates a local browser session.
ALLOWED_COMMAND_PATHS = ("/api/login",)


def enabled(config):
    return config.get("read_only") is True


def command_allowed(config, path):
    return not enabled(config) or path in ALLOWED_COMMAND_PATHS


def require_rpc(config, method):
    if enabled(config) and not str(method).startswith(READ_RPC_PREFIXES):
        raise ReadOnlyModeError(MESSAGE)


def require_cli(config, args):
    if enabled(config) and not (len(args) >= 2 and args[1] in READ_CLI_VERBS):
        raise ReadOnlyModeError(MESSAGE)


def require_redfish(config, method):
    if enabled(config) and method not in READ_REDFISH_METHODS:
        raise ReadOnlyModeError(MESSAGE)


def require_no_ssh(config):
    if enabled(config):
        raise ReadOnlyModeError(MESSAGE)
