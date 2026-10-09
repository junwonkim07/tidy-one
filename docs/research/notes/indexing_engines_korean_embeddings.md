# Indexing / Retrieval Engine Layer for a Personal Multi-Device Korean File & Notes Index

Research date: 2026-10-10. User context carried through: MacBook (Apple Silicon), Windows laptop, iPhone, Vultr VPS (1 vCPU / 2 GB RAM, Ubuntu 24.04). Currently on Basic Memory 0.23.2 (SQLite FTS + sqlite-vec, FastEmbed `paraphrase-multilingual-MiniLM-L12-v2`, 384-d) over a git repo of markdown. Sources dated before 2025 are flagged "(pre-2025, possibly outdated)". Licenses marked "(not re-verified)" come from general knowledge, not from a page fetched in this session.

---

## 1. Search engines / vector stores that fit a 2 GB VPS and laptops (RAM, hybrid, Korean analysis, incremental updates, license)

### Takeaway
For a personal corpus (thousands to low hundreds of thousands of chunks), embedded engines (SQLite FTS5 + sqlite-vec, LanceDB) fit the 2 GB VPS comfortably; Qdrant also fits with mmap. Meilisearch, Typesense with built-in models, and Elasticsearch/OpenSearch are too heavy for 2 GB once an embedding model shares the box. The real gap is **Korean keyword search**: plain SQLite FTS5 has no Korean morphological analysis (unicode61 indexes whole space-separated eojeol, and trigram cannot match 2-syllable words). Engines with built-in Korean analysis are LanceDB (`lindera/ko-dic`), Meilisearch (charabia + lindera ko-dic), Qdrant ≥1.15 (multilingual tokenizer), Elasticsearch/OpenSearch (nori), and PGroonga. With SQLite you get Korean analysis by pre-tokenizing with Kiwi or mecab-ko outside the database.

### Cited Findings

