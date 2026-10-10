# Photo and image indexing for text search by AI agents (macOS Photos, image files, screenshots; Apple Silicon M2; Korean)

Scope reminder: the tidy-one device agent runs on a MacBook M2 (24 GB) and computes everything locally. A Vultr VPS (Seoul, 4 GB RAM, 2 vCPU) holds a SQLite + sqlite-vec catalog and must embed only the **text query** at search time, then serves MCP `search_files` to Claude Code, Codex, claude.ai web/mobile and Aside. Sources: Photos Library (likely iCloud Photos + Optimize Mac Storage), ~/Pictures, ~/Downloads, ~/Desktop screenshots, iCloud Drive; a Windows laptop later. Queries are Korean ("작년 제주 바다 사진", "화이트보드에 적은 회의 내용", "영수증").

Research date: 2026-10-10. Items older than ~12 months are marked "(older)". One local test was run on this machine (Apple M2, macOS 26.2); it is labelled "[local test]" and has no URL.

---

## 1. Reading the Photos library programmatically (osxphotos, PhotoKit, iCloud-only originals, TCC)

### Takeaway
osxphotos (MIT, v0.77.2 on 2026-09-27, actively tracking macOS 27) reads Photos' own SQLite and search index directly. It exposes Apple's ML labels, a rich `search_info` (place names, activities, venues, events, pets, landmarks, and **Photos' own OCR text** on macOS 13+), named persons/faces, reverse-geocoded places, the mediaanalysisd AI caption, aesthetic scores, EXIF, iCloud status and **local derivative (preview) JPEG paths**. So the agent can index iCloud-only photos from local previews without downloading originals. It needs **Full Disk Access**, not the Photos TCC permission. PhotoKit (Swift) is the supported API, but it needs the Photos TCC grant, which a launchd CLI cannot prompt for. It also does not surface Apple's labels or OCR (inference; see below).

### Cited Findings
**osxphotos project status**
- MIT license, 3,894 stars. Latest release v0.77.2 (2026-09-27); last push 2026-10-05. — [GitHub API: RhetTbull/osxphotos](https://github.com/RhetTbull/osxphotos), [releases](https://github.com/RhetTbull/osxphotos/releases)
- Recent releases:
  - v0.77.2 (Sep 27, 2026): fixes for macOS 26+ shared albums and macOS 27 system-library detection.
  - v0.77.1 (Sep 23, 2026): adds SearchInfo properties `times_of_day`, `week_part` and `events`, and fixes missing search data on macOS 27 (`leo.sqlite`).
  - v0.77.0 (Sep 20, 2026): initial macOS 27 search/media-info support; uv-compatible packaging.
  - v0.76.x (Jun 2026): alpha support for the macOS 27 beta.
  — [osxphotos releases](https://github.com/RhetTbull/osxphotos/releases)
- The README lists support from macOS 10.12.6 to macOS 27.0 (Photos 12.0). It also says "OSXPhotos cannot read shared albums on macOS 26.x". The v0.77.2 notes mention shared-album fixes, so this may be partly resolved. — [osxphotos README](https://github.com/RhetTbull/osxphotos); [releases](https://github.com/RhetTbull/osxphotos/releases)

**What osxphotos exposes (PhotoInfo API)**
- `labels` / `labels_normalized`: "image categorization labels associated with the photo" (Photos 5+).
- `persons`, `person_info`, `face_info`: named people and their face records.
- `place` (PlaceInfo): reverse-geocode name, a structured `names` hierarchy, `country_code` and address.
- `score` (ScoreInfo): "computed aesthetic scores".
- `exif_info`: camera, lens, ISO, aperture, focal length, date.
- `moment_info`.
- `fingerprint`: hash of the original file. `hexdigest`: digest of the metadata, for change detection.
- Flags: `screenshot`, `live_photo`, `burst`, `shared`.
- `uuid`, `date_added`, `title`, `description`, `keywords`.
— [osxphotos API_README](https://rhettbull.github.io/osxphotos/API_README.html)
- `ai_caption`: "the AI generated caption if one exists", from the mediaanalysisd process. `media_analysis`: a dict that includes quality metrics and AI captions. — [API_README](https://rhettbull.github.io/osxphotos/API_README.html)
  - In source, media analysis is read from `private/com.apple.mediaanalysisd/MediaAnalysis/MediaAnalysis.sqlite` (or `mediaanalysis.db`). Its keys include `image_caption`, `video_caption`, `quality`, `sharpness`, `junk`, `feature_vector`, `shot_type` and scene segments. — [osxphotos/media_analysis.py](https://github.com/RhetTbull/osxphotos/blob/main/osxphotos/media_analysis.py)
- `search_info` / `search_info_normalized` (SearchInfo class, "machine learning labels that Photos knows about a photo") has these properties: labels, place_names, streets, neighborhoods, locality_names, city, state, country, country_code, region, continent, month, year, season, bodies_of_water, holidays, activities, venues, venue_types, media_types, **detected_text**, text_found, camera, source, times_of_day, week_part, day_of_week, home, areas_of_interest, events, event_performers, event_types, pets, age_groups, landmarks, sounds, human_actions, document_types, trip, photographic_style, file_type, captured_by_me. It also has `id_document_types` and `id_document_names` ("names read from identity documents… macOS 27+ only", excluded from `all()`). — [osxphotos/searchinfo.py](https://github.com/RhetTbull/osxphotos/blob/main/osxphotos/searchinfo.py)
- `search_info.detected_text`: "text detected in the photo (macOS 13+ / Photos 8+ only)". This reads text Photos itself already extracted. Search info can be absent "if Photo was missing or photoanalysisd not run yet". — [searchinfo.py](https://github.com/RhetTbull/osxphotos/blob/main/osxphotos/searchinfo.py)
- The separate `PhotoInfo.detected_text()` method runs Apple Vision OCR on demand. It uses the edited image, then the original, and "falls back to the preview image if neither edited or original is available". Results are cached in an extended attribute. The docs say it takes about 2 s per image on older Macs. — [osxphotos/photoinfo.py](https://github.com/RhetTbull/osxphotos/blob/main/osxphotos/photoinfo.py); [API_README](https://rhettbull.github.io/osxphotos/API_README.html)

**iCloud-only originals**
- osxphotos flags:
  - `ismissing`: True if the original "is missing on disk… e.g. not downloaded from iCloud".
  - `iscloudasset` / `incloud`: iCloud management and sync state.
  - `path_derivatives`: "paths to any derivative preview images… sorted… highest resolution preview will be the first element". These live under `resources/derivatives/masters/<first-uuid-char>/<uuid>_4_5005_c.jpeg` and similar paths.
  - Export can fetch originals with `--download-missing`.
  — [API_README](https://rhettbull.github.io/osxphotos/API_README.html); [photoinfo.py](https://github.com/RhetTbull/osxphotos/blob/main/osxphotos/photoinfo.py); [README](https://github.com/RhetTbull/osxphotos)
- Library layout: `originals` holds masters and `resources/derivatives` holds "previews and thumbnails Photos renders for fast scrolling". Optimize Storage "cannot remove the photos completely… Only the originals can be removed". The internal layout "can change between macOS releases". — [Mole blog (secondary)](https://mole.tw93.fun/blog/how-to-free-up-photos-storage-mac); [Apple Community thread 251344047](https://discussions-kr-prz.apple.com/thread/251344047)
- PhotoKit: when `isNetworkAccessAllowed` is false (the default) and the image is not on the device, the result dictionary reports the image as unavailable. When it is true, Photos downloads it from iCloud. — [Apple docs: PHImageRequestOptions.isNetworkAccessAllowed](https://developer.apple.com/documentation/photos/phimagerequestoptions/isnetworkaccessallowed)

**Permissions (TCC)**
- apple-photos-mcp, which is built on osxphotos, needs **Full Disk Access** because "Photos library SQLite lives in protected directory; osxphotos reads it directly". Automation permission is needed only for its write tools. — [sweetrb/apple-photos-mcp](https://github.com/sweetrb/apple-photos-mcp)
- An app must be allowed to read the Photos library through Full Disk Access in System Settings › Privacy & Security. — [TidBITS (secondary, 2021, older)](https://tidbits.com/2021/08/23/work-with-text-in-images-with-textsniper-and-photos-search/)
- A command-line tool launched by launchd that touches the Photos library gets no approval prompt and is silently denied. Such tools cannot be pre-authorized in the Photos privacy pane. — [Apple Developer Forums 106534](https://developer.apple.com/forums/thread/106534)
- PhotoKit requires `PHPhotoLibrary.requestAuthorization(for: .readWrite)` (or `.readOnly`-style access) from a process that can show the prompt. — [Apple Developer Forums 106534](https://developer.apple.com/forums/thread/106534); [PhotoKit skill summary (secondary)](https://skills.sh/dpearson2699/swift-ios-skills/photokit)
- Sibling research, same project: FDA/TCC grants attach to the binary path. Versioned binary paths lose the grant on each update, so ship the agent at a stable, signed path. — [research_notes/개인 기기 통합 인덱싱 설계/device_constraints_client_access.md](../개인%20기기%20통합%20인덱싱%20설계/device_constraints_client_access.md)

### Inferences
- **Use osxphotos as the Photos reader** (Python library, read-only on the DB). For each photo, take: uuid, dates, place (names in Photos' locale), labels, the whole `search_info` (minus `id_document_*`), persons, ai_caption, score, screenshot flag, fingerprint, `ismissing`, and `path_derivatives[0]` as the image to embed and OCR. This covers iCloud-optimized libraries with **zero iCloud downloads**. Previews are lower resolution, which is fine for CLIP (224–384 px input) and usually fine for OCR of screenshots and whiteboards. Tiny receipt text may need the original.
- **Reuse Apple's work first.** If `search_info.detected_text` exists (macOS 13+), skip running OCR yourself on Photos items. Run Vision OCR only where it is empty (photoanalysisd hasn't run yet, or the item is outside Photos).
- **PhotoKit is not needed for indexing** and adds TCC friction. As far as I could find, PhotoKit has no public API for Photos' scene labels, OCR text or captions; these come only from the private DBs that osxphotos reads (I found no source that says this either way; see Gaps). PhotoKit is useful later only for "request original on demand" (isNetworkAccessAllowed=true) if a user asks to open a full-resolution file.
- **Schema fragility.** Photos DB internals change every macOS release (osxphotos needed fixes for macOS 27's `leo.sqlite`). Pin the osxphotos version, keep the Photos indexer behind an interface, and let it degrade to "file + EXIF + own OCR/CLIP" if search_info is unavailable.
- **Privacy filter at the source:** never ship `id_document_names`/`id_document_types` (macOS 27 reads names off passports and ID cards) or face data to the VPS.
- Grant Full Disk Access once to a stable, signed agent binary (or a .app bundle used by the LaunchAgent). That one grant covers the Photos library package, ~/Pictures, ~/Desktop and ~/Downloads.

### Gaps
- No primary source found that states PhotoKit lacks access to labels and OCR. This is my understanding and is not verified.
- Language of Apple's `labels`/`search_info` strings: unknown whether they follow the system locale (Korean) or are stored in English. Test on the user's library with `osxphotos query --json` and inspect.
- Language of mediaanalysisd `ai_caption`: not documented; likely English. Unverified.
- How complete Photos' own OCR (`detected_text`) is across a large iCloud library is undocumented. Analysis runs when the Mac is idle or plugged in.
- Derivative resolution for iCloud-optimized assets (e.g., 1024 vs 2048 px) was not confirmed from a primary source.

---

## 2. On-device OCR for Korean (Apple Vision, Live Text, ocrmac, PaddleOCR, EasyOCR, Surya)

### Takeaway
Apple Vision `VNRecognizeTextRequest` revision 3 in **accurate** mode supports `ko-KR`. On this M2 it read Korean lines correctly in about **0.2 s per 1600×1200 image** after warm-up. **Fast mode does not support Korean** and returns garbage. Apple Vision (via ocrmac or a small Swift helper) is the default on the Mac. PaddleOCR PP-OCRv5 Korean (Apache-2.0, ~14 MB recognizer) is the cross-platform option for the future Windows agent. Surya is heavier and its weights carry a restrictive licence.

### Cited Findings
- Vision text recognition revision 3 (`VNRecognizeTextRequestRevision3`) powers Live Text. It added Korean and Japanese (WWDC22). Accurate mode can auto-detect language with `automaticallyDetectsLanguage`. — [WWDC22 session 10024](https://developer.apple.com/videos/play/wwdc2022/10024/?time=117); [Apple tutorial: recognizing text in images](https://developer.apple.com/tutorials/data/documentation/vision/recognizing-text-in-images.md)
- WWDC25 added `RecognizeDocumentsRequest` (Swift Vision, OS 26). It groups lines into paragraphs, reads tables and lists, detects QR codes, emails, phone numbers and URLs, and supports 26 languages. — [WWDC25 session 272](https://developer.apple.com/videos/play/wwdc2025/272/)
- **[local test]** Apple M2, macOS 26.2, Swift script in the scratchpad:
  - `VNRecognizeTextRequest().revision` = 3.
  - Accurate-mode languages include `ko-KR`, `ja-JP`, `zh-Hans/Hant`, `th-TH`, `vi-VT`, `ar-SA` and others (30 identifiers). Fast mode supports only en/fr/it/de/es/pt.
  - On a synthetic 1600×1200 image with 5 lines (4 Korean, 1 English), accurate mode with `["ko-KR","en-US"]` took 0.589 s cold, then 0.197–0.225 s. It recognized all Korean lines exactly ("화이트보드: 다음 주까지 인덱서 배포", "영수증 합계 … 부가세 포함"); "₩" was read as "W".
  - Fast mode took about 0.06 s but produced garbage for Korean ("2FOIE#E: EF-").
- ocrmac: MIT, 548 stars, v1.0.1 (2026-01-08). Python wrapper for Vision (`fast`/`accurate`) and the **LiveText** framework (macOS Sonoma+, no recognition levels). M3 Max timings: accurate 207 ms, fast 131 ms, LiveText 174 ms per image. Returns (text, confidence, bbox). — [straussmaximilian/ocrmac](https://github.com/straussmaximilian/ocrmac); [GitHub API](https://api.github.com/repos/straussmaximilian/ocrmac)
- Live Text languages include Korean (with Chinese, Japanese, English, etc.). — [iDownloadBlog (secondary, 2022, older)](https://www.idownloadblog.com/2022/09/22/how-to-use-live-text-on-iphone-mac/)
- osxphotos `detected_text()` uses Vision and takes about 2 s per image "on older Macs". — [osxphotos API_README](https://rhettbull.github.io/osxphotos/API_README.html)
- PaddleOCR:
  - Apache-2.0, 90.9k stars, v3.7.0 (2026-06-11). — [GitHub API: PaddlePaddle/PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR)
  - `korean_PP-OCRv5_mobile_rec`: ~14 MB, Korean + English + digits. Accuracy is reported as **88.0%** on PaddleOCR's Korean set, 65% better than the previous generation; another page reports 90.45% average recognition accuracy (sources disagree). — [HF: PaddlePaddle/korean_PP-OCRv5_mobile_rec](https://huggingface.co/PaddlePaddle/korean_PP-OCRv5_mobile_rec); [PP-OCRv5 multilingual docs](https://www.paddleocr.ai/latest/en/version3.x/algorithm/PP-OCRv5/PP-OCRv5_multi_languages.html)
  - Community ONNX exports exist. — [monkt/paddleocr-onnx](https://huggingface.co/monkt/paddleocr-onnx/commit/7b02d0a30a07ba2b92ad1ff5a8941ae2c633de65)
  - PaddleOCR-VL (0.9B VLM) covers 109 languages. — [arXiv 2510.14528](https://arxiv.org/pdf/2510.14528)
- Surya:
  - Code is Apache-2.0, but **weights** use "a modified AI Pubs Open Rail-M license (free for research, personal use, and startups under $5M funding/revenue)".
  - 90+ languages; Korean scores 86.7% on its internal benchmark. Surya 2 (650M params) scores 83.3% on olmOCR-bench.
  - On Apple Silicon it runs through llama.cpp/Metal at about 0.108 pages/s, so it is slow.
  - 21.5k stars, v0.22.1 (2026-07-20).
  — [datalab-to/surya](https://github.com/datalab-to/surya); [GitHub API](https://api.github.com/repos/datalab-to/surya)
- EasyOCR: Apache-2.0, 30.1k stars, but the last release is v1.7.2 from 2024-09 (stale). — [GitHub API: JaidedAI/EasyOCR](https://github.com/JaidedAI/EasyOCR)
- Immich's built-in OCR (v2.2.0, 2025-10-30) "officially supports English, Simplified and Traditional Chinese, and Japanese". Korean was not listed at launch. — [Linuxiac on Immich 2.2](https://linuxiac.com/immich-2-2-released-with-ocr-search-faster-web-layouts/); [Immich v2.2.0 blog](https://immich.app/blog/v2.2.0-release)

### Inferences
- Default OCR stack on the Mac:
  1. Photos' own `search_info.detected_text`, which costs nothing.
  2. Otherwise Vision accurate with `recognitionLanguages=["ko-KR","en-US"]` and `usesLanguageCorrection=true`, through a tiny Swift CLI or ocrmac.
  3. Optionally `RecognizeDocumentsRequest` for document-like screenshots and receipts, to keep table and paragraph structure.
- Never use `.fast` for Korean. It silently produces junk that would pollute FTS.
- Normalize "W" back to "₩" near digits, and index OCR text with SQLite FTS5 using the **trigram** tokenizer (or bigrams) for Korean substring matching.
- For Windows later: PaddleOCR PP-OCRv5 (Korean rec + multilingual det) through ONNX Runtime keeps the same output contract.
- Rough throughput: about 0.2–0.5 s/image × 30k images ≈ 2–4 h of single-stream OCR. It can run 2–3 in parallel and only needs to run on images that lack Photos OCR.

### Gaps
- No independent Korean OCR accuracy comparison (Vision vs PP-OCRv5 vs Surya) on real photos, receipts or whiteboards was found. My local test used clean synthetic text only.
- Whether Immich later added Korean OCR (after v2.2) was not checked.
- Windows' built-in `Windows.Media.Ocr` Korean support was not researched.

---

## 3. Text→image embedding models with Korean text encoders (quality, size, speed, licence; VPS text-encoder cost)

### Takeaway
Immich publishes per-language Crossmodal-3600 recall, which is the best Korean evidence available. **nllb-clip-base-siglip** (Korean 77.09) and **SigLIP2 L/SO400M** (74.5–77.1) lead. **SigLIP2 ViT-B/16** scores 71.09 for Korean vs 84.86 for English. The catch for tidy-one is that multilingual **text encoders are bigger than the image encoders**. In fp32 ONNX: SigLIP2-B/16 text is 1.16 GB, nllb-clip-base text 1.70 GB, SigLIP2-L/16 text 2.30 GB, nllb-large text 3.11 GB. On a 4 GB VPS the realistic choices are SigLIP2-B/16 or nllb-clip-base, quantized to int8/fp16. jina-clip-v2 is strong on Korean but is CC BY-NC with a 561M text tower. MobileCLIP2 is English-only.

### Cited Findings
**Immich Korean benchmark** (Crossmodal-3600; recall = mean of R@1/R@5/R@10; "Memory" = peak RSS, "Execution time" = mean of 100 passes, fp32, no acceleration, Ryzen 7800X3D; "only estimates"). — [Immich docs: Searching](https://docs.immich.app/features/searching)

| Model (Immich name) | Korean recall % | Memory MiB | Exec ms |
|---|---|---|---|
| nllb-clip-large-siglip__mrl | 80.56 | 4248 | 75.44 |
| nllb-clip-base-siglip__mrl | 77.09 | 4696 | 16.95 |
| ViT-SO400M-14-SigLIP2-378__webli | 77.08 | 3940 | 72.25 |
| ViT-SO400M-16-SigLIP2-384__webli | 76.92 | 3854 | 56.57 |
| ViT-SO400M-16-SigLIP2-256__webli | 76.20 | 3611 | 27.84 |
| ViT-L-16-SigLIP2-384__webli | 75.67 | 3057 | 51.70 |
| ViT-L-16-SigLIP2-256__webli | 74.52 | 2830 | 23.77 |
| XLM-Roberta-Large-ViT-H-14 (M-CLIP style) | 73.88 | 4014 | 39.14 |
| ViT-B-16-SigLIP2__webli | 71.09 | 3038 | 5.81 |
| ViT-B-16-SigLIP-i18n-256 | 68.87 | 3029 | 6.87 |
| ViT-B-32-SigLIP2-256__webli | 67.94 | 3061 | 3.31 |
| XLM-Roberta-Base-ViT-B-32 | 66.39 | 3030 | 3.20 |

- English reference: the top English rows are SigLIP2 SO400M/L at about 85.5–86.0%. ViT-B-16-SigLIP2 scores 84.86% in English, about 14 points above its Korean score. — [Immich docs](https://docs.immich.app/features/searching)
- Immich guidance:
  - NLLB models "expect the search query to be in the language specified in the user settings" and "tend to perform the best… when users primarily search in their native, non-English language".
  - XLM and SigLIP2 "understand search text regardless of the current language setting" and suit mixed-language search.
  - "The smaller models in this list are not too different in quality and many times faster."
  — [Immich docs](https://docs.immich.app/features/searching)
- **Text vs image ONNX file sizes** (fp32, from the Hugging Face API for `immich-app/*`, summed per folder; my calculation):

  | Model | textual | visual |
  |---|---|---|
  | ViT-B-16-SigLIP2 | **1,164 MB** (model.onnx 1,129 MB + tokenizer 34 MB) | 372 MB |
  | nllb-clip-base-siglip | **1,699 MB** | 373 MB |
  | nllb-clip-large-siglip | 3,113 MB | 1,713 MB |
  | ViT-L-16-SigLIP2-256 | 2,298 MB | 1,264 MB |
  | ViT-SO400M-16-SigLIP2-384 | 2,862 MB | 1,713 MB |
  | XLM-Roberta-Large-Vit-B-16Plus | 2,262 MB | 469 MB |
  | XLM-Roberta-Base-ViT-B-32 | 1,136 MB | 352 MB |

  — [HF API immich-app/ViT-B-16-SigLIP2__webli](https://huggingface.co/immich-app/ViT-B-16-SigLIP2__webli/tree/main), [nllb-clip-base-siglip__mrl](https://huggingface.co/immich-app/nllb-clip-base-siglip__mrl/tree/main), [Immich multilingual collection](https://huggingface.co/collections/immich-app/multilingual-clip)
- SigLIP 2:
  - "a family of new multilingual vision-language encoders". Sizes B (86M), L (303M), So400m (400M) and g (1B). Submitted 2025-02-20.
  - It beats SigLIP on XM3600 multilingual retrieval and is slightly behind mSigLIP.
  - The HF base model is Apache-2.0.
  — [arXiv 2502.14786](https://arxiv.org/abs/2502.14786); [HF google/siglip2-base-patch16-256](https://huggingface.co/google/siglip2-base-patch16-256)
  - A Core ML B/16-256 port (8-bit palettized, Apache-2.0) uses a 64-token text input with the Gemma SentencePiece tokenizer and a 768-d output. — [HF karaiman/siglip2-base-coreml](https://huggingface.co/karaiman/siglip2-base-coreml)
- jina-clip-v2:
  - 0.9B total: text encoder Jina-XLM-RoBERTa **561M**, vision EVA02-L14 304M.
  - 1024-d output with Matryoshka truncation down to 64; 512×512 input; 89 languages incl. Korean; ONNX available.
  - **CC BY-NC 4.0**.
  — [HF jinaai/jina-clip-v2](https://huggingface.co/jinaai/jina-clip-v2)
  - Korean text→image R@5: XTD10 ko 82.10 (nllb-siglip-large 85.20); Crossmodal-3600 ko 78.81 (nllb-siglip-large 78.75). — [jina-clip-v2 paper, arXiv 2412.08802](https://arxiv.org/html/2412.08802)
- Apple MobileCLIP2-S4 (Aug 2025):
  - Image encoder 321.6M, text encoder 123.6M. On iPhone 12 Pro Max: image 19.6 ms, text 6.6 ms. ImageNet zero-shot 81.9%.
  - No multilingual support documented (English examples only).
  - Licence: Apple AMLR.
  — [HF apple/MobileCLIP2-S4](https://huggingface.co/apple/MobileCLIP2-S4)
- Korean-specific CLIP: Bingsu/clip-vit-large-patch14-ko has 428M params and was distilled from CLIP ViT-L/14 using AIHub Korean–English parallel data. No retrieval benchmark is published on the model page. — [PromptLayer summary of model card (secondary)](https://www.promptlayer.com/models/clip-vit-large-patch14-ko); [HF Bingsu/clip-vit-large-patch14-ko](https://huggingface.co/Bingsu/clip-vit-large-patch14-ko/tree/436d2e3b38699f1c6bf55e81bdc0023a8aa10f8c)
- KoCLIP (2021, older) is a Flax community project. — [jaketae/koclip](https://github.com/jaketae/koclip); [HF forum](https://discuss.huggingface.co/t/koclip-pretraining-clip-on-korean/7280)
- Apple Silicon image-encoder speed:
  - SigLIP2-so400m Core ML fp16 at 378 px on an **M2 Pro**: CPU+GPU 224 ms/img (~4.5 img/s); CPU-only 353 ms; Neural Engine 184 ms (~5.4 img/s).
  - The ANE fp16 "drifts far enough to reorder search results" (top-10 overlap 82% vs 98% on GPU).
  - 815 MB, 1152-d output, Apache-2.0.
  — [HF antonlnz/siglip2-so400m-image-coreml](https://huggingface.co/antonlnz/siglip2-so400m-image-coreml)
  - rclip (OpenCLIP ViT-B/32): "7 minutes for 50,000 images on MacBook M1 Max". — [yurijmikhalevich/rclip](https://github.com/yurijmikhalevich/rclip)

### Inferences
- **Recommended default: SigLIP2 ViT-B/16 (256 px, `ViT-B-16-SigLIP2__webli`)**, Apache-2.0, language-agnostic. Reasons:
  - Smallest text encoder among the better multilingual models: about 282M params, mostly the large Gemma vocab embedding table (1.13 GB fp32 ONNX → about 0.3 GB int8 or 0.56 GB fp16).
  - Cheap per-query compute (Immich: 5.8 ms on a desktop CPU; probably tens of ms on 2 vCPU, unmeasured).
  - Fast image side on the M2.
  - Its Korean recall (71.1) is lower than nllb-base (77.1). The gap is narrowed in practice by hybrid search over OCR text, Apple labels, places and Korean captions.
- **Upgrade option if Korean quality matters more than RAM: nllb-clip-base-siglip.** Its text tower is 1.7 GB fp32 (~0.45 GB int8). Queries must be in the configured language (Korean). English or mixed queries degrade, which can be handled by giving the MCP tool a `query_ko` parameter that the agent fills. Avoid L/SO400M/nllb-large on the 4 GB VPS: 2.3–3.1 GB fp32 text towers.
- **Alternative design that sidesteps Korean text encoders:** the MCP callers are LLMs (Claude, Codex), so the `search_files` tool description can require the agent to send an **English paraphrase** (`query_en`) along with the Korean query. That makes English-only models (MobileCLIP2, OpenCLIP) usable, with a tiny text tower. Caveats: AMLR licence terms, and Aside or plain clients may not comply. Use it only as a fallback.
- **Model lock-in:** query and image vectors must come from the same model and version. Store `model_id` per vector, and plan a full re-embed (30k images ≈ tens of minutes on the M2 for B/16; see §7) when switching.
- Use GPU (`.cpuAndGPU`) rather than ANE for SigLIP-class models on the Mac. ANE fp16 measurably reorders results.
- The VPS should load only the **textual** ONNX (never the visual), quantized. Memory-mapping or fp16 keeps peak RSS well under 1 GB. This is inference; it must be measured on the VPS. Immich's 3,038 MiB "Memory" figure is the peak RSS of its full process in fp32, so it overstates a text-only, quantized deployment.

### Gaps
- No measured latency or RSS for SigLIP2/nllb text encoders on a 2-vCPU VPS, or for int8-quantized versions. Accuracy loss from int8-quantizing the SigLIP2 text tower is also unmeasured.
- Immich's table does not say whether "Execution time" is for the text or the image model.
- No Korean benchmark found for Bingsu/clip-vit-large-patch14-ko, KoCLIP or MobileCLIP2 (with translation).
- SigLIP2 per-language XM3600 numbers from the paper (Table 1 / Fig. 2) were not extracted.
- 2026 papers on multilingual VLM encoder failures were found but not read: [arXiv 2608.30725](https://arxiv.org/pdf/2608.30725), [arXiv 2510.26271](https://arxiv.org/pdf/2510.26271).

---

## 4. Captioning with a small local VLM (Qwen2.5/3-VL, Florence-2, SmolVLM, Moondream) — speed on M2 and worth vs CLIP

### Takeaway
Of the small VLMs checked, only the Qwen-VL family is a realistic **Korean** captioner (Qwen3-VL-4B is Apache-2.0 with 32-language OCR). Florence-2 is English-only (MIT). On Apple Silicon, Qwen3-VL-4B at 3–4-bit runs at roughly 20–40 tok/s on M1-class chips, which suggests about 5–10 s per photo on a base M2. Captioning 30k photos would take days. Use it **selectively** (screenshots, documents, whiteboards, receipts, and photos with no Apple caption or labels), not for the whole library. CLIP plus OCR plus Apple metadata covers most queries.

### Cited Findings
- Qwen3-VL-4B-Instruct: Apache-2.0, 4B params. OCR "Supports 32 languages (up from 19); robust in low light, blur, and tilt". Native context 256K. — [HF Qwen/Qwen3-VL-4B-Instruct](https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct)
- MLX 4-bit build: [mlx-community/Qwen3-VL-4B-Instruct-4bit](https://huggingface.co/mlx-community/Qwen3-VL-4B-Instruct-4bit). mlx-vlm: MIT, 5.6k stars, v0.7.6 (2026-10-05). — [GitHub API: Blaizzy/mlx-vlm](https://github.com/Blaizzy/mlx-vlm)
- vllm-mlx image benchmarks (page undated):
  - Qwen3-VL-4B-Instruct-3bit on M1 Max 64 GB: 40.7 tok/s aggregate over 224–1024 px (10.79 s for 439 tokens across 4 runs).
  - Qwen3-VL-8B-4bit on M1 Max: 21.1 tok/s.
  - Qwen3-VL-8B-4bit on M4 Max: 74.8 tok/s at 224 px down to 14.1 tok/s at 1920×1080.
  — [vllm-mlx image benchmarks](https://vllm-mlx.is-a.dev/benchmarks/image.md)
- A community oMLX benchmark: Qwen3-VL-4B-Instruct on M1 (8-core, 16 GB) generated text at 20.7 tok/s at 1k context. Search snippet only; not opened. — [oMLX community benchmarks](https://omlx.ai/benchmarks/wzpmndv0)
- Florence-2-large: 0.77B params, MIT. Tasks are caption, detailed caption, OCR, OCR-with-region, dense region caption and grounding. Docs cover English only. — [HF microsoft/Florence-2-large](https://huggingface.co/microsoft/Florence-2-large)
- Apple Photos already produces captions (mediaanalysisd `image_caption`), exposed by osxphotos `ai_caption`. — [osxphotos API_README](https://rhettbull.github.io/osxphotos/API_README.html)

### Inferences
- **Cost estimate (inference):**
  - A base M2 has about 100 GB/s memory bandwidth vs 400 GB/s on M1 Max, so decode should run at roughly 15–25 tok/s for Qwen3-VL-4B 4-bit.
  - A 60–100-token Korean caption plus prefill of about 300–1000 image tokens comes to about 5–10 s/image.
  - 30k photos would take 40–80 h of background compute. That is feasible spread over nights while plugged in, but it competes with the user's 24 GB RAM (~3 GB for the 4B model).
- **What captions add over CLIP:** a Korean text field for FTS (e.g., "화이트보드에 회의 일정과 할 일 목록이 적혀 있음") and better handling of compositional or document queries. CLIP handles scenes and objects ("제주 바다") well already, and OCR handles text-bearing images.
- **Selective policy:** caption (a) screenshots and documents, where OCR text is long or messy and a 1–2 sentence summary helps the agent; (b) images with OCR text present; (c) on demand, when the agent opens a result. Skip captioning of ordinary photos when Apple's labels/ai_caption exist.
- Florence-2, SmolVLM and Moondream produce English captions and tags only. They are useful only as English keyword generators; for Korean output, use Qwen3-VL. Prompt for both a Korean sentence and English keywords in one pass.

### Gaps
- No primary M2 (base) benchmark for Qwen3-VL-2B/4B in MLX found. No published Korean caption-quality evaluation for small VLMs found.
- SmolVLM and Moondream model cards were not fetched this pass. Their English-only status is from prior knowledge and is unverified here.
- Qwen2.5-VL-3B licence (reportedly a Qwen research licence, unlike 7B's Apache-2.0) was not verified.

---

## 5. Other signals: EXIF/GPS and Korean reverse geocoding, faces (privacy), duplicates

### Takeaway
Date and GPS turn queries like "작년 제주" into structured filters, which matters as much as embeddings. For Photos items, Apple's PlaceInfo and `search_info` place names are already reverse-geocoded. For loose files, use offline reverse geocoding: **krgc** for Korean administrative divisions (시/도, 시/군/구, 읍/면/동), and GeoNames-based `reverse_geocoder` for abroad. Take face identity only from Photos' named persons, and keep face data local, because Korean PIPA treats biometric data used to identify a person as **sensitive information**. For duplicates, use the Photos fingerprint plus perceptual hashes (imagehash, BSD-2).

### Cited Findings
- osxphotos `place` (PlaceInfo) gives a reverse-geocode name, a structured names hierarchy, country_code and address. `search_info` adds place_names, streets, neighborhoods, city, state, country, bodies_of_water, landmarks, areas_of_interest, home, trip. — [osxphotos API_README](https://rhettbull.github.io/osxphotos/API_README.html); [searchinfo.py](https://github.com/RhetTbull/osxphotos/blob/main/osxphotos/searchinfo.py)
- krgc (PyPI): "offline, deterministic reverse geocoding for South Korean administrative divisions", turning WGS84 lat/lon into province, city/district, town and village "with no network required". — [PyPI krgc](https://pypi.org/project/krgc/)
- reverse_geocoder (thampiman):
  - Uses GeoNames and returns city, country code and admin regions. GeoNames itself supports alternate names in many languages. — [thampiman/reverse-geocoder](https://github.com/thampiman/reverse-geocoder); [GeoNames manual](https://www.geonames.org/manual.html)
  - LGPL-2.1, 1.9k stars, last release v1.5 from **2016** (older; unmaintained). — [GitHub API](https://api.github.com/repos/thampiman/reverse-geocoder)
- Korean PIPA Enforcement Decree Art. 18(3) lists as sensitive data "Personal information resulting from specific technical processing of data relating to the physical, physiological or behavioral characteristics of an individual for the purpose of uniquely identifying that individual". — [Securiti PIPA overview](https://securiti.ai/south-korea-personal-information-protection-act/); [Hunton blog on PIPA regulations](https://www.hunton.com/privacy-and-cybersecurity-law-blog/korea-announces-regulations-to-personal-information-protection-act)
- InsightFace pretrained models (Immich uses buffalo_l and others) "are available for non-commercial research purposes only". Immich has written permission, which "does not extend to… third parties". — [Immich ML README mirror](https://ark.sudovanilla.org/Infrastructure/immich/raw/branch/main/machine-learning/README.md); [PyPI insightface](https://pypi.org/project/insightface/)
- osxphotos `fingerprint` is a hash of the original file. `hexdigest` reflects metadata changes, which suits incremental re-indexing. — [osxphotos API_README](https://rhettbull.github.io/osxphotos/API_README.html)
- apple-photos-mcp exposes a `find-duplicates` tool. — [sweetrb/apple-photos-mcp](https://github.com/sweetrb/apple-photos-mcp)
- imagehash (aHash/pHash/dHash/wHash): BSD-2-Clause, 3.9k stars, repo active (pushed 2026-10-05), last tagged release v4.1.0 (2021). — [GitHub API: JohannesBuchner/imagehash](https://github.com/JohannesBuchner/imagehash)

### Inferences
- Store `taken_at` (EXIF DateTimeOriginal, Photos date), `lat/lon` (rounded to about 100 m on the VPS for privacy), Korean `place_ko` (krgc for Korea, GeoNames `ko` alternate names elsewhere) and English `place_en` as filterable columns.
- Expose these as structured MCP parameters (`date_from`, `date_to`, `place`, `person`, `kind=screenshot|photo|document`). The calling LLM can turn "작년 제주 바다 사진" into `{date: 2025, place: "제주", query: "바다"}`. This beats pure embedding search for time and place queries.
- **Faces:** do not compute your own face embeddings. Use Photos' named `persons` only (the user already curated them), store only the person **names** in the central catalog, and keep face vectors and unnamed clusters off the VPS. Make person-name indexing opt-in.
- **Duplicates:** hash files (SHA-256) for exact duplicates and pHash/dHash (64-bit) for near-duplicates. This matters for screenshots copied between Desktop, Downloads and iCloud Drive, and for photos exported out of Photos into ~/Pictures. Collapse duplicates into one result with several locations.

### Gaps
- Which language Apple's PlaceInfo names come back in (Korean or English) on a Korean-locale Mac was not verified.
- krgc licence, maintenance and data source (e.g., 행정안전부 boundaries) were not checked.
- How reliable GeoNames `ko` alternate names are for small foreign places was not evaluated.

---

## 6. Existing OSS to borrow (Immich, PhotoPrism, LibrePhotos, rclip, clip-retrieval, Photos MCP servers)

### Takeaway
Immich's ML pipeline is the best reference for model choice and benchmarks: per-language recall tables, separate textual/visual ONNX exports on Hugging Face, OCR and faces. But its server needs ≥6 GB RAM, so borrow its **models and design, not its server**. For the Photos side, apple-photos-mcp (MIT, osxphotos-based, read-only, has `get-thumbnail` and labels/OCR/places/persons) is a close template for a local MCP. tidy-one needs the same data pushed to a remote catalog instead. rclip shows how fast a simple local CLIP indexer can be on Apple Silicon.

### Cited Findings
| Project | Stars / licence / latest | Relevance | Source |
|---|---|---|---|
| Immich | 115.9k ★, AGPL-3.0, v3.3.1 (2026-10-08) | CLIP smart search (multilingual SigLIP2/NLLB/XLM-R), OCR (v2.2+, en/zh/ja officially), faces (InsightFace). Server ≥6 GB RAM; 4 GB only with ML off | [GitHub API](https://github.com/immich-app/immich); [search docs](https://docs.immich.app/features/searching); [requirements](https://docs.immich.app/install/requirements) |
| Immich HF models | per-model `textual/` and `visual/` ONNX | Ready ONNX exports; text tower can be deployed alone | [HF collection](https://huggingface.co/collections/immich-app/multilingual-clip) |
| PhotoPrism | 40.3k ★, licence "NOASSERTION" on GitHub (AGPL-based with extras), release 261007 (2026-10-07) | Mature self-hosted photo app; ML features not re-checked | [GitHub API](https://github.com/photoprism/photoprism) |
| LibrePhotos | 8.1k ★, MIT, 1.2.1 (2026-09-29) | Self-hosted, Python/Django; ML stack not re-checked | [GitHub API](https://github.com/LibrePhotos/librephotos) |
| rclip | 1.0k ★, MIT, v4.0.1 (2026-09-19) | Local CLI CLIP search (OpenCLIP ViT-B/32, English); 50k images in 7 min on M1 Max; text/image/combined queries | [rclip](https://github.com/yurijmikhalevich/rclip) |
| clip-retrieval | 2.8k ★, MIT, 2.45.0 (2025-08, older) | Batch embedding + kNN index tooling; less active | [GitHub API](https://github.com/rom1504/clip-retrieval) |
| apple-photos-mcp (sweetrb) | 27 ★, MIT, v2.1.20 (2026-10-07) | Local MCP over osxphotos. Tools: `query`, `get-photo(s)`, `get-selected-photos`, `get-thumbnail`, `find-duplicates`, `list-albums/folders/keywords/persons`, `export`, `doctor`. Read-only by default (writes need `APPLE_PHOTOS_MCP_ENABLE_WRITES=1`). Exposes labels, Photos OCR text, places, persons, aesthetic score, EXIF. Needs Full Disk Access | [GitHub](https://github.com/sweetrb/apple-photos-mcp); [Glama](https://glama.ai/mcp/servers/sweetrb/apple-photos-mcp) |
| drolosoft/immich-photo-manager | 53 ★, MIT, v2.0.13 (2026-10-06) | MCP for Immich (CLIP + OCR search) | [GitHub API](https://github.com/drolosoft/immich-photo-manager) |
| ocrmac | 548 ★, MIT, v1.0.1 (2026-01) | Python Vision/LiveText OCR | [GitHub](https://github.com/straussmaximilian/ocrmac) |
| mlx-vlm | 5.6k ★, MIT, v0.7.6 (2026-10-05) | Local VLM captioning on Apple Silicon | [GitHub API](https://github.com/Blaizzy/mlx-vlm) |

- Sibling research found Immich, Khoj and similar full stacks too heavy for the VPS, and that Immich's mobile upload depends on OS-controlled background execution. — [research_notes/개인 기기 통합 인덱싱 설계/existing_oss_products.md](../개인%20기기%20통합%20인덱싱%20설계/existing_oss_products.md); [architecture_patterns.md](../개인%20기기%20통합%20인덱싱%20설계/architecture_patterns.md)

### Inferences
- **What to borrow from each:**
  - Immich: the model shortlist and the textual/visual ONNX split. Downloading only `textual/` to the VPS and `visual/` to the Mac is a direct fit.
  - apple-photos-mcp: the field selection and the read-only safety posture. Its `get-thumbnail` pattern suits an on-demand "show me" tool that proxies to the Mac when awake.
  - rclip: SQLite-backed incremental indexing (skip unchanged files by mtime/hash).
- Running Immich itself on the Mac with remote ML is possible but duplicates the Photos library (AGPL, Postgres, uploads). It does not match the "index in place, central catalog only" design.

### Gaps
- PhotoPrism's and LibrePhotos' current ML (CLIP or not, multilingual or not) were not verified this pass.
- No other "osxphotos MCP" with remote (HTTP/OAuth) transport was found; all found are local stdio.

---

## 7. Throughput for tens of thousands of photos on M2, catalog size, what to keep central — and recommended pipeline

### Takeaway
For about 30k images on the M2: Apple metadata takes minutes, OCR about 2 h (often skippable via Photos OCR), SigLIP2-B/16 embeddings under an hour, and optional VLM captions days, so captions must be selective. The central catalog stays small: about 25–100 MB of vectors plus about 30–60 MB of text for 30k items. Keep metadata, text and vectors central. Keep originals and face data on the device. Treat thumbnails as optional (small, about 5–20 KB each, or none).

### Cited Findings
- Measured or published speeds:
  - Vision accurate OCR: about 0.2 s/image on this M2 **[local test]**. 207 ms on M3 Max via ocrmac. — [ocrmac](https://github.com/straussmaximilian/ocrmac)
  - SigLIP2-so400m (378 px) on M2 Pro: about 4.5 img/s on GPU. — [antonlnz/siglip2-so400m-image-coreml](https://huggingface.co/antonlnz/siglip2-so400m-image-coreml)
  - OpenCLIP ViT-B/32 (rclip): 50k images in 7 min on M1 Max. — [rclip](https://github.com/yurijmikhalevich/rclip)
  - Qwen3-VL-4B-3bit: about 41 tok/s aggregate on M1 Max. — [vllm-mlx](https://vllm-mlx.is-a.dev/benchmarks/image.md)
- Output dimensions: SigLIP2-B/16 768-d ([karaiman/siglip2-base-coreml](https://huggingface.co/karaiman/siglip2-base-coreml)); so400m 1152-d ([antonlnz](https://huggingface.co/antonlnz/siglip2-so400m-image-coreml)); jina-clip-v2 1024-d, Matryoshka down to 64 ([HF](https://huggingface.co/jinaai/jina-clip-v2)).
- Optimize Storage keeps previews and thumbnails locally (`resources/derivatives`) and removes only originals. — [Mole blog (secondary)](https://mole.tw93.fun/blog/how-to-free-up-photos-storage-mac)

### Inferences
**Throughput estimate, 30k images on M2 24 GB** (my arithmetic from the figures above; to be measured):

| Stage | Per image | 30k images | Notes |
|---|---|---|---|
| osxphotos metadata + search_info + persons + places | ms | minutes | One DB read; incremental via `hexdigest` |
| Decode derivative/HEIC → 256–384 px | ~10–30 ms | ~5–15 min | ImageIO/sips; no iCloud download |
| SigLIP2-B/16 image embedding (GPU, batch) | ~20–60 ms (B/16 has ~1/4–1/5 the FLOPs of so400m@378) | ~10–30 min | rclip's B/32 figure (~120 img/s on M1 Max) is an upper bound |
| Vision OCR (accurate, ko+en) | ~0.2–0.5 s | ~2–4 h | Skip when Photos `detected_text` exists; skip `.fast` |
| Qwen3-VL-4B caption (selective) | ~5–10 s | 40–80 h if all | Caption only screenshots/docs/whiteboards (say 10–20% → 4–16 h) |

**Central catalog size for 30k items** (arithmetic):
- Vectors: 768-d float32 = 3 KB/item, about 92 MB; int8 about 23 MB. sqlite-vec supports float32 and int8/bit vectors.
- OCR, labels, captions and places: about 0.5–2 KB/item, about 15–60 MB, plus an FTS5 trigram index of about 2–3× the text size.
- Optional thumbnails: 160 px WebP at about 5–8 KB means 150–250 MB; 256 px JPEG at about 20 KB means about 600 MB. That is too much for a 4 GB VPS disk budget shared with other data, so leave them off by default and fetch them on demand from the Mac (or from iCloud through the user's device).

**What to keep central vs on device**
- Central (VPS): item id (`photos:<uuid>` or `file:<device>:<path-hash>`), source, path/URI for opening, timestamps, coarse geo, Korean and English place names, Apple labels and search_info (filtered), named persons (opt-in), OCR text, caption, sha256/pHash, the embedding vector plus `model_id`, and the screenshot/document flags.
- Device only: originals, derivatives/thumbnails, face vectors and unnamed clusters, `id_document_*` fields, raw EXIF beyond date/camera, and precise GPS (if the user prefers).

#### Recommended pipeline (inference, for tidy-one)
1. **Discovery**
   - Photos: osxphotos `PhotosDB()`, incremental by `hexdigest`/`date_modified`.
   - Files: FSEvents/Spotlight over ~/Pictures, ~/Desktop (screenshots via the `kMDItemIsScreenCapture` Spotlight attribute or the filename pattern), ~/Downloads (images only) and iCloud Drive. Skip `SF_DATALESS` (not-downloaded) files, as in the sibling research. Dedupe with sha256 and pHash.
2. **Image source per item:** Photos uses `path_derivatives[0]` (largest local preview), else `path` if local, never `--download-missing`. Files use the file itself, decoded via ImageIO.
3. **Metadata:**
   - Photos: date, PlaceInfo, `search_info` (labels, places, activities, venues, events, pets, landmarks, document_types, detected_text), persons (opt-in), ai_caption, score, screenshot flag.
   - Files: EXIF date and GPS.
   - Reverse geocoding: krgc (KR) and GeoNames `ko` names (abroad).
4. **OCR:** Photos `detected_text` if present; else Vision accurate `["ko-KR","en-US"]` (RecognizeDocumentsRequest for document-like screenshots). Store the text and index it with FTS5 (trigram).
5. **Embedding:** SigLIP2 ViT-B/16-256 image tower on the M2 (Core ML or ONNX/MLX on GPU), L2-normalized 768-d. Push int8 or float32 to sqlite-vec with `model_id`.
6. **Captions (selective):** Qwen3-VL-4B 4-bit via mlx-vlm, overnight, for screenshots, documents and whiteboards. Prompt: "한국어 1–2문장 설명 + English keywords".
7. **VPS query path:** load only the SigLIP2 textual ONNX, int8 or fp16 quantized (~0.3–0.6 GB), plus the Gemma tokenizer. `search_files(query, date_from, date_to, place, person, kind, k)` runs:
   - (a) SQL filters;
   - (b) FTS5 over OCR, caption, labels and places;
   - (c) vector kNN on the query embedding;
   - (d) a fused ranking (reciprocal-rank fusion).

   Results return text snippets plus open-on-device URIs, not images.
8. **Upgrade levers:**
   - Swap to nllb-clip-base-siglip if Korean recall disappoints and VPS RAM allows (text tower about 1.7 GB fp32).
   - Optionally ask the calling LLM for `query_en` so English-only models or English labels can be matched.
   - Windows later: the same contract, with PaddleOCR PP-OCRv5 Korean in place of Vision and SigLIP2 via ONNX Runtime/DirectML.

### Gaps
- None of the per-stage M2 timings except Vision OCR were measured on this machine: decode, SigLIP2-B/16 throughput, and Qwen3-VL caption time. Run a 500-image benchmark before committing.
- VPS-side text-encoder RSS and latency (fp32 vs int8 vs fp16, onnxruntime on 2 vCPU) are unmeasured. This is the key go/no-go number for the 4 GB box.
- No source found on sqlite-vec int8 recall loss for SigLIP2 vectors.
- The actual size of the user's Photos library, its iCloud-optimized share, and whether Photos' own OCR and captions are populated are unknown until a local osxphotos scan runs.
