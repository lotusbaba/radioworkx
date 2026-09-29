
CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS user_sessions (digest TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, expires REAL NOT NULL);
CREATE INDEX IF NOT EXISTS user_session_expiry ON user_sessions(expires);
CREATE TABLE IF NOT EXISTS account_attempts (bucket TEXT NOT NULL, created REAL NOT NULL);
CREATE INDEX IF NOT EXISTS account_attempt_bucket ON account_attempts(bucket,created);
CREATE TABLE IF NOT EXISTS user_likes (user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, track_id TEXT NOT NULL REFERENCES tracks(id), created REAL NOT NULL, PRIMARY KEY(user_id,track_id));
CREATE TABLE IF NOT EXISTS user_playlists (id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, name TEXT NOT NULL, created REAL NOT NULL);
CREATE INDEX IF NOT EXISTS user_playlist_owner ON user_playlists(user_id);
CREATE TABLE IF NOT EXISTS user_playlist_tracks (playlist_id TEXT NOT NULL REFERENCES user_playlists(id) ON DELETE CASCADE, track_id TEXT NOT NULL REFERENCES tracks(id), position INTEGER NOT NULL, PRIMARY KEY(playlist_id,track_id));

CREATE TABLE IF NOT EXISTS personal_downloads (listener TEXT NOT NULL, created REAL NOT NULL);
CREATE INDEX IF NOT EXISTS personal_download_time ON personal_downloads(created);
CREATE TABLE IF NOT EXISTS failed_downloads (
 id TEXT PRIMARY KEY, job_id TEXT NOT NULL, track_id TEXT NOT NULL,
 kind TEXT NOT NULL, source_url TEXT, page_url TEXT, error_type TEXT NOT NULL,
 error_detail TEXT NOT NULL, created REAL NOT NULL, replacement_id TEXT,
 UNIQUE(job_id,track_id)
);
CREATE TABLE IF NOT EXISTS app_tokens (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, digest TEXT NOT NULL UNIQUE,
 created REAL NOT NULL, last_used REAL, revoked REAL
);
CREATE TABLE IF NOT EXISTS tracks (
 id TEXT PRIMARY KEY, metadata TEXT NOT NULL, source TEXT, rights TEXT,
 status TEXT NOT NULL DEFAULT 'available', duration REAL, path TEXT, error TEXT,
 downloaded_at REAL
);
CREATE TABLE IF NOT EXISTS playlist (
 position INTEGER PRIMARY KEY AUTOINCREMENT, track_id TEXT UNIQUE REFERENCES tracks(id), priority INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS plays (
 id TEXT PRIMARY KEY, track_id TEXT NOT NULL, metadata TEXT NOT NULL,
 starts REAL NOT NULL, ends REAL NOT NULL, actual_end REAL
);
CREATE TABLE IF NOT EXISTS outbox (
 id TEXT PRIMARY KEY, queue TEXT NOT NULL, body TEXT NOT NULL,
 created REAL NOT NULL, sent REAL, done REAL, failed TEXT
);
CREATE TABLE IF NOT EXISTS reactions (
 id TEXT PRIMARY KEY, play_id TEXT NOT NULL, listener TEXT NOT NULL, emoji TEXT NOT NULL,
 accepted REAL NOT NULL, metadata TEXT NOT NULL, processed INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS requests (
 sequence INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, listener TEXT NOT NULL,
 query TEXT NOT NULL, mode TEXT NOT NULL, response TEXT NOT NULL, track_id TEXT REFERENCES tracks(id),
 status TEXT NOT NULL, created REAL NOT NULL, play_id TEXT
);
CREATE INDEX IF NOT EXISTS request_pending ON requests(status,sequence);
CREATE TABLE IF NOT EXISTS conversations (listener TEXT PRIMARY KEY, genres TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rag_embeddings (track_id TEXT PRIMARY KEY, model TEXT NOT NULL, digest TEXT NOT NULL, vector TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rag_pending (listener TEXT PRIMARY KEY, genres TEXT NOT NULL, track_ids TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rag_turns (id TEXT PRIMARY KEY, listener TEXT NOT NULL, created REAL NOT NULL, busy INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS announcements (id TEXT PRIMARY KEY, track_id TEXT NOT NULL, script TEXT NOT NULL, details TEXT NOT NULL, path TEXT NOT NULL, duration REAL NOT NULL, created REAL NOT NULL, voice TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS source_hosts (hostname TEXT PRIMARY KEY, provider TEXT NOT NULL, role TEXT NOT NULL, status TEXT NOT NULL, discovered_from TEXT, notes TEXT NOT NULL DEFAULT '', first_seen REAL NOT NULL, last_seen REAL NOT NULL, tracks_downloaded INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS host_downloads (track_id TEXT PRIMARY KEY, source_host TEXT NOT NULL, media_host TEXT, completed REAL NOT NULL);
CREATE TABLE IF NOT EXISTS crawl_frontier (url TEXT PRIMARY KEY, provider TEXT NOT NULL, genre TEXT, depth INTEGER NOT NULL DEFAULT 0, discovered_from TEXT, next_attempt REAL NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'pending', error TEXT);
CREATE TABLE IF NOT EXISTS crawl_runs (id TEXT PRIMARY KEY, started REAL NOT NULL, finished REAL, pages INTEGER NOT NULL DEFAULT 0, tracks INTEGER NOT NULL DEFAULT 0, errors INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS media_objects (object_key TEXT PRIMARY KEY, track_id TEXT NOT NULL, kind TEXT NOT NULL, path TEXT NOT NULL, mime TEXT NOT NULL, checked REAL);
CREATE TABLE IF NOT EXISTS track_visuals (track_id TEXT PRIMARY KEY, status TEXT NOT NULL, created REAL NOT NULL, submitted REAL, completed REAL, provider_id TEXT, artwork_source TEXT, artwork_key TEXT, video_key TEXT, error TEXT);
CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, body TEXT NOT NULL, done INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS reaction_play ON reactions(play_id,processed);
CREATE INDEX IF NOT EXISTS play_time ON plays(ends);
