#!/usr/bin/env python3
"""Turso Cloud Database synchronization utility for KuizuHub.

This script interacts with Turso's libSQL HTTP API (/v2/pipeline)
to initialize, query, seed, and pull data from Turso Cloud.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = REPOSITORY_ROOT / "server" / "migrations" / "001_initial.sql"
SEED_PATH = REPOSITORY_ROOT / "server" / "seed" / "questions.json"
LOCAL_DB_PATH = REPOSITORY_ROOT / "server" / "data" / "exam.db"

load_dotenv(REPOSITORY_ROOT / ".env")


class TursoClient:
    def __init__(self, db_url: str | None = None, auth_token: str | None = None):
        self.db_url = db_url or os.getenv("TURSO_DATABASE_URL", "")
        self.auth_token = auth_token or os.getenv("TURSO_AUTH_TOKEN", "")

        if not self.db_url:
            raise ValueError(
                "Missing TURSO_DATABASE_URL. Set it in .env or pass as argument."
            )

        # Normalize URL to HTTPS endpoint
        url = self.db_url.strip()
        if url.startswith("libsql://"):
            url = "https://" + url[len("libsql://") :]
        elif not url.startswith("http://") and not url.startswith("https://"):
            url = "https://" + url
        self.base_url = url.rstrip("/")
        self.pipeline_url = f"{self.base_url}/v2/pipeline"
        self.session = requests.Session()
        if self.auth_token:
            self.session.headers["Authorization"] = f"Bearer {self.auth_token}"
        self.session.headers["Content-Type"] = "application/json"

    def execute_statements(self, statements: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Execute a list of SQL statement requests via Turso HTTP Pipeline."""
        requests_payload: list[dict[str, Any]] = []
        for stmt in statements:
            req: dict[str, Any] = {
                "type": "execute",
                "stmt": {"sql": stmt["sql"]},
            }
            if "args" in stmt and stmt["args"]:
                # Convert args to Turso value format
                turso_args: list[dict[str, Any]] = []
                for arg in stmt["args"]:
                    if arg is None:
                        turso_args.append({"type": "null"})
                    elif isinstance(arg, int):
                        turso_args.append({"type": "integer", "value": str(arg)})
                    elif isinstance(arg, float):
                        turso_args.append({"type": "float", "value": arg})
                    elif isinstance(arg, (bytes, bytearray)):
                        import base64
                        turso_args.append({"type": "blob", "base64": base64.b64encode(arg).decode()})
                    else:
                        turso_args.append({"type": "text", "value": str(arg)})
                req["stmt"]["args"] = turso_args
            requests_payload.append(req)

        # Append close request
        requests_payload.append({"type": "close"})

        payload = {"requests": requests_payload}
        try:
            res = self.session.post(self.pipeline_url, json=payload, timeout=60)
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"Failed to connect to Turso at {self.pipeline_url}: {e}") from e

        if res.status_code != 200:
            raise RuntimeError(
                f"Turso API returned HTTP {res.status_code}: {res.text}"
            )

        data = res.json()
        results: list[dict[str, Any]] = []
        for item in data.get("results", []):
            if item.get("type") == "error":
                raise RuntimeError(f"SQL execution error on Turso: {item.get('error')}")
            if item.get("type") == "ok":
                results.append(item.get("response", {}))
        return results

    def query(self, sql: str, args: list[Any] | None = None) -> list[dict[str, Any]]:
        """Run a SELECT query and return list of dict rows."""
        res = self.execute_statements([{"sql": sql, "args": args or []}])
        if not res:
            return []
        resp = res[0].get("result", {})
        cols = [c["name"] for c in resp.get("cols", [])]
        rows: list[dict[str, Any]] = []
        for r in resp.get("rows", []):
            row_dict: dict[str, Any] = {}
            for col, val in zip(cols, r):
                row_dict[col] = val.get("value")
            rows.append(row_dict)
        return rows

    def exec(self, sql: str, args: list[Any] | None = None) -> None:
        """Run a single DDL or DML statement."""
        self.execute_statements([{"sql": sql, "args": args or []}])

    def check_connection(self) -> bool:
        """Ping Turso by running SELECT 1."""
        try:
            rows = self.query("SELECT 1 AS ok;")
            return len(rows) > 0 and rows[0].get("ok") in (1, "1")
        except Exception as e:
            print(f"[Turso Error] {e}", file=sys.stderr)
            return False


