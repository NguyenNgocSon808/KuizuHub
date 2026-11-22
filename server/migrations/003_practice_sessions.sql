CREATE TABLE practice_sessions (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    state TEXT NOT NULL DEFAULT 'IN_PROGRESS' CHECK (state IN ('IN_PROGRESS', 'SUBMITTED', 'AUTO_SUBMITTED')),
    topic TEXT NOT NULL,
    difficulty TEXT NOT NULL CHECK (difficulty IN ('easy', 'medium', 'hard')),
    question_count INTEGER NOT NULL CHECK (question_count > 0),
    duration_seconds INTEGER NOT NULL CHECK (duration_seconds > 0),
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ended_at TEXT NOT NULL,
    submitted_at TEXT,
    score REAL,
    correct_count INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE practice_session_questions (
    session_id INTEGER NOT NULL REFERENCES practice_sessions(id) ON DELETE CASCADE,
    question_id INTEGER NOT NULL REFERENCES questions(id),
    position INTEGER NOT NULL CHECK (position > 0),
    content_snapshot TEXT NOT NULL,
    correct_option_position INTEGER NOT NULL CHECK (correct_option_position BETWEEN 1 AND 4),
    PRIMARY KEY (session_id, question_id),
    UNIQUE (session_id, position)
);

CREATE TABLE practice_session_options (
    session_id INTEGER NOT NULL,
    question_id INTEGER NOT NULL,
    position INTEGER NOT NULL CHECK (position BETWEEN 1 AND 4),
    label TEXT NOT NULL CHECK (label IN ('A', 'B', 'C', 'D')),
    content_snapshot TEXT NOT NULL,
    PRIMARY KEY (session_id, question_id, position),
    FOREIGN KEY (session_id, question_id)
        REFERENCES practice_session_questions(session_id, question_id) ON DELETE CASCADE
);

CREATE TABLE practice_answers (
    session_id INTEGER NOT NULL,
    question_id INTEGER NOT NULL,
    selected_option_position INTEGER NOT NULL CHECK (selected_option_position BETWEEN 1 AND 4),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (session_id, question_id),
    FOREIGN KEY (session_id, question_id)
        REFERENCES practice_session_questions(session_id, question_id) ON DELETE CASCADE
);

CREATE INDEX idx_practice_sessions_user_state ON practice_sessions(user_id, state);
CREATE INDEX idx_practice_answers_session_question ON practice_answers(session_id, question_id);
