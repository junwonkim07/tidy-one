"""KURE-v1 passages on PyTorch: the Apple GPU (MPS, fp16) on Macs. Device-side only; the hub stays on ONNX.

Weights are the original Hugging Face checkpoint (`model.safetensors`), read from
`$TIDY_MODEL_DIR/<model_id>/hf/` or the Hugging Face cache that `scripts/export_kure.py` fills; nothing is
downloaded here. Vectors match the fp32 ONNX passages (mean cosine > 0.9999), so they share the hub's
int8 query space under the same `model_id`.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any, Literal

import numpy as np

from tidy_one.embed.text import BaseEncoder, ModelFilesMissing, load_tokenizer, model_meta, variant_dir

Device = Literal["mps", "cpu"]
DType = Literal["fp16", "fp32"]

MAX_BATCH_TOKENS = 16 * 512  # padded tokens per GPU batch: 16 full chunks, or many more short ones
WEIGHT_FILES = ("config.json", "model.safetensors", "tokenizer.json")


def torch_installed() -> bool:
    return all(importlib.util.find_spec(m) is not None for m in ("torch", "transformers"))


def mps_available() -> bool:
    if not torch_installed():
        return False
    import torch

    return bool(torch.backends.mps.is_available())


def checkpoint_dir(model_id: str = "kure-v1", model_dir: str | None = None) -> Path | None:
    """Folder holding the Hugging Face checkpoint, or None when it is not on this machine."""
    local = variant_dir(model_id, "hf", model_dir)
    if all((local / f).exists() for f in WEIGHT_FILES):
        return local
    repo = model_meta(model_id).get("source")
    if not repo:
        return None
    try:
        from huggingface_hub import snapshot_download

        snap = Path(snapshot_download(repo, allow_patterns=list(WEIGHT_FILES), local_files_only=True))
    except Exception:
        return None
    return snap if all((snap / f).exists() for f in WEIGHT_FILES) else None


class TorchTextEncoder(BaseEncoder):
    """Passage/query encoder on PyTorch; `device="mps", dtype="fp16"` is the fast path on Apple Silicon.

    Batches are length-sorted and dynamically padded under a token budget, so short chunks run many
    per batch. The model loads on first use; cached GPU memory is released after every call.
    """

    def __init__(
        self,
        model_id: str = "kure-v1",
        device: Device = "mps",
        dtype: DType = "fp16",
        model_dir: str | None = None,
        threads: int | None = None,
        max_tokens: int = MAX_BATCH_TOKENS,
    ):
        self.device = device
        self.dtype = dtype
        self.model_dir = model_dir
        self.threads = threads
        super().__init__(model_id, model_meta(model_id, variant_dir(model_id, "fp32", model_dir)))
        self.max_tokens = max_tokens
        self._model: Any = None
        self._torch: Any = None
        self._checkpoint: Path | None | bool = False

    @property
    def path(self) -> Path | None:
        if self._checkpoint is False:
            self._checkpoint = checkpoint_dir(self.model_id, self.model_dir)
        return self._checkpoint  # type: ignore[return-value]

    @property
    def available(self) -> bool:
        if not torch_installed() or (self.device == "mps" and not mps_available()):
            return False
        return self.path is not None

    def _load(self) -> None:
        if not torch_installed():
            raise ModelFilesMissing("torch backend needs PyTorch: `uv sync --extra export` (or use the onnx backend)")
        if self.path is None:
            raise ModelFilesMissing(
                f"{self.model_id} checkpoint not found in {variant_dir(self.model_id, 'hf', self.model_dir)} "
                "or the Hugging Face cache; run `uv run --extra export python scripts/export_kure.py`"
            )
        import torch
        from transformers import AutoModel
        from transformers.utils import logging as hf_logging

        if self.device == "mps" and not torch.backends.mps.is_available():
            raise RuntimeError("MPS (Apple GPU) is not available on this machine")
        if self.threads:
            torch.set_num_threads(self.threads)
        hf_logging.set_verbosity_error()
        dtype = torch.float16 if self.dtype == "fp16" else torch.float32
        model = AutoModel.from_pretrained(
            str(self.path), torch_dtype=dtype, attn_implementation="sdpa", add_pooling_layer=False
        )
        self._model = model.to(self.device).eval()
        self._torch = torch
        self._tokenizer, self._pad_id = load_tokenizer(self.path / "tokenizer.json", self.max_len)

    def _embed(self, ids: np.ndarray, mask: np.ndarray) -> np.ndarray:
        torch = self._torch
        with torch.inference_mode():
            m = torch.from_numpy(mask).to(self.device)
            hidden = self._model(input_ids=torch.from_numpy(ids).to(self.device), attention_mask=m).last_hidden_state
            if self.pooling == "cls":
                out = hidden[:, 0]
            elif self.pooling == "mean":
                w = m.unsqueeze(-1).to(hidden.dtype)
                out = (hidden * w).sum(1) / w.sum(1).clamp(min=1)
            else:
                raise ValueError(f"unsupported pooling {self.pooling!r}")
            return out.float().cpu().numpy()

    def _done(self) -> None:
        if self.device == "mps" and self._torch is not None and os.environ.get("TIDY_KEEP_GPU_CACHE") != "1":
            self._torch.mps.empty_cache()
