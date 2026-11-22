#!/usr/bin/env python3
"""Add reusable demo practice data to an existing KuizuHub SQLite database."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = REPOSITORY_ROOT / "server" / "data" / "exam.db"
DEMO_USERS = ("practice_demo_01", "practice_demo_02", "practice_demo_03")
DEMO_PASSWORD = "DemoPractice123"
TOPICS = ("TCP Socket", "UDP", "DNS")
DIFFICULTIES = ("easy", "medium", "hard")


def password_hash(password: str) -> str:
    """Use the same PBKDF2-SHA256 wire format as the C authentication module."""
    salt = os.urandom(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
    return f"pbkdf2_sha256$100000${salt.hex()}${derived.hex()}"


def require_practice_schema(connection: sqlite3.Connection) -> None:
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    required = {
        "users", "questions", "question_options", "practice_sessions",
        "practice_session_questions", "practice_session_options", "practice_answers",
        "practice_attempts",
    }
    missing = sorted(required - tables)
    if missing:
        raise RuntimeError(
            "Database is missing practice schema: " + ", ".join(missing) +
            ". Run scripts/seed_db.py --reset first."
        )


def demo_user_ids(connection: sqlite3.Connection) -> list[int]:
    ids: list[int] = []
    for username in DEMO_USERS:
        row = connection.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if row is None:
            cursor = connection.execute(
                "INSERT INTO users(username, password_hash, role) VALUES (?, ?, 'STUDENT')",
                (username, password_hash(DEMO_PASSWORD)),
            )
            ids.append(int(cursor.lastrowid))
        else:
            ids.append(int(row[0]))
    return ids


def questions_for(connection: sqlite3.Connection, topic: str, difficulty: str) -> list[tuple[int, str, int]]:
    rows = connection.execute(
        "SELECT q.id, q.content, correct.position "
        "FROM questions q JOIN question_options correct ON correct.id = q.correct_option_id "
        "WHERE q.is_active = 1 AND q.topic = ? AND q.difficulty = ? "
        "ORDER BY q.id LIMIT 3",
        (topic, difficulty),
    ).fetchall()
    if len(rows) != 3:
        raise RuntimeError(f"Need at least three active {difficulty} questions for topic {topic!r}")
    return [(int(question_id), str(content), int(correct_position)) for question_id, content, correct_position in rows]


def snapshot_questions(
    connection: sqlite3.Connection, session_id: int, questions: list[tuple[int, str, int]], seed: int
) -> tuple[int, int]:
    correct_count = 0
    for position, (question_id, content, correct_position) in enumerate(questions, start=1):
        connection.execute(
            "INSERT INTO practice_session_questions "
            "(session_id, question_id, position, content_snapshot, correct_option_position) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, question_id, position, content, correct_position),
        )
        options = connection.execute(
            "SELECT position, label, content FROM question_options WHERE question_id = ? ORDER BY position",
            (question_id,),
        ).fetchall()
        if len(options) != 4:
            raise RuntimeError(f"Question {question_id} does not have four options")
        connection.executemany(
            "INSERT INTO practice_session_options "
            "(session_id, question_id, position, label, content_snapshot) VALUES (?, ?, ?, ?, ?)",
            [(session_id, question_id, int(option[0]), str(option[1]), str(option[2])) for option in options],
        )
        selected_position = correct_position if (seed + position) % 3 == 0 else (correct_position % 4) + 1
        correct_count += int(selected_position == correct_position)
        connection.execute(
            "INSERT INTO practice_answers(session_id, question_id, selected_option_position) VALUES (?, ?, ?)",
            (session_id, question_id, selected_position),
        )
    return correct_count, len(questions)


def seed_practice_data(database_path: Path) -> None:
    if not database_path.exists():
        raise FileNotFoundError(f"Database not found: {database_path}")

    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        require_practice_schema(connection)
        existing = connection.execute(
            "SELECT COUNT(*) FROM practice_sessions s JOIN users u ON u.id = s.user_id "
            "WHERE u.username IN (?, ?, ?)",
            DEMO_USERS,
        ).fetchone()[0]
        if existing:
            print(f"Demo practice data already exists ({existing} sessions); nothing added.")
            return

        users = demo_user_ids(connection)
        now = datetime.now().replace(microsecond=0)
        created_sessions = 0
        created_attempts = 0
        for index, (topic, difficulty) in enumerate(
            (pair for pair in ((topic, difficulty) for topic in TOPICS for difficulty in DIFFICULTIES) for _ in range(2)),
            start=1,
        ):
            questions = questions_for(connection, topic, difficulty)
            user_id = users[(index - 1) % len(users)]
            duration = 600 if index % 2 else 900
            if index % 6 == 0:
                state = "IN_PROGRESS"
                started_at = now - timedelta(minutes=4)
                ended_at = now + timedelta(seconds=duration - 240)
                submitted_at: str | None = None
            else:
                state = "AUTO_SUBMITTED" if index % 5 == 0 else "SUBMITTED"
                started_at = now - timedelta(days=index, minutes=duration // 60)
                ended_at = started_at + timedelta(seconds=duration)
                submitted_at = ended_at if state == "AUTO_SUBMITTED" else started_at + timedelta(minutes=6)

            cursor = connection.execute(
                "INSERT INTO practice_sessions "
                "(user_id, state, topic, difficulty, question_count, duration_seconds, started_at, ended_at, submitted_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    user_id, state, topic, difficulty, len(questions), duration,
                    started_at.isoformat(sep=" "), ended_at.isoformat(sep=" "),
                    submitted_at.isoformat(sep=" ") if submitted_at else None,
                ),
            )
            session_id = int(cursor.lastrowid)
            correct_count, total = snapshot_questions(connection, session_id, questions, index)
            if state != "IN_PROGRESS":
                score = round(correct_count * 10.0 / total, 2)
                connection.execute(
                    "UPDATE practice_sessions SET score = ?, correct_count = ? WHERE id = ?",
                    (score, correct_count, session_id),
                )
                connection.execute(
                    "INSERT INTO practice_attempts "
                    "(user_id, score, correct_count, total, duration_seconds, configuration_json, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        user_id, score, correct_count, total, duration,
                        json.dumps({"source": "demo_practice", "session_id": session_id}),
                        submitted_at.isoformat(sep=" "),
                    ),
                )
                created_attempts += 1
            created_sessions += 1
        connection.commit()

    print(
        f"Added {created_sessions} demo practice sessions and {created_attempts} practice-history rows. "
        f"Demo login: {DEMO_USERS[0]} / {DEMO_PASSWORD}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DATABASE, help="Existing SQLite database")
    arguments = parser.parse_args()
    seed_practice_data(arguments.db.resolve())


if __name__ == "__main__":
    main()
