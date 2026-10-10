# Making personal videos searchable by content: techniques, OSS building blocks and a pipeline for tidy-one

Context carried through: Korean solo developer building "tidy-one". Device agents run on a MacBook M2 with 24 GB RAM (confirmed on this machine: `Apple M2`, 25,769,803,776 bytes). A Windows laptop comes later. Devices compute every embedding locally. Only metadata, short text excerpts and vectors go to a Vultr Seoul VPS (4 GB RAM, Ubuntu 24.04) that holds a SQLite + sqlite-vec catalog and exposes MCP tools (`search_files` and others) to Claude Code, Codex, claude.ai and Aside. The videos are iPhone clips (in the Photos library, ~/Movies and ~/Downloads), screen recordings, and meeting or lecture recordings with Korean speech. ffmpeg is not installed. Research date: 2026-10-10. GitHub star counts, licenses and last-push dates come from the GitHub API on 2026-10-10 unless noted. Anything dated before 2025 is marked as possibly outdated.

## Q1. Pipeline patterns and model choices: metadata, shot detection plus keyframes, frame embeddings, video-text embeddings, Korean ASR, keyframe captioning, OCR

### Takeaway
No single open model makes a personal video "readable" by itself. Every working system combines four things:
- cheap container metadata
- sampled keyframes embedded with a multilingual CLIP or SigLIP model, for "text → moment" search
- ASR transcripts, for speech
- optionally, VLM captions and OCR, which turn pixels into searchable text

For Korean in 2026, these are the strongest local choices:
- **Frame embeddings:** SigLIP2 (Apache-2.0). It understands Korean queries with no language setting.
- **Korean ASR:** Qwen3-ASR-1.7B (Apache-2.0, MLX ports at 8-bit). Whisper-large-v3-turbo through mlx-whisper is the mature fallback.
- **Whole-clip video vectors:** Qwen3-VL-Embedding-2B (Apache-2.0, MLX ports exist) is the first credible open "Twelve Labs-like" option. It is much heavier than SigLIP.

### Cited Findings

