"""Typed data shapes shared by service and UI layers."""

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class User:
    id: int
    full_name: str
    username: str
    email: str
    password: str
    role: str
    joined_at: str

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "User":
        return cls(**value)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Room:
    id: int
    name: str
    description: str
    owner_id: int
    owner_name: str
    topic: str
    difficulty: str
    question_count: int
    duration_minutes: int
    max_participants: int
    status: str = "WAITING"
    participant_ids: list[int] = field(default_factory=list)
    created_at: str = ""

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Room":
        return cls(**value)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Question:
    id: int
    content: str
    options: list[str]
    correct_index: int
    topic: str
    difficulty: str
    explanation: str

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Question":
        return cls(**value)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Attempt:
    id: int
    user_id: int
    title: str
    kind: str
    topic: str
    question_ids: list[int]
    answers: dict[str, int]
    score: float
    correct_count: int
    total: int
    created_at: str
    duration_seconds: int
    status: str = "SUBMITTED"
    room_id: int | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Attempt":
        return cls(**value)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
