"""Future backend boundary. It deliberately does not open sockets in this release."""

from typing import Any, Protocol


class ExamService(Protocol):
    def login(self, username: str, password: str) -> dict[str, Any]: ...
    def get_rooms(self, **filters: Any) -> list[dict[str, Any]]: ...
    def create_room(self, user_id: int, room_data: dict[str, Any]) -> dict[str, Any]: ...
    def join_room(self, room_id: int, user_id: int) -> dict[str, Any]: ...
    def start_room(self, room_id: int, user_id: int) -> dict[str, Any]: ...
    def submit_exam(self, user_id: int, payload: dict[str, Any]) -> dict[str, Any]: ...


class NetworkClient:
    """TCP/NDJSON placeholder for the C server integration phase.

    TODO: implement a worker-thread TCP client, newline-delimited JSON framing,
    request correlation, reconnect handling, and Qt signals.  Keeping this API
    aligned with ``MockApiService`` lets pages remain independent of transport.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 5050) -> None:
        self.host, self.port = host, port

    def request(self, _message_type: str, _payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("NetworkClient is a stub in the mock-only frontend")
