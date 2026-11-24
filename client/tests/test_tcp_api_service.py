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
                create_room = _read_line(connection)
                assert create_room["type"] == "CREATE_ROOM"
                assert create_room["token"] == "a" * 64
                assert create_room["payload"] == {
                    "name": "TCP Room",
                    "duration_seconds": 600,
                    "rules": [{"topic": "TCP Socket", "difficulty": "easy", "quantity": 2}],
                }
                _send_response(
                    connection,
                    create_room["request_id"],
                    {"room_id": 21, "status": "WAITING", "duration_seconds": 600},
                )
                list_rooms = _read_line(connection)
                assert list_rooms["type"] == "LIST_ROOMS"
                assert list_rooms["token"] == "a" * 64
                assert list_rooms["payload"] == {}
                _send_response(connection, list_rooms["request_id"], {"rooms": []})
                join_room = _read_line(connection)
                assert join_room["type"] == "JOIN_ROOM"
                assert join_room["token"] == "a" * 64
                assert join_room["payload"] == {"room_id": 21}
                _send_response(
                    connection,
                    join_room["request_id"],
                    {"room_id": 21, "status": "WAITING", "participant_state": "JOINED"},
                )
                start_room = _read_line(connection)
                assert start_room["type"] == "START_ROOM"
                assert start_room["token"] == "a" * 64
                assert start_room["payload"] == {"room_id": 21}
                _send_response(
                    connection,
                    start_room["request_id"],
                    {"room_id": 21, "status": "RUNNING", "question_count": 3},
                )
                get_exam = _read_line(connection)
                assert get_exam["type"] == "GET_EXAM"
                assert get_exam["token"] == "a" * 64
                assert get_exam["payload"] == {"room_id": 21}
                _send_response(connection, get_exam["request_id"], {"room_id": 21, "questions": []})
                save_answer = _read_line(connection)
                assert save_answer["type"] == "SAVE_ANSWER"
                assert save_answer["token"] == "a" * 64
                assert save_answer["payload"] == {"room_id": 21, "question_id": 3, "option_id": 12}
                _send_response(connection, save_answer["request_id"], {"saved": True})
                submit_exam = _read_line(connection)
                assert submit_exam["type"] == "SUBMIT_EXAM"
                assert submit_exam["token"] == "a" * 64
                assert submit_exam["payload"] == {"room_id": 21}
                _send_response(connection, submit_exam["request_id"], {"room_id": 21, "state": "SUBMITTED"})
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
    create_room_request_id: str | None = None
    list_rooms_request_id: str | None = None
    join_room_request_id: str | None = None
    start_room_request_id: str | None = None
    get_exam_request_id: str | None = None
    save_answer_request_id: str | None = None
    submit_exam_request_id: str | None = None

    def on_success(request_id: str, response: object) -> None:
        nonlocal profile_request_id, create_room_request_id, list_rooms_request_id, join_room_request_id, start_room_request_id, get_exam_request_id, save_answer_request_id, submit_exam_request_id
        successes[request_id] = response
        if request_id == login_request_id:
            profile_request_id = service.get_my_profile()
        elif request_id == profile_request_id:
            create_room_request_id = service.create_room(
                "TCP Room",
                600,
                [{"topic": "TCP Socket", "difficulty": "easy", "quantity": 2}],
            )
        elif request_id == create_room_request_id:
            list_rooms_request_id = service.list_rooms()
        elif request_id == list_rooms_request_id:
            join_room_request_id = service.join_room(21)
        elif request_id == join_room_request_id:
            start_room_request_id = service.start_room(21)
        elif request_id == start_room_request_id:
            get_exam_request_id = service.get_exam(21)
        elif request_id == get_exam_request_id:
            save_answer_request_id = service.save_answer(21, 3, 12)
        elif request_id == save_answer_request_id:
            submit_exam_request_id = service.submit_exam(21)
        elif request_id == submit_exam_request_id:
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
    assert create_room_request_id is not None
    assert list_rooms_request_id is not None
    assert join_room_request_id is not None
    assert start_room_request_id is not None
    assert get_exam_request_id is not None
    assert save_answer_request_id is not None
    assert submit_exam_request_id is not None
    assert login_request_id in successes
    assert profile_request_id in successes
    assert create_room_request_id in successes
    assert list_rooms_request_id in successes
    assert join_room_request_id in successes
    assert start_room_request_id in successes
    assert get_exam_request_id in successes
    assert save_answer_request_id in successes
    assert submit_exam_request_id in successes
    assert service.token == "a" * 64
    assert not server_thread.is_alive()
    assert not server_errors


