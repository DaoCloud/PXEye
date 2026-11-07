"""Safe transport errors; raw arguments and responses are not public messages."""


class RedfishRequestError(RuntimeError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class RPCRequestError(RuntimeError):
    """Only a local request-data parsing failure proves the RPC was not sent."""

    request_not_sent = True


class CoreConnectionError(RuntimeError):
    """Safe, actionable connection error; never contains raw command output."""

    def __init__(self, message, code):
        super().__init__(message)
        self.code = code
