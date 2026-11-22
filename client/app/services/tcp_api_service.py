"""Qt-facing asynchronous API service for the implemented Phase 1 flows."""

from __future__ import annotations

import uuid
from typing import Any

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal, Slot

from .network_client import NetworkClient, NetworkClientError


class _TcpRequestWorker(QObject):
    """Owns the blocking socket client and always runs outside the GUI thread."""

    response_received = Signal(str, object)
    request_failed = Signal(str, str)

    def __init__(self, host: str, port: int, timeout: float) -> None:
        super().__init__()
        self._client = NetworkClient(host, port, timeout)

    @Slot(str, str, object, object)
    def execute(self, request_id: str, request_type: str, payload: object, token: object) -> None:
        try:
            response = self._client.request(
                request_type,
                payload if isinstance(payload, dict) else {},
                request_id=request_id,
                token=token if isinstance(token, str) else None,
            )
        except NetworkClientError as error:
            self.request_failed.emit(request_id, str(error))
            return
        self.response_received.emit(request_id, response)

    @Slot()
    def close(self) -> None:
        self._client.close()


class PhaseOneApiService(QObject):
    """Non-blocking service layer for implemented TCP API requests.

    Callers receive a request ID immediately, then match it against
    ``request_succeeded`` or ``request_failed``.  The service deliberately
    covers only endpoints backed by the C server. Implemented room-listing,
    room-creation, and practice requests use the same worker; remaining room,
    history, and analytics flows are still not backed by mock data here.
    """

    request_succeeded = Signal(str, object)
    request_failed = Signal(str, str)
    _submit = Signal(str, str, object, object)
    _shutdown = Signal()

    def __init__(self, host: str = "127.0.0.1", port: int = 5050, timeout: float = 3.0) -> None:
        super().__init__()
        self._token: str | None = None
        self._pending_types: dict[str, str] = {}
        self._thread = QThread(self)
        self._worker = _TcpRequestWorker(host, port, timeout)
        self._worker.moveToThread(self._thread)
        self._submit.connect(self._worker.execute, Qt.QueuedConnection)
        self._shutdown.connect(self._worker.close, Qt.QueuedConnection)
        self._worker.response_received.connect(self._handle_response)
        self._worker.request_failed.connect(self._handle_transport_failure)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.start()

    @property
    def token(self) -> str | None:
        return self._token

    @property
    def authenticated(self) -> bool:
        return self._token is not None

    def close(self) -> None:
        """Stop the worker and release its persistent socket before app exit."""

        if not self._thread.isRunning():
            return
        self._shutdown.emit()
        self._thread.quit()
        self._thread.wait(2000)

    def request(self, request_type: str, payload: dict[str, Any] | None = None, *, authenticated: bool = False) -> str:
        request_id = str(uuid.uuid4())
        self._pending_types[request_id] = request_type
        if authenticated and self._token is None:
            QTimer.singleShot(0, lambda: self._handle_transport_failure(request_id, "No active session"))
            return request_id
        self._submit.emit(request_id, request_type, payload or {}, self._token if authenticated else None)
        return request_id

    def register(self, username: str, password: str, role: str) -> str:
        return self.request("REGISTER", {"username": username, "password": password, "role": role})

    def login(self, username: str, password: str) -> str:
        return self.request("LOGIN", {"username": username, "password": password})

    def logout(self) -> str:
        return self.request("LOGOUT", {}, authenticated=True)

    def get_my_profile(self) -> str:
        return self.request("GET_MY_PROFILE", {}, authenticated=True)

    def list_rooms(self) -> str:
        return self.request("LIST_ROOMS", {}, authenticated=True)

    def list_questions(
        self,
        *,
        query: str = "",
        topic: str = "",
        difficulty: str = "",
        include_inactive: bool = True,
        limit: int = 20,
        offset: int = 0,
    ) -> str:
        return self.request(
            "LIST_QUESTIONS",
            {
                "query": query,
                "topic": topic,
                "difficulty": difficulty,
                "include_inactive": 1 if include_inactive else 0,
                "limit": limit,
                "offset": offset,
            },
            authenticated=True,
        )

    def create_question(self, question: dict[str, Any]) -> str:
        return self.request("CREATE_QUESTION", question, authenticated=True)

    def update_question(
        self,
        question_id: int,
        *,
        question: dict[str, Any] | None = None,
        is_active: bool | None = None,
    ) -> str:
        payload: dict[str, Any] = {"id": question_id}
        if question is not None:
            payload["question"] = question
        if is_active is not None:
            payload["is_active"] = 1 if is_active else 0
        return self.request("UPDATE_QUESTION", payload, authenticated=True)

    def import_questions(self, questions: list[dict[str, Any]]) -> str:
        return self.request("IMPORT_QUESTIONS", {"questions": questions}, authenticated=True)

    def create_room(
        self,
        name: str,
        duration_seconds: int,
        rules: list[dict[str, Any]],
    ) -> str:
        return self.request(
            "CREATE_ROOM",
            {
                "name": name,
                "duration_seconds": duration_seconds,
                "rules": rules,
            },
            authenticated=True,
        )

    def join_room(self, room_id: int) -> str:
        return self.request("JOIN_ROOM", {"room_id": room_id}, authenticated=True)

    def start_room(self, room_id: int) -> str:
        return self.request("START_ROOM", {"room_id": room_id}, authenticated=True)

    def get_exam(self, room_id: int) -> str:
        return self.request("GET_EXAM", {"room_id": room_id}, authenticated=True)

    def save_answer(self, room_id: int, question_id: int, option_id: int) -> str:
        return self.request(
            "SAVE_ANSWER",
            {"room_id": room_id, "question_id": question_id, "option_id": option_id},
            authenticated=True,
        )

    def submit_exam(self, room_id: int) -> str:
        return self.request("SUBMIT_EXAM", {"room_id": room_id}, authenticated=True)

    def start_practice(self, topic: str, difficulty: str, question_count: int,
                       duration_seconds: int) -> str:
        return self.request(
            "START_PRACTICE",
            {"topic": topic, "difficulty": difficulty, "question_count": question_count,
             "duration_seconds": duration_seconds},
            authenticated=True,
        )

    def save_practice_answer(self, attempt_id: int, question_id: int,
                             selected_option_position: int) -> str:
        return self.request(
            "SAVE_PRACTICE_ANSWER",
            {"attempt_id": attempt_id, "question_id": question_id,
             "selected_option_position": selected_option_position},
            authenticated=True,
        )

    def submit_practice(self, attempt_id: int) -> str:
        return self.request("SUBMIT_PRACTICE", {"attempt_id": attempt_id}, authenticated=True)

    @Slot(str, object)
    def _handle_response(self, request_id: str, raw_response: object) -> None:
        request_type = self._pending_types.pop(request_id, "")
        if not isinstance(raw_response, dict):
            self.request_failed.emit(request_id, "Server response is not a JSON object")
            return
        if raw_response.get("type") != "OK":
            error = raw_response.get("error")
            if isinstance(error, dict):
                code = error.get("code", "ERROR")
                message = error.get("message", "Request failed")
                self.request_failed.emit(request_id, f"{code}: {message}")
            else:
                self.request_failed.emit(request_id, "Server returned an invalid error response")
            return
        if request_type == "LOGIN":
            data = raw_response.get("data")
            token = data.get("token") if isinstance(data, dict) else None
            if not isinstance(token, str) or not token:
                self.request_failed.emit(request_id, "Login response does not contain a session token")
                return
            self._token = token
        elif request_type == "LOGOUT":
            self._token = None
        self.request_succeeded.emit(request_id, raw_response)

    @Slot(str, str)
    def _handle_transport_failure(self, request_id: str, message: str) -> None:
        self._pending_types.pop(request_id, None)
        self.request_failed.emit(request_id, message)