**SQLite FTS5 (+ sqlite-vec), which Basic Memory and qmd already use**
- FTS5 `unicode61` tokenizer: "Each contiguous run of one or more token characters is considered to be a token". Separators are space and punctuation, and letters (category L, which includes Hangul) are token characters. — [SQLite FTS5 docs](https://www.sqlite.org/fts5.html)
- FTS5 `trigram` tokenizer: "Substrings consisting of fewer than 3 unicode characters do not match any rows when used with a full-text query". It also supports indexed LIKE/GLOB unless `remove_diacritics` is set. — [SQLite FTS5 docs](https://www.sqlite.org/fts5.html). Trigram has been built in since SQLite 3.34.0 (Dec 2020) — [simonw/sqlite-fts5-trigram](https://github.com/simonw/sqlite-fts5-trigram) (pre-2025)
- FTS5 has a custom tokenizer API (`fts5_tokenizer_v2`, registered via `xCreateTokenizer_v2()`), so a Korean morphological tokenizer can be plugged in at the C level. — [SQLite FTS5 docs](https://www.sqlite.org/fts5.html)
- sqlite-vec: stores float, int8, and binary vectors in `vec0` virtual tables, with metadata, auxiliary, and partition-key columns. The source tree now contains IVF-kmeans and DiskANN implementations (the IVF one appears experimental), alongside brute force. It is "pre-v1, so expect breaking changes". License is Apache-2.0/MIT dual. It runs on Linux/macOS/Windows/WASM, with Mozilla Builders support and sponsorship from Fly.io, Turso, and SQLite Cloud. — [asg017/sqlite-vec](https://github.com/asg017/sqlite-vec)
- sqlite-vec v0.1.6+ added metadata/partition/aux columns. A v0.1.9 upgrade appeared in downstream packaging in April 2026. For binary quantization the recommended pattern is to search a coarse binary index and then re-score the top candidates at full precision. — [sqlite-vec skill/README summary](https://skills.sh/harlan-zw/skilld/sqlite-vec-skilld), [cznic/sqlite changelog](https://gitlab.com/cznic/sqlite/compare/v1.45.0...v1.53.0) (secondary sources)
- Korean morphology matters for BM25. Basic BM25 keeps "금융보험" as one token, while Kiwi (kiwipiepy) splits it into ["금융", "보험"]. Korean LangChain tutorials use a `KiwiBM25Retriever` for this reason. — [WikiDocs: 한글 형태소 분석기와 BM25Retriever의 결합](https://wikidocs.net/251980), [WikiDocs Ensemble Retriever](https://wikidocs.net/231609)

**LanceDB (embedded, columnar; Python/TS/Rust)**
- FTS `base_tokenizer` options include `simple` (default), `icu`, `jieba/default`, `lindera/ipadic` (Japanese), and **`lindera/ko-dic` (Korean)**. The Lindera model must be installed and compiled, and its location is pointed to with `LANCE_LANGUAGE_MODEL_HOME`. Calling `table.optimize()` folds new rows into existing FTS and vector indexes (incremental updates). — [LanceDB FTS docs](https://docs.lancedb.com/search/full-text-search.md)
- Hybrid search runs FTS and vector search in parallel and combines them with RRF or weighted rerankers. — [LanceDB FTS](https://lancedb.com/docs/search/full-text-search), [Agno LanceDB hybrid example](https://docs.agno.com/knowledge/vector-stores/lancedb/usage/lance-db-hybrid-search)
- Lindera is a pure-Rust morphological analyzer for Japanese, Chinese, and Korean, used as a Tantivy tokenizer (for example the `lindera-tantivy` / `flutter_lindera_tantivy` packages). — [pub.dev flutter_lindera_tantivy](https://pub.dev/documentation/flutter_lindera_tantivy/latest/), [openapps lindera](https://openapps.pro/packages/lindera)
- License: Apache-2.0 (not re-verified).

**Qdrant (server, Rust)**
- Memory article from Dec 2022 (pre-2025, possibly outdated), 1M vectors × 100-d (glove): about 1.2 GB fully in RAM (OOM below that) at ~780 RPS. With vectors on mmap it needs ~600 MB minimum. With vectors and HNSW both on mmap it needs ~135 MB (OOM below 125 MB), at 0.33–50 RPS depending on disk IOPS. — [Qdrant: Minimal RAM to serve 1M vectors](https://qdrant.tech/articles/memory-consumption/)
- Current docs: quantization keeps a compressed copy in RAM and moves originals to disk. "TurboQuant" bits4 gives roughly 8× compression, and float16/int8 datatypes halve or quarter vector RAM. — [Qdrant: When your collection outgrows RAM](https://qdrant.tech/documentation/search-tuning/when-your-collection-outgrows-ram/), [Qdrant memory skill](https://skills.qdrant.tech/md/articles/memory-consumption/)
- Qdrant 1.15 (18 Jul 2025) reworked multilingual tokenization. Charabia had "significant memory overhead" for Korean and Japanese, so it had not been on by default. Korean, Japanese, and Chinese full-text indexing now ships in the main build, and stopwords plus Snowball stemming were added. — [Qdrant 1.15 blog](https://qdrant.tech/blog/qdrant-1.15.x/)
- Qdrant Edge has a built-in BM25 embedder with tokenizer `prefix|whitespace|word|multilingual`. — [Qdrant Edge BM25](https://qdrant.tech/documentation/edge/edge-bm25/)
- License: Apache-2.0 (not re-verified).

**Meilisearch**
- Korean goes through Charabia with "lindera KO dictionary segmentation" and "Decomposition" normalization, detected automatically. For multilingual data the docs recommend hybrid search with a multilingual embedder plus `localizedAttributes`. — [Meilisearch language docs](https://www.meilisearch.com/docs/learn/resources/language)
- Charabia's Korean pipeline is in the lowest throughput tier, about 2 MiB/s for segmentation and tokenization. — [charabia crate docs](https://docs.rs/crate/charabia/latest)
- RAM: the official docs say a RAM-to-disk ratio of about 1/3, often down to 1/10, works. `--max-indexing-memory` caps indexing RAM, and indexing uses at most two-thirds of available resources by default. — [Meilisearch storage/RAM docs](https://www.meilisearch.com/docs/resources/self_hosting/performance/ram_multithreading). A hosting provider lists 2 vCPU / 4 GB as minimum (third-party, unverified) — [vpsnet Meilisearch](https://www.vpsnet.com/en/applications/meilisearch)
- Since v1.8, hybrid search supports REST embedders and local Ollama embedders. — [Meilisearch releases](https://github.com/meilisearch/MeiliSearch/releases?page=1)

**Typesense**
- Typesense is fully in-memory. It needs 2–3× the searchable field size in RAM, and the process idles at about 20 MB. Vectors cost 7 bytes × dims × records (e.g. 384-d × 100k = 268.8 MB). **Built-in ML models (S-BERT/E5) need an extra 2–6 GB RAM.** — [Typesense system requirements](https://typesense.org/docs/guide/system-requirements.html)
- Korean (`ko` locale) uses ICU segmentation. The docs mention no morphological analysis. — [Typesense locale guide](https://typesense.org/docs/guide/locale.html). Meilisearch's comparison says Typesense's Unicode-based tokenization "struggles with languages that lack conventional word spacing or have rich morphology". This is a competitor's claim. — [Meilisearch vs Typesense](https://meilisearch.com/docs/resources/comparisons/typesense)
- License: GPL-3.0 (not re-verified).

**PostgreSQL + pgvector + PGroonga**
- PGroonga provides full-text search for all languages including CJK out of the box. Native Postgres FTS is "limited to alphabet and digit based languages". — [Supabase PGroonga docs](https://supabase.com/docs/guides/database/extensions/pgroonga.md). PGroonga 4.0.4 has been released — [postgresql.org news](https://www.postgresql.org/about/news/pgroonga-404-multilingual-fast-full-text-search-3150)
- Combined PGroonga + pgvector Docker images exist for hybrid search. — [Docker Hub cubeplex/postgresql-pgroonga-pgvector](https://hub.docker.com/r/cubeplex/postgresql-pgroonga-pgvector/tags)
- Basic Memory's Postgres backend supports pgvector (default) or Milvus via `semantic_vector_index`. — [Basic Memory v0.23](https://docs.basicmemory.com/whats-new/v0-23)

**Elasticsearch / OpenSearch + nori**
- `analysis-nori` has been the official Korean plugin since ES 6.4. It uses the mecab-ko-dic dictionary, supports user dictionaries, and offers `decompound_mode` none/discard (default)/mixed. — [Elastic blog: Nori](https://www.elastic.co/blog/nori-the-official-elasticsearch-plugin-for-korean-language-analysis) (2018, pre-2025), [nori tokenizer docs 8.19](https://www.elastic.co/guide/en/elasticsearch/plugins/8.19/analysis-nori-tokenizer.html)
- Heap: the default is 1 GB min/max in the 7.x docs. Keep the heap at or below 50% of RAM, because ES also needs off-heap buffers and the OS filesystem cache. — [ES heap size docs 7.x](https://www.elastic.co/guide/en/elasticsearch/reference/7.8/heap-size.html) (pre-2025)

### Inferences
- **Korean keyword search in SQLite.** With unicode61, a Korean token is a whole eojeol (word plus particle, e.g. "검색엔진을"). The query "검색엔진" matches only with a prefix query (`검색엔진*`), and a compound like "금융보험" never matches "보험". Trigram fails on any 2-syllable query (검색, 회의, 보험), which covers a large share of Korean nouns. Practical fix: run Kiwi or mecab-ko in the indexer and store a space-joined morpheme column in FTS5, tokenized the same way at query time. A C-level `fts5_tokenizer_v2` would also work but is harder to ship to Mac, Windows, and the VPS. A cheaper fallback is two FTS columns (unicode61 + trigram) plus a LIKE scan for short queries.
- **Vector storage is small at personal scale.** 50k chunks × 1024-d float32 ≈ 205 MB, int8 ≈ 51 MB, binary ≈ 6.4 MB. At 384-d float32 it is ≈ 77 MB. sqlite-vec brute-force KNN over that is fine, so no ANN index or vector server is needed.
- **2 GB VPS fit** (rough order, assuming the embedding model must also run there for queries):

| Engine | Fits 2 GB with an embed model? | Korean keyword analysis | Hybrid built in | Incremental |
|---|---|---|---|---|
| SQLite FTS5 + sqlite-vec | Yes (tens of MB) | None built in; Kiwi/mecab pre-tokenization | Do it yourself (RRF in app) | Yes (row level) |
| LanceDB (embedded) | Yes | lindera/ko-dic | Yes (RRF) | `optimize()` |
| Qdrant | Yes with mmap/quantization (~100–300 MB at this scale) | multilingual tokenizer (≥1.15); BM25 as sparse | Yes (query API fusion) | Yes |
| PG + pgvector + PGroonga | Marginal (Postgres ~200–400 MB tuned) | PGroonga (N-gram/MeCab) | Do it yourself in SQL | Yes |
| Meilisearch | Tight; vendor guidance favors ≥4 GB | lindera ko-dic (slow, ~2 MiB/s) | Yes | Yes |
| Typesense (built-in model) | No (+2–6 GB for model) | ICU only | Yes | Yes |
| Elasticsearch/OpenSearch + nori | No (≥1 GB heap plus FS cache) | Best (nori) | Yes | Yes |

- Because the Mac and Windows laptops also need search, an **embedded single-file index** (SQLite or Lance) that a server can host or that devices can sync is simpler than a server engine.

### Gaps
- No fresh Qdrant RAM benchmark for 1024-d vectors at about 50k points. The 2022 article is the only number.
- Could not confirm whether Qdrant 1.15's Korean tokenizer does morphological analysis or only segmentation, or which library replaced charabia.
- No measurement found of LanceDB `lindera/ko-dic` install friction on Windows, or of its memory use.
- Licenses for Meilisearch (MIT CE vs BUSL enterprise features), Typesense, Tantivy/Quickwit, PGroonga, and ES (AGPL/SSPL/ELv2) were not re-verified.
- No source found for Tantivy/Quickwit resource use or `textsearch_ko` (mecab-ko for Postgres) status in 2026.
- Kiwi (kiwipiepy) license and speed were not verified.

---

## 2. Local file-indexing tools, reusing OS indexes, and content extraction (incl. Korean OCR)

### Takeaway
OS indexes can tell an indexer **what changed and where files are**, but they cannot provide clean text, chunks, or embeddings. Spotlight (`mdfind`) and Windows Search (`SystemIndex` via OLE DB) can be queried read-only. Everything is filename-oriented. A custom indexer should piggyback on them only for discovery and change detection, and run its own extraction. For extraction: markitdown (MIT, many formats, MCP) is the lightest, and docling has the strongest PDF/OCR pipeline with Apple Vision (`ocrmac`) and PP-OCR backends that support Korean. Korean HWP/HWPX needs a dedicated tool such as kordoc.

### Cited Findings
- **macOS Spotlight**: `mdfind` queries the central metadata store and returns matching file paths. Content can be searched with `kMDItemTextContent == "...*"cdw`, and CJK queries work. — [mdfind man page (Oracle mirror)](https://docs.oracle.com/cd/E88353_01/html/E37839/mdfind-1.html), [softantenna Spotlight blog](https://softantenna.com/blog/spotlight/), [npm mdfind wrapper](https://www.npmjs.com/package/mdfind). Spotlight has documented quirks in local search — [Eclectic Light: Quirks of Spotlight local search (Sep 2025)](https://eclecticlight.co/2025/09/04/quirks-of-spotlight-local-search/)
- **Windows Search**: query via OLE DB with `provider=Search.CollatorDSO.1;EXTENDED PROPERTIES="Application=Windows"`. It is read-only (SELECT only), and `SystemIndex` is the only table, e.g. `SELECT System.ItemName ... FROM SystemIndex`. Microsoft recommends `ISearchQueryHelper` to build the SQL. — [Microsoft Learn: Querying the Index Programmatically](https://learn.microsoft.com/en-us/windows/win32/search/-search-3x-wds-qryidx-overview), [Scripting Guy: Querying the Windows Search Index](https://devblogs.microsoft.com/scripting/?p=18221) (pre-2025)
- **voidtools Everything**: the SDK embeds Everything search in other programs, `ES.exe` is a CLI for scripts, and community MCP servers wrap `es.exe`. — [voidtools forum: using Everything API](https://www.voidtools.com/forum/viewtopic.php?p=62514), [everything-mcp CLAUDE.md](https://glama.ai/mcp/servers/@danielsimonjr/everything-mcp/blob/084b8ef45d3b070c860ad28f71fbb14ec450fd2e/CLAUDE.md)
- **Recoll (Xapian)**: Hangul is handled poorly by both the whitespace splitter and the CJK n-gram splitter. Since 1.27, Recoll calls an external Korean analyzer: originally Konlpy, now `python-mecab-ko` by default as the best performance/quality trade-off. — [Recoll Korean page](https://www.recoll.org/pages/recoll-korean.html)
- **docling OCR engines**: Tesseract, EasyOCR, RapidOCR, macOS Vision (`ocrmac`), and Auto. RapidOCR backends are onnxruntime (default), openvino, paddle, and torch, running PP-OCR v4/v5/v6. PP-OCRv4 supports Korean. OcrMac uses locale codes (e.g. `ko-KR`) with "accurate" or "fast" levels. — [Docling OCR concepts](https://docling-project.github.io/docling/concepts/OCR/), [Docling OCR options](https://mintlify.com/docling-project/docling/api/options/ocr-options)
- **Apple Vision OCR** (`VNRecognizeTextRequest`) supports `ko-KR`. The language list depends on recognition level. — [Apple Developer Forums thread](https://developer.apple.com/forums/thread/121048), [Apple RecognizeTextRequest docs](https://developer.apple.com/documentation/vision/recognizetextrequest.md). OCRmyPDF has an Apple OCR plugin — [OCRmyPDF-AppleOCR](https://github.com/mkyt/OCRmyPDF-AppleOCR)
- **PaddleOCR PP-OCRv5**: 37 languages including Korean. `korean_PP-OCRv5_mobile_rec` reaches 88.0% accuracy on its dataset, and multilingual accuracy is more than 30% higher than PP-OCRv3. — [PaddleOCR PP-OCRv5 multilingual](https://www.paddleocr.ai/latest/en/version3.x/algorithm/PP-OCRv5/PP-OCRv5_multi_languages.html)
- **Tesseract vs PaddleOCR on Korean**: in a Korean academic comparison, Tesseract was better on high-quality images and PaddleOCR was more robust to image-quality changes. — [KoreaScience paper](https://koreascience.or.kr/article/CFKO202333854975639.pdf) (2023, pre-2025)
- **markitdown (Microsoft)**: MIT license, Python 3.10–3.14. It converts PDF, PPTX, DOCX, XLSX, images (EXIF plus OCR), audio (transcription), HTML, CSV/JSON/XML, ZIP, EPUB, and YouTube. The `markitdown-ocr` plugin OCRs PDF/DOCX/PPTX/XLSX using vision LLMs, Azure Document Intelligence is optional, and `markitdown-mcp` exposes it over MCP. It has a third-party plugin system (`#markitdown-plugin`). — [microsoft/markitdown](https://github.com/microsoft/markitdown)
- **Korean HWP/HWPX**: kordoc is a TypeScript CLI and MCP server that parses HWP3/5, HWPX, HWPML, PDF, and Office files into Markdown, with Korean table-pattern recognition. A MarkItDown HWP plugin also exists. — [kordoc (dev.co)](https://dev.co/ai/mcp/kordoc), [sourcepulse kordoc](https://www.sourcepulse.org/projects/27164665), [GitHub topic markitdown-plugin](https://github.com/topics/markitdown-plugin)

### Inferences
- **Piggybacking on OS indexes.** Spotlight and Windows Search return paths and metadata, not their extracted text in usable form. Windows `SystemIndex` can expose some properties but not reliable full text, and Everything indexes names only (from NTFS metadata). Use them for (a) quick "where is file X" tools exposed over MCP and (b) change discovery. For change detection, FSEvents/`fswatch` on macOS, `ReadDirectoryChangesW`/USN on Windows, or git diff for the notes repo are more deterministic than polling an OS index.
- **Recommended extraction chain for Korean:** markdown/code → raw read; DOCX/PPTX/XLSX → markitdown; born-digital PDF → text layer (pdfplumber/pypdf, or docling); scanned PDF or images → docling with `ocrmac` on the MacBook (Apple Vision `ko-KR`, no extra models) or RapidOCR PP-OCRv5 Korean on Windows/VPS; HWP/HWPX → kordoc. Run OCR on the Mac rather than the 1-vCPU VPS.
- Recoll's choice of mecab-ko for Korean confirms that Korean keyword quality depends on a morphological analyzer. The same applies to the custom indexer's FTS.

### Gaps
- No fresh 2025–2026 sources were gathered on Apache Tika, unstructured.io, pandoc, Tracker/localsearch, or plocate. plocate is filename-only (not verified this session).
- No benchmark found of Apple Vision vs PP-OCRv5 vs Tesseract `kor` accuracy on Korean documents.
- No source on whether Spotlight's `kMDItemTextContent` index tokenizes Korean well, e.g. whether particles break matches.
- iOS Core Spotlight is per-app. No mechanism was found for an external indexer to read other apps' iPhone content, so the iPhone is likely a query-only client.

---

## 3. Korean/multilingual embedding models (as of Oct 2026)

### Takeaway
On Korean retrieval benchmarks, **Korean-tuned bge-m3 derivatives** (KURE-v1, BGE-m3-ko, dragonkue snowflake-arctic-ko) beat generic multilingual models of the same size. The August 2026 **KURE-v2** (154M, late-interaction/ColBERT) is the new top score at nDCG@10 0.816 on MTEB-ko-retrieval, but it needs a multi-vector index (PyLate/PLAID), not sqlite-vec. Qwen3-Embedding-0.6B and EmbeddingGemma-300M are convenient (GGUF/Ollama/MLX, used by qmd) but score lower or are unproven on Korean. The user's current `paraphrase-multilingual-MiniLM-L12-v2` is far behind on Korean retrieval (AutoRAG top-1 F1 ≈ 0.30 vs ≈ 0.70 for Korean-tuned models), so upgrading the model is the single biggest quality win.

### Cited Findings

**Korean benchmark numbers**
- MTEB-ko-retrieval (9 tasks, MTEB(kor, v2)), average nDCG@10 / Recall@10: KURE-v2 (late-interaction, 154M) **0.8160 / 0.8921**; Qwen3-Embedding-8B (7.6B) 0.7826 / 0.8815; KURE-v1 (568M) 0.7616 / 0.8629; BGE-m3-ko 0.7547 / 0.8513; BAAI/bge-m3 0.7509 / 0.8588; KoE5 (560M) 0.7337 / 0.8300. — [nlpai-lab/KURE GitHub](https://github.com/nlpai-lab/KURE), [data-dynamics Korean embedding guide (8 Sep 2026)](https://www.data-dynamics.io/ko/blog/embedding-model-guide)
- KURE-v2 per-task nDCG@10: AutoRAG 0.9718, PubHealthQA 0.8229, Ko-StrategyQA 0.8070, LawIRKo 0.7550, SQuADKorV1 0.9846, Belebele 0.9660, MrTidy 0.5974, MLDR 0.7159, MIRACL 0.7237. Other results: colbert-ko-en-v2 0.8063, lightonai/mLateOn 0.7906, snowflake-arctic-embed-l-v2.0-ko 0.7653. — [nlpai-lab/KURE-v2](https://huggingface.co/nlpai-lab/KURE-v2)
- dragonkue's own 8-dataset Korean benchmark, average nDCG@10: snowflake-arctic-embed-l-v2.0-ko **0.7404**, BGE-m3-ko 0.7300, KURE-v1 0.7277, bge-m3 0.7242, multilingual-e5-large 0.7216, jina-embeddings-v3 0.7013, **Qwen3-Embedding-0.6B 0.6762**. — [dragonkue/snowflake-arctic-embed-l-v2.0-ko](https://huggingface.co/dragonkue/snowflake-arctic-embed-l-v2.0-ko). The snowflake-ko figure differs between this table (0.740) and the KURE-v2 table (0.7653) because the task sets differ.
- KURE-v1 card (top-1 average over Ko-StrategyQA, AutoRAG, MIRACL, PublicHealthQA, Belebele, MrTidy, MLDR, XPQA): Recall@1 KURE-v1 0.5264, BGE-m3-ko 0.5236, bge-m3 0.5178, Snowflake Arctic 0.5125, multilingual-e5-large 0.5005. Recall@10 / nDCG@10: KURE-v1 0.7968 / 0.6947, bge-m3 0.7920 / 0.6872. — [nlpai-lab/KURE-v1](https://huggingface.co/nlpai-lab/KURE-v1) (Dec 2024, pre-2025)
- **User's current model.** In the AutoRAG Korean (finance-domain) embedding benchmark, `paraphrase-multilingual-MiniLM-L12-v2` scores top-1 F1/Recall **0.2982** vs multilingual-e5-large-instruct 0.4649. In the same family of tables, KU-HIAI-ONTHEIT-large-v1.1 scores 0.7193, KoE5 0.6930–0.7018, and BGE-m3-ko 0.7456. — search summary of [AutoRAG Korean embedding benchmark](https://github.com/Marker-Inc-Korea/AutoRAG-example-korean-embedding-benchmark). The repo page directly confirmed KU-HIAI 0.7193 and KoE5 0.6930 top-1 F1, and bge-m3 as best top-10 F1 (0.1754). The MiniLM 0.2982 figure came via search snippet and should be verified (pre-2025, possibly outdated).
- A 2026 Korean practitioner comparison found Qwen3-Embedding "one step weaker" than bge-m3 and KURE-v1 on Korean self-introduction data, and KURE-v1 best on tagging (top-1 0.914). — [data-dynamics guide](https://www.data-dynamics.io/ko/blog/embedding-model-guide), [Cking-LLM-Benchmark PR #7](https://github.com/URECA-Cking/Cking-LLM-Benchmark/pull/7)

**Model specs**
- **KURE-v2**: base `skt/A.X-Encoder-base` (Apache-2.0), 154M params, one 128-d vector per token with MaxSim scoring, documents up to 8,192 tokens, query expansion to 64 tokens. License MIT, released 29 Aug 2026. Use via **PyLate** or sentence-transformers `MultiVectorEncoder`, with PLAID or faiss BinaryIVF indexes. The full 9-corpus index with 3× hierarchical pooling plus 1-bit quantization takes 1.7 GB, vs 13.1–50.0 GB for single-vector HNSW. It serves 43–55 QPS, and p95 is 38 ms at 1.5M docs with BinaryIVF. — [KURE-v2 card](https://huggingface.co/nlpai-lab/KURE-v2), [KURE GitHub](https://github.com/nlpai-lab/KURE)
- **KURE-v1**: bge-m3 fine-tune, 568M, 1024-d, 8192 context, MIT, Dec 2024. **KoE5**: multilingual-e5-large fine-tune, 560M, MIT, needs `query:`/`passage:` prefixes. — [KURE GitHub](https://github.com/nlpai-lab/KURE)
- **dragonkue/snowflake-arctic-embed-l-v2.0-ko**: 0.6B, 1024-d, 8192 context, Apache-2.0, trained on AI Hub Korean data. The card does not mention Matryoshka. — [HF card](https://huggingface.co/dragonkue/snowflake-arctic-embed-l-v2.0-ko)
- **bge-m3** in Ollama: 568M, 1024-d, 8192 context, **1.2 GB** on disk. It is the only Ollama embedding model offering dense, sparse, and ColBERT outputs. Loading in F16 takes about 1.06 GB. — [morphllm Ollama embedding models](https://www.morphllm.com/ollama-embedding-models), [localaimaster](https://localaimaster.com/blog/best-ollama-embedding-models) (secondary)
- **Qwen3-Embedding-0.6B**: 28 layers, 32K context, MRL dims 32–1024, instruction-aware (+1–5% with instructions), Apache-2.0, released 5 Jun 2025. MMTEB multilingual scores: 64.33 (0.6B), 69.45 (4B), 70.58 (8B). Needs transformers ≥4.51, sentence-transformers ≥2.7, vLLM ≥0.8.5, and is supported by TEI. — [Qwen/Qwen3-Embedding-0.6B](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B). Available in Ollama as `qwen3-embedding` (0.6B/4B/8B; 8B Q4 ≈ 4.9 GB) — [Ollama library](https://registry.ollama.ai/library/qwen3-embedding). Multiple GGUF quants (Q4_K_M, Q8_0) on HF — [Mungert/Qwen3-Embedding-0.6B-GGUF](https://huggingface.co/Mungert/Qwen3-Embedding-0.6B-GGUF). MLX 4-bit DWQ and 8-bit builds exist — [mlx-embeddings](https://github.com/mzbac/mlx.embeddings), [AutomatosX MLX 8bit](https://huggingface.co/AutomatosX/AX-Qwen3-Embedding-0.6B-MLX-8bit)
- **EmbeddingGemma-300M** (308M): 768-d with MRL to 512/256/128, 2,048-token context, 100+ languages, Gemma license. MMTEB v2 mean task score 61.15. fp16 is not supported (use fp32/bf16). It runs in under 200 MB RAM with QAT quantization, embeds 256 tokens in under 15 ms on EdgeTPU, and was released 4 Sep 2025. — [google/embeddinggemma-300m](https://huggingface.co/google/embeddinggemma-300m), [Google Developers Blog](https://developers.googleblog.com/en/introducing-embeddinggemma/). It is 622 MB in Ollama — [morphllm](https://www.morphllm.com/ollama-embedding-models). qmd ships it as its default embedder in Q8_0 GGUF (~300 MB) but calls it "optimized for English" and recommends Qwen3-Embedding-0.6B for CJK. — [tobi/qmd](https://github.com/tobi/qmd)
- **jina-embeddings-v3**: CC BY-NC 4.0 (non-commercial), released 18 Sep 2024. jina-v4 is under the Qwen Research License. jina-v5-text-small and -nano (Feb 2026) are CC BY-NC 4.0. Jina AI has been part of Elastic since Oct 2025. — [jina.ai v3 page](https://jina.ai/models/jina-embeddings-v3/), [jina v4](https://jina.ai/en-US/models/jina-embeddings-v4/)
- **nomic-embed-text-v2-moe**: 475M total / 305M active (MoE, 8 experts, top-2), 768-d with Matryoshka to 256, **512-token max**, about 100 languages, Apache-2.0, Feb 2025. BEIR 52.86, MIRACL 65.80. — [nomic-ai/nomic-embed-text-v2-moe](https://huggingface.co/nomic-ai/nomic-embed-text-v2-moe)
- **potion-multilingual-128M** (model2vec static): distilled from bge-m3, 101 languages, 256-d, no context limit. It reaches 90.86% of LaBSE's score and is strongest at classification and clustering. model2vec claims "up to 50× smaller and 500× faster" than Sentence Transformers, and an int8 variant exists. — [minishlab/potion-multilingual-128M](https://huggingface.co/minishlab/potion-multilingual-128m), [model2vec GitHub](https://github.com/MinishLab/model2vec)
- **multilingual-e5 family**: Korean AutoRAGRetrieval scores of e5-base 77.66 and e5-large 80.66 (search-snippet attribution, unverified). A secondary source reports e5-small at 226 docs/s and e5-large at 21 docs/s on a Ryzen 9 7950X with OpenVINO (unverified; the underlying doc lacked citations). — [AutoRAG benchmark search summary](https://github.com/Marker-Inc-Korea/AutoRAG-example-korean-embedding-benchmark), [folder-mcp research doc](https://glama.ai/mcp/servers/@okets/folder-mcp/blob/d01bb52143b8721e59eae8d588a80c2dd8391cc9/docs/features/embedding-models-research.md)

**Availability in the user's current stack (FastEmbed / Basic Memory)**
- The FastEmbed supported-models page lists `paraphrase-multilingual-MiniLM-L12-v2` (384-d, 0.22 GB, Apache-2.0), `intfloat/multilingual-e5-large` (1024-d, 2.24 GB), and the reranker `jina-reranker-v2-base-multilingual` (1.11 GB, CC-BY-NC-4.0). It does **not** list bge-m3, KURE, Qwen3-Embedding, EmbeddingGemma, snowflake-arctic-l-v2.0, multilingual-e5-small/base, or bge-reranker-v2-m3. — [FastEmbed Supported Models](https://qdrant.github.io/fastembed/examples/Supported_Models/) (the docs page may lag the code)
- Basic Memory's default is FastEmbed `BAAI/bge-small-en-v1.5` (384-d). For multilingual it suggests `intfloat/multilingual-e5-large` with `passage: `/`query: ` prefixes. Config keys: `semantic_embedding_provider`, `semantic_embedding_model`, `semantic_embedding_dimensions`, `semantic_embedding_document_prefix`/`_query_prefix`. Providers are FastEmbed (local) and OpenAI. Changing the model requires `bm reindex --embeddings`. — [Basic Memory semantic search docs](https://docs.basicmemory.com/concepts/semantic-search)

### Inferences
- **CPU speed on the 1-vCPU VPS (back-of-envelope, unverified).** Encoder cost is about 2 × params × tokens FLOPs. A 512-token chunk through a 568M model (bge-m3/KURE-v1) is about 0.58 TFLOP. At a plausible 50–150 effective GFLOPS on one vCPU with ONNX/int8, that is roughly 4–12 s per chunk. **Bulk-embedding 20k chunks on the VPS would take about a day or more**, so embed on the MacBook (Metal via Ollama/llama.cpp/MLX) and ship vectors. A single ~20-token query costs about 23 GFLOP, roughly 0.2–0.5 s on the VPS, which is acceptable for query-time embedding. A 154M model (KURE-v2) or 118M e5-small is about 4–5× cheaper. Benchmark on the actual VPS before relying on these numbers.
- **RAM on the 2 GB VPS.** bge-m3/KURE-v1 at fp16 is about 1.1 GB. An int8 ONNX build would be about 0.6 GB (not measured here). EmbeddingGemma QAT is under 200 MB per Google. Qwen3-Embedding-0.6B at Q8 is about 0.6 GB. All fit for query-only use with the SQLite index (tens of MB), but not alongside Meilisearch, ES, or a reranker.
- **Model choice matrix for this user:**
  - *Best Korean quality, dense, sqlite-vec compatible:* KURE-v1 or dragonkue snowflake-arctic-ko (1024-d, 568M–0.6B). Neither is in the FastEmbed list, so it needs a custom ONNX/GGUF path. KURE-v1 shares bge-m3's XLM-R architecture, so llama.cpp/Ollama-style GGUF conversion should work (unverified).
  - *Least friction inside Basic Memory today:* `intfloat/multilingual-e5-large` via FastEmbed. On Korean it is far better than MiniLM but slightly below bge-m3 and KURE, and at 2.24 GB fp32 it is heavy for the VPS.
  - *Highest Korean score:* KURE-v2 (154M). It needs PyLate/PLAID multi-vector storage, roughly 64× more vectors per chunk before pooling and quantization. That is a different engine from sqlite-vec, and PyTorch on a 2 GB VPS is tight.
  - *Easiest cross-platform runtime (Ollama/GGUF/MLX):* Qwen3-Embedding-0.6B (MRL lets you store 256–512-d to save space). Korean scores are 0.676 vs 0.724 for bge-m3 on dragonkue's benchmark. bge-m3 itself is in Ollama.
  - Avoid jina-v3/v5 for anything commercial (CC BY-NC). Avoid nomic-v2-moe for long notes (512-token limit). Use potion-multilingual only as a fallback or pre-filter: it is fast but has no Korean retrieval benchmark.
- **Matryoshka / quantization.** Qwen3-Embedding (32–1024) and EmbeddingGemma (768/512/256/128) allow truncation. bge-m3, KURE-v1, and snowflake-ko have no documented MRL, so use int8 or binary quantization with re-scoring (sqlite-vec supports int8 and bit) instead.

### Gaps
- No primary measurement of embedding throughput on a 1-vCPU VPS or on Apple Silicon (MLX/Metal/CoreML) for any of these models. All speed numbers above are estimates or secondary.
- No Korean retrieval benchmark found for EmbeddingGemma-300M, nomic-embed-text-v2-moe, potion-multilingual-128M, or multilingual-e5-small.
- Could not confirm KURE-v1 or KURE-v2 GGUF/Ollama/MLX ports, or whether FastEmbed's custom-model API (`add_custom_model`) can load KURE-v1 ONNX.
- The official MTEB leaderboard's Korean tab was not fetched directly. Korean numbers come from the KURE and dragonkue model cards, which are self-reported.
- bge-m3 (MIT), multilingual-e5 (MIT), and model2vec (MIT) licenses were not re-verified this session.

---

## 4. Rerankers for Korean, and whether they're worth it at this scale

### Takeaway
A cross-encoder reranker clearly improves Korean top-1 precision: bge-reranker-v2-m3-ko scores 0.912 top-1 vs 0.877 for the base model and 0.807 for jina-v2 on AutoRAG finance. Basic Memory's own eval shows MRR rising from 0.616 to 0.719. But a 0.6B cross-encoder over 20–50 candidates is expensive on a 1-vCPU VPS. It is worth running on the MacBook, or on the VPS only over a small top-k (≤10–20) with a latency budget.

### Cited Findings
- AutoRAG Korean finance reranker benchmark, top-1 F1: **bge-reranker-v2-m3-ko 0.9123**, bge-reranker-v2-m3 0.8772, upskyy/ko-reranker-8k 0.8684, Dongjin-kr/ko-reranker 0.8509, upskyy/ko-reranker 0.8333, jina-reranker-v2-base-multilingual 0.8070, gte-multilingual-reranker-base 0.7281. Top-3 recall: 0.9649 / 0.9561 / 0.9561 / 0.9298 (-ko / base / ko-reranker-8k / jina). bge-reranker-v2-m3-ko is 0.6B and Apache-2.0. — [dragonkue/bge-reranker-v2-m3-ko](https://huggingface.co/dragonkue/bge-reranker-v2-m3-ko)
- jina-reranker-v2-base-multilingual is in FastEmbed (1.11 GB) under **CC-BY-NC-4.0**. — [FastEmbed Supported Models](https://qdrant.github.io/fastembed/examples/Supported_Models/)
- Basic Memory v0.23 (Aug 2026) added opt-in cross-encoder reranking. The default provider is a local FastEmbed ONNX model, with Cohere/Jina/Voyage available via LiteLLM. Reranking raised MRR from 0.616 to 0.719 (+17%) in their evaluation. — [Basic Memory v0.23](https://docs.basicmemory.com/whats-new/v0-23)
- qmd uses **Qwen3-Reranker-0.6B q8_0 (~640 MB GGUF)** with position-aware RRF blending, so top-ranked retrieval results keep their confidence and lower-ranked ones lean more on the reranker. — [tobi/qmd](https://github.com/tobi/qmd)
- Korean RAG guidance pairs a lightweight retriever with `dragonkue/bge-reranker-v2-m3-ko` or `BAAI/bge-reranker-v2-m3`. — [apiyi Korean rerank docs](https://docs.apiyi.com/ko/api-capabilities/rerank/rag-best-practices.md)
- Khoj's multilingual configuration pairs `paraphrase-multilingual-MiniLM-L12-v2` with a small `mixedbread-ai/mxbai-rerank-xsmall-v1` cross-encoder. — [Khoj multilingual docs](https://docs.khoj.dev/advanced/support-multilingual-docs)

### Inferences
- Cost estimate (unverified): a 0.6B cross-encoder reading 20 pairs × ~400 tokens is about 2 × 0.57B × 8k ≈ 9 TFLOP, likely tens of seconds on one vCPU. That is too slow for interactive MCP calls from the VPS, while the Mac with Metal handles it easily. On the VPS, either skip reranking, rerank only top-5 to 10, or use a smaller reranker.
- The jina reranker is CC-BY-NC (fine for personal use, not for anything commercial). bge-reranker-v2-m3(-ko) is Apache-2.0 and best on the Korean benchmark.
- With a good Korean embedder (KURE/bge-m3 class) plus morpheme-aware BM25 and RRF, the marginal gain from reranking will be smaller than the +17% Basic Memory measured on its own default stack. Treat reranking as phase 2.

### Gaps
- Qwen3-Reranker-0.6B was not in the Korean reranker benchmark found. No Korean head-to-head against bge-reranker-v2-m3-ko.
- The default FastEmbed reranker model name in Basic Memory 0.23 was not stated on the page fetched.
- No measured CPU latency for any reranker.

---

## 5. Turnkey retrieval tools: qmd, Basic Memory, Khoj, LlamaIndex/LangChain, txtai, Chroma (Korean handling)

### Takeaway
**qmd** (MIT, Node/Bun) is the most complete local stack: FTS5 BM25, vectors, RRF, Qwen3 reranker, query expansion, MCP over stdio or HTTP, and hash-based incremental indexing. Its default embedder is English-optimized, so set `QMD_EMBED_MODEL=Qwen3-Embedding-0.6B` for Korean. Its three models total about 2 GB, so it suits the Mac better than the VPS. **Basic Memory 0.23** already provides hybrid FTS5 + sqlite-vec, chunking, hash-incremental reindexing, CJK query relaxation, and optional reranking. Its weak point for Korean is the embedding model (FastEmbed-limited) and no Korean morphological FTS. Khoj is too heavy for 2 GB. Chroma's defaults are English. txtai is a flexible library, not a product.

### Cited Findings
- **qmd (tobi)**: SQLite FTS5 BM25 + vector search + LLM reranking fused by RRF with position-aware blending. Models run as GGUF via node-llama-cpp: EmbeddingGemma-300M-Q8_0 (~300 MB), Qwen3-Reranker-0.6B-q8_0 (~640 MB), QMD-Query-Expansion-1.7B-q4_k_m (~1.1 GB), cached in `~/.cache/qmd/models/`. CJK: set `QMD_EMBED_MODEL` to Qwen3-Embedding-0.6B (119 languages) and re-embed with `qmd embed -f`. Chunking is about 900 tokens with 15% overlap at markdown boundaries, with optional tree-sitter AST chunking for TS/JS/Python/Go/Rust. Docids are 6-character content hashes and only changed files are reprocessed. MCP tools are `query`, `get`, `multi_get`, `status`, and metadata, over stdio or an HTTP daemon that keeps models loaded. It needs Node ≥22 or Bun ≥1.0, and on macOS a Homebrew SQLite. It runs on Windows and Linux, is MIT-licensed, and is published on npm as `@tobilu/qmd`. — [tobi/qmd](https://github.com/tobi/qmd)
- **Basic Memory**: v0.23.0 shipped in Aug 2026, and v0.23.1 and v0.23.2 followed on 25 Aug 2026. Changes include FTS covering the full note body (previously capped at about 6,000 chars), CJK/Cyrillic/Greek/Hebrew/Arabic queries "now process correctly", L2-normalized FastEmbed embeddings for non-BGE models, and deadlock-free concurrent indexing. — [Basic Memory v0.23](https://docs.basicmemory.com/whats-new/v0-23). Chunking: header boundaries, then observations and relations indexed individually, then prose merged into ~900-char chunks with ~120-char overlap. Hybrid fusion keeps the dominant signal plus a 30% bonus from the weaker one (not RRF). Question-form queries are retried as a relaxed any-word query. `bm reindex` is incremental via content hashing, with `--full`, `--embeddings`, and `--search` options. — [Basic Memory semantic search](https://docs.basicmemory.com/concepts/semantic-search)
- **Khoj**: self-hosting needs the Khoj server, pgvector Postgres, the Terrarium sandbox, and SearxNG. Embeddings live in pgvector. The multilingual setting uses `bi_encoder: paraphrase-multilingual-MiniLM-L12-v2` and `cross_encoder: mxbai-rerank-xsmall-v1`. — [Railway Khoj template](https://railway.com/deploy/khoj-ai-second-brain), [Khoj multilingual docs](https://docs.khoj.dev/advanced/support-multilingual-docs)
- **txtai**: v6.0 added sparse, hybrid, and subindexes, with BM25 plus FAISS and configurable normalization and quantization. — [txtai v6.0 release](https://github.com/neuml/txtai/releases/tag/v6.0.0) (2023, pre-2025)
- **Chroma**: the default embedding function is Sentence Transformers `all-MiniLM-L6-v2` (English), run locally. A built-in local BM25 sparse embedding function exists. — [Chroma embedding functions](https://docs.trychroma.com/docs/embeddings/embedding-functions), [Chroma BM25](https://docs.trychroma.com/integrations/embedding-models/chroma-bm25)
- **LangChain (Korean)**: Korean tutorials build hybrid `EnsembleRetriever` setups from a Kiwi-tokenized BM25 retriever plus a vector retriever. — [WikiDocs Ensemble Retriever](https://wikidocs.net/231609), [WikiDocs Kiwi+BM25](https://wikidocs.net/251980)

### Inferences
- **Korean readiness:**
  - qmd: good on vectors once switched to Qwen3-Embedding, though that model is the weakest of the strong Korean models. Keyword side is unknown: its FTS5 tokenizer for Hangul is undocumented.
  - Basic Memory: fixed CJK query relaxation in 0.23, but its FTS tokenizer is undocumented and probably unicode61. The embedding model is the bottleneck, and the FastEmbed list lacks Korean-tuned models.
  - Khoj: MiniLM by default, weak for Korean.
  - Chroma: English default, BM25 tokenizer probably not Korean-aware.
  - txtai and LangChain: flexible enough to plug in Kiwi and KURE.
- **Fastest path to better Korean recall with what the user already runs:** keep Basic Memory as the notes MCP and switch its model to `intfloat/multilingual-e5-large` with prefixes, then `bm reindex --embeddings`. For larger gains, put a custom indexer beside it (SQLite FTS5 with Kiwi morphemes + sqlite-vec + KURE-v1 or snowflake-arctic-ko, embedding on the Mac) or use qmd on the Mac.
- qmd's model bundle (~2 GB plus runtime) exceeds what a 2 GB VPS can host next to anything else. Run qmd's HTTP MCP daemon on the MacBook, or run only the embedder on the VPS.

### Gaps
- Not verified: qmd's FTS5 tokenizer choice and any Korean-specific handling; Basic Memory's SQLite FTS tokenizer; whether Basic Memory accepts arbitrary ONNX models through FastEmbed.
- No current (2025–2026) source checked for LlamaIndex Korean loaders, or for Khoj's indexer file types and RAM.

---

## 6. Chunking strategies for Korean markdown/PDF and hash-based incremental re-embedding

### Takeaway
Both mature tools chunk structure-first (markdown headings, code AST), then size-bounded with overlap: qmd uses about 900 tokens with 15% overlap, Basic Memory about 900 characters with 120-character overlap. Both use content hashes so only changed content is re-embedded. For Korean, apply the same heading-first strategy, but measure chunk size in model tokens rather than characters, because Korean token density differs from English. Store hashes per chunk, not just per file.

### Cited Findings
- qmd: about 900-token chunks with 15% overlap. Boundaries prefer headings, code blocks, and paragraph breaks. Optional tree-sitter AST chunking for code. 6-character content-hash docids drive incremental updates, and embedding can be deferred and run with `qmd embed`. — [tobi/qmd](https://github.com/tobi/qmd)
- Basic Memory: headers make chunk boundaries, observations and relations are indexed individually, prose is merged into ~900-char chunks with ~120-char overlap, and incremental reindex skips unchanged content via content hashing, re-embedding only modified chunks. — [Basic Memory semantic search](https://docs.basicmemory.com/concepts/semantic-search)
- Long-context models allow large chunks: KURE-v1, bge-m3, and snowflake-ko support 8192 tokens, Qwen3-Embedding 32K, EmbeddingGemma 2,048, nomic-v2-moe only 512. — [KURE-v1](https://huggingface.co/nlpai-lab/KURE-v1), [snowflake-ko](https://huggingface.co/dragonkue/snowflake-arctic-embed-l-v2.0-ko), [Qwen3-Embedding-0.6B](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B), [EmbeddingGemma](https://huggingface.co/google/embeddinggemma-300m), [nomic v2 moe](https://huggingface.co/nomic-ai/nomic-embed-text-v2-moe)
- KURE-v2 handles 8,192-token documents and uses hierarchical token pooling (3×) to shrink multi-vector storage. — [KURE-v2](https://huggingface.co/nlpai-lab/KURE-v2)
- Docling and markitdown emit Markdown, so PDFs and Office docs can share the markdown heading-aware chunker. — [Docling OCR](https://docling-project.github.io/docling/concepts/OCR/), [markitdown](https://github.com/microsoft/markitdown)

### Inferences
- **Recommended Korean chunking**:
  1. Split on markdown headings (and docling/markitdown output headings for PDF and Office files).
  2. Within a section, pack sentence-aware windows of about 300–600 model tokens with 10–15% overlap. Use Kiwi's sentence splitter for Korean, because Korean sentence endings like "~다." and "~요." don't always have clean punctuation in notes.
  3. Prefix each chunk with document title and heading path ("contextual header") to help both BM25 and dense retrieval.
  4. Code: AST chunks as in qmd.
  5. PDF: chunk per page or section, keeping page numbers in metadata for citations.
  Character-based limits (Basic Memory's 900 chars) give Korean chunks roughly 2–3× more semantic content per character than English, so token-based limits are more consistent (unverified ratio).
- **Incremental re-embedding design**:
  - Keep `file_hash` (to skip unchanged files) plus a `chunk_hash` covering normalized chunk text, model id, and prefix. Re-embed only missing chunk_hashes, and garbage-collect orphans.
  - Store `model_id` and dims with each vector so a model switch (e.g. MiniLM to KURE) triggers a controlled full re-embed, which Basic Memory already requires via `bm reindex --embeddings`.
  - For multi-device use, run heavy embedding on the MacBook and sync the resulting SQLite or LanceDB file, or push the vectors, to the VPS. The VPS then embeds only queries, using the same model.
- Hash-keyed chunk caches also make it cheap to re-tokenize the BM25 side (e.g. adding Kiwi user-dictionary words) without touching vectors.

### Gaps
- No Korean-specific study found on optimal chunk size for KURE or bge-m3 retrieval, or on Korean token density per model tokenizer (XLM-R vs Gemma vs Qwen).
- No source on semantic or "late" chunking performance for Korean.
