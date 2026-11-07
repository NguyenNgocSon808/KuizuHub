"""Local JSON-backed implementation of the application's service boundary."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import DATA_DIR
from ..models import Attempt, Question, Room, User


class ServiceError(ValueError):
    """Expected validation/permission error that can be shown by the UI."""


class MockApiService:
    """Small persistence layer used until a TCP C server replaces it.

    UI code only calls this class; it never reads JSON files directly. Changes
    are stored in ``mock_state.json`` and can safely be reset from Profile.
    """

    def __init__(self, data_dir: Path | None = None, seed_dir: Path = DATA_DIR) -> None:
        self.data_dir = Path(data_dir or DATA_DIR)
        self.seed_dir = Path(seed_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.data_dir / "mock_state.json"
        self._load()

    @staticmethod
    def _now() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M")

    def _seed_payload(self) -> dict[str, list[dict[str, Any]]]:
        names = ("users", "rooms", "questions", "attempts")
        payload: dict[str, list[dict[str, Any]]] = {}
        for name in names:
            with (self.seed_dir / f"{name}.json").open(encoding="utf-8") as stream:
                payload[name] = json.load(stream)
        return payload

    def _load(self) -> None:
        if self.state_path.exists():
            with self.state_path.open(encoding="utf-8") as stream:
                raw = json.load(stream)
        else:
            raw = self._seed_payload()
        self.users = [User.from_dict(value) for value in raw.get("users", [])]
        self.rooms = [Room.from_dict(value) for value in raw.get("rooms", [])]
        self.questions = [Question.from_dict(value) for value in raw.get("questions", [])]
        self.attempts = [Attempt.from_dict(value) for value in raw.get("attempts", [])]

    def _save(self) -> None:
        payload = {
            "users": [user.to_dict() for user in self.users],
            "rooms": [room.to_dict() for room in self.rooms],
            "questions": [question.to_dict() for question in self.questions],
            "attempts": [attempt.to_dict() for attempt in self.attempts],
        }
        with self.state_path.open("w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)

    def reset_demo(self) -> None:
        if self.state_path.exists():
            self.state_path.unlink()
        self._load()

    @staticmethod
    def _next_id(values: list[Any]) -> int:
        return max((value.id for value in values), default=0) + 1

    def _user(self, user_id: int) -> User:
        for user in self.users:
            if user.id == user_id:
                return user
        raise ServiceError("Không tìm thấy người dùng.")

    def _room(self, room_id: int) -> Room:
        for room in self.rooms:
            if room.id == room_id:
                return room
        raise ServiceError("Không tìm thấy phòng thi.")

    def _question(self, question_id: int) -> Question:
        for question in self.questions:
            if question.id == question_id:
                return question
        raise ServiceError("Không tìm thấy câu hỏi.")

    # Authentication -----------------------------------------------------
    def login(self, username: str, password: str) -> User:
        if not username.strip() or not password:
            raise ServiceError("Vui lòng nhập username và mật khẩu.")
        for user in self.users:
            if user.username.lower() == username.strip().lower() and user.password == password:
                return user
        raise ServiceError("Username hoặc mật khẩu không chính xác.")

    def register(self, full_name: str, username: str, email: str, password: str, confirm: str) -> User:
        if not all([full_name.strip(), username.strip(), email.strip(), password, confirm]):
            raise ServiceError("Vui lòng điền đầy đủ thông tin.")
        if len(username.strip()) < 3:
            raise ServiceError("Username cần ít nhất 3 ký tự.")
        if "@" not in email:
            raise ServiceError("Email chưa hợp lệ.")
        if len(password) < 6:
            raise ServiceError("Mật khẩu cần ít nhất 6 ký tự.")
        if password != confirm:
            raise ServiceError("Xác nhận mật khẩu chưa khớp.")
        if any(user.username.lower() == username.strip().lower() for user in self.users):
            raise ServiceError("Username đã tồn tại.")
        user = User(self._next_id(self.users), full_name.strip(), username.strip(), email.strip(), password, "STUDENT", self._now()[:10])
        self.users.append(user)
        self._save()
        return user

    # Rooms --------------------------------------------------------------
    def get_rooms(self, search: str = "", status: str = "Tất cả") -> list[Room]:
        text = search.strip().lower()
        result = self.rooms[:]
        if text:
            result = [room for room in result if text in room.name.lower() or text in room.topic.lower()]
        lookup = {"Chờ": "WAITING", "Đang diễn ra": "RUNNING", "Đã kết thúc": "ENDED"}
        if status in lookup:
            result = [room for room in result if room.status == lookup[status]]
        return sorted(result, key=lambda room: room.id, reverse=True)

    def create_room(self, owner_id: int, data: dict[str, Any]) -> Room:
        owner = self._user(owner_id)
        if owner.role != "HOST":
            raise ServiceError("Chỉ chủ phòng mới có thể tạo phòng thi.")
        required = ("name", "topic", "difficulty", "question_count", "duration_minutes", "max_participants")
        if any(not data.get(key) for key in required):
            raise ServiceError("Vui lòng điền đầy đủ thông tin phòng.")
        try:
            count, duration, maximum = (int(data["question_count"]), int(data["duration_minutes"]), int(data["max_participants"]))
        except (TypeError, ValueError) as exc:
            raise ServiceError("Số câu hỏi, thời gian và sức chứa phải là số.") from exc
        if min(count, duration, maximum) <= 0:
            raise ServiceError("Số câu hỏi, thời gian và sức chứa phải lớn hơn 0.")
        pool = self._question_pool(data["topic"], data["difficulty"])
        if len(pool) < count:
            raise ServiceError(f"Ngân hàng hiện chỉ có {len(pool)} câu phù hợp cấu hình này.")
        room = Room(
            id=self._next_id(self.rooms), name=data["name"].strip(), description=data.get("description", "").strip(),
            owner_id=owner.id, owner_name=owner.full_name, topic=data["topic"], difficulty=data["difficulty"],
            question_count=count, duration_minutes=duration, max_participants=maximum, created_at=self._now(),
        )
        self.rooms.append(room)
        self._save()
        return room

    def join_room(self, room_id: int, user_id: int) -> Room:
        room, user = self._room(room_id), self._user(user_id)
        if user.role != "STUDENT":
            raise ServiceError("Chủ phòng không thể tham gia với vai trò thí sinh.")
        if room.status != "WAITING":
            raise ServiceError("Chỉ có thể tham gia phòng đang chờ.")
        if user_id not in room.participant_ids:
            if len(room.participant_ids) >= room.max_participants:
                raise ServiceError("Phòng đã đủ số lượng thí sinh.")
            room.participant_ids.append(user_id)
            self._save()
        return room

    def leave_room(self, room_id: int, user_id: int) -> Room:
        room = self._room(room_id)
        if room.status != "WAITING":
            raise ServiceError("Không thể rời phòng sau khi bài thi bắt đầu.")
        if user_id in room.participant_ids:
            room.participant_ids.remove(user_id)
            self._save()
        return room

    def start_room(self, room_id: int, user_id: int) -> Room:
        room = self._room(room_id)
        if room.owner_id != user_id:
            raise ServiceError("Chỉ chủ phòng mới có thể bắt đầu thi.")
        if room.status != "WAITING":
            raise ServiceError("Phòng không còn ở trạng thái chờ.")
        student_count = sum(self._user(pid).role == "STUDENT" for pid in room.participant_ids)
        if student_count < 1:
            raise ServiceError("Cần ít nhất một thí sinh để bắt đầu phòng.")
        if len(self._question_pool(room.topic, room.difficulty)) < room.question_count:
            raise ServiceError("Không đủ câu hỏi phù hợp để bắt đầu phòng này.")
        room.status = "RUNNING"
        self._save()
        return room

    def end_room(self, room_id: int, user_id: int) -> Room:
        room = self._room(room_id)
        if room.owner_id != user_id:
            raise ServiceError("Chỉ chủ phòng mới có thể kết thúc phòng.")
        room.status = "ENDED"
        self._save()
        return room

    def room_participants(self, room_id: int) -> list[User]:
        room = self._room(room_id)
        return [self._user(pid) for pid in room.participant_ids]

    # Questions ----------------------------------------------------------
    def _question_pool(self, topic: str = "Trộn", difficulty: str = "Trộn") -> list[Question]:
        return [
            item for item in self.questions
            if (topic in ("Tất cả", "Trộn") or item.topic == topic)
            and (difficulty in ("Tất cả", "Trộn") or item.difficulty == difficulty)
        ]

    def get_questions(self, search: str = "", topic: str = "Tất cả", difficulty: str = "Tất cả") -> list[Question]:
        text = search.lower().strip()
        return [q for q in self._question_pool(topic, difficulty) if text in q.content.lower()]

    def save_question(self, data: dict[str, Any], question_id: int | None = None) -> Question:
        content = str(data.get("content", "")).strip()
        options = [str(value).strip() for value in data.get("options", [])]
        if not content or len(options) != 4 or any(not value for value in options):
            raise ServiceError("Câu hỏi cần nội dung và đủ 4 đáp án.")
        try:
            correct = int(data.get("correct_index"))
        except (TypeError, ValueError) as exc:
            raise ServiceError("Hãy chọn đáp án đúng.") from exc
        if correct not in range(4):
            raise ServiceError("Đáp án đúng không hợp lệ.")
        question = self._question(question_id) if question_id else Question(
            self._next_id(self.questions), content, options, correct, data["topic"], data["difficulty"], data.get("explanation", "")
        )
        question.content, question.options, question.correct_index = content, options, correct
        question.topic, question.difficulty, question.explanation = data["topic"], data["difficulty"], data.get("explanation", "")
        if question_id is None:
            self.questions.append(question)
        self._save()
        return question

    def delete_question(self, question_id: int) -> None:
        question = self._question(question_id)
        self.questions.remove(question)
        self._save()

    # Exam and history ---------------------------------------------------
    def get_exam_questions(self, topic: str, difficulty: str, count: int) -> list[Question]:
        pool = self._question_pool(topic, difficulty)
        if len(pool) < count:
            raise ServiceError(f"Không đủ câu hỏi: cần {count}, hiện có {len(pool)}.")
        return pool[:count]

    def get_room_exam(self, room_id: int, user_id: int) -> tuple[Room, list[Question]]:
        room = self._room(room_id)
        if room.status != "RUNNING" or user_id not in room.participant_ids:
            raise ServiceError("Bạn chưa có quyền làm bài trong phòng này.")
        return room, self.get_exam_questions(room.topic, room.difficulty, room.question_count)

    def submit_attempt(self, user_id: int, *, title: str, kind: str, topic: str, questions: list[Question], answers: dict[int, int], duration_seconds: int, room_id: int | None = None, auto: bool = False) -> Attempt:
        correct = sum(1 for question in questions if answers.get(question.id) == question.correct_index)
        total = len(questions)
        attempt = Attempt(
            id=self._next_id(self.attempts), user_id=user_id, title=title, kind=kind, topic=topic,
            question_ids=[question.id for question in questions], answers={str(key): value for key, value in answers.items()},
            score=round(10 * correct / total, 1) if total else 0.0, correct_count=correct, total=total,
            created_at=self._now(), duration_seconds=max(0, duration_seconds),
            status="AUTO_SUBMITTED" if auto else "SUBMITTED", room_id=room_id,
        )
        self.attempts.append(attempt)
        if room_id:
            room = self._room(room_id)
            # A local mock closes the room once its attendee has submitted.
            room.status = "ENDED"
        self._save()
        return attempt

    def get_attempt(self, attempt_id: int) -> Attempt:
        for attempt in self.attempts:
            if attempt.id == attempt_id:
                return attempt
        raise ServiceError("Không tìm thấy kết quả bài làm.")

    def history(self, user_id: int) -> list[Attempt]:
        return sorted([attempt for attempt in self.attempts if attempt.user_id == user_id], key=lambda item: item.id, reverse=True)

    def user_stats(self, user_id: int) -> dict[str, Any]:
        attempts = self.history(user_id)
        total_questions = sum(item.total for item in attempts)
        correct = sum(item.correct_count for item in attempts)
        average = round(sum(item.score for item in attempts) / len(attempts), 1) if attempts else 0
        return {"attempts": len(attempts), "average": average, "correct": correct, "total_questions": total_questions, "streak": 4}

    def host_stats(self, user_id: int) -> dict[str, int]:
        own = [room for room in self.rooms if room.owner_id == user_id]
        return {"rooms": len(own), "waiting": sum(room.status == "WAITING" for room in own), "running": sum(room.status == "RUNNING" for room in own), "students": len({pid for room in own for pid in room.participant_ids})}

    def room_results(self, room_id: int) -> list[Attempt]:
        return [attempt for attempt in self.attempts if attempt.room_id == room_id]

    # Profile ------------------------------------------------------------
    def update_profile(self, user_id: int, full_name: str, email: str) -> User:
        if not full_name.strip() or "@" not in email:
            raise ServiceError("Họ tên và email hợp lệ là bắt buộc.")
        user = self._user(user_id)
        user.full_name, user.email = full_name.strip(), email.strip()
        self._save()
        return user

    def change_password(self, user_id: int, current: str, new: str) -> None:
        user = self._user(user_id)
        if user.password != current:
            raise ServiceError("Mật khẩu hiện tại không đúng.")
        if len(new) < 6:
            raise ServiceError("Mật khẩu mới cần ít nhất 6 ký tự.")
        user.password = new
        self._save()
