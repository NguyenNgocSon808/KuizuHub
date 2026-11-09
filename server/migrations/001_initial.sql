PRAGMA foreign_keys = ON;

CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'STUDENT' CHECK (role IN ('STUDENT', 'HOST', 'ADMIN')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL,
    revoked_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE questions (
    id INTEGER PRIMARY KEY,
    content TEXT NOT NULL,
    topic TEXT NOT NULL,
    difficulty TEXT NOT NULL CHECK (difficulty IN ('easy', 'medium', 'hard')),
    correct_option_id INTEGER,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE question_options (
    id INTEGER PRIMARY KEY,
    question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    label TEXT NOT NULL CHECK (label IN ('A', 'B', 'C', 'D')),
    content TEXT NOT NULL,
    position INTEGER NOT NULL CHECK (position BETWEEN 1 AND 4),
    UNIQUE (question_id, label),
    UNIQUE (question_id, position)
);

CREATE TABLE exam_rooms (
    id INTEGER PRIMARY KEY,
    owner_id INTEGER NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'WAITING' CHECK (status IN ('WAITING', 'RUNNING', 'ENDED')),
    duration_seconds INTEGER NOT NULL CHECK (duration_seconds > 0),
    started_at TEXT,
    ended_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE room_question_rules (
    room_id INTEGER NOT NULL REFERENCES exam_rooms(id) ON DELETE CASCADE,
    topic TEXT NOT NULL,
    difficulty TEXT NOT NULL CHECK (difficulty IN ('easy', 'medium', 'hard')),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    PRIMARY KEY (room_id, topic, difficulty)
);

CREATE TABLE room_questions (
    room_id INTEGER NOT NULL REFERENCES exam_rooms(id) ON DELETE CASCADE,
    question_id INTEGER NOT NULL REFERENCES questions(id),
    position INTEGER NOT NULL CHECK (position > 0),
    content_snapshot TEXT NOT NULL,
    correct_option_snapshot INTEGER NOT NULL,
    PRIMARY KEY (room_id, question_id),
    UNIQUE (room_id, position)
);

CREATE TABLE room_participants (
    room_id INTEGER NOT NULL REFERENCES exam_rooms(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    state TEXT NOT NULL DEFAULT 'JOINED' CHECK (state IN ('JOINED', 'IN_PROGRESS', 'SUBMITTED', 'AUTO_SUBMITTED')),
    submitted_at TEXT,
    score REAL,
    correct_count INTEGER,
    PRIMARY KEY (room_id, user_id)
);

CREATE TABLE attempt_answers (
    room_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    question_id INTEGER NOT NULL REFERENCES questions(id),
    selected_option_id INTEGER NOT NULL REFERENCES question_options(id),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (room_id, user_id, question_id),
    FOREIGN KEY (room_id, user_id) REFERENCES room_participants(room_id, user_id) ON DELETE CASCADE
);

CREATE TABLE practice_attempts (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    score REAL NOT NULL,
    correct_count INTEGER NOT NULL,
    total INTEGER NOT NULL CHECK (total > 0),
    duration_seconds INTEGER NOT NULL CHECK (duration_seconds >= 0),
    configuration_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE activity_logs (
    id INTEGER PRIMARY KEY,
    actor_id INTEGER REFERENCES users(id),
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_users_username ON users(username);
CREATE INDEX idx_sessions_token_hash ON sessions(token_hash);
CREATE INDEX idx_exam_rooms_status ON exam_rooms(status);
CREATE INDEX idx_room_participants_room_user ON room_participants(room_id, user_id);
CREATE INDEX idx_attempt_answers_room_user_question ON attempt_answers(room_id, user_id, question_id);
