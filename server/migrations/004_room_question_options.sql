CREATE TABLE room_question_options (
    room_id INTEGER NOT NULL,
    question_id INTEGER NOT NULL,
    option_id_snapshot INTEGER NOT NULL,
    position INTEGER NOT NULL CHECK (position BETWEEN 1 AND 4),
    label TEXT NOT NULL CHECK (label IN ('A', 'B', 'C', 'D')),
    content_snapshot TEXT NOT NULL,
    PRIMARY KEY (room_id, question_id, position),
    UNIQUE (room_id, question_id, option_id_snapshot),
    FOREIGN KEY (room_id, question_id)
        REFERENCES room_questions(room_id, question_id) ON DELETE CASCADE
);

CREATE INDEX idx_room_question_options_room_question
    ON room_question_options(room_id, question_id, position);
