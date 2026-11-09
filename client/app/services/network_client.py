"""Small synchronous TCP/NDJSON client used by the Phase 0 health check.

GUI traffic will move to a worker thread in Phase 1. This module is deliberately
independent of PySide6 so the command-line health check and integration tests can
use exactly the same transport implementation.
"""

from __future__ import annotations

import json
import socket
import uuid
from typing import Any, Protocol


class ExamService(Protocol):
    def login(self, username: str, password: str) -> dict[str, Any]: ...
    def get_rooms(self, **filters: Any) -> list[dict[str, Any]]: ...
    def create_room(self, user_id: int, room_data: dict[str, Any]) -> dict[str, Any]: ...
    def join_room(self, room_id: int, user_id: int) -> dict[str, Any]: ...
    def start_room(self, room_id: int, user_id: int) -> dict[str, Any]: ...
    def submit_exam(self, user_id: int, payload: dict[str, Any]) -> dict[str, Any]: ...


class NetworkClientError(RuntimeError):
    """Raised when the TCP peer violates the NDJSON request/response contract."""


class NetworkClient:
    """One-request-per-connection NDJSON client for Phase 0.

    Keeping one short-lived connection makes the health-check behavior explicit.
    Persistent sockets, a receive worker and request correlation will be added
    when the GUI is connected to the server in Phase 1.
    """

    max_line_bytes = 64 * 1024

    def __init__(self, host: str = "127.0.0.1", port: int = 5050, timeout: float = 3.0) -> None:
        self.host, self.port, self.timeout = host, port, timeout

    def request(self, message_type: str, payload: dict[str, Any] | None = None,
                *, request_id: str | None = None, token: str | None = None) -> dict[str, Any]:
        identifier = request_id or str(uuid.uuid4())
        request: dict[str, Any] = {"type": message_type, "request_id": identifier, "payload": payload or {}}
        if token is not None:
            request["token"] = token
        encoded = (json.dumps(request, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        if len(encoded) > self.max_line_bytes:
            raise NetworkClientError("Request exceeds the 64 KiB NDJSON limit")

        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout) as connection:
                connection.settimeout(self.timeout)
                connection.sendall(encoded)
                response_line = self._receive_line(connection)
        except OSError as error:
            raise NetworkClientError(f"Cannot reach {self.host}:{self.port}: {error}") from error

        try:
            response = json.loads(response_line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise NetworkClientError("Server returned invalid JSON") from error
        if not isinstance(response, dict):
            raise NetworkClientError("Server response must be a JSON object")
        if response.get("request_id") != identifier:
            raise NetworkClientError("Server response has a mismatched request_id")
        return response

    def ping(self, *, request_id: str | None = None) -> dict[str, Any]:
        """Send the Phase 0 PING request and return its server response."""

        return self.request("PING", {}, request_id=request_id)

    def _receive_line(self, connection: socket.socket) -> bytes:
        received = bytearray()
        while len(received) <= self.max_line_bytes:
            chunk = connection.recv(4096)
            if not chunk:
                raise NetworkClientError("Server closed the connection before a response")
            received.extend(chunk)
            newline_index = received.find(b"\n")
            if newline_index >= 0:
                return bytes(received[:newline_index])
        raise NetworkClientError("Server response exceeds the 64 KiB NDJSON limit")
