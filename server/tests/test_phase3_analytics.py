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


class PhaseThreeAnalyticsTests(unittest.TestCase):
    server: subprocess.Popen[str]
    temp_dir: tempfile.TemporaryDirectory[str]
    db_path: Path
    port: int
    counter = 0

    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.temp_dir.name) / "phase3.db"
        with contextlib.closing(sqlite3.connect(cls.db_path)) as db:
            db.executescript((SERVER_DIR / "migrations" / "001_initial.sql").read_text(encoding="utf-8"))
            for index in range(4):
                question_id = db.execute(
                    "INSERT INTO questions(content, topic, difficulty, is_active) VALUES (?, 'TCP Socket', 'easy', 1)",
                    (f"Phase 3 question {index}",),
                ).lastrowid
                option_ids = []
                for position, label in enumerate("ABCD", start=1):
                    option_ids.append(
                        db.execute(
                            "INSERT INTO question_options(question_id, label, content, position) VALUES (?, ?, ?, ?)",
                            (question_id, label, f"Option {label}", position),
                        ).lastrowid
                    )
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
                    return
            except OSError:
                time.sleep(0.03)
        cls.tearDownClass()
        raise RuntimeError("Phase 3 server did not start")

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

    def send(self, request_type: str, payload: dict[str, object], *, token: str | None = None,
             request_id: str = "phase3") -> dict[str, object]:
        envelope: dict[str, object] = {"type": request_type, "request_id": request_id, "payload": payload}
        if token is not None:
            envelope["token"] = token
        with socket.create_connection(("127.0.0.1", self.port), timeout=3) as connection:
            connection.sendall(json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n")
            return receive_json_line(connection)

    def register_login(self, role: str) -> tuple[str, int]:
        type(self).counter += 1
        username = f"phase3_{role.lower()}_{self.counter}"
        password = "PhaseThreePass123"
        registered = self.send(
            "REGISTER", {"username": username, "password": password, "role": role},
            request_id=f"register-{username}",
        )
        self.assertEqual("OK", registered["type"])
        logged_in = self.send("LOGIN", {"username": username, "password": password}, request_id=f"login-{username}")
        self.assertEqual("OK", logged_in["type"])
        return logged_in["data"]["token"], logged_in["data"]["user"]["id"]  # type: ignore[index,return-value]

    def test_01_profile_update_is_migrated_and_does_not_expose_password(self) -> None:
        token, _user_id = self.register_login("STUDENT")
        before = self.send("GET_MY_PROFILE", {}, token=token, request_id="profile-before")
        self.assertEqual("OK", before["type"])
        self.assertIn("display_name", before["data"]["user"])  # type: ignore[index]
        updated = self.send(
            "UPDATE_MY_PROFILE",
            {"display_name": "Người học Phase 3", "current_password": "PhaseThreePass123", "new_password": "NewPhaseThree123"},
            token=token,
            request_id="profile-update",
        )
        self.assertEqual("OK", updated["type"], updated)
        self.assertEqual("Người học Phase 3", updated["data"]["user"]["display_name"])  # type: ignore[index]
        serialized = json.dumps(updated)
        self.assertNotIn("password", serialized.lower())
        old_login = self.send(
            "LOGIN", {"username": before["data"]["user"]["username"], "password": "PhaseThreePass123"},  # type: ignore[index]
            request_id="old-password",
        )
        self.assertEqual("ERROR", old_login["type"])
        new_login = self.send(
            "LOGIN", {"username": before["data"]["user"]["username"], "password": "NewPhaseThree123"},  # type: ignore[index]
            request_id="new-password",
        )
        self.assertEqual("OK", new_login["type"])

    def test_02_practice_appears_in_history_and_stats(self) -> None:
        token, _user_id = self.register_login("STUDENT")
        started = self.send(
            "START_PRACTICE",
            {"topic": "TCP Socket", "difficulty": "easy", "question_count": 2, "duration_seconds": 600},
            token=token,
            request_id="start-practice-history",
        )
        self.assertEqual("OK", started["type"])
        attempt_id = started["data"]["attempt_id"]  # type: ignore[index]
        submitted = self.send("SUBMIT_PRACTICE", {"attempt_id": attempt_id}, token=token, request_id="submit-practice-history")
        self.assertEqual("OK", submitted["type"])
        history = self.send("GET_MY_HISTORY", {"limit": 20, "offset": 0}, token=token, request_id="history")
        self.assertEqual("OK", history["type"])
        attempts = history["data"]["attempts"]  # type: ignore[index]
        self.assertTrue(any(item["kind"] == "PRACTICE" and item["attempt_id"] == attempt_id for item in attempts))
        stats = self.send("GET_MY_STATS", {}, token=token, request_id="stats")
        self.assertEqual("OK", stats["type"])
        self.assertEqual(1, stats["data"]["attempts"])  # type: ignore[index]
        self.assertTrue(any(bucket["topic"] == "TCP Socket" for bucket in stats["data"]["by_topic"]))  # type: ignore[index]

    def test_03_room_results_are_private_but_leaderboard_is_public_after_end(self) -> None:
        host_token, _host_id = self.register_login("HOST")
        student_token, student_id = self.register_login("STUDENT")
        created = self.send(
            "CREATE_ROOM",
            {"name": "Phase 3 result room", "duration_seconds": 600,
             "rules": [{"topic": "TCP Socket", "difficulty": "easy", "quantity": 2}]},
            token=host_token,
            request_id="create-result-room",
        )
        room_id = created["data"]["room_id"]  # type: ignore[index]
        self.assertEqual("OK", self.send("JOIN_ROOM", {"room_id": room_id}, token=student_token)["type"])
        lobby = self.send("GET_ROOM_LOBBY", {"room_id": room_id}, token=student_token, request_id="waiting-lobby")
        self.assertEqual("OK", lobby["type"])
        self.assertEqual(student_id, lobby["data"]["participants"][0]["user_id"])  # type: ignore[index]
        self.assertEqual("OK", self.send("START_ROOM", {"room_id": room_id}, token=host_token)["type"])
        with contextlib.closing(sqlite3.connect(self.db_path)) as db:
            question_id, correct_option_id = db.execute(
                "SELECT question_id, correct_option_snapshot FROM room_questions WHERE room_id = ? ORDER BY position LIMIT 1",
                (room_id,),
            ).fetchone()
        self.assertEqual(
            "OK",
            self.send(
                "SAVE_ANSWER", {"room_id": room_id, "question_id": question_id, "option_id": correct_option_id},
                token=student_token,
            )["type"],
        )
        self.assertEqual("OK", self.send("SUBMIT_EXAM", {"room_id": room_id}, token=student_token)["type"])
        premature = self.send("GET_ROOM_RESULTS", {"room_id": room_id}, token=student_token, request_id="premature-results")
        self.assertEqual("ERROR", premature["type"])
        self.assertEqual("CONFLICT", premature["error"]["code"])  # type: ignore[index]
        self.assertEqual("OK", self.send("END_ROOM", {"room_id": room_id}, token=host_token)["type"])
        owner_results = self.send("GET_ROOM_RESULTS", {"room_id": room_id}, token=host_token, request_id="owner-results")
        self.assertEqual("OK", owner_results["type"])
        self.assertTrue(any(result["user_id"] == student_id for result in owner_results["data"]["results"]))  # type: ignore[index]
        student_results = self.send("GET_ROOM_RESULTS", {"room_id": room_id}, token=student_token, request_id="student-results")
        self.assertEqual("OK", student_results["type"])
        self.assertEqual(1, len(student_results["data"]["results"]))  # type: ignore[index]
        self.assertTrue(student_results["data"]["review"])  # type: ignore[index]
        outsider_token, _outsider_id = self.register_login("STUDENT")
        forbidden = self.send("GET_ROOM_RESULTS", {"room_id": room_id}, token=outsider_token, request_id="outsider-results")
        self.assertEqual("ERROR", forbidden["type"])
        self.assertEqual("FORBIDDEN", forbidden["error"]["code"])  # type: ignore[index]
        leaderboard = self.send("GET_LEADERBOARD", {"room_id": room_id}, token=outsider_token, request_id="leaderboard")
        self.assertEqual("OK", leaderboard["type"])
        self.assertEqual(student_id, leaderboard["data"]["entries"][0]["user_id"])  # type: ignore[index]


if __name__ == "__main__":
    unittest.main()
