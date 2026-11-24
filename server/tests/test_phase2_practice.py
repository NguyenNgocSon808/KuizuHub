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
            raise AssertionError("Server closed connection before response")
        received.extend(chunk)
    return json.loads(received.split(b"\n", 1)[0].decode("utf-8"))


class PracticeFlowTests(unittest.TestCase):
    server: subprocess.Popen[str]
    port: int
    temp_dir: tempfile.TemporaryDirectory[str]
    db_path: Path
    token: str
    user_id: int

    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.temp_dir.name) / "practice.db"
        with contextlib.closing(sqlite3.connect(cls.db_path)) as db:
            db.executescript((SERVER_DIR / "migrations" / "001_initial.sql").read_text(encoding="utf-8"))
            for number in range(4):
                question_id = db.execute(
                    "INSERT INTO questions(content, topic, difficulty, is_active) VALUES (?, 'TCP Socket', 'easy', 1)",
                    (f"Practice question {number}",),
                ).lastrowid
                option_ids: list[int] = []
                for position, label in enumerate("ABCD", start=1):
                    option_ids.append(db.execute(
                        "INSERT INTO question_options(question_id, label, content, position) VALUES (?, ?, ?, ?)",
                        (question_id, label, f"Option {label} for {number}", position),
                    ).lastrowid)
                db.execute("UPDATE questions SET correct_option_id = ? WHERE id = ?", (option_ids[0], question_id))
            db.commit()

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            cls.port = int(probe.getsockname()[1])
        environment = os.environ.copy()
        environment["KUIZUHUB_DB_PATH"] = str(cls.db_path)
        cls.server = subprocess.Popen(
            [str(SERVER_BINARY), str(cls.port)], cwd=SERVER_DIR, text=True,
            env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", cls.port), timeout=0.1):
                    break
            except OSError:
                time.sleep(0.03)
        else:
            cls.tearDownClass()
            raise RuntimeError("Practice server did not start")

        cls.send("REGISTER", {"username": "practice_user", "password": "PracticePass123"})
        login = cls.send("LOGIN", {"username": "practice_user", "password": "PracticePass123"})
        cls.token = login["data"]["token"]  # type: ignore[index,assignment]
        cls.user_id = login["data"]["user"]["id"]  # type: ignore[index,assignment]

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "server") and cls.server.poll() is None:
            cls.server.terminate()
            cls.server.wait(timeout=3)
        if hasattr(cls, "server") and cls.server.stderr is not None:
            cls.server.stderr.close()
        if hasattr(cls, "temp_dir"):
            cls.temp_dir.cleanup()

    @classmethod
    def send(cls, request_type: str, payload: dict[str, object], *, token: str | None = None) -> dict[str, object]:
        request: dict[str, object] = {"type": request_type, "request_id": f"{request_type}-test", "payload": payload}
        if token is not None:
            request["token"] = token
        with socket.create_connection(("127.0.0.1", cls.port), timeout=3) as connection:
            connection.sendall(json.dumps(request, separators=(",", ":")).encode("utf-8") + b"\n")
            return receive_json_line(connection)

    def start(self, count: int = 2) -> dict[str, object]:
        return self.send("START_PRACTICE", {
            "topic": "TCP Socket", "difficulty": "easy", "question_count": count,
            "duration_seconds": 600,
        }, token=self.token)

    def test_01_migrates_practice_schema_and_starts_snapshot(self) -> None:
        with contextlib.closing(sqlite3.connect(self.db_path)) as db:
            migrations = {row[0] for row in db.execute("SELECT name FROM schema_migrations")}
        self.assertIn("003_practice_sessions", migrations)

        started = self.start()
        self.assertEqual(started["type"], "OK")
        data = started["data"]  # type: ignore[index]
        self.assertIsInstance(data["attempt_id"], int)
        self.assertEqual(len(data["questions"]), 2)
        self.assertNotIn("correct_option_position", data["questions"][0])
        self.assertEqual(len(data["questions"][0]["options"]), 4)

    def test_02_change_answer_submit_and_idempotency(self) -> None:
        started = self.start()
        data = started["data"]  # type: ignore[index]
        attempt_id = data["attempt_id"]
        questions = data["questions"]
        for question in questions:
            wrong = self.send("SAVE_PRACTICE_ANSWER", {
                "attempt_id": attempt_id, "question_id": question["id"], "selected_option_position": 2,
            }, token=self.token)
            self.assertEqual(wrong["type"], "OK")
            changed = self.send("SAVE_PRACTICE_ANSWER", {
                "attempt_id": attempt_id, "question_id": question["id"], "selected_option_position": 1,
            }, token=self.token)
            self.assertEqual(changed["type"], "OK")
        submitted = self.send("SUBMIT_PRACTICE", {"attempt_id": attempt_id}, token=self.token)
        repeated = self.send("SUBMIT_PRACTICE", {"attempt_id": attempt_id}, token=self.token)
        self.assertEqual(submitted["data"]["correct_count"], 2)  # type: ignore[index]
        self.assertEqual(submitted["data"]["score"], 10.0)  # type: ignore[index]
        self.assertEqual(repeated["data"], submitted["data"])  # type: ignore[index]
        with contextlib.closing(sqlite3.connect(self.db_path)) as db:
            count = db.execute("SELECT COUNT(*) FROM practice_attempts WHERE user_id = ?", (self.user_id,)).fetchone()[0]
        self.assertEqual(count, 1)

    def test_03_rejects_unavailable_question_count(self) -> None:
        rejected = self.start(count=5)
        self.assertEqual(rejected["type"], "ERROR")
        self.assertEqual(rejected["error"]["code"], "CONFLICT")  # type: ignore[index]

    def test_04_expired_practice_is_graded_without_a_client_submission(self) -> None:
        attempt = self.start(count=1)["data"]
        attempt_id = attempt["attempt_id"]
        saved = self.send("SAVE_PRACTICE_ANSWER", {
            "attempt_id": attempt_id, "question_id": attempt["questions"][0]["id"],
            "selected_option_position": 1,
        }, token=self.token)
        self.assertEqual(saved["type"], "OK")
        with contextlib.closing(sqlite3.connect(self.db_path)) as db:
            db.execute("UPDATE practice_sessions SET ended_at = datetime('now', '-1 second') WHERE id = ?", (attempt_id,))
            db.commit()
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline:
                row = db.execute("SELECT state, score FROM practice_sessions WHERE id = ?", (attempt_id,)).fetchone()
                if row == ("AUTO_SUBMITTED", 10.0):
                    break
                time.sleep(0.05)
            else:
                self.fail("Server did not grade the expired practice")
            history_before = db.execute("SELECT COUNT(*) FROM practice_attempts").fetchone()[0]
            repeated = self.send("SUBMIT_PRACTICE", {"attempt_id": attempt_id}, token=self.token)["data"]
            self.assertEqual((repeated["state"], repeated["score"]), row)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM practice_attempts").fetchone()[0], history_before)


if __name__ == "__main__":
    unittest.main()
