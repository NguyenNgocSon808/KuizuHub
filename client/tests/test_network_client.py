from __future__ import annotations

import json
import socket
import threading

from client.app.services.network_client import NetworkClient


def _read_line(connection: socket.socket) -> dict[str, object]:
    received = bytearray()
    while b"\n" not in received:
        chunk = connection.recv(4096)
        if not chunk:
            raise AssertionError("Client closed connection before sending a full request")
        received.extend(chunk)
    return json.loads(received.split(b"\n", 1)[0].decode("utf-8"))


def test_network_client_reuses_connection_and_handles_split_and_large_responses() -> None:
    accepted_connections: list[int] = []
    exam_data = {"content": "q" * (70 * 1024)}
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    host, port = listener.getsockname()

    def fake_server() -> None:
        try:
            connection, _ = listener.accept()
            accepted_connections.append(1)
            with connection:
                first = _read_line(connection)
                first_response = (
                    json.dumps(
                        {"type": "OK", "request_id": first["request_id"], "data": {"sequence": 1}}
                    ).encode("utf-8")
                    + b"\n"
                )
                connection.sendall(first_response[:9])
                connection.sendall(first_response[9:])

                second = _read_line(connection)
                second_response = (
                    json.dumps(
                        {"type": "OK", "request_id": second["request_id"], "data": exam_data}
                    ).encode("utf-8")
                    + b"\n"
                )
                connection.sendall(second_response)
        finally:
            listener.close()

    server_thread = threading.Thread(target=fake_server, daemon=True)
    server_thread.start()
    client = NetworkClient(str(host), int(port), timeout=2)
    try:
        assert client.request("PING", request_id="first")["data"] == {"sequence": 1}
        assert client.request("GET_EXAM", request_id="second")["data"] == exam_data
    finally:
        client.close()
    server_thread.join(timeout=2)

    assert not server_thread.is_alive()
    assert accepted_connections == [1]