def cmd_init_cloud(client: TursoClient, reset: bool = False) -> None:
    """Initialize Turso Cloud Database with schema and questions."""
    print("Checking connection to Turso...")
    if not client.check_connection():
        print("❌ Cannot connect to Turso. Check TURSO_DATABASE_URL and TURSO_AUTH_TOKEN in .env")
        sys.exit(1)
    print(" Connected to Turso successfully.")

    if reset:
        print("Dropping existing tables on Turso...")
        tables = [
            "attempt_answers", "room_participants", "room_questions",
            "room_question_rules", "exam_rooms", "question_options",
            "questions", "sessions", "practice_attempts", "activity_logs", "users"
        ]
        for tbl in tables:
            try:
                client.exec(f"DROP TABLE IF EXISTS {tbl};")
            except Exception as e:
                print(f"  Note dropping {tbl}: {e}")

    # Read and execute migration script
    print(f"Applying schema from {MIGRATION_PATH}...")
    sql_script = MIGRATION_PATH.read_text(encoding="utf-8")
    # Split by semicolon for individual statements (skipping empty lines)
    stmts: list[dict[str, Any]] = []
    for raw_stmt in sql_script.split(";"):
        stmt = raw_stmt.strip()
        if stmt and not stmt.startswith("--"):
            stmts.append({"sql": stmt})

    # Execute in chunks of 20 to avoid payload limits
    chunk_size = 20
    for i in range(0, len(stmts), chunk_size):
        chunk = stmts[i : i + chunk_size]
        client.execute_statements(chunk)

    print("Schema applied successfully on Turso.")

    # Seed questions
    print(f"Seeding questions from {SEED_PATH}...")
    questions = json.loads(SEED_PATH.read_text(encoding="utf-8"))

    # Clear questions before re-seeding
    client.execute_statements([
        {"sql": "DELETE FROM question_options;"},
        {"sql": "DELETE FROM questions;"}
    ])

    batch_stmts: list[dict[str, Any]] = []
    opt_counter = 1
    for q_id, q in enumerate(questions, start=1):
        # 1. Insert question
        batch_stmts.append({
            "sql": "INSERT INTO questions(id, content, topic, difficulty, correct_option_id, is_active) VALUES (?, ?, ?, ?, NULL, 1);",
            "args": [q_id, q["content"], q["topic"], q["difficulty"]]
        })

        # 2. Insert 4 options
        opt_ids: list[int] = []
        for pos, opt_text in enumerate(q["options"], start=1):
            lbl = "ABCD"[pos - 1]
            batch_stmts.append({
                "sql": "INSERT INTO question_options(id, question_id, label, content, position) VALUES (?, ?, ?, ?, ?);",
                "args": [opt_counter, q_id, lbl, opt_text, pos]
            })
            opt_ids.append(opt_counter)
            opt_counter += 1

        # 3. Update correct_option_id
        correct_idx = q["correct_option_index"]
        batch_stmts.append({
            "sql": "UPDATE questions SET correct_option_id = ? WHERE id = ?;",
            "args": [opt_ids[correct_idx], q_id]
        })

    # Execute all seed statements in 2-3 fast chunks
    chunk_size = 50
    for i in range(0, len(batch_stmts), chunk_size):
        chunk = batch_stmts[i : i + chunk_size]
        client.execute_statements(chunk)

    print(f" Seeded {len(questions)} questions on Turso Cloud successfully!")


def cmd_pull_to_local(client: TursoClient) -> None:
    """Pull questions and schema from Turso Cloud to local SQLite database (server/data/exam.db)."""
    print("Checking connection to Turso...")
    if not client.check_connection():
        print("❌ Cannot connect to Turso.")
        sys.exit(1)

    LOCAL_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if LOCAL_DB_PATH.exists():
        LOCAL_DB_PATH.unlink()

    print(f"Initializing local SQLite database at {LOCAL_DB_PATH}...")
    with sqlite3.connect(LOCAL_DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.executescript(MIGRATION_PATH.read_text(encoding="utf-8"))

        print("Fetching questions from Turso Cloud...")
        questions = client.query("SELECT id, content, topic, difficulty, is_active FROM questions;")
        options = client.query("SELECT id, question_id, label, content, position FROM question_options;")
        
        for q in questions:
            conn.execute(
                "INSERT INTO questions(id, content, topic, difficulty, correct_option_id, is_active) VALUES (?, ?, ?, ?, NULL, ?);",
                (q["id"], q["content"], q["topic"], q["difficulty"], q["is_active"])
            )

        for opt in options:
            conn.execute(
                "INSERT INTO question_options(id, question_id, label, content, position) VALUES (?, ?, ?, ?, ?);",
                (opt["id"], opt["question_id"], opt["label"], opt["content"], opt["position"])
            )

        # Update correct_option_id from Turso
        q_updates = client.query("SELECT id, correct_option_id FROM questions WHERE correct_option_id IS NOT NULL;")
        for u in q_updates:
            conn.execute(
                "UPDATE questions SET correct_option_id = ? WHERE id = ?;",
                (u["correct_option_id"], u["id"])
            )

        conn.commit()

    print(f" Successfully pulled {len(questions)} questions from Turso to {LOCAL_DB_PATH}!")


def main() -> None:
    parser = argparse.ArgumentParser(description="KuizuHub Turso Cloud Database Manager")
    parser.add_argument("--status", action="store_true", help="Check connection to Turso Cloud")
    parser.add_argument("--init", action="store_true", help="Initialize schema and seed questions on Turso")
    parser.add_argument("--reset", action="store_true", help="Reset all tables before init on Turso")
    parser.add_argument("--pull", action="store_true", help="Pull latest schema and questions from Turso to local SQLite")
    parser.add_argument("--query", type=str, help="Execute a read-only SQL query on Turso")
    args = parser.parse_args()

    try:
        client = TursoClient()
    except ValueError as e:
        print(f"Configuration Error: {e}")
        print("\nPlease configure .env file:")
        print("  1. Copy .env.example to .env")
        print("  2. Add your TURSO_DATABASE_URL and TURSO_AUTH_TOKEN")
        sys.exit(1)

    if args.status:
        if client.check_connection():
            print(" Turso Cloud connection is active!")
            users = client.query("SELECT count(*) AS total FROM users;")
            questions = client.query("SELECT count(*) AS total FROM questions;")
            print(f"  • Users on Cloud: {users[0]['total'] if users else 0}")
            print(f"  • Questions on Cloud: {questions[0]['total'] if questions else 0}")
        else:
            print("❌ Turso Cloud connection failed.")
            sys.exit(1)
    elif args.init:
        cmd_init_cloud(client, reset=args.reset)
    elif args.pull:
        cmd_pull_to_local(client)
    elif args.query:
        rows = client.query(args.query)
        print(json.dumps(rows, indent=2, ensure_ascii=False))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
