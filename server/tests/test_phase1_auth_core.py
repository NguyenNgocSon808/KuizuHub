from __future__ import annotations

import contextlib
import hashlib
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


class PhaseOneAuthCoreTests(unittest.TestCase):
    server: subprocess.Popen[str]
    port: int
    temp_dir: tempfile.TemporaryDirectory[str]
    db_path: Path

    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.temp_dir.name) / "test_phase1.db"

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
        raise RuntimeError("Phase 1 server did not start")

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

    def connect(self) -> socket.socket:
        connection = socket.create_connection(("127.0.0.1", self.port), timeout=3)
        self.addCleanup(connection.close)
        return connection

    def send_request(
        self,
        req_type: str,
        payload: dict[str, object] | None = None,
        *,
        request_id: str = "req-1",
        token: str | None = None,
    ) -> dict[str, object]:
        conn = self.connect()
        envelope: dict[str, object] = {
            "type": req_type,
            "request_id": request_id,
            "payload": payload or {},
        }
        if token is not None:
            envelope["token"] = token
        raw = (json.dumps(envelope, separators=(",", ":")) + "\n").encode("utf-8")
        conn.sendall(raw)
        return receive_json_line(conn)

    def test_01_register_success_and_duplicate_conflict(self) -> None:
        res = self.send_request(
            "REGISTER",
            {"username": "host_son", "password": "StrongPassword123", "role": "HOST"},
            request_id="reg-host",
        )
        self.assertEqual(res["type"], "OK")
        self.assertEqual(res["request_id"], "reg-host")
        user = res["data"]["user"]  # type: ignore[index]
        self.assertEqual(user["username"], "host_son")
        self.assertEqual(user["role"], "HOST")

        dup = self.send_request(
            "REGISTER",
            {"username": "host_son", "password": "AnotherPassword123"},
            request_id="reg-dup",
        )
        self.assertEqual(dup["type"], "ERROR")
        self.assertEqual(dup["error"]["code"], "CONFLICT")  # type: ignore[index]

    def test_02_register_validation_errors(self) -> None:
        short_user = self.send_request(
            "REGISTER",
            {"username": "ab", "password": "StrongPassword123"},
            request_id="reg-short-user",
        )
        self.assertEqual(short_user["type"], "ERROR")
        self.assertEqual(short_user["error"]["code"], "BAD_REQUEST")  # type: ignore[index]

        short_pass = self.send_request(
            "REGISTER",
            {"username": "valid_user", "password": "123"},
            request_id="reg-short-pass",
        )
        self.assertEqual(short_pass["type"], "ERROR")
        self.assertEqual(short_pass["error"]["code"], "BAD_REQUEST")  # type: ignore[index]

    def test_03_login_pbkdf2_token_hash_and_wrong_password(self) -> None:
        self.send_request(
            "REGISTER",
            {"username": "student_bao", "password": "SecretPass999"},
            request_id="reg-student",
        )

        wrong = self.send_request(
            "LOGIN",
            {"username": "student_bao", "password": "WrongPassword999"},
            request_id="login-wrong",
        )
        self.assertEqual(wrong["type"], "ERROR")
        self.assertEqual(wrong["error"]["code"], "UNAUTHORIZED")  # type: ignore[index]

        ok = self.send_request(
            "LOGIN",
            {"username": "student_bao", "password": "SecretPass999"},
            request_id="login-ok",
        )
        self.assertEqual(ok["type"], "OK")
        token = ok["data"]["token"]  # type: ignore[index]
        self.assertTrue(isinstance(token, str) and len(token) == 64)

        # Verify DB stores PBKDF2 password hash and SHA-256 token_hash (never raw token)
        expected_token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with contextlib.closing(sqlite3.connect(self.db_path)) as db:
            pw_hash = db.execute(
                "SELECT password_hash FROM users WHERE username = 'student_bao'"
            ).fetchone()[0]
            self.assertTrue(pw_hash.startswith("pbkdf2_sha256$"))
            self.assertNotIn("SecretPass999", pw_hash)

            session_row = db.execute(
                "SELECT token_hash FROM sessions WHERE token_hash = ?",
                (expected_token_hash,),
            ).fetchone()
            self.assertIsNotNone(session_row)
            raw_row = db.execute(
                "SELECT token_hash FROM sessions WHERE token_hash = ?",
                (token,),
            ).fetchone()
            self.assertIsNone(raw_row)

    def test_04_protected_requests_logout_and_expired_session(self) -> None:
        no_tok = self.send_request("LIST_ROOMS", {}, request_id="rooms-no-tok")
        self.assertEqual(no_tok["type"], "ERROR")
        self.assertEqual(no_tok["error"]["code"], "UNAUTHORIZED")  # type: ignore[index]

        login_res = self.send_request(
            "LOGIN",
            {"username": "student_bao", "password": "SecretPass999"},
            request_id="login-session",
        )
        token = login_res["data"]["token"]  # type: ignore[index]

        rooms_ok = self.send_request("LIST_ROOMS", {}, request_id="rooms-ok", token=token)
        self.assertEqual(rooms_ok["type"], "OK")
        self.assertIn("rooms", rooms_ok["data"])  # type: ignore[arg-type]

        prof_ok = self.send_request("GET_MY_PROFILE", {}, request_id="prof-ok", token=token)
        self.assertEqual(prof_ok["type"], "OK")
        self.assertEqual(prof_ok["data"]["user"]["username"], "student_bao")  # type: ignore[index]

        # Logout revokes session
        logout_res = self.send_request("LOGOUT", {}, request_id="logout-1", token=token)
        self.assertEqual(logout_res["type"], "OK")

        after_logout = self.send_request("LIST_ROOMS", {}, request_id="rooms-revoked", token=token)
        self.assertEqual(after_logout["type"], "ERROR")
        self.assertEqual(after_logout["error"]["code"], "UNAUTHORIZED")  # type: ignore[index]

        # Test expired session
        login_exp = self.send_request(
            "LOGIN",
            {"username": "student_bao", "password": "SecretPass999"},
            request_id="login-exp",
        )
        exp_token = login_exp["data"]["token"]  # type: ignore[index]
        exp_hash = hashlib.sha256(exp_token.encode("utf-8")).hexdigest()
        with contextlib.closing(sqlite3.connect(self.db_path)) as db:
            db.execute(
                "UPDATE sessions SET expires_at = datetime('now', '-1 hour') WHERE token_hash = ?",
                (exp_hash,),
            )
            db.commit()

        expired_res = self.send_request("GET_MY_PROFILE", {}, request_id="prof-exp", token=exp_token)
        self.assertEqual(expired_res["type"], "ERROR")
        self.assertEqual(expired_res["error"]["code"], "UNAUTHORIZED")  # type: ignore[index]

    def test_05_room_owner_access_control(self) -> None:
        host_login = self.send_request(
            "LOGIN",
            {"username": "host_son", "password": "StrongPassword123"},
            request_id="host-login",
        )
        host_token = host_login["data"]["token"]  # type: ignore[index]
        host_id = host_login["data"]["user"]["id"]  # type: ignore[index]

        student_login = self.send_request(
            "LOGIN",
            {"username": "student_bao", "password": "SecretPass999"},
            request_id="student-login",
        )
        student_token = student_login["data"]["token"]  # type: ignore[index]

        with contextlib.closing(sqlite3.connect(self.db_path)) as db:
            cur = db.execute(
                "INSERT INTO exam_rooms(owner_id, name, status, duration_seconds) "
                "VALUES (?, 'Network Room 1', 'WAITING', 600)",
                (host_id,),
            )
            room_id = cur.lastrowid
            db.commit()

        # Student attempts START_ROOM -> FORBIDDEN
        forbidden = self.send_request(
            "START_ROOM",
            {"room_id": room_id},
            request_id="start-forbidden",
            token=student_token,
        )
        self.assertEqual(forbidden["type"], "ERROR")
        self.assertEqual(forbidden["error"]["code"], "FORBIDDEN")  # type: ignore[index]

        # Owner calls START_ROOM -> OK
        allowed = self.send_request(
            "START_ROOM",
            {"room_id": room_id},
            request_id="start-allowed",
            token=host_token,
        )
        self.assertEqual(allowed["type"], "OK")
        self.assertEqual(allowed["data"]["status"], "RUNNING")  # type: ignore[index]

    def test_06_split_three_chunks_and_oversized_payload_recovery(self) -> None:
        # 1 JSON split across 3 sends
        conn = self.connect()
        conn.sendall(b'{"type":"PI')
        time.sleep(0.02)
        conn.sendall(b'NG","request_id":"three-part')
        time.sleep(0.02)
        conn.sendall(b's","payload":{}}\n')
        res = receive_json_line(conn)
        self.assertEqual(res["type"], "OK")
        self.assertEqual(res["request_id"], "three-parts")

        # Payload > 64 KB returns BAD_REQUEST, and another client still works afterwards
        big_conn = self.connect()
        big_line = b'{"type":"PING","request_id":"huge","payload":{"pad":"' + (b"x" * 66000) + b'"}}\n'
        big_conn.sendall(big_line)
        big_res = receive_json_line(big_conn)
        self.assertEqual(big_res["type"], "ERROR")
        self.assertEqual(big_res["error"]["code"], "BAD_REQUEST")  # type: ignore[index]

        after_big = self.send_request("PING", {}, request_id="still-alive")
        self.assertEqual(after_big["type"], "OK")
        self.assertEqual(after_big["data"]["message"], "pong")  # type: ignore[index]

    def test_07_activity_logs_recorded_without_sensitive_secrets(self) -> None:
        with contextlib.closing(sqlite3.connect(self.db_path)) as db:
            actions = {
                row[0]
                for row in db.execute("SELECT DISTINCT action FROM activity_logs").fetchall()
            }
            self.assertIn("REGISTER_SUCCESS", actions)
            self.assertIn("LOGIN_SUCCESS", actions)
            self.assertIn("LOGIN_FAILED", actions)
            self.assertIn("ACCESS_DENIED", actions)
            self.assertIn("CONNECTION_CLOSED", actions)

            all_details = " ".join(
                row[0] for row in db.execute("SELECT detail_json FROM activity_logs").fetchall()
            )
            self.assertNotIn("StrongPassword123", all_details)
            self.assertNotIn("SecretPass999", all_details)

        log_file = SERVER_DIR / "logs" / "server.log"
        self.assertTrue(log_file.exists())
        log_text = log_file.read_text(encoding="utf-8")
        self.assertIn("action=LOGIN_SUCCESS", log_text)
        self.assertIn("action=ACCESS_DENIED", log_text)
        self.assertIn("action=CONNECTION_CLOSED", log_text)
        self.assertNotIn("StrongPassword123", log_text)
        self.assertNotIn("SecretPass999", log_text)


if __name__ == "__main__":
    unittest.main()
