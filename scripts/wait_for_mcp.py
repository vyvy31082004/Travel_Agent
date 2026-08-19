from __future__ import annotations

import os
import socket
import sys
import time

DEFAULT_PORTS = "8001,8002,8003,8004,8005"


def _ports() -> list[int]:
    raw = os.getenv("MCP_SIDECAR_PORTS", DEFAULT_PORTS)
    return [int(part.strip()) for part in raw.split(",") if part.strip()]


def main() -> int:
    host = os.getenv("MCP_SIDECAR_HOST", "127.0.0.1")
    timeout = int(os.getenv("MCP_STARTUP_TIMEOUT_SECONDS", "90"))
    interval = float(os.getenv("MCP_STARTUP_CHECK_INTERVAL_SECONDS", "2"))
    deadline = time.monotonic() + timeout
    ports = _ports()

    while time.monotonic() < deadline:
        pending: list[int] = []
        for port in ports:
            try:
                with socket.create_connection((host, port), timeout=2):
                    pass
            except OSError:
                pending.append(port)
        if not pending:
            print(f"All MCP sidecar ports are reachable on {host}: {ports}", flush=True)
            return 0
        print(f"Waiting for MCP sidecars on {host}; pending ports: {pending}", flush=True)
        time.sleep(interval)

    print(
        f"Timed out after {timeout}s waiting for MCP sidecar ports on {host}: {ports}",
        file=sys.stderr,
        flush=True,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
