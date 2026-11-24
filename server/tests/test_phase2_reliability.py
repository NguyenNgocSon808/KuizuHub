from __future__ import annotations

import concurrent.futures
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
SERVER_BINARY = SERVER_DIR / "build" / ("kuizuhub-server.exe" if os.name == "nt" else "kuizuhub-server")


def receive_json_line(connection: socket.socket) -> dict[str, object]:
    received = bytearray()
    while b"\n" not in received:
        chunk = connection.recv(4096)
        if not chunk:
            raise AssertionError("Server closed the connection before its response")
        received.extend(chunk)
    return json.loads(received.split(b"\n", 1)[0].decode("utf-8"))


class PhaseTwoReliabilityTests(unittest.TestCase):
    server: subprocess.Popen[str]
    port: int
    temp_dir: tempfile.TemporaryDirectory[str]
    db_path: Path

    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.temp_dir.name) / "test_phase2_reliability.db"

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
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", cls.port), timeout=0.1):
                    return
            except OSError:
                time.sleep(0.03)
        cls.tearDownClass()
        raise RuntimeError("Phase 2 server did not start")

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

    def connect(self, timeout: float = 5.0) -> socket.socket:
        connection = socket.create_connection(("127.0.0.1", self.port), timeout=timeout)
        self.addCleanup(connection.close)
        return connection

    def rpc(
        self,
        req_type: str,
        payload: dict[str, object] | None = None,
        *,
        request_id: str = "rel-1",
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
        conn.sendall((json.dumps(envelope, separators=(",", ":")) + "\n").encode("utf-8"))
        return receive_json_line(conn)

    def test_01_tcp_framing_split_sticky_and_oversized(self) -> None:
        # 1) 1 JSON split into 3 separate TCP sends
        conn = self.connect()
        for part in (
            b'{"type":"PI',
            b'NG","request_id":"frag-3-parts',
            b'","payload":{}}\n',
        ):
            conn.sendall(part)
            time.sleep(0.03)
        res = receive_json_line(conn)
        self.assertEqual(res["type"], "OK")
        self.assertEqual(res["request_id"], "frag-3-parts")

        # 2) 2 NDJSON messages coalesced into a single send
        conn.sendall(
            b'{"type":"PING","request_id":"sticky-a","payload":{}}\n'
            b'{"type":"PING","request_id":"sticky-b","payload":{}}\n'
        )
        with conn.makefile("rb") as reader:
            first = json.loads(reader.readline().decode("utf-8"))
            second = json.loads(reader.readline().decode("utf-8"))
        self.assertEqual([first["request_id"], second["request_id"]], ["sticky-a", "sticky-b"])

        # 3) Payload > 64 KB gets BAD_REQUEST and server keeps serving other clients
        huge_conn = self.connect()
        huge_conn.sendall(b'{"type":"PING","request_id":"big","payload":{"x":"' + (b"a" * 66000) + b'"}}\n')
        huge_res = receive_json_line(huge_conn)
        self.assertEqual(huge_res["type"], "ERROR")
        self.assertEqual(huge_res["error"]["code"], "BAD_REQUEST")  # type: ignore[index]

        alive = self.rpc("PING", {}, request_id="after-huge")
        self.assertEqual(alive["type"], "OK")

    def test_02_rate_limit_blocks_after_five_failures(self) -> None:
        reg = self.rpc(
            "REGISTER",
            {"username": "brute_target", "password": "ValidPassword123"},
            request_id="reg-brute",
        )
        self.assertEqual(reg["type"], "OK")

        for attempt in range(5):
            fail = self.rpc(
                "LOGIN",
                {"username": "brute_target", "password": "WrongPassword999"},
                request_id=f"brute-fail-{attempt}",
            )
            self.assertEqual(fail["type"], "ERROR")
            self.assertEqual(fail["error"]["code"], "UNAUTHORIZED")  # type: ignore[index]

        # 6th attempt is blocked even with the correct password
        blocked = self.rpc(
            "LOGIN",
            {"username": "brute_target", "password": "ValidPassword123"},
            request_id="brute-blocked-6",
        )
        self.assertEqual(blocked["type"], "ERROR")
        self.assertEqual(blocked["error"]["code"], "UNAUTHORIZED")  # type: ignore[index]
        self.assertIn("Too many", str(blocked["error"]["message"]))  # type: ignore[index]

        with contextlib.closing(sqlite3.connect(self.db_path)) as db:
            row = db.execute(
                "SELECT COUNT(*) FROM activity_logs WHERE action = 'LOGIN_RATE_LIMITED'"
            ).fetchone()
            self.assertGreaterEqual(row[0], 1)

    def test_03_permission_enforcement_student_cannot_start_room(self) -> None:
        host_reg = self.rpc(
            "REGISTER",
            {"username": "rel_host", "password": "HostPassword123", "role": "HOST"},
            request_id="reg-rel-host",
        )
        self.assertEqual(host_reg["type"], "OK")
        host_id = host_reg["data"]["user"]["id"]  # type: ignore[index]

        self.rpc(
            "REGISTER",
            {"username": "rel_student", "password": "StudentPassword123", "role": "STUDENT"},
            request_id="reg-rel-student",
        )
        student_login = self.rpc(
            "LOGIN",
            {"username": "rel_student", "password": "StudentPassword123"},
            request_id="login-rel-student",
        )
        student_token = student_login["data"]["token"]  # type: ignore[index]

        with contextlib.closing(sqlite3.connect(self.db_path)) as db:
            cur = db.execute(
                "INSERT INTO exam_rooms(owner_id, name, status, duration_seconds) "
                "VALUES (?, 'Reliability Exam Room', 'WAITING', 600)",
                (host_id,),
            )
            room_id = cur.lastrowid
            db.commit()

        res = self.rpc(
            "START_ROOM",
            {"room_id": room_id},
            request_id="student-start-denied",
            token=student_token,
        )
        self.assertEqual(res["type"], "ERROR")
        self.assertEqual(res["error"]["code"], "FORBIDDEN")  # type: ignore[index]

    def test_04_session_reconnect_get_my_active_exam(self) -> None:
        # Unauthenticated request rejected
        no_tok = self.rpc("GET_MY_ACTIVE_EXAM", {}, request_id="recon-no-tok")
        self.assertEqual(no_tok["type"], "ERROR")
        self.assertEqual(no_tok["error"]["code"], "UNAUTHORIZED")  # type: ignore[index]

        # Login as student
        login = self.rpc(
            "LOGIN",
            {"username": "rel_student", "password": "StudentPassword123"},
            request_id="login-recon",
        )
        token = login["data"]["token"]  # type: ignore[index]
        student_id = login["data"]["user"]["id"]  # type: ignore[index]

        # Initially no active exam
        empty = self.rpc("GET_MY_ACTIVE_EXAM", {}, request_id="recon-empty", token=token)
        self.assertEqual(empty["type"], "OK")
        self.assertIsNone(empty["data"]["active_exam"])  # type: ignore[index]

        # Seed a RUNNING room with a snapshot question and a saved answer
        with contextlib.closing(sqlite3.connect(self.db_path)) as db:
            host_id = db.execute("SELECT id FROM users WHERE username = 'rel_host'").fetchone()[0]
            q_cur = db.execute(
                "INSERT INTO questions(content, topic, difficulty, correct_option_id, is_active) "
                "VALUES ('What does SO_REUSEADDR do?', 'TCP Socket', 'medium', NULL, 1)"
            )
            q_id = q_cur.lastrowid
            opt_ids = []
            for pos, (lbl, text) in enumerate(
                [("A", "Allows port reuse"), ("B", "Disables TCP"), ("C", "Encrypts data"), ("D", "Closes socket")],
                start=1,
            ):
                o_cur = db.execute(
                    "INSERT INTO question_options(question_id, label, content, position) VALUES (?, ?, ?, ?)",
                    (q_id, lbl, text, pos),
                )
                opt_ids.append(o_cur.lastrowid)
            db.execute("UPDATE questions SET correct_option_id = ? WHERE id = ?", (opt_ids[0], q_id))

            r_cur = db.execute(
                "INSERT INTO exam_rooms(owner_id, name, status, duration_seconds, started_at, ended_at) "
                "VALUES (?, 'Reconnect Room', 'RUNNING', 900, datetime('now'), datetime('now', '+900 seconds'))",
                (host_id,),
            )
            room_id = r_cur.lastrowid
            db.execute(
                "INSERT INTO room_questions(room_id, question_id, position, content_snapshot, correct_option_snapshot) "
                "VALUES (?, ?, 1, 'What does SO_REUSEADDR do?', ?)",
                (room_id, q_id, opt_ids[0]),
            )
            db.execute(
                "INSERT INTO room_participants(room_id, user_id, state) VALUES (?, ?, 'IN_PROGRESS')",
                (room_id, student_id),
            )
            db.execute(
                "INSERT INTO attempt_answers(room_id, user_id, question_id, selected_option_id) VALUES (?, ?, ?, ?)",
                (room_id, student_id, q_id, opt_ids[0]),
            )
            db.commit()

        # Simulate reconnect on a brand-new TCP socket using the existing session token
        recovered = self.rpc("GET_MY_ACTIVE_EXAM", {}, request_id="recon-ok", token=token)
        self.assertEqual(recovered["type"], "OK")
        exam = recovered["data"]["active_exam"]  # type: ignore[index]
        self.assertEqual(exam["room_id"], room_id)
        self.assertEqual(exam["room_name"], "Reconnect Room")
        self.assertEqual(len(exam["questions"]), 1)
        self.assertEqual(len(exam["questions"][0]["options"]), 4)
        # Never leak correct answers during an active exam
        self.assertNotIn("correct_option_id", exam["questions"][0])
        self.assertNotIn("correct_option_snapshot", exam["questions"][0])
        self.assertEqual(
            exam["saved_answers"],
            [{"question_id": q_id, "selected_option_id": opt_ids[0]}],
        )

    def test_05_concurrent_stress_15_clients(self) -> None:
        client_count = 15
        for i in range(client_count):
            reg = self.rpc(
                "REGISTER",
                {"username": f"stress_user_{i}", "password": "StressPassword123"},
                request_id=f"stress-reg-{i}",
            )
            self.assertEqual(reg["type"], "OK")

        def run_client(idx: int) -> bool:
            with socket.create_connection(("127.0.0.1", self.port), timeout=10.0) as sock:
                login_msg = {
                    "type": "LOGIN",
                    "request_id": f"stress-login-{idx}",
                    "payload": {"username": f"stress_user_{idx}", "password": "StressPassword123"},
                }
                sock.sendall((json.dumps(login_msg, separators=(",", ":")) + "\n").encode("utf-8"))
                login_res = receive_json_line(sock)
                if login_res.get("type") != "OK":
                    return False
                token = login_res["data"]["token"]  # type: ignore[index]

                for step, req_type in enumerate(("PING", "LIST_ROOMS", "GET_MY_PROFILE")):
                    req = {
                        "type": req_type,
                        "request_id": f"stress-{idx}-{step}",
                        "token": token,
                        "payload": {},
                    }
                    sock.sendall((json.dumps(req, separators=(",", ":")) + "\n").encode("utf-8"))
                    resp = receive_json_line(sock)
                    if resp.get("type") != "OK":
                        return False
                return True

        with concurrent.futures.ThreadPoolExecutor(max_workers=client_count) as pool:
            outcomes = list(pool.map(run_client, range(client_count)))
        self.assertTrue(all(outcomes), f"Concurrent stress failures: {outcomes}")

    def test_06_idle_socket_timeout_closes_stale_connection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "idle.db"
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.bind(("127.0.0.1", 0))
                idle_port = int(probe.getsockname()[1])

            env = os.environ.copy()
            env["KUIZUHUB_DB_PATH"] = str(db_path)
            env["KUIZUHUB_IDLE_TIMEOUT_SEC"] = "1"
            proc = subprocess.Popen(
                [str(SERVER_BINARY), str(idle_port)],
                cwd=SERVER_DIR,
                text=True,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            try:
                deadline = time.monotonic() + 3.0
                while time.monotonic() < deadline:
                    try:
                        with socket.create_connection(("127.0.0.1", idle_port), timeout=0.1):
                            break
                    except OSError:
                        time.sleep(0.03)

                with socket.create_connection(("127.0.0.1", idle_port), timeout=3.0) as idle_sock:
                    idle_sock.settimeout(3.0)
                    # Do not send anything; server should close after ~1s
                    data = idle_sock.recv(1024)
                    self.assertEqual(data, b"")
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    proc.wait(timeout=3)
                if proc.stderr is not None:
                    proc.stderr.close()


if __name__ == "__main__":
    unittest.main()
