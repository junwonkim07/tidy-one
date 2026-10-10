"""Text embeddings: KURE-v1 on onnxruntime (`TextEncoder`), the fastest local passage backend
(`passage_encoder`: Apple GPU + Neural Engine on Apple Silicon, ONNX CPU elsewhere) and a hash-based
stand-in for tests (`FakeEncoder`)."""

from tidy_one.embed.backends import passage_encoder
from tidy_one.embed.fake import FakeEncoder
from tidy_one.embed.text import ModelFilesMissing, TextEncoder

__all__ = ["FakeEncoder", "ModelFilesMissing", "TextEncoder", "passage_encoder"]
