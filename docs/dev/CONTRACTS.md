# tidy-one module contracts (v0.1, E1: schema + documents)

Design source: `docs/research/` (reports "개인 기기 통합 인덱싱 설계", "개인 통합 인덱싱 미디어 클라우드 확장").
Shared data model + wire format: `tidy_one/model.py` (do not change field names without updating every module).

```
device (Mac)                                         hub (VPS, 4GB)
tidy index ─ scan ─ extract ─ chunk ─ embed(fp32) ─▶ outbox/*.jsonl ─ tidy push (ssh) ─▶ tidy ingest ─▶ catalog.sqlite
                                                                                          tidy serve (MCP, 127.0.0.1) ◀─ mcp-auth-proxy ◀─ clients
                                                                                          query embed(int8)
```

## Text embedding model
- `model_id = "kure-v1"`: `nlpai-lab/KURE-v1` (MIT, bge-m3 fine-tune, 1024-d, CLS pooling, L2-normalised; verify pooling from its sentence-transformers config).
- Device embeds passages with fp32 ONNX; hub embeds queries with int8 ONNX (dynamic quantisation). Same `model_id`; vectors are compatible.
- Model files: `$TIDY_MODEL_DIR` (default `~/.cache/tidy-one/models`) / `kure-v1/{fp32,int8}/model.onnx` + `tokenizer.json`.
- Max sequence 512 tokens; chunks are ~900 chars so they fit.

## Module ownership and interfaces

### `tidy_one/text/morph.py` + `tidy_one/catalog/` (catalog owner)
- `morph(text: str) -> str` — Kiwi morphemes (content words + stems, lowercased Latin), space-joined, for FTS5 `unicode61`. Same function for documents and queries.
- `tidy_one/catalog/schema.sql` — tables from the report §"공통 스키마": `sources, cursors, documents, chunks, chunks_fts (fts5 text_morph,title), chunks_trigram (fts5 trigram over text+title), vec_text (vec0, int8[1024], cosine), vec_visual (vec0, int8[768], cosine), models`. Tombstones via `documents.deleted_at`; deleted docs never returned.
- `class Catalog(path: str)`:
  - `apply(rec: Record) -> None` — upsert document; replace its chunks atomically; insert vectors for chunks whose vectors are present (skip vectors for unknown model ids unless registered); one transaction.
  - `delete(doc_id: str, deleted_at: str) -> None` — tombstone + drop chunks/vectors.
  - `search(query: str, qvec_text: np.ndarray | None, qvec_visual: np.ndarray | None, *, kind: str | None = None, source: str | None = None, date_from: str | None = None, date_to: str | None = None, place: str | None = None, k: int = 10) -> list[dict]` — hybrid: Kiwi FTS + trigram (short/identifier-like queries) + text kNN + visual kNN, fused with RRF (k=60), grouped by `doc_id`. Each hit: `doc_id, title, uri, modality, source_id, updated_at|taken_at, score, excerpt (<=300 chars around best chunk), field, page, t_start, signals: list[str]`.
  - `fetch(doc_id: str, offset: int = 0, length: int = 4000) -> dict` — concatenated chunk text slice + document metadata.
  - `get_document(doc_id) -> dict | None`, `list_sources() -> list[dict]`, `stats() -> dict`.
  - int8 quantisation: `round(clip(v,-1,1) * 127)`; queries quantised the same way.

### `tidy_one/embed/` (embedding owner)
- `class TextEncoder(model_id: str = "kure-v1", variant: Literal["fp32","int8"] = "fp32", model_dir: str | None = None, threads: int | None = None)`
  - `encode_passages(texts: list[str], batch_size: int = 16) -> np.ndarray` (n, 1024) float32, unit norm.
  - `encode_query(text: str) -> np.ndarray` (1024,) float32, unit norm. (KURE/bge-m3 use no instruction prefix.)
  - `dim`, `model_id` attributes.
- `scripts/export_kure.py` — downloads `nlpai-lab/KURE-v1`, exports ONNX fp32, makes int8 dynamic-quantised copy, writes tokenizer.json; prints sizes; checks cosine(fp32, int8) on a few Korean/English sentences (> 0.98 expected) and agreement with sentence-transformers.
- `tidy_one/embed/fake.py` — deterministic `FakeEncoder(dim=1024)` (hash-based) for tests of other modules.

