#!/usr/bin/env python3
"""Create the reproducible Phase 0 SQLite database from checked-in sources."""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = REPOSITORY_ROOT / "server" / "data" / "exam.db"
MIGRATION_PATH = REPOSITORY_ROOT / "server" / "migrations" / "001_initial.sql"
SEED_PATH = REPOSITORY_ROOT / "server" / "seed" / "questions.json"
REQUIRED_DIFFICULTIES = {"easy", "medium", "hard"}


def load_and_validate_questions() -> list[dict[str, object]]:
    questions = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    if not isinstance(questions, list) or len(questions) < 30:
        raise ValueError("Seed must contain at least 30 questions.")

    difficulties_by_topic: dict[str, set[str]] = defaultdict(set)
    for index, question in enumerate(questions, start=1):
        if not isinstance(question, dict):
            raise ValueError(f"Question {index} must be an object.")
        content, topic, difficulty = (question.get(key) for key in ("content", "topic", "difficulty"))
        options = question.get("options")
        correct = question.get("correct_option_index")
        if not all(isinstance(value, str) and value.strip() for value in (content, topic, difficulty)):
            raise ValueError(f"Question {index} needs non-empty content, topic and difficulty.")
        if difficulty not in REQUIRED_DIFFICULTIES:
            raise ValueError(f"Question {index} has unsupported difficulty {difficulty!r}.")
        if not isinstance(options, list) or len(options) != 4 or not all(isinstance(item, str) and item.strip() for item in options):
            raise ValueError(f"Question {index} must have exactly four non-empty options.")
        if not isinstance(correct, int) or correct not in range(4):
            raise ValueError(f"Question {index} has an invalid correct_option_index.")
        difficulties_by_topic[topic].add(difficulty)

    if len(difficulties_by_topic) < 3:
        raise ValueError("Seed must contain at least three topics.")
    incomplete = sorted(topic for topic, values in difficulties_by_topic.items() if values != REQUIRED_DIFFICULTIES)
    if incomplete:
        raise ValueError(f"Every topic must contain easy, medium and hard questions: {', '.join(incomplete)}")
    return questions


def seed_database(database_path: Path, reset: bool) -> None:
    questions = load_and_validate_questions()
    if database_path.exists() and not reset:
        raise FileExistsError(f"{database_path} already exists; pass --reset to recreate it.")
    if reset and database_path.exists():
        database_path.unlink()
    database_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(MIGRATION_PATH.read_text(encoding="utf-8"))
        for question in questions:
            cursor = connection.execute(
                "INSERT INTO questions(content, topic, difficulty, correct_option_id, is_active) VALUES (?, ?, ?, NULL, 1)",
                (question["content"], question["topic"], question["difficulty"]),
            )
            question_id = cursor.lastrowid
            option_ids: list[int] = []
            for position, content in enumerate(question["options"], start=1):
                option_cursor = connection.execute(
                    "INSERT INTO question_options(question_id, label, content, position) VALUES (?, ?, ?, ?)",
                    (question_id, "ABCD"[position - 1], content, position),
                )
                option_ids.append(option_cursor.lastrowid)
            connection.execute(
                "UPDATE questions SET correct_option_id = ? WHERE id = ?",
                (option_ids[question["correct_option_index"]], question_id),
            )
        connection.commit()

    print(f"Created {database_path} with {len(questions)} questions.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DATABASE, help="Output SQLite file")
    parser.add_argument("--reset", action="store_true", help="Replace an existing output database")
    arguments = parser.parse_args()
    seed_database(arguments.db.resolve(), arguments.reset)


if __name__ == "__main__":
    main()
