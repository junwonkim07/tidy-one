"""KURE-v1 passages on the Apple Neural Engine through onnxruntime's CoreML execution provider; no torch.

The Neural Engine runs fp16 programs with static shapes only, so this backend keeps an fp16 copy of the
ONNX model (`$TIDY_MODEL_DIR/<model_id>/fp16/`, made once from the fp32 export) and runs each text alone,
padded up to the nearest length bucket. Core ML compiles one program per bucket on first use (about three
minutes and ~10GB of transient memory, once) and caches it on disk (~4GB per bucket); later loads take about
a minute. Vectors match the fp32 ONNX passages (mean cosine > 0.9999), so they share the hub's int8 query
space under the same `model_id`.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import threading
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from tidy_one.embed.text import BaseEncoder, ModelFilesMissing, load_tokenizer, model_meta, pool, variant_dir

BUCKETS = (256, 512)
COMPUTE_UNITS = "CPUAndNeuralEngine"
MODEL_FILES = ("model.onnx", "tokenizer.json")
INPUT_DIMS = ("batch_size", "sequence_length")  # symbolic input dims of the optimum export
READY = "ready"


def coreml_provider_available() -> bool:
    if sys.platform != "darwin":
        return False
    import onnxruntime as ort

    return "CoreMLExecutionProvider" in ort.get_available_providers()


def onnx_installed() -> bool:
    import importlib.util

    return importlib.util.find_spec("onnx") is not None


def files_stamp(path: Path, *extra: str) -> str:
    """Changes whenever the ONNX files under `path` (or `extra`) do."""
    parts = list(extra)
    for f in sorted(path.glob("model.onnx*")):
        st = f.stat()
        parts.append(f"{f.name}:{st.st_size}:{st.st_mtime_ns}")
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:12]


def prepare_fp16(model_id: str = "kure-v1", model_dir: str | None = None) -> Path:
    """`<model_id>/fp16/` from the fp32 export (needs the `onnx` package, ~15s, 1.1GB); redone only when the
    fp32 export changes."""
    dst = variant_dir(model_id, "fp16", model_dir)
    src = variant_dir(model_id, "fp32", model_dir)
    have_src = all((src / f).exists() for f in MODEL_FILES)
    if all((dst / f).exists() for f in MODEL_FILES):
        made_from = model_meta(model_id, dst).get("source_stamp")
        if not have_src or made_from == files_stamp(src):
            return dst
    if not have_src:
        raise ModelFilesMissing(
            f"{model_id} fp32 model files not found in {src}; run `uv run --extra export python scripts/export_kure.py`"
        )
    if not onnx_installed():
        raise ModelFilesMissing("the fp16 copy for Core ML is made with the `onnx` package: `uv sync --extra export`")
    import onnx
    from onnxruntime.transformers.float16 import convert_float_to_float16

    tmp = dst.with_name(f"{dst.name}.tmp-{os.getpid()}")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    try:
        model = onnx.load(str(src / "model.onnx"))
        model = convert_float_to_float16(model, keep_io_types=True, disable_shape_infer=True)
        dims = [d.dim_param for d in model.graph.input[0].type.tensor_type.shape.dim]
        onnx.save(model, str(tmp / "model.onnx"), save_as_external_data=True, all_tensors_to_one_file=True,
                  location="model.onnx_data")
        del model
        shutil.copy2(src / "tokenizer.json", tmp / "tokenizer.json")
        meta = model_meta(model_id, src) | {
            "variant": "fp16", "derived_from": "fp32", "source_stamp": files_stamp(src), "input_dims": dims,
        }
        (tmp / "model.json").write_text(json.dumps(meta, indent=2) + "\n")
        shutil.rmtree(dst, ignore_errors=True)
        tmp.rename(dst)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return dst


def model_stamp(path: Path, units: str) -> str:
    """Changes whenever the fp16 files, onnxruntime or the compute units do; onnxruntime keys its Core ML
    cache by model path only, so a stale cache must never be reused for a new model."""
    import onnxruntime as ort

    return files_stamp(path, ort.__version__, units)


class CoreMLTextEncoder(BaseEncoder):
    """Passage/query encoder on Core ML; `units` are Core ML compute units (default: CPU and Neural Engine).

    One text per call, padded to the smallest bucket that holds it; bucket programs load on first use and
    `preload()` builds them ahead of time. Thread-safe: sessions are shared, loads are serialised.
    """

    def __init__(
        self,
        model_id: str = "kure-v1",
        model_dir: str | None = None,
        buckets: Sequence[int] = BUCKETS,
        units: str = COMPUTE_UNITS,
        threads: int | None = None,
    ):
        self.model_dir = model_dir
        self.path = variant_dir(model_id, "fp16", model_dir)
        super().__init__(model_id, model_meta(model_id, variant_dir(model_id, "fp32", model_dir)))
        self.buckets = tuple(sorted({min(int(b), self.max_len) for b in buckets} | {self.max_len}))
        self.units = units
        self.threads = threads
        self.batch_size_override = 1
        self._sessions: dict[int, Any] = {}
        self._session_lock = threading.Lock()
        self._output = "last_hidden_state"
        self._inputs: list[str] = []
        self._cache: Path | None = None

    @property
    def available(self) -> bool:
        if not coreml_provider_available():
            return False
        if all((self.path / f).exists() for f in MODEL_FILES):
            return True
        src = variant_dir(self.model_id, "fp32", self.model_dir)
        return all((src / f).exists() for f in MODEL_FILES) and onnx_installed()

    def bucket(self, length: int) -> int:
        return next((b for b in self.buckets if b >= length), self.buckets[-1])

    def ready_bucket(self, length: int) -> int | None:
        """Smallest already-loaded bucket that holds `length` tokens, if any."""
        return next((b for b in self.buckets if b >= length and b in self._sessions), None)

    def compiled(self, bucket: int) -> bool:
        """The program for `bucket` is already built for the current fp16 files (loads without compiling)."""
        if not all((self.path / f).exists() for f in MODEL_FILES):
            return False
        return (self.path / "coreml" / model_stamp(self.path, self.units) / f"s{self.bucket(bucket)}" / READY).exists()

    def _load(self) -> None:
        if not coreml_provider_available():
            raise RuntimeError("onnxruntime's CoreML execution provider is not available on this machine")
        path = prepare_fp16(self.model_id, self.model_dir)
        stamp = model_stamp(path, self.units)
        root = path / "coreml"
        if root.exists():
            for old in root.iterdir():
                if old.name != stamp:
                    shutil.rmtree(old, ignore_errors=True)
        self._cache = root / stamp
        tok, self._pad_id = load_tokenizer(path / "tokenizer.json", self.max_len)
        self._tokenizer = tok

    def _session(self, bucket: int) -> Any:
        sess = self._sessions.get(bucket)
        if sess is not None:
            return sess
        self._ensure()
        with self._session_lock:
            if bucket not in self._sessions:
                self._sessions[bucket] = self._open(bucket)
        return self._sessions[bucket]

    def _open(self, bucket: int) -> Any:
        import onnxruntime as ort

        assert self._cache is not None
        cache = self._cache / f"s{bucket}"
        if cache.exists() and not (cache / READY).exists():
            shutil.rmtree(cache)  # an interrupted compile
        cache.mkdir(parents=True, exist_ok=True)
        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        batch_dim, seq_dim = model_meta(self.model_id, self.path).get("input_dims", INPUT_DIMS)
        opts.add_free_dimension_override_by_name(batch_dim, 1)
        opts.add_free_dimension_override_by_name(seq_dim, bucket)
        opts.log_severity_level = 3
        if self.threads:
            opts.intra_op_num_threads = self.threads
        provider = ("CoreMLExecutionProvider", {
            "ModelFormat": "MLProgram", "MLComputeUnits": self.units, "RequireStaticInputShapes": "1",
            "ModelCacheDirectory": str(cache),
        })
        sess = ort.InferenceSession(str(self.path / "model.onnx"), opts, providers=[provider, "CPUExecutionProvider"])
        self._inputs = [i.name for i in sess.get_inputs()]
        outputs = [o.name for o in sess.get_outputs()]
        self._output = next((n for n in ("last_hidden_state", "token_embeddings") if n in outputs), outputs[0])
        ids = np.full((1, bucket), self._pad_id, dtype=np.int64)
        ids[0, :2] = (0, 2)
        mask = np.zeros_like(ids)
        mask[0, :2] = 1
        sess.run([self._output], self._feeds(ids, mask))
        (cache / READY).touch()
        return sess

    def preload(self, buckets: Sequence[int] | None = None) -> None:
        """Build (first time) or load the programs for `buckets` (default: all)."""
        for b in buckets or self.buckets:
            self._session(self.bucket(b))

    def _feeds(self, ids: np.ndarray, mask: np.ndarray) -> dict[str, np.ndarray]:
        feeds = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self._inputs:
            feeds["token_type_ids"] = np.zeros_like(ids)
        return {k: v for k, v in feeds.items() if k in self._inputs}

    def _run(self, ids: Sequence[int], bucket: int) -> np.ndarray:
        """Pooled (not normalised) vector of one tokenised text, padded to `bucket`."""
        sess = self._session(bucket)
        x = np.full((1, bucket), self._pad_id, dtype=np.int64)
        x[0, : len(ids)] = ids
        m = np.zeros((1, bucket), dtype=np.int64)
        m[0, : len(ids)] = 1
        hidden = sess.run([self._output], self._feeds(x, m))[0]
        return pool(hidden.astype(np.float32, copy=False), m, self.pooling)[0]

    def embed_one(self, ids: Sequence[int], bucket: int) -> np.ndarray:
        """Unit vector of one tokenised text run in `bucket` (any loaded bucket that holds it)."""
        return self._finish(self._run(ids, bucket)[None])[0]

    def _embed(self, ids: np.ndarray, mask: np.ndarray) -> np.ndarray:
        rows = []
        for row, m in zip(ids, mask):
            n = int(m.sum())
            rows.append(self._run(row[:n], self.bucket(n)))
        return np.stack(rows)