### `tidy_one/extract/` (extraction owner)
- `scan(roots: list[str], excludes: list[str]) -> Iterator[FileInfo]` where `FileInfo(path, size, mtime, ctime)`; skips hidden files/dirs, `.git`, `node_modules`, `.venv`, `__pycache__`, `~/Library`, app bundles, packages (`*.app`, `*.photoslibrary`), iCloud dataless files (`st_flags & SF_DATALESS`), files > 200MB, plus user `excludes` (glob).
- `is_secret_path(path) -> bool` — `.env*`, `*.pem`, `*.key`, `id_rsa*`, `id_ed25519*`, `*.kdbx`, `*.p12`, `*.keychain*`, names containing password/passwd/secret/credential/token (ko: 비밀번호, 암호). Secret files are never extracted or sent.
- `extract_file(path) -> Extracted(title, mime, modality, text_blocks: list[TextBlock(text, page|None)], sensitivity, extra)`; supports md/txt/csv/json/rtf/html, pdf, docx, pptx, xlsx, hwpx, hwp (best effort), else metadata-only (empty blocks).
- `chunk_blocks(blocks, max_chars=900, overlap=120) -> list[Chunk]` in `tidy_one/extract/chunk.py` — paragraph/sentence-aware for Korean (split on blank lines, `다.`, `요.`, `. `, `? `, `! `), keeps page numbers, adds one `field="meta"` chunk with title + path components + dates.
- Content sensitivity heuristic: resident registration numbers (`\d{6}-[1-4]\d{6}`), passport/card numbers → `SENS_ID`; private keys/API tokens patterns → `SENS_SECRET` (whole document skipped).

### `tidy_one/hub/` (hub owner)
- `ingest(lines: Iterable[str], catalog: Catalog) -> dict` (counts; bad lines reported, not fatal). CLI: `tidy ingest [FILE|-]`.
- `server.py`: MCP server (official `mcp` SDK, FastMCP) over streamable-http on `127.0.0.1:${TIDY_PORT:-8100}` path `/mcp`; tools:
  - `search(query: str, kind?: "text"|"image"|"video"|"audio"|"message", source?: str, date_from?: str, date_to?: str, place?: str, k: int = 10)` — embeds `query` with int8 `TextEncoder`, calls `Catalog.search`. Small input schema (<16KiB).
  - `fetch(doc_id: str, offset: int = 0, length: int = 4000)`
  - `list_sources()`, `stats()`
  - Tool descriptions in English with a Korean hint; results compact JSON text.
- Env: `TIDY_DB` (default `~/.local/share/tidy-one/catalog.sqlite`), `TIDY_MODEL_DIR`, `TIDY_PORT`.

### `tidy_one/agent/` + `tidy_one/cli.py` (agent owner)
- Config `~/.config/tidy-one/config.toml`: `device_id`, `roots`, `excludes`, `hub` (`ssh = "memory@host"`, `remote_cmd = "tidy ingest -"`), `outbox_dir`.
- `state.sqlite` per device: `path -> size, mtime, content_hash, doc_id, chunk_hashes, pushed_at`; unchanged (size, mtime) → skip; changed bytes → re-extract; changed chunks only → re-embed; vanished paths → tombstone record.
- `tidy index [--limit N] [--dry-run]` → writes `outbox/<ts>.jsonl` batches (≤ 500 records each).
- `tidy push` → streams outbox batches to hub over `ssh <target> <remote_cmd>`; moves sent batches to `outbox/sent/`. `tidy push --local DB` applies to a local catalog (for testing / Mac-local search).
- `tidy serve`, `tidy ingest`, `tidy search QUERY` (local debug, prints hits) — CLI wires hub functions.
- `client/macos/com.tidy-one.agent.plist` — launchd job: `tidy index && tidy push` every 30 min, low priority.

## Rules for every module
- Python 3.11+, type hints, no network calls in tests (use `FakeEncoder`, temp dirs).
- Do not edit `pyproject.toml` or another owner's files; if you need a dependency, say so in your final report.
- Tests in `tests/test_<module>.py`; run with `uv run pytest -q tests/test_<module>.py`.
- Never read or print secrets; never send real user file contents anywhere off this Mac.