**Metadata only (cheapest layer)**
- ExifTool's QuickTime "Keys" tag table includes Apple keys such as `location.ISO6709` (GPS) and `camera.lens_model`, so iPhone clips carry GPS and lens or device information in the container. — [ExifTool QuickTime tags](https://exiftool.org/TagNames/QuickTime.html)
- osxphotos (MIT, 3,894★, pushed 2026-10-05) gives read-only access to the Apple Photos library from Python or the CLI:
  - It has a `labels` command that prints the Photos ML image-classification labels.
  - Its `query` and `export` commands take `--only-movies` and `{label}` keyword templates. Labels are available on Photos 5 and later.
  - Sources: [osxphotos on PyPI](https://pypi.org/project/osxphotos/); [GitHub](https://github.com/RhetTbull/osxphotos)
- Apple Photos' own Apple Intelligence search (macOS 15.1+, M1 or later) accepts natural-language descriptions and can find "a key moment in a video". This means Photos already builds a semantic video index on the device. — [Apple Support: Search with Apple Intelligence on Mac](https://support.apple.com/guide/mac-help/mchl35c53342); [Tom's Guide on iOS 18.1 video moments](https://www.tomsguide.com/phones/ios-18-1-lets-you-search-for-moments-in-videos-heres-how-it-works)

**Shot/scene detection and keyframe sampling**
- PySceneDetect (BSD-3-Clause, 5,228★, latest release v0.7.1 on 2026-07-22) is the maintained Python scene-cut detector. — [GitHub](https://github.com/Breakthrough/PySceneDetect)
- TransNetV2 (MIT, 1,053★) is a neural shot-boundary detector. Its last push was 2023-12, so it is possibly outdated and unmaintained. — [GitHub](https://github.com/soCzech/TransNetV2)
- ffmpeg's `select` filter exposes a `scene` score (for example `select='gt(scene,0.3)'`), so a separate detector is not strictly needed. — [ffmpeg filters docs](https://ffmpeg.org/ffmpeg-filters.html#select_002c-aselect)
- Qwen3-VL-Embedding samples video itself. Defaults are `fps=1.0` and `max_frames=64`, with a total pixel budget of 1,843,200. — [Qwen3-VL-Embedding GitHub](https://github.com/QwenLM/Qwen3-VL-Embedding)

**Frame embeddings with multilingual CLIP/SigLIP (text → frame search)**
- Immich's docs benchmark multilingual CLIP models on Crossmodal-3600 and XTD-10. Korean recall (average of R@1, R@5 and R@10) and CPU cost, measured f32 on a Ryzen 7800X3D without acceleration:

  | Model | Korean recall | Peak memory | Time per pass | License |
  |---|---|---|---|---|
  | nllb-clip-large-siglip | 80.56% | 4,248 MiB | 75 ms | — |
  | ViT-SO400M-14-SigLIP2-378 | 77.08% | 3,940 MiB | 72 ms | — |
  | ViT-SO400M-16-SigLIP2-256 | 76.2% | 3,611 MiB | 28 ms | — |
  | ViT-L-16-SigLIP2-256 | 74.52% | 2,830 MiB | 24 ms | — |
  | XLM-Roberta-Large-ViT-H-14 | 73.88% | — | — | — |
  | ViT-B-16-SigLIP2 | 71.09% | 3,038 MiB | 5.8 ms | — |
  | ViT-B-32-SigLIP2-256 | 67.94% | — | 3.3 ms | — |
  | XLM-Roberta-Base-ViT-B-32 | 66.39% | — | — | — |

  Source: [Immich searching.md](https://github.com/immich-app/immich/blob/main/docs/docs/features/searching.md)
- Per Immich, `nllb` models expect the query in the language set in user settings. `xlm` and `siglip2` models "understand search text regardless of the current language setting". — [Immich searching.md](https://github.com/immich-app/immich/blob/main/docs/docs/features/searching.md)
- License traps:
  - NLLB-CLIP (both large and base) is CC-BY-NC-4.0 and dates from 2023-11, so it is possibly outdated. — [HF visheratin/nllb-clip-large-siglip](https://huggingface.co/visheratin/nllb-clip-large-siglip)
  - jina-clip-v2 (89 languages including ko, 512×512 input, Matryoshka dimensions; released 2024-12, possibly outdated) is also CC-BY-NC-4.0. — [HF jinaai/jina-clip-v2](https://huggingface.co/jinaai/jina-clip-v2); [jina-clip-v2 paper](https://arxiv.org/html/2412.08802v1)
  - SigLIP2 (for example `google/siglip2-so400m-patch16-384`) is Apache-2.0. — [HF google/siglip2-so400m-patch16-384](https://huggingface.co/google/siglip2-so400m-patch16-384)
- Community Korean vocabulary-trimmed SigLIP2 variants exist, for example `siglip2-large-patch16-512-kor-16384`, which is 27.81% smaller via vocabulary trimming. — [HF alphaedge-ai](https://huggingface.co/alphaedge-ai/siglip2-large-patch16-512-kor-16384)
- MEXMA-SigLIP2 (MEXMA multilingual text encoder plus SigLIP2 image encoder, 80 languages) reports state of the art on Crossmodal-3600: 62.54% R@1 for image retrieval. — [HF visheratin/mexma-siglip2](https://huggingface.co/visheratin/mexma-siglip2)
- Apple MobileCLIP2 (released 2025-08-28; S4 "matches SigLIP-SO400M/14 with 2x fewer parameters"):
  - Its weights are under the `apple-amlr` research license.
  - It is an English-trained CLIP; no multilingual claim was found.
  - Sources: [ml-mobileclip README](https://github.com/apple-aiml-research/ml-mobileclip); [HF apple/MobileCLIP2-S2](https://huggingface.co/apple/MobileCLIP2-S2)
- Older multilingual CLIPs are possibly outdated: FreddeFrallan/Multilingual-CLIP (MIT, last push 2023-05). — [GitHub](https://github.com/FreddeFrallan/Multilingual-CLIP)
- MLX ports: `mlx-community/siglip2-so400m-patch16-384` and `siglip2-base-patch16-224-8bit` exist on Hugging Face. — [HF API search, mlx-community siglip2](https://huggingface.co/mlx-community)

**Dedicated video-text embedding models**
- Qwen3-VL-Embedding (Apache-2.0, 1,395★):
  - Released January 2026 ([arXiv 2601.04720](https://arxiv.org/abs/2601.04720v1)), in 2B and 8B sizes.
  - Inputs: text, images, screenshots, video and mixed inputs, in 30+ languages.
  - Matryoshka dimensions from 64 up to 2048 (2B) or 4096 (8B), with 32K context. A Qwen3-VL-Reranker (2B/8B) is also available.
  - MMEB-V2 scores, 2B / 8B: video retrieval 53.9 / 58.7, video moment retrieval 53.3 / 56.1, overall 73.2 / 77.8. For comparison, older open embedders score video retrieval 20.6 (VLM2Vec-2B), 28.8 (VLM2Vec-V2-2B) and 28.4 (GME-7B).
  - Sources: [HF model card](https://huggingface.co/Qwen/Qwen3-VL-Embedding-2B); [GitHub](https://github.com/QwenLM/Qwen3-VL-Embedding)
- MLX ports of Qwen3-VL-Embedding-2B exist in bf16, 8-bit, 6-bit, 5-bit, 4-bit, mxfp8, mxfp4 and nvfp4. The 8-bit port (created 2026-03-13) has about 1k downloads. A `Qwen3-VL-Reranker-2B` MLX port exists too. — [HF mlx-community/Qwen3-VL-Embedding-2B-8bit](https://huggingface.co/mlx-community/Qwen3-VL-Embedding-2B-8bit)
- Pre-2025 or English-centric video-text models (possibly outdated):
  - LanguageBind: MIT, 888★, last push 2024-03. — [GitHub](https://github.com/PKU-YuanGroup/LanguageBind)
  - InternVideo / InternVideo2: Apache-2.0, 2,401★, pushed 2026-07. — [GitHub](https://github.com/OpenGVLab/InternVideo)
  - ImageBind (used by VideoRAG): CC BY-NC-SA 4.0, so non-commercial. — [ImageBind LICENSE](https://github.com/facebookresearch/ImageBind)
  - Meta perception_models (Perception Encoder): Apache-2.0, 2,381★. — [GitHub](https://github.com/facebookresearch/perception_models)
  - Google VideoPrism: Apache-2.0, 397★, pushed 2026-10-08. — [GitHub](https://github.com/google-deepmind/videoprism)
  - TIGER-Lab VLM2Vec(-V2): Apache-2.0. — [GitHub](https://github.com/TIGER-AI-Lab/VLM2Vec)

**Korean ASR**
- Qwen3-ASR (Apache-2.0, released 2026-01-29, 0.6B and 1.7B):
  - Covers 30 languages plus 22 Chinese dialects, including Korean, with built-in language ID.
  - Takes a single offline input of up to 20 minutes (1200 s).
  - Its tech report (Table A.2) gives Korean CER for 0.6B / 1.7B / Flash-API: FLEURS-ko 3.72 / 2.57 / 2.07, CommonVoice-ko 8.48 / 5.88 / 3.82, and the conversational MLC-SLM-ko set 10.31 / 8.61 / 8.09.
  - Sources: [Qwen3-ASR Technical Report, arXiv 2601.21337](https://arxiv.org/pdf/2601.21337); [GitHub](https://github.com/QwenLM/Qwen3-ASR)
- Qwen3-ForcedAligner-0.6B (word or character timestamps, up to 300 s per alignment, 11 languages) covers Korean. Its Korean timestamp shift (AAS) is 37.2 ms on raw clips and 42.2 ms on 300 s concatenations. — [Qwen3-ASR Technical Report, Table 9](https://arxiv.org/pdf/2601.21337). The GitHub README summary did not list Korean for the aligner; the paper table does.
- Independent FLEURS-ko runs:
  - On an M5 MacBook Air (32 GB), Qwen3-ASR-1.7B (MLX 8-bit) scored 3.54% CER against 4.25% for Whisper-large-v3-turbo (whisper.cpp on Metal), "inside the 95% band". Median speed was 9.6× vs 2.6× realtime across languages. Posted 2026-08-25. — [WhisperNotes blog](https://whispernotes.app/blog/qwen3-asr-vs-whisper)
  - Handy's FLEURS Q8_0 ranking: Qwen3-ASR-1.7B 4.60% CER, whisper-large-v3 4.89%, whisper-large-v2 4.99%, Fun-ASR-MLT-Nano-2512 5.20%, whisper-large-v3-turbo 5.24%. — [models.handy.computer/languages/ko](https://models.handy.computer/languages/ko)
- **Quantization matters a lot for Korean.** Soniqo's MLX benchmark (M5 Pro) shows Qwen3-ASR FLEURS-Korean WER of 19.95 at 4-bit vs 6.89 at 8-bit. English barely changes (6.57 vs 5.64). — [soniqo.audio benchmarks](https://soniqo.audio/benchmarks)
- On LibriSpeech English (M5 Pro), memory and speed:

  | Model | WER | Realtime factor | Peak memory |
  |---|---|---|---|
  | Qwen3-ASR-1.7B 5-bit | 1.32 | 0.027 | 1.92 GB |
  | WhisperKit large-v3-turbo | 1.71 | 0.084 | 0.43 GB |
  | Parakeet TDT v3 INT8 | 2.37 | 0.009 | 0.9 GB |

  Parakeet v3 covers English plus 25 European languages, not Korean. — [soniqo.audio benchmarks](https://soniqo.audio/benchmarks); [mlx-audio README](https://github.com/Blaizzy/mlx-audio)
- mlx-audio (MIT, 8,019★, pushed 2026-10-09) bundles STT on MLX:
  - Whisper large-v3-turbo
  - Qwen3-ASR (KO), for example `mlx-community/Qwen3-ASR-1.7B-8bit`
  - Parakeet, VibeVoice-ASR (diarization and timestamps), Voxtral Realtime, Canary and MMS

  — [GitHub](https://github.com/Blaizzy/mlx-audio)
- `mlx-community/Qwen3-ASR-0.6B-8bit` has about 217k downloads, which signals heavy real-world MLX use. — [HF mlx-community](https://huggingface.co/mlx-community/Qwen3-ASR-0.6B-8bit)
- SenseVoiceSmall:
  - Language ID covers zh, yue, en, ja and ko, plus emotion, audio-event and "nospeech" tags. Diarization needs separate FunASR FSMN-VAD and CAM++ models.
  - It is non-autoregressive and claims to be ">15 times faster than Whisper-Large". Model license is "other" (FunASR model license); code is MIT.
  - Sources: [SenseVoice README](https://github.com/FunAudioLLM/SenseVoice); [HF FunAudioLLM/SenseVoiceSmall](https://huggingface.co/FunAudioLLM/SenseVoiceSmall)
  - A vendor blog recommends SenseVoice over Whisper-turbo for Korean, citing "52× real-time" on CJK, and says Turbo's pruned 4-layer decoder loses more accuracy in non-English languages. — [WhisperNotes on Whisper turbo](https://whispernotes.app/blog/introducing-whisper-large-v3-turbo)
- WhisperX (BSD-2-Clause, 24,444★, v3.8.6 on 2026-05-25):
  - Built on the faster-whisper backend.
  - Word-level timestamps via wav2vec2. Korean uses `kresnik/wav2vec2-large-xlsr-korean`.
  - Diarization via `pyannote/speaker-diarization-community-1`, which needs a Hugging Face token and accepting the model agreement.
  - GPU acceleration is CUDA-only.
  - Sources: [whisperX README](https://github.com/m-bain/whisperX); [alignment.py](https://github.com/m-bain/whisperX/blob/main/whisperx/alignment.py)
- whisper.cpp (MIT, 54,259★, v1.9.5 on 2026-10-06) and faster-whisper (MIT, 25,781★) are both active. — [whisper.cpp](https://github.com/ggml-org/whisper.cpp); [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
- Other Korean-capable options:
  - Fun-ASR (Apache-2.0, 1,564★). — [GitHub](https://github.com/QwenAudio/Fun-ASR)
  - sherpa-onnx (Apache-2.0, 15,190★, cross-platform, so it also fits the later Windows agent). — [GitHub](https://github.com/k2-fsa/sherpa-onnx)
  - Korean fine-tunes of Qwen3-ASR, for example TeamUNIVA/qwen3_asr_1.7b_ko_beta: combined CER 0.0537 across clova_call, CommonVoice, FLEURS, KsponSpeech and Zeroth, which is 1.49 points better than base. — [HF TeamUNIVA](https://huggingface.co/TeamUNIVA/qwen3_asr_1.7b_ko_beta)

**Captioning keyframes with a small local VLM**
- mlx-vlm (MIT, 5,591★, v0.7.6 on 2026-10-05) runs Qwen2/3-VL, Gemma 3, SmolVLM and other models on MLX. — [GitHub](https://github.com/Blaizzy/mlx-vlm)
- MLX quantized VLMs available on Hugging Face:
  - `Qwen3-VL-4B-Instruct-4bit` (about 22k downloads)
  - `Qwen3-VL-2B-Instruct-4bit`
  - `Qwen3-VL-8B-Instruct-4bit`
  - `SmolVLM2-500M-Video-Instruct-mlx` and `SmolVLM2-256M-Video-Instruct-mlx`
  - `FastVLM-0.5B-bf16`

  — [HF mlx-community](https://huggingface.co/mlx-community)
- Qwen3-VL (Apache-2.0, 20,053★) is the base family. — [GitHub](https://github.com/QwenLM/Qwen3-VL)
- Moondream (Apache-2.0, 10,096★). — [GitHub](https://github.com/m87-labs/moondream)
- Apple FastVLM (7,422★): the 0.5B model reaches 85× faster time-to-first-token than LLaVA-OneVision-0.5B, and Apple Silicon export is provided. The weights are under the Apple ML Research Model license, "for the sole purpose of scientific research". — [ml-fastvlm README and LICENSE_MODEL](https://github.com/apple-aiml-research/ml-fastvlm)

**OCR for screen recordings**
- Apple Vision `VNRecognizeTextRequest` supports `ko-KR` on recent macOS. A developer-forum list for Sonoma includes Korean. Revision 1 was English-only. — [Apple Developer Forums 121048](https://developer.apple.com/forums/thread/121048); [recognitionLanguages docs](https://developer.apple.com/tutorials/data/documentation/vision/vnrecognizetextrequest/recognitionlanguages.md)
- ocrmac (MIT, 548★) is a Python wrapper around the Vision framework. — [GitHub](https://github.com/straussmaximilian/ocrmac)

### Inferences
- **For short iPhone clips, scene detection adds little.** Most clips are 5–60 s single shots. Uniform sampling (first frame, last frame, and one every 2–3 s) plus near-duplicate removal (cosine > ~0.95 between consecutive frame embeddings) is simpler and is enough. Use PySceneDetect or ffmpeg `scene` only for long, edited or lecture videos.
- **Choosing the SigLIP2 size.** On Immich's numbers, ViT-B-16-SigLIP2 (71% Korean recall, about 6 ms per pass on a desktop CPU) is the speed pick. ViT-SO400M-16-SigLIP2-256/384 (76–77%) is the quality pick. Both are Apache-2.0 and take Korean queries directly. Avoid NLLB-CLIP and jina-clip-v2 if tidy-one might ever be commercial, because both are CC-BY-NC.
- **Qwen3-VL-Embedding-2B as a second index.** It is the best open option for "find the clip where…" queries over whole clips or 10–30 s segments, including screenshot or screen-recording understanding. At 2B parameters it is about 5–10× heavier per input than SigLIP2-B. Use it as a second-tier index (one vector per clip or segment) on top of per-frame SigLIP2 vectors, not as a replacement. Store it at a Matryoshka dimension of 512–1024.
- **Korean ASR choice.** Qwen3-ASR-1.7B at 8-bit (not 4-bit) via mlx-audio is the best accuracy-to-speed choice on Apple Silicon. Whisper-large-v3-turbo via mlx-whisper is the fallback when timestamps or ecosystem maturity matter. SenseVoiceSmall is the fastest option for "is there speech, and what roughly is said" on short clips.
- **Diarization.** WhisperX diarization runs CPU-only on a Mac. VibeVoice-ASR in mlx-audio might replace it on MLX, but its Korean support is unverified (see Gaps).
- **Native macOS route around ffmpeg.** AVFoundation (frame extraction and metadata), Vision (OCR) and osxphotos (Photos labels and UUIDs) are macOS-native. The Mac agent could therefore skip ffmpeg at first. ffmpeg (or PyAV) is still needed on Windows and for odd codecs.

### Gaps
- No public, verified Korean benchmark for Whisper-large-v3-turbo on KsponSpeech (spontaneous Korean) was found. All comparisons above are FLEURS (read speech) or CommonVoice, so meeting-style Korean accuracy is unknown. The best proxy is Qwen3-ASR's MLC-SLM-ko conversational CER of 8.61 (1.7B).
- No Korean-specific text→video retrieval benchmark was found for SigLIP2 or Qwen3-VL-Embedding. The Immich Korean recall figures are image retrieval on Crossmodal-3600 and XTD-10.
- No 2025–2026 Gemma-based video embedding model was found. Gemma-based embedders seen were text-only, and this was not verified in depth.
- VibeVoice-ASR's Korean quality and Qwen3-ForcedAligner availability on MLX (as opposed to PyTorch) were not verified.
- Whether Apple Photos exposes its Apple Intelligence video-moment index, or per-video ML labels, through osxphotos or PhotoKit was not verified.

## Q2. Existing open-source "video RAG / video search" projects to borrow from

### Takeaway
No existing OSS project fits tidy-one as is. Each project falls short in one of these ways:
- Built for NVIDIA GPUs or Docker, which cannot use the Apple GPU (NVIDIA VSS, VideoRAG, Edit Mind).
- Only one embedding per video (Immich).
- Dependent on cloud LLMs.
- English-only.
- Non-commercial or commercial licenses (ImageBind in VideoRAG, screenpipe).

The useful parts to borrow are:
- Immich's model-benchmark data and its single-preview approach, as a baseline.
- VideoRAG's structure: ASR, captions, then a knowledge graph, with retrieval over both text and visual vectors.
- Edit Mind's per-scene index fields: transcription, objects, faces and OCR text.

### Cited Findings

**HKUDS/VideoRAG + Vimo**
- Stats: 3,390★, last push 2026-03-18.
- License: dual. The framework is MIT; the bundled third-party models carry their own licenses.
- Pipeline:
  - ASR: `faster-distil-whisper-large-v3`, which is English-oriented. The README says "only been tested in an English environment" and says to change `WhisperModel` in `asr.py` for other languages.
  - Captions: MiniCPM-V-2.6-int4.
  - Visual retrieval: ImageBind (CC BY-NC-SA).
  - LLM: OpenAI GPT-4o-mini by default, with Ollama support. Also uses neo4j, hnswlib and nano-vectordb.
  - Indexing claims "hundreds of hours on a single RTX 3090 (24GB)".
- Vimo is the desktop app: "macOS Apple Silicon first", beta.
- Sources: [VideoRAG README](https://github.com/HKUDS/VideoRAG); [VideoRAG-algorithm README](https://github.com/HKUDS/VideoRAG/tree/main/VideoRAG-algorithm); [LICENSE](https://github.com/HKUDS/VideoRAG/blob/main/LICENSE)

**Immich**
- Stats: AGPL-3.0, 115,878★, v3.3.1 on 2026-10-08.
- The smart-search job computes one CLIP embedding per asset from the asset's Preview file (`withFiles(eb, AssetFileType.Preview)`, then `encodeImage(asset.files[0].path)`). A video therefore gets a single preview-frame embedding, with no per-moment search. — [smart-info.service.ts](https://github.com/immich-app/immich/blob/main/server/src/services/smart-info.service.ts); [asset-job.repository.ts](https://github.com/immich-app/immich/blob/main/server/src/repositories/asset-job.repository.ts)
- Uses VectorChord in Postgres. Multilingual CLIP models are selectable (see the Q1 table). — [Immich searching.md](https://github.com/immich-app/immich/blob/main/docs/docs/features/searching.md)

**PhotoPrism**
- Stats: 40,280★; the GitHub license field reads NOASSERTION.
- Generates captions and labels with Ollama or the OpenAI API, in addition to its built-in TensorFlow models. Ollama runs at 720 px, and a GPU server is recommended.
- `photoprism vision run -m caption|labels` runs these manually. A 2026-03-05 service release added `OLLAMA_BASE_URL` and `OLLAMA_API_KEY`.
- FFmpeg 8 Vulkan transcoding is supported.
- Sources: [PhotoPrism AI docs](https://docs.photoprism.app/user-guide/ai/); [using Ollama](https://docs.photoprism.app/user-guide/ai/using-ollama); [releases](https://github.com/photoprism/photoprism/releases)

**NVIDIA Video Search & Summarization (VSS) blueprint**
- Stats: 1,919★, pushed 2026-10-10.
- Components: Cosmos VLM, Nemotron LLM, CA-RAG with embeddings, Elasticsearch, Kibana and Redis.
- Hardware: DGX, IGX-Thor, Jetson and x86 hosts with NVIDIA GPUs. No macOS or Apple Silicon support.
- License: Apache-2.0 code plus the NVIDIA Asset License for models and data.
- Too heavy for this setup; borrow only the ideas.
- Source: [GitHub](https://github.com/NVIDIA-AI-Blueprints/video-search-and-summarization)

**Edit Mind (IliasHad/edit-mind)**
- Stats: 1,810★, pushed 2026-06-30; the GitHub license field reads NOASSERTION.
- A "local-first video knowledge base" using YOLO, DeepFace, Whisper, OCR, ChromaDB, and Gemini or Ollama, run with Docker Compose.
- The author says Docker cannot use the Apple GPU. A paid desktop app exists for that.
- Source: [GitHub](https://github.com/IliasHad/edit-mind)

**QmiAI/Qmedia**
- Stats: MIT, 635★.
- A LlamaIndex-based multimodal RAG search over images, text and short videos, with a "pure local" model option.
- Source: [GitHub](https://github.com/QmiAI/Qmedia)

**video-db/Director**
- Stats: MIT, 1,550★, last push 2026-01.
- Not evaluated in depth.
- Source: [GitHub](https://github.com/video-db/Director)

**screenpipe**
- Stats: 21,891★.
- Records the screen and audio with OCR and transcription.
- Now under a "Screenpipe Commercial License" (Negentropy Labs).
- Source: [LICENSE](https://github.com/screenpipe/screenpipe)

**MCP servers**
- MCP servers found are YouTube transcript or semantic-search servers, Reka Vision MCP (a hosted API to upload, index and Q&A over videos), and `@clipy/mcp` (transcripts and key moments of the Clipy screen-recorder app).
- A GitHub search for "video search mcp" found no notable local personal-video MCP server.
- Sources: [Reka Vision MCP docs](https://docs.reka.ai/vision/mcp-server); [@clipy/mcp on socket.dev](https://socket.dev/npm/package/@clipy/mcp/overview/0.8.5); [LobeHub MCP list](https://lobehub.com/mcp?q=videos)

**Commercial "Twelve Labs alternative" articles**
- These are mostly vendor marketing (Mixpeek) and list Edit Mind and Qmedia as the self-hosted options. — [Mixpeek blog](https://blog.mixpeek.com/twelve-labs-alternative/); [startuphub list](https://www.startuphub.ai/startups/twelvelabs/open-source-alternatives)

**rclip**
- Stats: MIT, 1,015★, pushed 2026-09.
- A CLI for CLIP photo search; a minimal reference for a local CLIP index.
- Source: [GitHub](https://github.com/yurijmikhalevich/rclip)

### Inferences
- Immich's one-vector-per-video design is the right "phase 0" baseline because it is cheap. It is also exactly the limitation tidy-one should go beyond, with per-keyframe vectors plus timestamps, so an agent can answer "at 0:42 in IMG_1234.MOV".
- VideoRAG's lasting idea is to turn videos into text (ASR and captions), index that text with ordinary text RAG, and keep visual vectors as a second retrieval channel. Its code is not portable as is: it is English-only, needs CUDA, and uses non-commercial ImageBind.
- tidy-one will have to write its own small MCP tools (`search_videos`, `get_video_segments`). The building blocks are more mature than the end-to-end projects.

### Gaps
- LlamaIndex and LangChain video loaders were not examined in this pass. Qmedia shows LlamaIndex being used for video RAG.
- Whether PhotoPrism labels or captions videos, and from which frame(s), was not verified.
- Vimo's macOS build and its local-model configuration were not tested.

## Q3. Practical throughput on Apple Silicon M2 and catalog storage per video

### Takeaway
On an M2 (base chip, 100 GB/s memory bandwidth), expect roughly these speeds:
- **Korean ASR:** about 5–10× realtime, so a 1-hour meeting takes about 6–12 minutes.
- **SigLIP-class frame embeddings:** tens of frames per second.
- **VLM captions:** several seconds per frame.

Captions are the bottleneck, so caption selectively and overnight. Central storage is tiny: about 15–30 KB per minute of video with int8 vectors, or roughly 30–60 MB for a typical personal library of a few thousand clips.

### Cited Findings
- **Whisper-large-v3-turbo via CoreML on the Neural Engine:** 10 min of audio in 63 s on a MacBook Pro M2 (about 9.5× realtime), a 5.0× speedup over v3. iPad Pro M2: 71 s. — [WhisperNotes: introducing turbo](https://whispernotes.app/blog/introducing-whisper-large-v3-turbo) (vendor blog, updated 2026-08-24)
- **mlx-whisper (large-v3-turbo):** "12 minutes in 14 seconds" on an M2 Ultra, about 50× realtime. This is pre-2025 and possibly outdated. — [Simon Willison, 2024-10-01](https://simonwillison.net/2024/Oct/1/whisper-large-v3-turbo-model/)
- **mlx_whisper vs whisper.cpp:** 13.1 s vs 26.7 s on the same file with turbo models (unspecified Mac, 2026-01), so mlx_whisper was 2.0× faster. — [billmill notes](https://notes.billmill.org/dev_blog/2026/01/updated_my_mlx_whisper_vs._whisper.cpp_benchmark.html)
- **Qwen3-ASR-1.7B MLX 8-bit vs whisper.cpp turbo:** 9.6× vs 2.6× median realtime on an M5 MacBook Air. — [WhisperNotes FLEURS run](https://whispernotes.app/blog/qwen3-asr-vs-whisper)
- **Qwen3-ASR on an M5 Pro:** 0.6B 5-bit RTF 0.014 (about 70× realtime) with 1.03 GB RSS; 1.7B 5-bit RTF 0.027 with 1.92 GB. — [soniqo Qwen3-ASR vs Whisper](https://soniqo.audio/ko/benchmarks/qwen3-asr-vs-whisper)
- **VLM on an M4 Max (546 GB/s):** vllm-mlx reports Qwen3-VL-4B (4-bit) at 143 tok/s. A single 1024×1024 image query took 21.7 s uncached and 0.78 s with its content-based prefix cache. — [vllm-mlx paper, arXiv 2601.19139](https://arxiv.org/html/2601.19139v2)
- **Base M2 memory bandwidth** is 100 GB/s. — [Apple Newsroom, M2 announcement (2022)](https://www.apple.com/newsroom/2022/06/apple-unveils-m2-with-breakthrough-performance-and-capabilities/)
- **CLIP/SigLIP CPU costs** (Ryzen 7800X3D, f32, no acceleration): ViT-B-32-SigLIP2-256 3.3 ms, ViT-B-16-SigLIP2 5.8 ms, SO400M-16-SigLIP2-256 27.8 ms, SO400M-16-SigLIP2-384 56.6 ms per pass. Peak RSS is about 3–4 GB for the multilingual SigLIP2 models. — [Immich searching.md](https://github.com/immich-app/immich/blob/main/docs/docs/features/searching.md)
- **sqlite-vec** stores float, int8 and binary vectors in `vec0` tables. — [sqlite-vec README](https://github.com/asg017/sqlite-vec)
- **Embedding dimensions:** Qwen3-VL-Embedding-2B outputs 64–2048 dimensions (Matryoshka). — [HF model card](https://huggingface.co/Qwen/Qwen3-VL-Embedding-2B)

### Inferences
These are derived estimates, not measurements.

**ASR on M2 base**
- Scaling from the M5 and M2 Ultra figures, expect about 5–10× realtime for Whisper-turbo (mlx/CoreML) and for Qwen3-ASR-1.7B 8-bit.
- A 1-hour lecture therefore takes about 6–12 min, and a 30 s clip about 3–6 s, plus model load if the model is not kept warm.
- Run ASR as a queue with the model resident in memory. It uses about 2–3 GB of RAM, which fits easily in 24 GB.

**VLM captions on M2 base**
- Scaling decode by memory bandwidth (100/546 × 143 tok/s) gives about 25 tok/s for Qwen3-VL-4B 4-bit.
- An 80-token Korean+English caption plus image prefill takes about 4–8 s per frame. 3,000 keyframes therefore take about 3–7 h, an overnight job on AC power.
- Qwen3-VL-2B or SmolVLM2 would be about 2× faster, at lower caption quality.

**SigLIP2 image embeddings on the M2 GPU**
- Likely tens of frames/s for B/16 and single digits to low tens for SO400M. This has not been measured (see Gaps).

**Storage per minute of video (central catalog)**
- **Per-frame vectors:** sampling one keyframe per 3 s gives at most 20 frames/min. At SigLIP2-B 768-d int8 that is 768 B each, about 15 KB/min. At float32 (3,072 B each) it is about 60 KB/min. Binary 96 B/frame is possible for a coarse first pass.
- **Clip/segment vectors:** one Qwen3-VL-Embedding vector per 30 s segment at 1024-d int8 adds about 2 KB/min.
- **Transcript:** text chunks of 30–60 s add about 1–2 KB of Korean UTF-8 text per minute of speech (this assumes typical conversational speech rates), plus 1–2 text vectors.
- **Totals:** about 20–25 KB/min with int8, about 70–80 KB/min with float32. A library of 3,000 clips averaging 40 s (about 33 h) is about 40–160 MB, comfortable on the 4 GB VPS.

### Gaps
- No published M2 (base) numbers were found for mlx-whisper, Qwen3-ASR, SigLIP2 or Qwen3-VL captioning. All M2 throughput figures above are extrapolations.
- A 15-minute micro-benchmark on the user's M2 should replace these estimates. It would measure mlx-whisper turbo and Qwen3-ASR-1.7B-8bit on a 5-minute Korean meeting clip, SigLIP2-B and SO400M on 500 frames, and Qwen3-VL-2B/4B-4bit on 20 frames.
- The memory needed to run only the multilingual SigLIP2 text tower (at fp16 or int8) for query embedding on a 4 GB VPS was not measured. Immich's 3–4 GB figures are f32 for the whole process.

## Q4. What to store centrally vs keep on device

### Takeaway
Centralize only what search and agent answers need: metadata, derived text (summaries, tags, transcript snippets with timestamps) and vectors, all keyed back to a device and file or Photos UUID. Keep original files, full-resolution frames, and by default full transcripts and thumbnails on the device, served on demand through the device agent.

Model choice also creates a hard architectural constraint. Text queries must be embedded with the same model's text tower at search time. Either the VPS hosts a small text encoder, or searches fail while the Mac is asleep.

### Cited Findings
- Immich keeps CLIP embeddings server-side and performs search as "a standard nearest-neighbor search inside the CLIP space", with text embedded by the same model. — [Immich smart search docs (archive)](https://v1.107.1.archive.immich.app/docs/features/smart-search); [Immich searching.md](https://github.com/immich-app/immich/blob/main/docs/docs/features/searching.md)
- Peak memory for multilingual CLIP/SigLIP2 in Immich's f32 setup is about 2.8–4.2 GB per model process, which is at or above the whole VPS RAM budget. — [Immich searching.md](https://github.com/immich-app/immich/blob/main/docs/docs/features/searching.md)
- Qwen3-VL-Embedding supports flexible output dimensions and claims "strong performance even with quantized embeddings", which favours storing compact int8 vectors centrally. — [HF model card](https://huggingface.co/Qwen/Qwen3-VL-Embedding-2B)
- iPhone video containers carry precise GPS (`location.ISO6709`). — [ExifTool QuickTime tags](https://exiftool.org/TagNames/QuickTime.html)
- Meeting audio may contain other people's voices and names. WhisperX and pyannote diarization produce speaker labels, not identities. — [whisperX README](https://github.com/m-bain/whisperX)

### Inferences
**Store centrally (VPS):**
- file id, device id, path or Photos UUID, content hash
- duration, creation time, timezone, rounded GPS (for example a geohash at about 1 km, or a reverse-geocoded place name), device model, resolution, `has_audio`
- video kind: phone clip, screen recording or meeting
- a one-paragraph Korean summary plus tags (from captions and ASR)
- transcript chunks of at most a few hundred characters each, with start and end times
- OCR keywords for screen recordings
- per-keyframe SigLIP2 vectors (int8) with timestamps
- optional per-segment Qwen3-VL-Embedding vectors

**Keep on device:**
- originals, keyframe JPEGs and thumbnails
- full transcripts
- exact GPS
- face or speaker data

The device agent can expose a `get_thumbnail` / `get_transcript` endpoint that the MCP server proxies when the device is online.

**Thumbnails:** if previews must show while the Mac sleeps (for claude.ai mobile), upload a small (for example 256 px) WebP for photos and clips. Make it opt-in, because a thumbnail is the most privacy-revealing derived artifact.

**Query embedding:** pick a model whose text tower can run on the 4 GB VPS. Options:
- SigLIP2-B text tower alone, exported to ONNX at fp16 or int8, is plausible but needs measuring.
- Have each device also upload query-free "keyword" text (captions and tags) so plain text search (FTS5 plus multilingual text embeddings) still works when no visual encoder is available.

Qwen3-VL-Embedding-2B as a query encoder on a 4 GB CPU VPS is likely too slow and too large. That argues for SigLIP2 as the central visual index and Qwen3-VL-Embedding as a device-side or optional extra.

**Sensitive categories:** default meeting recordings and screen recordings (which may show passwords, chats or customer data) to "transcript and OCR stay local; only the summary and vectors go central". Mark them so production-like or customer data is not echoed to external agents.

### Gaps
- No source quantified the privacy leakage of CLIP vectors (whether images can be reconstructed from them) for this threat model. Treat vectors as sensitive but less sensitive than thumbnails.
- The actual RSS of a SigLIP2 text-only encoder on the Vultr 4 GB box was not measured.

## Q5. Recommended pipeline for tidy-one (Apple Silicon M2, mostly short personal clips, Korean speech)

### Takeaway
Build a tiered, resumable pipeline on the Mac agent:

| Tier | What it does | When it runs |
|---|---|---|
| T0 | Metadata | every video, cheap |
| T1 | Keyframes + SigLIP2 vectors | every video |
| T2 | Speech detection, then Korean ASR | only clips with speech |
| T3 | VLM captions + OCR | selective or overnight |

Optionally add Qwen3-VL-Embedding segment vectors. Everything is MLX- or Apple-framework-based on the Mac, uses Apache/MIT licenses, and sends only text and vectors to the VPS.

### Cited Findings
- **T0 metadata:**
  - osxphotos for the Photos library (UUIDs, labels, `--only-movies`). — [osxphotos](https://pypi.org/project/osxphotos/)
  - ExifTool QuickTime Keys for GPS and lens on loose files in ~/Movies and ~/Downloads. — [ExifTool](https://exiftool.org/TagNames/QuickTime.html)
- **T1 frame vectors:**
  - SigLIP2 (Apache-2.0); Korean recall 71% (B/16) to 77% (SO400M) in Immich's evaluation. — [Immich searching.md](https://github.com/immich-app/immich/blob/main/docs/docs/features/searching.md)
  - MLX ports exist. — [HF mlx-community/siglip2-so400m-patch16-384](https://huggingface.co/mlx-community/siglip2-so400m-patch16-384)
  - Use PySceneDetect only for long videos. — [PySceneDetect](https://github.com/Breakthrough/PySceneDetect)
- **T2 ASR:**
  - Qwen3-ASR-1.7B 8-bit via mlx-audio (FLEURS-ko CER 2.57 in the tech report; 3.54 independent). — [arXiv 2601.21337](https://arxiv.org/pdf/2601.21337); [mlx-audio](https://github.com/Blaizzy/mlx-audio); [WhisperNotes](https://whispernotes.app/blog/qwen3-asr-vs-whisper)
  - Avoid 4-bit for Korean. — [soniqo](https://soniqo.audio/benchmarks)
  - Fallback: Whisper-large-v3-turbo via mlx-whisper (2× faster than whisper.cpp). — [billmill](https://notes.billmill.org/dev_blog/2026/01/updated_my_mlx_whisper_vs._whisper.cpp_benchmark.html)
  - Speech or no-speech gate: SenseVoiceSmall `nospeech` / language ID. — [SenseVoice](https://github.com/FunAudioLLM/SenseVoice)
  - Meeting diarization: WhisperX + pyannote community-1 (CPU on Mac). — [whisperX](https://github.com/m-bain/whisperX)
- **T3 captions and OCR:**
  - Qwen3-VL-4B-Instruct-4bit (or 2B) via mlx-vlm. — [mlx-vlm](https://github.com/Blaizzy/mlx-vlm); [HF mlx-community/Qwen3-VL-4B-Instruct-4bit](https://huggingface.co/mlx-community/Qwen3-VL-4B-Instruct-4bit)
  - Apple Vision OCR (`ko-KR`) via ocrmac for screen recordings. — [Apple forum](https://developer.apple.com/forums/thread/121048); [ocrmac](https://github.com/straussmaximilian/ocrmac)
- **Optional segment embeddings:** Qwen3-VL-Embedding-2B (MLX 8-bit) at Matryoshka 512–1024 dimensions, video retrieval 53.9 on MMEB-V2. — [HF model card](https://huggingface.co/Qwen/Qwen3-VL-Embedding-2B); [mlx-community port](https://huggingface.co/mlx-community/Qwen3-VL-Embedding-2B-8bit)

### Inferences
**Concrete flow per video**

1. **Discover the file.** Use the Photos UUID through osxphotos, or the path for ~/Movies and ~/Downloads. Hash it and skip unchanged files.
2. **T0 metadata:**
   - Read duration, creation date and timezone, GPS, make and model, resolution, `has_audio`, and Photos labels.
   - Classify the kind:
     - screen recording: no camera make, and a "Screen Recording" or "화면 기록" filename or display-like resolution
     - meeting or lecture: long (> 10 min), mostly static frames
     - phone clip
3. **T1 keyframes:**
   - Phone clips: first and last frames, one every 2–3 s, deduplicated.
   - Screen recordings and lectures: frame-difference sampling, so only frames where content changed.
   - Embed each frame with SigLIP2 and store (video_id, t_sec, vector int8).
4. **T2 speech:**
   - If there is an audio track, run VAD or SenseVoice to check for speech.
   - If there is speech, run Qwen3-ASR-1.7B-8bit in chunks of at most 20 min.
   - Store timestamped 30–60 s chunks, plus a text embedding using the project's chosen multilingual text model, which is covered in the separate Korean-embedding note.
5. **T3 captions and OCR:**
   - For the 1–3 most representative frames (medoids of the SigLIP clusters), generate a short Korean+English caption and tags with Qwen3-VL. This runs overnight.
   - For screen recordings, run Vision OCR on the changed frames.
   - Have a small LLM (or the same VLM) write a 1–2 sentence Korean summary from the transcript and captions.
6. **Upload** metadata, summary, tags, transcript snippets, OCR keywords and vectors to the VPS. Thumbnails are opt-in.

**Search tools on the VPS** fuse three signals:
- FTS5 over summaries, captions, transcripts and OCR
- a multilingual text-vector search
- SigLIP2 text→frame vector search

Results return (video, timestamp, snippet) so agents can cite "IMG_1234.MOV at 0:42".

**Time and cost estimates (derived)**
- Assume a typical personal backlog of 3,000 clips at 40 s average (about 33 h of video) with about 10% containing meaningful speech, plus 20 h of meetings and lectures:
  - T0: minutes.
  - T1: about 30k–60k frames at tens of frames/s, roughly 0.5–2 h.
  - T2: about 23 h of audio at 5–10× realtime, roughly 2.5–5 h.
  - T3: 3k–9k captions at 4–8 s, roughly 3–20 h.
- The whole backlog fits into 1–3 nights on the M2 with no cloud cost.
- Incremental daily cost is seconds to minutes.
- Peak RAM if models run one at a time: SigLIP2-SO400M about 2–4 GB, Qwen3-ASR-1.7B-8bit about 2.7 GB, Qwen3-VL-4B-4bit about 3–4 GB. This is safe within 24 GB, even alongside the user's apps.

**Install footprint**
- `ffmpeg` (or PyAV) plus `exiftool` via Homebrew are needed for loose files and for the future Windows agent.
- Python packages: `mlx`, `mlx-vlm`, `mlx-audio` (or `mlx-whisper`), `open_clip` or MLX SigLIP, `osxphotos`, `ocrmac`, `scenedetect`.

**Windows later**
- None of the MLX pieces port to Windows.
- Plan ONNX or CUDA equivalents instead: SigLIP2 via open_clip or ONNX, Qwen3-ASR via transformers or sherpa-onnx-class runtimes, and Windows OCR.
- Keep the catalog schema model-tagged (`model_id`, `dim`, `quant`) so vectors from different devices or models are never mixed in one sqlite-vec table.

### Gaps
- The quality of Korean VLM captions from Qwen3-VL-2B/4B (natural Korean vs English-then-translate) was not benchmarked.
- No measured end-to-end run on this M2 exists yet. All hour estimates above should be validated with the micro-benchmark described in Q3 before committing to model sizes.
