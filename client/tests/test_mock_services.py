from pathlib import Path

import pytest

from client.app.config import DATA_DIR
from client.app.services import MockApiService, ServiceError


@pytest.fixture()
def service(tmp_path: Path) -> MockApiService:
    return MockApiService(data_dir=tmp_path, seed_dir=DATA_DIR)


def test_demo_login_and_invalid_password(service: MockApiService) -> None:
    assert service.login("bao", "123456").role == "STUDENT"
    assert service.login("son", "123456").role == "HOST"
    with pytest.raises(ServiceError):
        service.login("bao", "wrong")


def test_host_creates_room_and_student_joins(service: MockApiService) -> None:
    host, student = service.login("son", "123456"), service.login("bao", "123456")
    room = service.create_room(host.id, {"name": "Kiểm tra HTTP", "description": "", "topic": "HTTP/HTTPS", "difficulty": "Dễ", "question_count": 3, "duration_minutes": 10, "max_participants": 5})
    assert room.status == "WAITING"
    assert student.id not in room.participant_ids
    service.join_room(room.id, student.id)
    assert student.id in service._room(room.id).participant_ids
    service.start_room(room.id, host.id)
    assert service._room(room.id).status == "RUNNING"
    with pytest.raises(ServiceError):
        service.create_room(student.id, {"name": "Sai quyền", "topic": "UDP", "difficulty": "Dễ", "question_count": 1, "duration_minutes": 10, "max_participants": 2})


def test_scoring_uses_latest_answer(service: MockApiService) -> None:
    student = service.login("bao", "123456")
    questions = service.get_exam_questions("TCP Socket", "Trộn", 3)
    answers = {question.id: question.correct_index for question in questions}
    answers[questions[0].id] = 0  # one deliberate last-answer change
    attempt = service.submit_attempt(student.id, title="Practice", kind="Luyện tập", topic="TCP Socket", questions=questions, answers=answers, duration_seconds=90)
    expected = sum(question.correct_index == answers[question.id] for question in questions)
    assert attempt.correct_count == expected
    assert attempt.score == round(10 * expected / len(questions), 1)
