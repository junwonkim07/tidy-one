"""Korean/English text embeddings (KURE-v1) on onnxruntime + tokenizers; no torch at runtime.

Model files come from `scripts/export_kure.py`:
`$TIDY_MODEL_DIR/<model_id>/<variant>/{model.onnx, tokenizer.json, model.json}`.

`BaseEncoder` holds what every backend shares: NFC + tokenisation, length-sorted batches with
dynamic padding (each batch is padded only to its own longest text), pooling and L2 normalisation.
"""

from __future__ import annotations

import json
import os
import threading
import unicodedata
from pathlib import Path
from typing import Any, Literal, Sequence

import numpy as np

Variant = Literal["fp32", "int8"]

DEFAULT_MODEL_DIR = "~/.cache/tidy-one/models"
DEFAULTS: dict[str, dict[str, Any]] = {
    "kure-v1": {"dim": 1024, "pooling": "cls", "max_len": 512, "normalize": True, "source": "nlpai-lab/KURE-v1"},
}


class ModelFilesMissing(FileNotFoundError):
    pass


def models_root(model_dir: str | None = None) -> Path:
    return Path(model_dir or os.environ.get("TIDY_MODEL_DIR") or DEFAULT_MODEL_DIR).expanduser()


def variant_dir(model_id: str = "kure-v1", variant: str = "fp32", model_dir: str | None = None) -> Path:
    return models_root(model_dir) / model_id / variant


def model_meta(model_id: str, path: Path | None = None) -> dict[str, Any]:
    """Built-in defaults for `model_id`, overridden by `<path>/model.json` when present."""
    meta = dict(DEFAULTS.get(model_id, {}))
    if path is not None and (path / "model.json").exists():
        meta.update(json.loads((path / "model.json").read_text()))
    return meta


