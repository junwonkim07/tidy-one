-- tidy-one hub catalog (schema v1). Requires sqlite-vec loaded and SQLite >= 3.43.

-- Explicit INTEGER PRIMARY KEYs keep rowids stable across VACUUM: vec0 rows refer to them.
CREATE TABLE IF NOT EXISTS sources (
  id INTEGER PRIMARY KEY,
  source_id TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL,
  account TEXT,
  workspace TEXT,
  device_id TEXT,
  default_visibility TEXT NOT NULL DEFAULT 'private',
  enabled INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS cursors (
  source_id TEXT NOT NULL,
  cursor_kind TEXT NOT NULL,
  value TEXT,
  updated_at TEXT,
  PRIMARY KEY (source_id, cursor_kind)
);

-- id survives upserts (ON CONFLICT DO UPDATE); vec_visual rowids are (documents.id << 12) + frame index.
CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY,
  doc_id TEXT NOT NULL UNIQUE,
  source_id TEXT NOT NULL,
  native_id TEXT NOT NULL,
  modality TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  uri TEXT NOT NULL DEFAULT '',
  mime TEXT,
  author TEXT,
  participants TEXT,
  created_at TEXT,
  updated_at TEXT,
  taken_at TEXT,
  duration_s REAL,
  geo_cell TEXT,
  place_ko TEXT,
  place_en TEXT,
  persons TEXT,
  labels TEXT,
  size_bytes INTEGER,
  content_hash TEXT,
  phash TEXT,
  parent_id TEXT,
  device_id TEXT,
  visibility TEXT NOT NULL DEFAULT 'private',
  sensitivity INTEGER NOT NULL DEFAULT 0,
  extra_json TEXT NOT NULL DEFAULT '{}',
  n_frames INTEGER NOT NULL DEFAULT 0,
  ingested_at TEXT,
  deleted_at TEXT,
  sort_at TEXT GENERATED ALWAYS AS (coalesce(taken_at, updated_at, created_at)) VIRTUAL
);
CREATE INDEX IF NOT EXISTS documents_source ON documents(source_id);
CREATE INDEX IF NOT EXISTS documents_taken ON documents(taken_at);
CREATE INDEX IF NOT EXISTS documents_updated ON documents(updated_at);
CREATE INDEX IF NOT EXISTS documents_deleted ON documents(deleted_at);
CREATE INDEX IF NOT EXISTS documents_sort ON documents(sort_at);
CREATE INDEX IF NOT EXISTS documents_modality ON documents(modality);

-- id is the rowid shared with chunks_fts, chunks_trigram and vec_text.
CREATE TABLE IF NOT EXISTS chunks (
  id INTEGER PRIMARY KEY,
  chunk_id TEXT NOT NULL UNIQUE,
  doc_id TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
  ordinal INTEGER NOT NULL,
  field TEXT NOT NULL DEFAULT 'body',
  page INTEGER,
  t_start REAL,
  t_end REAL,
  text TEXT NOT NULL,
  text_morph TEXT NOT NULL,
  chunk_hash TEXT,
  token_count INTEGER
);
CREATE INDEX IF NOT EXISTS chunks_doc ON chunks(doc_id);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
  text_morph, title,
  content='', contentless_delete=1,
  tokenize="unicode61 remove_diacritics 2 tokenchars '_'"
);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_trigram USING fts5(
  text, title,
  content='', contentless_delete=1,
  tokenize='trigram'
);

-- int8 vectors from unit-norm floats, so L2 ranks like cosine; sqlite-vec's int8 L2 path is
-- SIMD (~3x faster than int8 cosine at 30k rows). Metadata mirrors documents so filters run inside
-- the kNN scan: source_n = sources.id, day = YYYYMMDD of coalesce(taken_at, updated_at,
-- created_at), 0 when unknown (integers: long TEXT metadata is slow to compare in vec0).
CREATE VIRTUAL TABLE IF NOT EXISTS vec_text USING vec0(
  embedding int8[1024],
  model_id TEXT PARTITION KEY,
  modality TEXT,
  source_n INTEGER,
  day INTEGER
);

CREATE VIRTUAL TABLE IF NOT EXISTS vec_visual USING vec0(
  embedding int8[768],
  model_id TEXT PARTITION KEY,
  modality TEXT,
  source_n INTEGER,
  day INTEGER,
  +frame_id TEXT,
  +t_sec float
);

CREATE TABLE IF NOT EXISTS models (
  model_id TEXT PRIMARY KEY,
  space TEXT NOT NULL,
  dim INTEGER NOT NULL,
  quant TEXT NOT NULL DEFAULT 'int8',
  active INTEGER NOT NULL DEFAULT 0,
  seen_at TEXT
);
INSERT OR IGNORE INTO models(model_id, space, dim, quant, active) VALUES ('kure-v1', 'text', 1024, 'int8', 1);

PRAGMA user_version = 1;
