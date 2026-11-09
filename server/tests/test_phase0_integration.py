from __future__ import annotations

import json
import os
import socket
import subprocess
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


class PhaseZeroServerTests(unittest.TestCase):
    server: subprocess.Popen[str]
    port: int

    @classmethod
    def setUpClass(cls) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            cls.port = int(probe.getsockname()[1])
        cls.server = subprocess.Popen(
            [str(SERVER_BINARY), str(cls.port)], cwd=SERVER_DIR, text=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", cls.port), timeout=0.1):
                    return
            except OSError:
                time.sleep(0.03)
        cls.tearDownClass()
        raise RuntimeError("Phase 0 server did not start")

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "server") and cls.server.poll() is None:
            cls.server.terminate()
            cls.server.wait(timeout=3)

    def connect(self) -> socket.socket:
        connection = socket.create_connection(("127.0.0.1", self.port), timeout=2)
        self.addCleanup(connection.close)
        return connection

    def test_ping_survives_split_tcp_receive(self) -> None:
        connection = self.connect()
        connection.sendall(b'{"type":"PI')
        connection.sendall(b'NG","request_id":"split-1","payload":{}}\n')
        self.assertEqual(
            receive_json_line(connection),
            {"type": "OK", "request_id": "split-1", "data": {"message": "pong"}},
        )

    def test_two_messages_in_one_send_receive_two_responses(self) -> None:
        connection = self.connect()
        connection.sendall(
            b'{"type":"PING","request_id":"first","payload":{}}\n'
            b'{"type":"PING","request_id":"second","payload":{}}\n'
        )
        with connection.makefile("rb") as reader:
            first = json.loads(reader.readline().decode("utf-8"))
            second = json.loads(reader.readline().decode("utf-8"))
        self.assertEqual([first["request_id"], second["request_id"]], ["first", "second"])
        self.assertTrue(all(response["type"] == "OK" for response in (first, second)))

    def test_invalid_json_gets_standard_error(self) -> None:
        connection = self.connect()
        connection.sendall(b'not-json\n')
        response = receive_json_line(connection)
        self.assertEqual(response["type"], "ERROR")
        self.assertEqual(response["request_id"], None)
        self.assertEqual(response["error"]["code"], "BAD_REQUEST")
