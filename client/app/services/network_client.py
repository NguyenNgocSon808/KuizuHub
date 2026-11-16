"""Persistent TCP/NDJSON transport shared by the CLI and the Qt worker.

``NetworkClient`` has no Qt dependency: the GUI keeps one instance inside a
dedicated worker thread, while ``ping_client.py`` can use it synchronously.
Responses are correlated with request IDs and the receive buffer preserves
partial or coalesced NDJSON frames.
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
    """A persistent, serial request/response TCP NDJSON client.

    The class is deliberately not thread-safe. The Qt layer owns one instance
    in a single worker thread, which prevents UI blocking and keeps socket I/O
    ordered. A receive buffer and response cache still provide request-ID
    correlation when the server coalesces responses.
    """

    max_line_bytes = 64 * 1024

    def __init__(self, host: str = "127.0.0.1", port: int = 5050, timeout: float = 3.0) -> None:
        self.host, self.port, self.timeout = host, port, timeout
        self._connection: socket.socket | None = None
        self._received = bytearray()
        self._responses: dict[str, dict[str, Any]] = {}

    def __enter__(self) -> "NetworkClient":
        return self

    def __exit__(self, _exc_type: object, _exc_value: object, _traceback: object) -> None:
        self.close()

    @property
    def connected(self) -> bool:
        return self._connection is not None

    def close(self) -> None:
        """Close the persistent connection and discard unread frames."""

        connection, self._connection = self._connection, None
        self._received.clear()
        self._responses.clear()
        if connection is None:
            return
        try:
            connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        connection.close()

    def request(
        self,
        message_type: str,
        payload: dict[str, Any] | None = None,
        *,
        request_id: str | None = None,
        token: str | None = None,
    ) -> dict[str, Any]:
        """Send one envelope and wait for the response with the same ID."""

        identifier = request_id or str(uuid.uuid4())
        if identifier in self._responses:
            return self._responses.pop(identifier)
        request: dict[str, Any] = {"type": message_type, "request_id": identifier, "payload": payload or {}}
        if token is not None:
            request["token"] = token
        encoded = (json.dumps(request, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        if len(encoded) > self.max_line_bytes:
            raise NetworkClientError("Request exceeds the 64 KiB NDJSON limit")

        try:
            connection = self._ensure_connection()
            connection.sendall(encoded)
            return self._wait_for_response(identifier)
        except NetworkClientError:
            self.close()
            raise
        except (OSError, TimeoutError) as error:
            self.close()
            raise NetworkClientError(f"Cannot reach {self.host}:{self.port}: {error}") from error

    def ping(self, *, request_id: str | None = None) -> dict[str, Any]:
        """Send a health-check request over the persistent connection."""

        return self.request("PING", {}, request_id=request_id)

    def _ensure_connection(self) -> socket.socket:
        if self._connection is not None:
            return self._connection
        try:
            connection = socket.create_connection((self.host, self.port), timeout=self.timeout)
            connection.settimeout(self.timeout)
        except OSError as error:
            raise NetworkClientError(f"Cannot reach {self.host}:{self.port}: {error}") from error
        self._connection = connection
        return connection

    def _wait_for_response(self, request_id: str) -> dict[str, Any]:
        cached = self._responses.pop(request_id, None)
        if cached is not None:
            return cached
        while True:
            line = self._next_complete_line()
            if line is None:
                connection = self._connection
                if connection is None:
                    raise NetworkClientError("TCP connection is unavailable")
                chunk = connection.recv(4096)
                if not chunk:
                    raise NetworkClientError("Server closed the connection before a response")
                self._received.extend(chunk)
                if len(self._received) > self.max_line_bytes and b"\n" not in self._received:
                    raise NetworkClientError("Server response exceeds the 64 KiB NDJSON limit")
                continue
            response = self._decode_response(line)
            response_id = response.get("request_id")
            if not isinstance(response_id, str):
                raise NetworkClientError("Server response is missing a string request_id")
            if response_id == request_id:
                return response
            self._responses[response_id] = response

    def _next_complete_line(self) -> bytes | None:
        newline_index = self._received.find(b"\n")
        if newline_index < 0:
            return None
        line = bytes(self._received[:newline_index])
        del self._received[: newline_index + 1]
        if len(line) > self.max_line_bytes:
            raise NetworkClientError("Server response exceeds the 64 KiB NDJSON limit")
        return line

    @staticmethod
    def _decode_response(response_line: bytes) -> dict[str, Any]:
        try:
            response = json.loads(response_line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise NetworkClientError("Server returned invalid JSON") from error
        if not isinstance(response, dict):
            raise NetworkClientError("Server response must be a JSON object")
        return response
