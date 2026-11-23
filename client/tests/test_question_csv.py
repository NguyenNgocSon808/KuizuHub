from __future__ import annotations

from pathlib import Path

import pytest

from client.app.ui.phase1_main_window import QuestionBankPage


def test_csv_question_rows_accepts_letter_or_numeric_correct_answer_and_reports_line(tmp_path: Path) -> None:
    valid_path = tmp_path / "questions.csv"
    valid_path.write_text(
        "content,topic,difficulty,option_a,option_b,option_c,option_d,correct_option_index,explanation\n"
        "TCP uses which transport?,TCP Socket,easy,UDP,TCP,ICMP,ARP,B,Connection oriented\n"
        "Which port is HTTPS?,HTTP/HTTPS,medium,20,21,443,53,2,Well-known port\n",
        encoding="utf-8",
    )

    rows = QuestionBankPage._csv_question_rows(str(valid_path))

    assert [row["correct_option_index"] for row in rows] == [1, 2]
    assert rows[0]["options"] == ["UDP", "TCP", "ICMP", "ARP"]

    invalid_path = tmp_path / "invalid.csv"
    invalid_path.write_text(
        "content,topic,difficulty,option_a,option_b,option_c,option_d,correct_option_index\n"
        "Broken,TCP Socket,unknown,A,B,C,D,0\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Dòng 2"):
        QuestionBankPage._csv_question_rows(str(invalid_path))
