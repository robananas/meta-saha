from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any

SOCKET_PATH = Path("/run/saha/board-status/events.sock")


def emit_board_status(
    component: str,
    state: str,
    *,
    level: str = "info",
    error_code: str | None = None,
    detail: Any = None,
) -> None:
    payload = {
        "component": component,
        "state": state,
        "level": level,
        "errorCode": error_code,
        "detail": detail,
    }
    client = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        client.sendto(json.dumps(payload, separators=(",", ":")).encode("utf-8"), str(SOCKET_PATH))
    except OSError:
        pass
    finally:
        client.close()
