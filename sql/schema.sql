-- Schéma de la base de résultats

-- Une ligne = combien de publications citent un hashtag ou un domaine pour une plateforme et un jour donnés
CREATE TABLE IF NOT EXISTS daily_counts (
	day        DATE    NOT NULL,
	platform   TEXT    NOT NULL,
	kind       TEXT    NOT NULL CHECK (kind IN ('hashtag', 'domain')),
	value      TEXT    NOT NULL,
	posts      INTEGER NOT NULL CHECK (posts >= 0),
	originals  INTEGER NOT NULL CHECK (originals >= 0 AND originals <= posts),

	-- clé primaire interdit doublons
	PRIMARY KEY (day, platform, kind, value)
);

CREATE TABLE IF NOT EXISTS tasks (
    platform      TEXT        NOT NULL,
    day           DATE        NOT NULL,
    object_key    TEXT        NOT NULL,
    status        TEXT        NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending', 'done', 'failed')),
    attempts      INTEGER     NOT NULL DEFAULT 0,
    available_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_error    TEXT,
    worker_id     TEXT,
    stats         JSONB,
    ...
    PRIMARY KEY (platform, day)
);

CREATE INDEX IF NOT EXISTS tasks_pending_idx ON tasks (available_at) WHERE status = 'pending';