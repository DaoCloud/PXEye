"""Safe error classification and request correlation without credential logging."""

import json
import sqlite3
import time
import traceback
import uuid
from pathlib import Path
from pxeye.clients.errors import CoreConnectionError, RedfishRequestError, RPCRequestError
from pxeye.services.resources import ImportReadbackError


def failure(error, *, method, path, request_id=None):
    request_id = request_id or uuid.uuid4().hex
    name = type(error).__name__
    if isinstance(error, CoreConnectionError):
        status, code, message = 502, error.code, str(error)
    elif isinstance(error, RPCRequestError):
        status, code, message = 502, "RPC_REQUEST_INVALID", str(error)
    elif isinstance(error, RedfishRequestError):
        status, code, message = 502, "REDFISH_REQUEST_FAILED", str(error)
    elif isinstance(error, ImportReadbackError):
        status, code, message = 502, "IMPORT_READBACK_FAILED", str(error)
    elif isinstance(error, ValueError):
        status, code, message = 400, "INVALID_REQUEST", str(error)
    elif isinstance(error, (KeyError, TypeError)):
        status, code, message = 400, "INVALID_FIELDS", "请求字段无效，请刷新后核对。"
    elif isinstance(error, (OSError, sqlite3.Error)):
        status, code, message = (
            503,
            "PERSISTENCE_UNAVAILABLE",
            "本地数据读取或保存失败，请提供错误编号查看服务日志。",
        )
    elif isinstance(error, RuntimeError):
        status, code, message = (
            502,
            "OPERATION_FAILED",
            "操作失败，请提供错误编号查看服务日志；未自动重试写操作。",
        )
    else:
        status, code, message = (
            500,
            "INTERNAL_ERROR",
            "服务处理失败，请提供错误编号查看日志；未自动重试写操作。",
        )
    # Only frame metadata: no locals, source excerpts, argv or unreviewed exception text.
    frames = [
        {"file": Path(frame.filename).name, "line": frame.lineno, "function": frame.name}
        for frame in traceback.extract_tb(error.__traceback__)[-12:]
    ]
    print(
        json.dumps(
            {
                "at": time.time(),
                "event": "request_failed",
                "request_id": request_id,
                "method": method,
                "path": path,
                "code": code,
                "exception_type": name,
                "frames": frames,
            }
        ),
        flush=True,
    )
    return status, {"error": message, "code": code, "request_id": request_id}
