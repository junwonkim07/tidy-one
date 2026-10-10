"""Choose the device-side passage encoder:
`$TIDY_EMBED_BACKEND` = auto | onnx | coreml | torch-mps | torch-cpu | tandem.

- `onnx`: fp32 ONNX on the CPU; works everywhere (Linux, Windows, Intel Macs, no extras).
- `coreml`: fp16 on the Apple Neural Engine via onnxruntime's CoreML provider; no torch.
- `torch-mps`: fp16 on the Apple GPU (needs the `export` extra and the Hugging Face checkpoint).
- `tandem`: the GPU and the Neural Engine together on one queue (see `tidy_one.embed.tandem`).
- `auto`: on Apple Silicon `tandem` (with 16GB+ of memory) or `torch-mps`, then `coreml` when torch or
  the checkpoint is missing; everywhere else `onnx`.

Every backend produces vectors in the same `kure-v1` space as the hub's int8 ONNX query encoder.
"""

from __future__ import annotations

import os
import platform
import sys
from typing import Any

from tidy_one.embed.text import TextEncoder

BACKENDS = ("auto", "onnx", "coreml", "torch-mps", "torch-cpu", "tandem")
ENV = "TIDY_EMBED_BACKEND"
TANDEM_MIN_MEMORY = 16 * 1024**3  # a first Core ML compile briefly needs ~10GB


def backend_name(backend: str | None = None) -> str:
    name = (backend or os.environ.get(ENV) or "auto").strip().lower()
    if name not in BACKENDS:
        raise ValueError(f"unknown embedding backend {name!r}; choose one of {', '.join(BACKENDS)}")
    return name


def apple_silicon() -> bool:
    return sys.platform == "darwin" and platform.machine() == "arm64"


def physical_memory() -> int:
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        return 0


def _make(name: str, model_id: str, model_dir: str | None) -> Any:
    if name == "onnx":
        return TextEncoder(model_id, "fp32", model_dir=model_dir)
    if name == "coreml":
        from tidy_one.embed.coreml_text import CoreMLTextEncoder

        return CoreMLTextEncoder(model_id, model_dir=model_dir)
    from tidy_one.embed.torch_text import TorchTextEncoder

    if name == "torch-cpu":
        return TorchTextEncoder(model_id, device="cpu", dtype="fp32", model_dir=model_dir)
    gpu = TorchTextEncoder(model_id, device="mps", dtype="fp16", model_dir=model_dir)
    if name == "torch-mps":
        return gpu
    from tidy_one.embed.coreml_text import CoreMLTextEncoder
    from tidy_one.embed.tandem import TandemEncoder

    ane = CoreMLTextEncoder(model_id, model_dir=model_dir)
    return TandemEncoder(gpu, ane if ane.available else None)


def auto_backend(model_id: str = "kure-v1", model_dir: str | None = None) -> str:
    """Fastest backend usable here; the GPU and Neural Engine paths only on Apple Silicon."""
    if not apple_silicon():
        return "onnx"
    if _make("torch-mps", model_id, model_dir).available:
        if physical_memory() >= TANDEM_MIN_MEMORY and _make("coreml", model_id, model_dir).available:
            return "tandem"
        return "torch-mps"
    if _make("coreml", model_id, model_dir).available:
        return "coreml"
    return "onnx"


def passage_encoder(model_id: str = "kure-v1", model_dir: str | None = None, backend: str | None = None) -> Any:
    """Encoder for device-side passages, chosen by `backend` or `$TIDY_EMBED_BACKEND` (default auto)."""
    name = backend_name(backend)
    if name == "auto":
        name = auto_backend(model_id, model_dir)
    return _make(name, model_id, model_dir)
