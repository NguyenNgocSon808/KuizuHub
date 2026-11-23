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


def question_payload(content: str = "Which call creates a TCP socket?") -> dict[str, object]:
    return {
        "content": content,
        "topic": "TCP Socket",
        "difficulty": "easy",
        "options": ["socket()", "bind()", "listen()", "accept()"],
        "correct_option_index": 0,
        "explanation": "socket() creates the endpoint before bind/listen.",
    }


class PhaseOneQuestionBankTests(unittest.TestCase):
    server: subprocess.Popen[str]
    port: int
    temp_dir: tempfile.TemporaryDirectory[str]
    db_path: Path
    admin_token: str
    student_token: str
    created_question_id: int

    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.temp_dir.name) / "legacy_phase1.db"

        # Simulate an existing Phase 1 database created before migration 002.
        with contextlib.closing(sqlite3.connect(cls.db_path)) as db:
            db.executescript(
                (SERVER_DIR / "migrations" / "001_initial.sql").read_text(encoding="utf-8")
            )
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
        raise RuntimeError("Question-bank server did not start")

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
        payload: dict[str, object] | None = None,
        *,
        token: str | None = None,
        request_id: str = "question-request",
    ) -> dict[str, object]:
        envelope: dict[str, object] = {
            "type": request_type,
            "request_id": request_id,
            "payload": payload or {},
        }
        if token is not None:
            envelope["token"] = token
        with socket.create_connection(("127.0.0.1", self.port), timeout=3) as connection:
            connection.sendall(json.dumps(envelope, separators=(",", ":")).encode("utf-8") + b"\n")
            return receive_json_line(connection)

    def test_01_migrates_existing_database_and_authenticates_roles(self) -> None:
        with contextlib.closing(sqlite3.connect(self.db_path)) as db:
            columns = {row[1] for row in db.execute("PRAGMA table_info(questions)")}
            migrations = {row[0] for row in db.execute("SELECT name FROM schema_migrations")}
        self.assertIn("explanation", columns)
        self.assertEqual(
            {
                "001_initial",
                "002_question_explanation",
                "003_practice_sessions",
                "004_room_question_options",
                "005_profile_analytics",
            },
            migrations,
        )

        admin_registered = self.send_request(
            "REGISTER",
            {"username": "question_admin", "password": "QuestionAdmin123", "role": "ADMIN"},
            request_id="register-admin",
        )
        self.assertEqual(admin_registered["type"], "OK")
        student_registered = self.send_request(
            "REGISTER",
            {"username": "question_student", "password": "QuestionStudent123", "role": "STUDENT"},
            request_id="register-student",
        )
        self.assertEqual(student_registered["type"], "OK")

        admin_login = self.send_request(
            "LOGIN",
            {"username": "question_admin", "password": "QuestionAdmin123"},
            request_id="login-admin",
        )
        student_login = self.send_request(
            "LOGIN",
            {"username": "question_student", "password": "QuestionStudent123"},
            request_id="login-student",
        )
        self.__class__.admin_token = admin_login["data"]["token"]  # type: ignore[index,assignment]
        self.__class__.student_token = student_login["data"]["token"]  # type: ignore[index,assignment]

    def test_02_non_admin_cannot_read_or_modify_questions(self) -> None:
        listing = self.send_request(
            "LIST_QUESTIONS", {}, token=self.student_token, request_id="student-list"
        )
        self.assertEqual(listing["type"], "ERROR")
        self.assertEqual(listing["error"]["code"], "FORBIDDEN")  # type: ignore[index]

        creation = self.send_request(
            "CREATE_QUESTION", question_payload(), token=self.student_token, request_id="student-create"
        )
        self.assertEqual(creation["type"], "ERROR")
        self.assertEqual(creation["error"]["code"], "FORBIDDEN")  # type: ignore[index]

    def test_03_admin_creates_lists_and_updates_question(self) -> None:
        created = self.send_request(
            "CREATE_QUESTION", question_payload(), token=self.admin_token, request_id="create-question"
        )
        self.assertEqual(created["type"], "OK")
        self.assertEqual(created["request_id"], "create-question")
        question_id = created["data"]["question_id"]  # type: ignore[index]
        self.assertIsInstance(question_id, int)
        self.__class__.created_question_id = question_id  # type: ignore[assignment]

        listed = self.send_request(
            "LIST_QUESTIONS",
            {"query": "creates a TCP", "include_inactive": 1, "limit": 20, "offset": 0},
            token=self.admin_token,
            request_id="list-created",
        )
        self.assertEqual(listed["type"], "OK")
        questions = listed["data"]["questions"]  # type: ignore[index]
        self.assertEqual(len(questions), 1)
        self.assertEqual(questions[0]["correct_option_index"], 0)
        self.assertEqual(questions[0]["explanation"], question_payload()["explanation"])
        self.assertEqual(len(questions[0]["options"]), 4)

        replacement = question_payload("Which operation attaches an address to a socket?")
        replacement["correct_option_index"] = 1
        replacement["explanation"] = "bind() attaches the local address."
        updated = self.send_request(
            "UPDATE_QUESTION",
            {"id": self.created_question_id, "question": replacement, "is_active": 0},
            token=self.admin_token,
            request_id="update-question",
        )
        self.assertEqual(updated["type"], "OK")

        active_only = self.send_request(
            "LIST_QUESTIONS",
            {"query": "attaches an address", "include_inactive": 0},
            token=self.admin_token,
            request_id="list-active-only",
        )
        self.assertEqual(active_only["data"]["questions"], [])  # type: ignore[index]
        including_inactive = self.send_request(
            "LIST_QUESTIONS",
            {"query": "attaches an address", "include_inactive": 1},
            token=self.admin_token,
            request_id="list-inactive",
        )
        returned = including_inactive["data"]["questions"][0]  # type: ignore[index]
        self.assertEqual(returned["id"], self.created_question_id)
        self.assertEqual(returned["correct_option_index"], 1)
        self.assertEqual(returned["is_active"], 0)

    def test_04_import_is_atomic_and_records_audit_event(self) -> None:
        valid = question_payload("Imported valid question")
        invalid = question_payload("Imported invalid question")
        invalid["options"] = ["A", "B", "C"]
        rejected = self.send_request(
            "IMPORT_QUESTIONS",
            {"questions": [valid, invalid]},
            token=self.admin_token,
            request_id="import-invalid",
        )
        self.assertEqual(rejected["type"], "ERROR")
        self.assertEqual(rejected["error"]["code"], "BAD_REQUEST")  # type: ignore[index]

        with contextlib.closing(sqlite3.connect(self.db_path)) as db:
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM questions WHERE content = 'Imported valid question'"
                ).fetchone()[0],
                0,
            )

        valid_second = question_payload("Imported second valid question")
        imported = self.send_request(
            "IMPORT_QUESTIONS",
            {"questions": [valid, valid_second]},
            token=self.admin_token,
            request_id="import-valid",
        )
        self.assertEqual(imported["type"], "OK")
        self.assertEqual(imported["data"]["imported"], 2)  # type: ignore[index]

        with contextlib.closing(sqlite3.connect(self.db_path)) as db:
            actions = {
                row[0] for row in db.execute("SELECT action FROM activity_logs").fetchall()
            }
        self.assertIn("QUESTION_CREATED", actions)
        self.assertIn("QUESTION_UPDATED", actions)
        self.assertIn("QUESTIONS_IMPORTED", actions)


if __name__ == "__main__":
    unittest.main()
