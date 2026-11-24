from __future__ import annotations

import contextlib
import json
import os
import socket
import sqlite3
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


SERVER_DIR = Path(__file__).resolve().parents[1]
SERVER_BINARY = SERVER_DIR / "build" / "kuizuhub-server"
if os.name == "nt":
    SERVER_BINARY = SERVER_BINARY.with_suffix(".exe")


def receive_json_line(connection: socket.socket) -> dict[str, object]:
    received = bytearray()
    while b"\n" not in received:
        chunk = connection.recv(4096)
        if not chunk:
            raise AssertionError("Server closed the connection before its response")
        received.extend(chunk)
    return json.loads(received.split(b"\n", 1)[0].decode("utf-8"))


class CreateRoomTests(unittest.TestCase):
    server: subprocess.Popen[str]
    port: int
    temp_dir: tempfile.TemporaryDirectory[str]
    db_path: Path
    username_counter = 0

    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.temp_dir.name) / "rooms.db"
        with contextlib.closing(sqlite3.connect(cls.db_path)) as db:
            db.executescript(
                (SERVER_DIR / "migrations" / "001_initial.sql").read_text(encoding="utf-8")
            )

            def add_question(content: str, difficulty: str) -> None:
                question_id = db.execute(
                    "INSERT INTO questions(content, topic, difficulty, is_active) "
                    "VALUES (?, 'TCP Socket', ?, 1)",
                    (content, difficulty),
                ).lastrowid
                option_ids = []
                for position, label in enumerate("ABCD", start=1):
                    option_ids.append(
                        db.execute(
                            "INSERT INTO question_options(question_id, label, content, position) "
                            "VALUES (?, ?, ?, ?)",
                            (question_id, label, f"{content} option {label}", position),
                        ).lastrowid
                    )
                db.execute(
                    "UPDATE questions SET correct_option_id = ? WHERE id = ?",
                    (option_ids[0], question_id),
                )

            for index in range(4):
                add_question(f"Easy TCP question {index}", "easy")
            for index in range(3):
                add_question(f"Medium TCP question {index}", "medium")
            db.commit()

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            cls.port = int(probe.getsockname()[1])

        env = os.environ.copy()
        env["KUIZUHUB_DB_PATH"] = str(cls.db_path)
        cls.server = subprocess.Popen(
            [str(SERVER_BINARY), str(cls.port)],
            cwd=SERVER_DIR,
            text=True,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", cls.port), timeout=0.1):
                    return
            except OSError:
                time.sleep(0.03)
        cls.tearDownClass()
        raise RuntimeError("Room server did not start")

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "server"):
            if cls.server.poll() is None:
                cls.server.terminate()
                cls.server.wait(timeout=3)
            if cls.server.stderr is not None:
                cls.server.stderr.close()
        if hasattr(cls, "temp_dir"):
            cls.temp_dir.cleanup()

    def send_request(
        self,
        request_type: str,
        payload: dict[str, object],
        *,
        token: str | None = None,
        request_id: str = "room-request",
    ) -> dict[str, object]:
        envelope: dict[str, object] = {
            "type": request_type,
            "request_id": request_id,
            "payload": payload,
        }
        if token is not None:
            envelope["token"] = token
        with socket.create_connection(("127.0.0.1", self.port), timeout=3) as connection:
            connection.sendall(json.dumps(envelope, separators=(",", ":")).encode("utf-8") + b"\n")
            return receive_json_line(connection)

    def register_and_login(self, role: str) -> tuple[str, int]:
        type(self).username_counter += 1
        username = f"room_{role.lower()}_{self.username_counter}"
        registered = self.send_request(
            "REGISTER",
            {"username": username, "password": "RoomPassword123", "role": role},
            request_id=f"register-{username}",
        )
        self.assertEqual(registered["type"], "OK")
        logged_in = self.send_request(
            "LOGIN",
            {"username": username, "password": "RoomPassword123"},
            request_id=f"login-{username}",
        )
        self.assertEqual(logged_in["type"], "OK")
        return (
            logged_in["data"]["token"],  # type: ignore[index,return-value]
            logged_in["data"]["user"]["id"],  # type: ignore[index,return-value]
        )

    @staticmethod
    def valid_rules() -> list[dict[str, object]]:
        return [
            {"topic": "TCP Socket", "difficulty": "easy", "quantity": 2},
            {"topic": "TCP Socket", "difficulty": "medium", "quantity": 1},
        ]

    def test_01_host_creates_room_and_rules(self) -> None:
        token, owner_id = self.register_and_login("HOST")
        response = self.send_request(
            "CREATE_ROOM",
            {"name": "TCP midterm", "duration_seconds": 600, "rules": self.valid_rules()},
            token=token,
            request_id="create-host-room",
        )

        self.assertEqual(response["type"], "OK")
        self.assertEqual(response["request_id"], "create-host-room")
        self.assertEqual(response["data"]["status"], "WAITING")  # type: ignore[index]
        room_id = response["data"]["room_id"]  # type: ignore[index]
        self.assertIsInstance(room_id, int)

        with contextlib.closing(sqlite3.connect(self.db_path)) as db:
            room = db.execute(
                "SELECT owner_id, name, status, duration_seconds FROM exam_rooms WHERE id = ?",
                (room_id,),
            ).fetchone()
            rules = db.execute(
                "SELECT topic, difficulty, quantity FROM room_question_rules "
                "WHERE room_id = ? ORDER BY difficulty",
                (room_id,),
            ).fetchall()
        self.assertEqual(room, (owner_id, "TCP midterm", "WAITING", 600))
        self.assertEqual(
            rules,
            [("TCP Socket", "easy", 2), ("TCP Socket", "medium", 1)],
        )

    def test_02_list_rooms_returns_owner_status_and_aggregate_participant_count(self) -> None:
        host_token, host_id = self.register_and_login("HOST")
        _, first_student_id = self.register_and_login("STUDENT")
        _, second_student_id = self.register_and_login("STUDENT")

        with contextlib.closing(sqlite3.connect(self.db_path)) as db:
            owner_name = db.execute(
                "SELECT username FROM users WHERE id = ?", (host_id,)
            ).fetchone()[0]
            waiting_id = db.execute(
                "INSERT INTO exam_rooms(owner_id, name, status, duration_seconds) "
                "VALUES (?, 'Waiting room', 'WAITING', 600)",
                (host_id,),
            ).lastrowid
            running_id = db.execute(
                "INSERT INTO exam_rooms(owner_id, name, status, duration_seconds) "
                "VALUES (?, 'Running room', 'RUNNING', 900)",
                (host_id,),
            ).lastrowid
            ended_id = db.execute(
                "INSERT INTO exam_rooms(owner_id, name, status, duration_seconds) "
                "VALUES (?, 'Ended room', 'ENDED', 300)",
                (host_id,),
            ).lastrowid
            db.executemany(
                "INSERT INTO room_participants(room_id, user_id) VALUES (?, ?)",
                [
                    (waiting_id, first_student_id),
                    (waiting_id, second_student_id),
                    (running_id, first_student_id),
                ],
            )
            db.commit()

        response = self.send_request(
            "LIST_ROOMS", {}, token=host_token, request_id="list-room-details"
        )

        self.assertEqual(response["type"], "OK")
        rooms = response["data"]["rooms"]  # type: ignore[index]
        self.assertIsInstance(rooms, list)
        rooms_by_id = {room["id"]: room for room in rooms}  # type: ignore[index,union-attr]
        self.assertEqual(rooms_by_id[waiting_id]["owner_name"], owner_name)
        self.assertEqual(rooms_by_id[waiting_id]["status"], "WAITING")
        self.assertEqual(rooms_by_id[waiting_id]["participant_count"], 2)
        self.assertEqual(rooms_by_id[running_id]["status"], "RUNNING")
        self.assertEqual(rooms_by_id[running_id]["participant_count"], 1)
        self.assertEqual(rooms_by_id[ended_id]["status"], "ENDED")
        self.assertEqual(rooms_by_id[ended_id]["participant_count"], 0)
        self.assertTrue(
            all(room["status"] in {"WAITING", "RUNNING", "ENDED"} for room in rooms)  # type: ignore[index,union-attr]
        )

    def test_03_student_cannot_create_room(self) -> None:
        token, _ = self.register_and_login("STUDENT")
        response = self.send_request(
            "CREATE_ROOM",
            {"name": "Denied room", "duration_seconds": 600, "rules": self.valid_rules()},
            token=token,
            request_id="create-student-room",
        )
        self.assertEqual(response["type"], "ERROR")
        self.assertEqual(response["error"]["code"], "FORBIDDEN")  # type: ignore[index]

    def test_04_invalid_duration_and_duplicate_rules_are_rejected(self) -> None:
        token, _ = self.register_and_login("ADMIN")
        duration_response = self.send_request(
            "CREATE_ROOM",
            {"name": "Too short", "duration_seconds": 59, "rules": self.valid_rules()},
            token=token,
            request_id="create-short-room",
        )
        duplicate_response = self.send_request(
            "CREATE_ROOM",
            {
                "name": "Duplicate rules",
                "duration_seconds": 600,
                "rules": [
                    {"topic": "TCP Socket", "difficulty": "easy", "quantity": 1},
                    {"topic": "TCP Socket", "difficulty": "easy", "quantity": 1},
                ],
            },
            token=token,
            request_id="create-duplicate-rule-room",
        )
        self.assertEqual(duration_response["error"]["code"], "BAD_REQUEST")  # type: ignore[index]
        self.assertEqual(duplicate_response["error"]["code"], "BAD_REQUEST")  # type: ignore[index]

    def test_05_insufficient_questions_rolls_back(self) -> None:
        token, _ = self.register_and_login("HOST")
        with contextlib.closing(sqlite3.connect(self.db_path)) as db:
            before = db.execute("SELECT COUNT(*) FROM exam_rooms").fetchone()[0]

        response = self.send_request(
            "CREATE_ROOM",
            {
                "name": "Too many questions",
                "duration_seconds": 600,
                "rules": [{"topic": "TCP Socket", "difficulty": "easy", "quantity": 5}],
            },
            token=token,
            request_id="create-insufficient-room",
        )
        self.assertEqual(response["type"], "ERROR")
        self.assertEqual(response["error"]["code"], "CONFLICT")  # type: ignore[index]

        with contextlib.closing(sqlite3.connect(self.db_path)) as db:
            after = db.execute("SELECT COUNT(*) FROM exam_rooms").fetchone()[0]
        self.assertEqual(after, before)

    def test_06_student_joins_waiting_room_once_and_running_room_rejects_join(self) -> None:
        host_token, _ = self.register_and_login("HOST")
        created = self.send_request(
            "CREATE_ROOM",
            {"name": "Joinable room", "duration_seconds": 600, "rules": self.valid_rules()},
            token=host_token,
            request_id="create-joinable-room",
        )
        room_id = created["data"]["room_id"]  # type: ignore[index]
        student_token, student_id = self.register_and_login("STUDENT")

        joined = self.send_request(
            "JOIN_ROOM", {"room_id": room_id}, token=student_token, request_id="join-once"
        )
        self.assertEqual(joined["type"], "OK")
        self.assertEqual(joined["data"]["status"], "WAITING")  # type: ignore[index]
        self.assertEqual(joined["data"]["participant_state"], "JOINED")  # type: ignore[index]
        self.assertEqual(joined["data"]["participant_count"], 1)  # type: ignore[index]

        duplicate = self.send_request(
            "JOIN_ROOM", {"room_id": room_id}, token=student_token, request_id="join-duplicate"
        )
        self.assertEqual(duplicate["type"], "ERROR")
        self.assertEqual(duplicate["error"]["code"], "CONFLICT")  # type: ignore[index]

        with contextlib.closing(sqlite3.connect(self.db_path)) as db:
            participant = db.execute(
                "SELECT state FROM room_participants WHERE room_id = ? AND user_id = ?",
                (room_id, student_id),
            ).fetchone()
            participant_count = db.execute(
                "SELECT COUNT(*) FROM room_participants WHERE room_id = ?", (room_id,)
            ).fetchone()[0]
            db.execute("UPDATE exam_rooms SET status = 'RUNNING' WHERE id = ?", (room_id,))
            db.commit()
        self.assertEqual(participant, ("JOINED",))
        self.assertEqual(participant_count, 1)

        another_student_token, _ = self.register_and_login("STUDENT")
        running = self.send_request(
            "JOIN_ROOM", {"room_id": room_id}, token=another_student_token,
            request_id="join-running-room",
        )
        self.assertEqual(running["type"], "ERROR")
        self.assertEqual(running["error"]["code"], "CONFLICT")  # type: ignore[index]

    def test_07_only_running_room_participant_receives_exam_snapshot(self) -> None:
        host_token, _ = self.register_and_login("HOST")
        created = self.send_request(
            "CREATE_ROOM",
            {"name": "Exam snapshot room", "duration_seconds": 600, "rules": self.valid_rules()},
            token=host_token,
            request_id="create-exam-snapshot-room",
        )
        room_id = created["data"]["room_id"]  # type: ignore[index]
        student_token, student_id = self.register_and_login("STUDENT")
        self.send_request("JOIN_ROOM", {"room_id": room_id}, token=student_token, request_id="join-exam-room")

        waiting = self.send_request(
            "GET_EXAM", {"room_id": room_id}, token=student_token, request_id="get-waiting-room"
        )
        self.assertEqual(waiting["type"], "ERROR")
        self.assertEqual(waiting["error"]["code"], "CONFLICT")  # type: ignore[index]
        self.send_request("START_ROOM", {"room_id": room_id}, token=host_token, request_id="start-exam-room")

        with contextlib.closing(sqlite3.connect(self.db_path)) as db:
            question_id, selected_option_id = db.execute(
                "SELECT question_id, option_id_snapshot FROM room_question_options "
                "WHERE room_id = ? ORDER BY question_id, position LIMIT 1",
                (room_id,),
            ).fetchone()
            db.execute(
                "INSERT INTO attempt_answers(room_id, user_id, question_id, selected_option_id) "
                "VALUES (?, ?, ?, ?)",
                (room_id, student_id, question_id, selected_option_id),
            )
            db.commit()

        exam = self.send_request(
            "GET_EXAM", {"room_id": room_id}, token=student_token, request_id="get-running-room"
        )
        self.assertEqual(exam["type"], "OK")
        questions = exam["data"]["questions"]  # type: ignore[index]
        self.assertEqual(len(questions), 3)
        self.assertEqual(len(questions[0]["options"]), 4)
        selected = next(question for question in questions if question["id"] == question_id)
        self.assertEqual(selected["selected_option_id"], selected_option_id)
        serialized = json.dumps(exam)
        self.assertNotIn("correct_option_snapshot", serialized)
        self.assertNotIn("correct_option_id", serialized)

        outsider_token, _ = self.register_and_login("STUDENT")
        forbidden = self.send_request(
            "GET_EXAM", {"room_id": room_id}, token=outsider_token, request_id="get-exam-outsider"
        )
        self.assertEqual(forbidden["type"], "ERROR")
        self.assertEqual(forbidden["error"]["code"], "FORBIDDEN")  # type: ignore[index]

    def test_08_save_answer_uses_snapshot_upsert_and_server_deadline(self) -> None:
        host_token, _ = self.register_and_login("HOST")
        created = self.send_request(
            "CREATE_ROOM",
            {"name": "Answer room", "duration_seconds": 600, "rules": self.valid_rules()},
            token=host_token,
            request_id="create-answer-room",
        )
        room_id = created["data"]["room_id"]  # type: ignore[index]
        student_token, student_id = self.register_and_login("STUDENT")
        self.send_request("JOIN_ROOM", {"room_id": room_id}, token=student_token, request_id="join-answer-room")
        self.send_request("START_ROOM", {"room_id": room_id}, token=host_token, request_id="start-answer-room")

        with contextlib.closing(sqlite3.connect(self.db_path)) as db:
            question_id = db.execute(
                "SELECT question_id FROM room_questions WHERE room_id = ? ORDER BY position LIMIT 1",
                (room_id,),
            ).fetchone()[0]
            option_ids = [
                row[0] for row in db.execute(
                    "SELECT option_id_snapshot FROM room_question_options "
                    "WHERE room_id = ? AND question_id = ? ORDER BY position",
                    (room_id, question_id),
                )
            ]

        first_save = self.send_request(
            "SAVE_ANSWER",
            {"room_id": room_id, "question_id": question_id, "option_id": option_ids[0]},
            token=student_token,
            request_id="save-first-answer",
        )
        changed_save = self.send_request(
            "SAVE_ANSWER",
            {"room_id": room_id, "question_id": question_id, "option_id": option_ids[1]},
            token=student_token,
            request_id="save-changed-answer",
        )
        invalid_option = self.send_request(
            "SAVE_ANSWER",
            {"room_id": room_id, "question_id": question_id, "option_id": 999999},
            token=student_token,
            request_id="save-invalid-option",
        )
        self.assertEqual(first_save["type"], "OK")
        self.assertEqual(changed_save["type"], "OK")
        self.assertEqual(invalid_option["type"], "ERROR")
        self.assertEqual(invalid_option["error"]["code"], "BAD_REQUEST")  # type: ignore[index]

        with contextlib.closing(sqlite3.connect(self.db_path)) as db:
            answer = db.execute(
                "SELECT selected_option_id FROM attempt_answers "
                "WHERE room_id = ? AND user_id = ? AND question_id = ?",
                (room_id, student_id, question_id),
            ).fetchone()
            answer_count = db.execute(
                "SELECT COUNT(*) FROM attempt_answers "
                "WHERE room_id = ? AND user_id = ? AND question_id = ?",
                (room_id, student_id, question_id),
            ).fetchone()[0]
            db.execute("UPDATE exam_rooms SET ended_at = datetime('now', '-1 second') WHERE id = ?", (room_id,))
            db.commit()
        self.assertEqual(answer, (option_ids[1],))
        self.assertEqual(answer_count, 1)

        after_deadline = self.send_request(
            "SAVE_ANSWER",
            {"room_id": room_id, "question_id": question_id, "option_id": option_ids[0]},
            token=student_token,
            request_id="save-after-deadline",
        )
        self.assertEqual(after_deadline["type"], "ERROR")
        self.assertEqual(after_deadline["error"]["code"], "CONFLICT")  # type: ignore[index]

    def test_09_submit_exam_grades_once_and_returns_idempotent_result(self) -> None:
        host_token, _ = self.register_and_login("HOST")
        sensitive_room_marker = "password-should-never-be-audit-logged"
        created = self.send_request(
            "CREATE_ROOM",
            {"name": sensitive_room_marker, "duration_seconds": 600, "rules": self.valid_rules()},
            token=host_token,
            request_id="create-submit-room",
        )
        room_id = created["data"]["room_id"]  # type: ignore[index]
        student_token, student_id = self.register_and_login("STUDENT")
        self.send_request("JOIN_ROOM", {"room_id": room_id}, token=student_token, request_id="join-submit-room")
        self.send_request("START_ROOM", {"room_id": room_id}, token=host_token, request_id="start-submit-room")

        with contextlib.closing(sqlite3.connect(self.db_path)) as db:
            question_id, correct_option_id = db.execute(
                "SELECT question_id, correct_option_snapshot FROM room_questions "
                "WHERE room_id = ? ORDER BY position LIMIT 1",
                (room_id,),
            ).fetchone()
        saved = self.send_request(
            "SAVE_ANSWER",
            {"room_id": room_id, "question_id": question_id, "option_id": correct_option_id},
            token=student_token,
            request_id="save-correct-for-submit",
        )
        self.assertEqual(saved["type"], "OK")

        first_submit = self.send_request(
            "SUBMIT_EXAM", {"room_id": room_id}, token=student_token, request_id="submit-once"
        )
        repeated_submit = self.send_request(
            "SUBMIT_EXAM", {"room_id": room_id}, token=student_token, request_id="submit-twice"
        )
        self.assertEqual(first_submit["type"], "OK")
        self.assertEqual(first_submit["data"]["state"], "SUBMITTED")  # type: ignore[index]
        self.assertEqual(first_submit["data"]["correct_count"], 1)  # type: ignore[index]
        self.assertEqual(first_submit["data"]["total"], 3)  # type: ignore[index]
        self.assertEqual(first_submit["data"]["score"], 3.33)  # type: ignore[index]
        self.assertEqual(repeated_submit["data"], first_submit["data"])  # type: ignore[index]

        with contextlib.closing(sqlite3.connect(self.db_path)) as db:
            participant = db.execute(
                "SELECT state, correct_count, score, submitted_at IS NOT NULL "
                "FROM room_participants WHERE room_id = ? AND user_id = ?",
                (room_id, student_id),
            ).fetchone()
            submit_logs = db.execute(
                "SELECT COUNT(*) FROM activity_logs WHERE actor_id = ? AND action = 'EXAM_SUBMITTED'",
                (student_id,),
            ).fetchone()[0]
            room_logs = db.execute(
                "SELECT action, detail_json FROM activity_logs "
                "WHERE entity_type = 'exam_room' AND entity_id = ?",
                (str(room_id),),
            ).fetchall()
        self.assertEqual(participant, ("SUBMITTED", 1, 10.0 / 3.0, 1))
        self.assertEqual(submit_logs, 1)
        self.assertTrue({"ROOM_CREATED", "ROOM_JOINED", "ROOM_STARTED", "ANSWER_SAVED", "EXAM_SUBMITTED"}
                        .issubset({row[0] for row in room_logs}))
        details = " ".join(row[1] for row in room_logs)
        self.assertNotIn(host_token, details)
        self.assertNotIn(student_token, details)
        self.assertNotIn(sensitive_room_marker, details)
        self.assertNotIn("selected_option_id", details)
        self.assertNotIn("correct_option_snapshot", details)

    def test_10_expiry_worker_auto_submits_and_ends_room(self) -> None:
        host_token, _ = self.register_and_login("HOST")
        created = self.send_request(
            "CREATE_ROOM",
            {"name": "Expiry worker room", "duration_seconds": 600, "rules": self.valid_rules()},
            token=host_token,
            request_id="create-expiry-worker-room",
        )
        room_id = created["data"]["room_id"]  # type: ignore[index]
        student_token, student_id = self.register_and_login("STUDENT")
        self.send_request("JOIN_ROOM", {"room_id": room_id}, token=student_token, request_id="join-expiry-worker-room")
        self.send_request("START_ROOM", {"room_id": room_id}, token=host_token, request_id="start-expiry-worker-room")
        with contextlib.closing(sqlite3.connect(self.db_path)) as db:
            question_id, correct_option_id = db.execute(
                "SELECT question_id, correct_option_snapshot FROM room_questions "
                "WHERE room_id = ? ORDER BY position LIMIT 1",
                (room_id,),
            ).fetchone()
        self.send_request(
            "SAVE_ANSWER",
            {"room_id": room_id, "question_id": question_id, "option_id": correct_option_id},
            token=student_token,
            request_id="save-before-expiry-worker",
        )
        with contextlib.closing(sqlite3.connect(self.db_path)) as db:
            db.execute("UPDATE exam_rooms SET ended_at = datetime('now', '-1 second') WHERE id = ?", (room_id,))
            db.commit()

        deadline = time.monotonic() + 3.0
        room = None
        participant = None
        while time.monotonic() < deadline:
            with contextlib.closing(sqlite3.connect(self.db_path)) as db:
                room = db.execute("SELECT status FROM exam_rooms WHERE id = ?", (room_id,)).fetchone()
                participant = db.execute(
                    "SELECT state, correct_count, score FROM room_participants WHERE room_id = ? AND user_id = ?",
                    (room_id, student_id),
                ).fetchone()
            if room == ("ENDED",) and participant is not None and participant[0] == "AUTO_SUBMITTED":
                break
            time.sleep(0.05)

        self.assertEqual(room, ("ENDED",))
        self.assertEqual(participant, ("AUTO_SUBMITTED", 1, 10.0 / 3.0))
        with contextlib.closing(sqlite3.connect(self.db_path)) as db:
            auto_logs = db.execute(
                "SELECT COUNT(*) FROM activity_logs WHERE actor_id = ? AND action = 'EXAM_AUTO_SUBMITTED'",
                (student_id,),
            ).fetchone()[0]
            end_logs = db.execute(
                "SELECT COUNT(*) FROM activity_logs "
                "WHERE actor_id IS NULL AND action = 'ROOM_ENDED' "
                "AND entity_type = 'exam_room' AND entity_id = ?",
                (str(room_id),),
            ).fetchone()[0]
        self.assertEqual(auto_logs, 1)
        self.assertEqual(end_logs, 1)

    def test_11_owner_starts_room_only_after_complete_question_snapshot(self) -> None:
        host_token, _ = self.register_and_login("HOST")
        created = self.send_request(
            "CREATE_ROOM",
            {"name": "Startable room", "duration_seconds": 600, "rules": self.valid_rules()},
            token=host_token,
            request_id="create-startable-room",
        )
        room_id = created["data"]["room_id"]  # type: ignore[index]
        student_token, student_id = self.register_and_login("STUDENT")
        self.send_request("JOIN_ROOM", {"room_id": room_id}, token=student_token, request_id="join-startable")

        started = self.send_request(
            "START_ROOM", {"room_id": room_id}, token=host_token, request_id="start-snapshot-room"
        )
        self.assertEqual(started["type"], "OK")
        self.assertEqual(started["data"]["status"], "RUNNING")  # type: ignore[index]
        self.assertEqual(started["data"]["question_count"], 3)  # type: ignore[index]
        self.assertEqual(started["data"]["participants_started"], 1)  # type: ignore[index]

        with contextlib.closing(sqlite3.connect(self.db_path)) as db:
            room = db.execute(
                "SELECT status, started_at IS NOT NULL, ended_at IS NOT NULL FROM exam_rooms WHERE id = ?",
                (room_id,),
            ).fetchone()
            question_count = db.execute(
                "SELECT COUNT(*) FROM room_questions WHERE room_id = ?", (room_id,)
            ).fetchone()[0]
            option_count = db.execute(
                "SELECT COUNT(*) FROM room_question_options WHERE room_id = ?", (room_id,)
            ).fetchone()[0]
            participant = db.execute(
                "SELECT state FROM room_participants WHERE room_id = ? AND user_id = ?",
                (room_id, student_id),
            ).fetchone()
        self.assertEqual(room, ("RUNNING", 1, 1))
        self.assertEqual(question_count, 3)
        self.assertEqual(option_count, 12)
        self.assertEqual(participant, ("IN_PROGRESS",))

        repeated = self.send_request(
            "START_ROOM", {"room_id": room_id}, token=host_token, request_id="start-twice"
        )
        self.assertEqual(repeated["type"], "ERROR")
        self.assertEqual(repeated["error"]["code"], "CONFLICT")  # type: ignore[index]

    def test_12_incomplete_snapshot_keeps_room_waiting(self) -> None:
        host_token, _ = self.register_and_login("HOST")
        created = self.send_request(
            "CREATE_ROOM",
            {
                "name": "Broken snapshot room",
                "duration_seconds": 600,
                "rules": [{"topic": "TCP Socket", "difficulty": "easy", "quantity": 2}],
            },
            token=host_token,
            request_id="create-broken-snapshot-room",
        )
        room_id = created["data"]["room_id"]  # type: ignore[index]
        with contextlib.closing(sqlite3.connect(self.db_path)) as db:
            db.execute(
                "DELETE FROM question_options WHERE question_id IN "
                "(SELECT id FROM questions WHERE topic = 'TCP Socket' AND difficulty = 'easy')"
            )
            db.commit()

        started = self.send_request(
            "START_ROOM", {"room_id": room_id}, token=host_token,
            request_id="start-broken-snapshot-room",
        )
        self.assertEqual(started["type"], "ERROR")
        self.assertEqual(started["error"]["code"], "CONFLICT")  # type: ignore[index]
        with contextlib.closing(sqlite3.connect(self.db_path)) as db:
            status = db.execute("SELECT status FROM exam_rooms WHERE id = ?", (room_id,)).fetchone()[0]
            snapshots = db.execute(
                "SELECT COUNT(*) FROM room_questions WHERE room_id = ?", (room_id,)
            ).fetchone()[0]
        self.assertEqual(status, "WAITING")
        self.assertEqual(snapshots, 0)

    def test_13_large_exam_loads_and_early_end_grades_saved_answers(self) -> None:
        topic = "Long questions"
        with contextlib.closing(sqlite3.connect(self.db_path)) as db:
            for index in range(26):
                question_id = db.execute(
                    "INSERT INTO questions(content, topic, difficulty) VALUES (?, ?, 'easy')",
                    (f"Question {index} " + "q" * 1100, topic),
                ).lastrowid
                for position, label in enumerate("ABCD", start=1):
                    option_id = db.execute(
                        "INSERT INTO question_options(question_id, label, content, position) VALUES (?, ?, ?, ?)",
                        (question_id, label, label + "o" * 379, position),
                    ).lastrowid
                    if position == 1:
                        db.execute("UPDATE questions SET correct_option_id = ? WHERE id = ?", (option_id, question_id))
            db.commit()

        host, _ = self.register_and_login("HOST")
        student, _ = self.register_and_login("STUDENT")
        created = self.send_request("CREATE_ROOM", {
            "name": "Large exam", "duration_seconds": 600,
            "rules": [{"topic": topic, "difficulty": "easy", "quantity": 26}],
        }, token=host)
        room = {"room_id": created["data"]["room_id"]}
        self.assertEqual(self.send_request("JOIN_ROOM", room, token=student)["type"], "OK")
        self.assertEqual(self.send_request("START_ROOM", room, token=host)["type"], "OK")

        exam = self.send_request("GET_EXAM", room, token=student)["data"]
        self.assertEqual(len(exam["questions"]), 26)
        self.assertGreater(exam["remaining_seconds"], 0)
        question = exam["questions"][0]
        self.assertEqual(self.send_request("SAVE_ANSWER", {
            **room, "question_id": question["id"], "option_id": question["options"][0]["id"],
        }, token=student)["type"], "OK")
        recovered = self.send_request("GET_MY_ACTIVE_EXAM", {}, token=student)["data"]["active_exam"]
        self.assertEqual(len(recovered["questions"]), 26)
        self.assertEqual(len(recovered["saved_answers"]), 1)

        self.assertEqual(self.send_request("END_ROOM", room, token=host)["type"], "OK")
        submitted = self.send_request("SUBMIT_EXAM", room, token=student)["data"]
        self.assertEqual(submitted["state"], "AUTO_SUBMITTED")
        self.assertEqual(submitted["correct_count"], 1)
        results = self.send_request("GET_ROOM_RESULTS", room, token=student)["data"]
        self.assertEqual(len(results["review"]), 26)


if __name__ == "__main__":
    unittest.main()