def test_phase_three_service_sends_profile_result_and_analytics_requests() -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    host, port = listener.getsockname()
    server_errors: list[BaseException] = []
    expected = [
        ("LOGIN", {"username": "student", "password": "StrongPassword123"}),
        ("UPDATE_MY_PROFILE", {
            "display_name": "Student", "current_password": "StrongPassword123", "new_password": "NewPassword123",
        }),
        ("GET_ROOM_RESULTS", {"room_id": 11}),
        ("GET_ROOM_LOBBY", {"room_id": 11}),
        ("GET_MY_HISTORY", {"limit": 10, "offset": 0}),
        ("GET_MY_STATS", {}),
        ("GET_LEADERBOARD", {"room_id": 11, "limit": 10, "offset": 0}),
    ]

    def fake_server() -> None:
        try:
            connection, _ = listener.accept()
            with connection:
                for index, (request_type, payload) in enumerate(expected):
                    request = _read_line(connection)
                    assert request["type"] == request_type
                    assert request["payload"] == payload
                    if index:
                        assert request["token"] == "b" * 64
                    if request_type == "LOGIN":
                        data = {"token": "b" * 64, "user": {"id": 2, "username": "student", "role": "STUDENT"}}
                    elif request_type == "UPDATE_MY_PROFILE":
                        data = {"user": {"id": 2, "username": "student", "display_name": "Student", "role": "STUDENT"}}
                    elif request_type == "GET_ROOM_RESULTS":
                        data = {"room": {"id": 11, "name": "Room"}, "results": [], "review": []}
                    elif request_type == "GET_ROOM_LOBBY":
                        data = {"room": {"id": 11, "name": "Room", "status": "WAITING"}, "participants": []}
                    elif request_type == "GET_MY_HISTORY":
                        data = {"attempts": [], "limit": 10, "offset": 0, "has_more": False}
                    elif request_type == "GET_MY_STATS":
                        data = {"attempts": 0, "by_topic": []}
                    else:
                        data = {"room_id": 11, "entries": [], "limit": 10, "offset": 0, "has_more": False}
                    _send_response(connection, request["request_id"], data)
        except BaseException as error:
            server_errors.append(error)
        finally:
            listener.close()

    server_thread = threading.Thread(target=fake_server, daemon=True)
    server_thread.start()
    app = QCoreApplication.instance() or QCoreApplication([])
    service = PhaseOneApiService(str(host), int(port), timeout=2)
    event_loop = QEventLoop()
    failures: list[str] = []
    steps: list[str] = []

    def on_success(_request_id: str, _response: object) -> None:
        if not steps:
            steps.append("login")
            service.update_my_profile(
                display_name="Student", current_password="StrongPassword123", new_password="NewPassword123"
            )
        elif steps[-1] == "login":
            steps.append("profile")
            service.get_room_results(11)
        elif steps[-1] == "profile":
            steps.append("results")
            service.get_room_lobby(11)
        elif steps[-1] == "results":
            steps.append("lobby")
            service.get_my_history(limit=10)
        elif steps[-1] == "lobby":
            steps.append("history")
            service.get_my_stats()
        elif steps[-1] == "history":
            steps.append("stats")
            service.get_leaderboard(11, limit=10)
        else:
            steps.append("leaderboard")
            event_loop.quit()

    service.request_succeeded.connect(on_success)
    service.request_failed.connect(lambda _request_id, message: failures.append(message))
    service.login("student", "StrongPassword123")
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(event_loop.quit)
    timeout.start(3000)
    event_loop.exec()
    service.close()
    server_thread.join(timeout=2)

    assert not failures
    assert steps == ["login", "profile", "results", "lobby", "history", "stats", "leaderboard"]
    assert service.token == "b" * 64
    assert not server_thread.is_alive()
    assert not server_errors
