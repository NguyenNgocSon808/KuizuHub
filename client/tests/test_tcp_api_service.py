from __future__ import annotations

import json
import socket
import threading

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

from client.app.services.tcp_api_service import PhaseOneApiService


def _read_line(connection: socket.socket) -> dict[str, object]:
    received = bytearray()
    while b"\n" not in received:
        chunk = connection.recv(4096)
        if not chunk:
            raise AssertionError("Client closed the connection before its request")
        received.extend(chunk)
    return json.loads(received.split(b"\n", 1)[0].decode("utf-8"))


def _send_response(connection: socket.socket, request_id: object, data: dict[str, object]) -> None:
    connection.sendall(
        (json.dumps({"type": "OK", "request_id": request_id, "data": data}) + "\n").encode("utf-8")
    )


def test_phase_one_service_runs_requests_in_worker_and_keeps_session_token() -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    host, port = listener.getsockname()
    server_errors: list[BaseException] = []

    def fake_server() -> None:
        try:
            connection, _ = listener.accept()
            with connection:
                login = _read_line(connection)
                assert login["type"] == "LOGIN"
                _send_response(
                    connection,
                    login["request_id"],
                    {
                        "token": "a" * 64,
                        "user": {"id": 7, "username": "admin", "role": "ADMIN"},
                    },
                )
                profile = _read_line(connection)
                assert profile["type"] == "GET_MY_PROFILE"
                assert profile["token"] == "a" * 64
                _send_response(
                    connection,
                    profile["request_id"],
                    {
                        "user": {
                            "id": 7,
                            "username": "admin",
                            "role": "ADMIN",
                            "created_at": "2026-11-16 10:00:00",
                        }
                    },
                )
        except BaseException as error:  # Surface failures from the worker thread in the test.
            server_errors.append(error)
        finally:
            listener.close()

    server_thread = threading.Thread(target=fake_server, daemon=True)
    server_thread.start()

    app = QCoreApplication.instance() or QCoreApplication([])
    service = PhaseOneApiService(str(host), int(port), timeout=2)
    event_loop = QEventLoop()
    successes: dict[str, object] = {}
    failures: list[str] = []
    profile_request_id: str | None = None

    def on_success(request_id: str, response: object) -> None:
        nonlocal profile_request_id
        successes[request_id] = response
        if request_id == login_request_id:
            profile_request_id = service.get_my_profile()
        elif request_id == profile_request_id:
            event_loop.quit()

    service.request_succeeded.connect(on_success)
    service.request_failed.connect(lambda _request_id, message: failures.append(message))
    login_request_id = service.login("admin", "StrongPassword123")
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(event_loop.quit)
    timeout.start(3000)
    event_loop.exec()
    service.close()
    server_thread.join(timeout=2)

    assert not failures
    assert profile_request_id is not None
    assert login_request_id in successes
    assert profile_request_id in successes
    assert service.token == "a" * 64
    assert not server_thread.is_alive()
    assert not server_errors