def length_batches(lengths: Sequence[int], batch_size: int, max_tokens: int = 0) -> list[list[int]]:
    """Indices grouped shortest-first so padding stays small. A batch holds up to `batch_size` texts,
    or more short ones while its padded size (count x longest) stays within `max_tokens`."""
    batches: list[list[int]] = []
    cur: list[int] = []
    for i in sorted(range(len(lengths)), key=lengths.__getitem__):
        cap = max(batch_size, max_tokens // max(lengths[i], 1)) if max_tokens else batch_size
        if cur and len(cur) + 1 > cap:
            batches.append(cur)
            cur = []
        cur.append(i)
    if cur:
        batches.append(cur)
    return batches


def pad_batch(seqs: Sequence[Sequence[int]], pad_id: int) -> tuple[np.ndarray, np.ndarray]:
    """(input_ids, attention_mask) int64, right-padded to the longest sequence of this batch."""
    width = max(len(s) for s in seqs)
    ids = np.full((len(seqs), width), pad_id, dtype=np.int64)
    mask = np.zeros((len(seqs), width), dtype=np.int64)
    for i, s in enumerate(seqs):
        ids[i, : len(s)] = s
        mask[i, : len(s)] = 1
    return ids, mask


def load_tokenizer(path: Path, max_len: int) -> tuple[Any, int]:
    from tokenizers import Tokenizer

    tok = Tokenizer.from_file(str(path))
    tok.no_padding()
    tok.enable_truncation(max_length=max_len)
    pad = tok.token_to_id("<pad>")
    return tok, 0 if pad is None else pad


class BaseEncoder:
    """Shared passage/query logic; subclasses load a model in `_load()` and pool one padded batch in `_embed()`."""

    model_id: str
    dim: int
    pooling: str
    max_len: int
    normalize: bool
    max_tokens: int = 0  # padded-token budget per batch (0: `batch_size` texts per batch)
    batch_size_override: int | None = None  # backends that must not batch (int8 ONNX) set 1

    def __init__(self, model_id: str, meta: dict[str, Any]):
        self.model_id = model_id
        self.dim = int(meta.get("dim", 1024))
        self.pooling = meta.get("pooling", "cls")
        self.max_len = int(meta.get("max_len", 512))
        self.normalize = bool(meta.get("normalize", True))
        self._tokenizer: Any = None
        self._pad_id = 0
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        raise NotImplementedError

    def _load(self) -> None:
        raise NotImplementedError

    def _embed(self, ids: np.ndarray, mask: np.ndarray) -> np.ndarray:
        raise NotImplementedError

    def _ensure(self) -> None:
        if self._tokenizer is not None:
            return
        with self._lock:
            if self._tokenizer is None:
                self._load()

    def _done(self) -> None:
        """Hook after each `encode_passages` call (e.g. release cached device memory)."""

    def _finish(self, pooled: np.ndarray) -> np.ndarray:
        out = np.asarray(pooled, dtype=np.float32)
        if self.normalize:
            out /= np.maximum(np.linalg.norm(out, axis=1, keepdims=True), 1e-12)
        return out

    def _ids(self, texts: list[str]) -> list[list[int]]:
        return [e.ids for e in self._tokenizer.encode_batch([unicodedata.normalize("NFC", t) for t in texts])]

    def count_tokens(self, texts: list[str]) -> list[int]:
        """Tokens per text, special tokens included, before truncation: above `max_len`, the end of the
        text would be cut off when embedded. The chunker uses it to re-split chunks that do not fit."""
        self._ensure()
        encs = self._tokenizer.encode_batch([unicodedata.normalize("NFC", t) for t in texts])
        return [len(e.ids) + sum(len(o.ids) for o in getattr(e, "overflowing", None) or ()) for e in encs]

    def encode_passages(self, texts: list[str], batch_size: int = 16) -> np.ndarray:
        """(n, dim) float32, unit norm. Texts are NFC-normalised (macOS names are often NFD), sorted by
        token length and run in batches padded only to their own longest text."""
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        self._ensure()
        ids = self._ids(texts)
        out = np.empty((len(texts), self.dim), dtype=np.float32)
        bs = self.batch_size_override or batch_size
        max_tokens = 0 if self.batch_size_override else self.max_tokens
        try:
            for idx in length_batches([len(x) for x in ids], bs, max_tokens):
                out[idx] = self._finish(self._embed(*pad_batch([ids[i] for i in idx], self._pad_id)))
        finally:
            self._done()
        return out

    def encode_query(self, text: str) -> np.ndarray:
        """(dim,) float32, unit norm. KURE/bge-m3 use no instruction prefix."""
        self._ensure()
        return self._finish(self._embed(*pad_batch(self._ids([text]), self._pad_id)))[0]


def pool(hidden: np.ndarray, mask: np.ndarray, pooling: str) -> np.ndarray:
    if pooling == "cls":
        return hidden[:, 0]
    if pooling == "mean":
        m = mask[..., None].astype(hidden.dtype)
        return (hidden * m).sum(1) / np.maximum(m.sum(1), 1e-9)
    raise ValueError(f"unsupported pooling {pooling!r}")


class TextEncoder(BaseEncoder):
    """ONNX passage/query encoder returning L2-normalised float32 vectors. The session is created on first use.

    `threads` sets onnxruntime intra-op threads (default: onnxruntime's choice); `providers` defaults to CPU.
    int8 runs one text at a time: dynamic quantisation scales activations per batch, so batch partners
    would change the vectors.
    """

    def __init__(
        self,
        model_id: str = "kure-v1",
        variant: Variant = "fp32",
        model_dir: str | None = None,
        threads: int | None = None,
        providers: list[Any] | None = None,
    ):
        self.variant = variant
        self.path = variant_dir(model_id, variant, model_dir)
        super().__init__(model_id, model_meta(model_id, self.path))
        self.threads = threads
        self.providers = providers or ["CPUExecutionProvider"]
        self.batch_size_override = 1 if variant == "int8" else None
        self._session: Any = None
        self._input_names: list[str] = []
        self._output = ""

    @property
    def available(self) -> bool:
        return (self.path / "model.onnx").exists() and (self.path / "tokenizer.json").exists()

    def _load(self) -> None:
        if not self.available:
            raise ModelFilesMissing(
                f"{self.model_id} ({self.variant}) model files not found in {self.path}; "
                "run `uv run --extra export python scripts/export_kure.py` (or set TIDY_MODEL_DIR)"
            )
        import onnxruntime as ort

        tok, pad_id = load_tokenizer(self.path / "tokenizer.json", self.max_len)
        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        if self.threads:
            opts.intra_op_num_threads = self.threads
            opts.inter_op_num_threads = 1
        session = ort.InferenceSession(str(self.path / "model.onnx"), opts, providers=self.providers)
        self._input_names = [i.name for i in session.get_inputs()]
        outputs = [o.name for o in session.get_outputs()]
        self._output = next((n for n in ("last_hidden_state", "token_embeddings") if n in outputs), outputs[0])
        self._session = session
        self._pad_id = pad_id
        self._tokenizer = tok

    def _embed(self, ids: np.ndarray, mask: np.ndarray) -> np.ndarray:
        feeds = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self._input_names:
            feeds["token_type_ids"] = np.zeros_like(ids)
        hidden = self._session.run([self._output], {k: v for k, v in feeds.items() if k in self._input_names})[0]
        return pool(hidden, mask, self.pooling)
