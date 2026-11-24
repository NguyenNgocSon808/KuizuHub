/*
 * Keep profile data and question taxonomy immutable enough for analytics.
 * Existing rows receive empty snapshots and the query layer falls back to the
 * current question metadata for historical databases created before Phase 3.
 */
ALTER TABLE users ADD COLUMN display_name TEXT NOT NULL DEFAULT '';

ALTER TABLE room_questions ADD COLUMN topic_snapshot TEXT NOT NULL DEFAULT '';
ALTER TABLE room_questions ADD COLUMN difficulty_snapshot TEXT NOT NULL DEFAULT '';

ALTER TABLE practice_session_questions ADD COLUMN topic_snapshot TEXT NOT NULL DEFAULT '';
ALTER TABLE practice_session_questions ADD COLUMN difficulty_snapshot TEXT NOT NULL DEFAULT '';

CREATE INDEX idx_room_participants_user_state
    ON room_participants(user_id, state, submitted_at);
CREATE INDEX idx_practice_sessions_user_state_submitted
    ON practice_sessions(user_id, state, submitted_at);
