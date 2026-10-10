from __future__ import annotations

import sys
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from tidy_one.embed import FakeEncoder, ModelFilesMissing, TextEncoder, backends, coreml_text, torch_text
from tidy_one.embed.coreml_text import CoreMLTextEncoder
from tidy_one.embed.tandem import TandemEncoder
from tidy_one.embed.text import BaseEncoder, length_batches, pad_batch
from tidy_one.embed.torch_text import TorchTextEncoder

TEXTS = [
    "오늘 회의에서 다음 분기 마케팅 예산을 늘리기로 했다.",
    "The quarterly revenue report is due next Friday.",
    "제주도 여행 일정: 성산일출봉, 우도, 한라산",
]
PASSAGES = [
    "오늘 회의에서 다음 분기 마케팅 예산을 20% 늘리기로 결정했다. 담당자는 김 팀장이다.",
    "제주도 여행 일정은 성산일출봉, 우도, 한라산 등반으로 3박 4일 동안 이어진다.",
    "서버 비용이 지난달보다 크게 늘어서 인스턴스 크기를 줄이는 방안을 검토하고 있다.",
    "연말 정산 서류로 의료비 영수증, 기부금 영수증, 월세 납부 내역을 준비해야 한다.",
    "고양이 사료를 바꾼 뒤로 털 빠짐이 줄었고 체중도 안정적으로 유지되고 있다.",
    "The quarterly revenue report is due next Friday; finance needs the draft by Wednesday.",
    "Kubernetes 클러스터의 노드 하나가 메모리 부족으로 재시작되면서 배포가 실패했다.",
    "할머니 생신 잔치는 다음 달 둘째 주 토요일 저녁 여섯 시에 한정식 집에서 열린다.",
]
QUERIES = [
    "마케팅 예산 증액 결정",
    "제주 여행 계획",
    "클라우드 서버 비용 절감",
    "연말정산 준비물",
    "반려묘 사료 교체 효과",
    "when is the revenue report due?",
    "쿠버네티스 배포 실패 원인",
    "할머니 생신 모임 장소",
]


def _encoder(variant: str) -> TextEncoder:
    enc = TextEncoder("kure-v1", variant)  # type: ignore[arg-type]
    if not enc.available:
        pytest.skip(f"kure-v1 {variant} not exported; run scripts/export_kure.py")
    return enc


@pytest.fixture(scope="module", params=["fp32", "int8"])
def encoder(request: pytest.FixtureRequest) -> TextEncoder:
    return _encoder(request.param)


@pytest.fixture(scope="module")
def mps_encoder() -> TorchTextEncoder:
    enc = TorchTextEncoder("kure-v1", device="mps", dtype="fp16")
    if not enc.available:
        pytest.skip("torch-mps backend unavailable (needs Apple GPU, the export extra and the KURE-v1 checkpoint)")
    return enc


@pytest.fixture(scope="module")
def coreml_encoder() -> CoreMLTextEncoder:
    enc = CoreMLTextEncoder("kure-v1")
    if not enc.available:
        pytest.skip("coreml backend unavailable (needs macOS, onnxruntime's CoreML provider and the fp32 export)")
    if not all(enc.compiled(b) for b in enc.buckets):
        pytest.skip("Core ML programs not built yet (first build takes minutes): run the coreml backend once")
    return enc


class _Tok:
    def encode_batch(self, texts: list[str]) -> list[SimpleNamespace]:
        return [SimpleNamespace(ids=[0] + [5] * (len(t) - 1)) for t in texts]


class _LengthEncoder(BaseEncoder):
    """Embeds a text as [true length, padded width]; records every batch it is given."""

    def __init__(self, max_tokens: int = 0):
        super().__init__("toy", {"dim": 2, "normalize": False})
        self.max_tokens = max_tokens
        self.batches: list[tuple[int, int]] = []

    @property
    def available(self) -> bool:
        return True

    def _load(self) -> None:
        self._tokenizer = _Tok()

    def _embed(self, ids: np.ndarray, mask: np.ndarray) -> np.ndarray:
        self.batches.append(ids.shape)
        return np.stack([mask.sum(1), np.full(len(ids), ids.shape[1])], axis=1).astype(np.float32)


class _SlowLengthEncoder(_LengthEncoder):
    """GPU stand-in: token-budget batches that take a little while, recording the lengths it embedded."""

    def __init__(self, delay: float = 0.02):
        super().__init__()
        self.delay = delay
        self.seen: list[int] = []

    def _embed(self, ids: np.ndarray, mask: np.ndarray) -> np.ndarray:
        time.sleep(self.delay)
        self.seen += mask.sum(1).tolist()
        return super()._embed(ids, mask)


class _ToyHelper(_LengthEncoder):
    """Neural Engine stand-in: one text per call in a loaded bucket; loads can be held back or fail."""

    def __init__(self, fail_after: int | None = None, gate: threading.Event | None = None, delay: float = 0.01):
        super().__init__()
        self._ensure()
        self.buckets = (8, 512)
        self.ready: set[int] = set()
        self.load_order: list[int] = []
        self.seen: list[int] = []
        self.used: list[tuple[int, int]] = []
        self.fail_after = fail_after
        self.gate = gate
        self.delay = delay

    def ready_bucket(self, length: int) -> int | None:
        return next((b for b in self.buckets if b >= length and b in self.ready), None)

    def preload(self, buckets=None) -> None:
        if self.gate is not None:
            self.gate.wait()
        for b in buckets or self.buckets:
            self.load_order.append(b)
            self.ready.add(b)

    def embed_one(self, ids: list[int], bucket: int) -> np.ndarray:
        assert len(ids) <= bucket
        if self.fail_after is not None and len(self.seen) >= self.fail_after:
            raise RuntimeError("ANE went away")
        time.sleep(self.delay)
        self.seen.append(len(ids))
        self.used.append((len(ids), bucket))
        return np.array([len(ids), bucket], dtype=np.float32)


def test_fake_encoder_shape_norm_determinism() -> None:
    enc = FakeEncoder()
    a = enc.encode_passages(TEXTS)
    assert a.shape == (3, 1024) and a.dtype == np.float32
    np.testing.assert_allclose(np.linalg.norm(a, axis=1), 1.0, atol=1e-5)
    np.testing.assert_array_equal(a[1], enc.encode_query(TEXTS[1]))
    assert enc.encode_passages([]).shape == (0, 1024)


def test_length_batches_sorted_and_budgeted() -> None:
    lengths = [50, 5, 400, 7, 6, 300, 8]
    assert length_batches(lengths, 3) == [[1, 4, 3], [6, 0, 5], [2]]
    # a token budget lets short texts share a bigger batch, long ones keep `batch_size`
    assert length_batches(lengths, 2, max_tokens=40) == [[1, 4, 3, 6], [0, 5], [2]]
    assert sorted(i for b in length_batches(lengths, 4, 1000) for i in b) == list(range(len(lengths)))
    assert length_batches([], 4) == []


def test_pad_batch_dynamic_width() -> None:
    ids, mask = pad_batch([[0, 9, 2], [0, 2]], pad_id=1)
    assert ids.dtype == mask.dtype == np.int64
    np.testing.assert_array_equal(ids, [[0, 9, 2], [0, 2, 1]])
    np.testing.assert_array_equal(mask, [[1, 1, 1], [1, 1, 0]])


def test_batches_padded_only_to_their_longest_text_and_returned_in_input_order() -> None:
    enc = _LengthEncoder()
    texts = ["x" * n for n in (90, 3, 40, 5, 4, 70)]
    out = enc.encode_passages(texts, batch_size=2)
    np.testing.assert_array_equal(out[:, 0], [90, 3, 40, 5, 4, 70])
    assert enc.batches == [(2, 4), (2, 40), (2, 90)]
    assert out[1, 1] == 4 and out[0, 1] == 90
    enc = _LengthEncoder(max_tokens=20)
    enc.encode_passages(texts, batch_size=2)
    assert enc.batches[0] == (3, 5)
    assert enc.encode_query("abc")[0] == 3


def test_missing_model_files_error(tmp_path) -> None:
    enc = TextEncoder("kure-v1", "int8", model_dir=str(tmp_path))
    assert not enc.available and enc.dim == 1024 and enc.model_id == "kure-v1"
    assert enc.encode_passages([]).shape == (0, 1024)
    with pytest.raises(ModelFilesMissing, match="export_kure.py"):
        enc.encode_query("안녕하세요")


def test_model_dir_from_env(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TIDY_MODEL_DIR", str(tmp_path))
    (tmp_path / "kure-v1" / "fp32").mkdir(parents=True)
    (tmp_path / "kure-v1" / "fp32" / "model.json").write_text('{"dim": 8, "pooling": "mean", "max_len": 64}')
    enc = TextEncoder()
    assert enc.path == tmp_path / "kure-v1" / "fp32"
    assert (enc.dim, enc.pooling, enc.max_len) == (8, "mean", 64)


def test_backend_selection(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv(backends.ENV, raising=False)
    assert backends.backend_name() == "auto"
    monkeypatch.setenv(backends.ENV, " ONNX ")
    enc = backends.passage_encoder(model_dir=str(tmp_path))
    assert isinstance(enc, TextEncoder) and enc.variant == "fp32" and enc.model_id == "kure-v1"
    monkeypatch.setenv(backends.ENV, "torch-mps")
    enc = backends.passage_encoder(model_dir=str(tmp_path))
    assert isinstance(enc, TorchTextEncoder) and (enc.device, enc.dtype) == ("mps", "fp16")
    with pytest.raises(ValueError, match="unknown embedding backend"):
        backends.passage_encoder(backend="cuda")
    monkeypatch.setattr(sys, "platform", "linux")
    assert isinstance(backends.passage_encoder(backend="auto"), TextEncoder)


def test_auto_falls_back_to_onnx_without_checkpoint(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(torch_text, "checkpoint_dir", lambda *a, **k: None)
    monkeypatch.setattr(backends.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(sys, "platform", "darwin")
    assert isinstance(backends.passage_encoder(model_dir=str(tmp_path), backend="auto"), TextEncoder)
    enc = TorchTextEncoder(model_dir=str(tmp_path), device="cpu")
    assert not enc.available and enc.dim == 1024
    assert enc.encode_passages([]).shape == (0, 1024)
    with pytest.raises(ModelFilesMissing, match="export"):
        enc.encode_query("안녕하세요")


def test_shape_and_norm(encoder: TextEncoder) -> None:
    v = encoder.encode_passages(TEXTS, batch_size=2)
    assert v.shape == (3, encoder.dim) == (3, 1024) and v.dtype == np.float32
    np.testing.assert_allclose(np.linalg.norm(v, axis=1), 1.0, atol=1e-5)
    q = encoder.encode_query(TEXTS[0])
    assert q.shape == (1024,) and q.dtype == np.float32
    assert abs(float(np.linalg.norm(q)) - 1.0) < 1e-5


def test_deterministic_and_batch_invariant(encoder: TextEncoder) -> None:
    a = encoder.encode_passages(TEXTS, batch_size=16)
    b = encoder.encode_passages(TEXTS, batch_size=1)
    np.testing.assert_allclose(a, encoder.encode_passages(TEXTS, batch_size=16), atol=1e-6)
    assert float((a * b).sum(1).min()) > 0.999  # padding must not change the vectors
    assert float(a[2] @ encoder.encode_query(TEXTS[2])) > 0.999


def test_long_text_truncated(encoder: TextEncoder) -> None:
    long = "개인 통합 인덱스는 모든 파일을 한곳에서 검색하게 해 준다. " * 200
    v = encoder.encode_passages([long, "짧은 문장"])
    assert v.shape == (2, 1024) and np.isfinite(v).all()


def test_semantic_ranking(encoder: TextEncoder) -> None:
    passages = encoder.encode_passages(TEXTS)
    q = encoder.encode_query("제주 여행 계획")
    assert int(np.argmax(passages @ q)) == 2
    q = encoder.encode_query("when is the revenue report due?")
    assert int(np.argmax(passages @ q)) == 1


def test_fp32_int8_compatible() -> None:
    fp32, int8 = _encoder("fp32"), _encoder("int8")
    a, b = fp32.encode_passages(TEXTS), int8.encode_passages(TEXTS)
    assert float((a * b).sum(1).min()) > 0.97


def test_mps_matches_fp32_onnx_and_int8_queries(mps_encoder: TorchTextEncoder) -> None:
    fp32, int8 = _encoder("fp32"), _encoder("int8")
    dev = mps_encoder.encode_passages(PASSAGES, batch_size=16)
    ref = fp32.encode_passages(PASSAGES)
    assert dev.shape == (8, 1024) and dev.dtype == np.float32
    np.testing.assert_allclose(np.linalg.norm(dev, axis=1), 1.0, atol=1e-5)
    assert float((dev * ref).sum(1).min()) > 0.999
    one = mps_encoder.encode_passages(PASSAGES, batch_size=1)
    assert float((dev * one).sum(1).min()) > 0.999  # padding must not change the vectors
    q = np.stack([int8.encode_query(t) for t in QUERIES])
    assert ((q @ dev.T).argmax(1) == (q @ ref.T).argmax(1)).all()
    assert ((q @ dev.T).argmax(1) == np.arange(len(QUERIES))).all()


LENGTHS = [90, 3, 40, 5, 4, 70, 12, 7, 300, 6, 9, 60, 2, 33, 120, 8]


def test_tandem_splits_queue_by_length_and_keeps_order() -> None:
    gpu, ane = _SlowLengthEncoder(), _ToyHelper()
    enc = TandemEncoder(gpu, ane, assist_after=0)  # type: ignore[arg-type]
    enc.preload()
    out = enc.encode_passages(["x" * n for n in LENGTHS], batch_size=2)
    np.testing.assert_array_equal(out[:, 0], LENGTHS)
    assert sorted(gpu.seen + ane.seen) == sorted(LENGTHS) and ane.seen and gpu.seen
    assert max(ane.seen) <= min(gpu.seen)  # Neural Engine from the short end, GPU from the long end
    assert enc.helped == len(ane.seen) and enc.dim == gpu.dim and enc.model_id == "toy"


def test_tandem_helper_joins_only_for_a_backlog() -> None:
    gpu, ane = _SlowLengthEncoder(), _ToyHelper()
    enc = TandemEncoder(gpu, ane, assist_after=20)  # type: ignore[arg-type]
    texts = ["x" * n for n in LENGTHS]
    enc.encode_passages(texts, batch_size=2)
    assert ane.seen == [] and not ane.ready and enc.encoded == len(texts)
    out = enc.encode_passages(texts, batch_size=2)  # 32 > 20: the helper is invited
    np.testing.assert_array_equal(out[:, 0], LENGTHS)
    assert ane.ready
    assert TandemEncoder(gpu, None).encode_passages(texts).shape == (len(texts), 2)  # type: ignore[arg-type]
    assert TandemEncoder(gpu, None).encode_passages([]).shape == (0, 2)  # type: ignore[arg-type]


def test_tandem_never_waits_for_a_helper_load() -> None:
    gate = threading.Event()
    gpu, ane = _SlowLengthEncoder(delay=0), _ToyHelper(gate=gate)
    enc = TandemEncoder(gpu, ane, assist_after=0)  # type: ignore[arg-type]
    t0 = time.monotonic()
    out = enc.encode_passages(["x" * n for n in LENGTHS])
    assert time.monotonic() - t0 < 5 and ane.seen == [] and sorted(gpu.seen) == sorted(LENGTHS)
    np.testing.assert_array_equal(out[:, 0], LENGTHS)
    gate.set()
    enc.preload()
    assert ane.ready == {8, 512} and ane.load_order == [512, 8]  # the longest bucket holds every text


def test_tandem_helper_uses_a_longer_bucket_while_the_short_one_loads() -> None:
    gpu, ane = _SlowLengthEncoder(), _ToyHelper()
    ane.ready = {512}
    enc = TandemEncoder(gpu, ane, assist_after=0)  # type: ignore[arg-type]
    enc._loader = threading.Thread(target=lambda: None)  # the 8-token program never arrives during this call
    enc._loader.start()
    out = enc.encode_passages(["x" * n for n in LENGTHS], batch_size=2)
    np.testing.assert_array_equal(out[:, 0], LENGTHS)
    assert ane.used and all(b == 512 for _, b in ane.used)


def test_tandem_falls_back_to_gpu_when_helper_fails() -> None:
    gpu, ane = _SlowLengthEncoder(), _ToyHelper(fail_after=2)
    enc = TandemEncoder(gpu, ane, assist_after=0)  # type: ignore[arg-type]
    enc.preload()
    out = enc.encode_passages(["x" * n for n in LENGTHS], batch_size=2)
    np.testing.assert_array_equal(out[:, 0], LENGTHS)
    assert len(ane.seen) == 2 and sorted(gpu.seen + ane.seen) == sorted(LENGTHS)
    gpu.seen.clear()
    enc.encode_passages(["x" * n for n in LENGTHS])
    assert sorted(gpu.seen) == sorted(LENGTHS) and len(ane.seen) == 2


class _FakeSession:
    def __init__(self, path: str, opts=None, providers=None, dim: int = 2):
        self.path, self.providers, self.dim, self.calls = path, providers, dim, []

    def get_inputs(self):
        return [SimpleNamespace(name="input_ids"), SimpleNamespace(name="attention_mask")]

    def get_outputs(self):
        return [SimpleNamespace(name="last_hidden_state")]

    def run(self, names, feeds):
        ids, mask = feeds["input_ids"], feeds["attention_mask"]
        self.calls.append(ids.shape)
        hidden = np.zeros((*ids.shape, self.dim), dtype=np.float16)
        hidden[:, 0, 0], hidden[:, 0, 1] = mask.sum(1), ids.shape[1]
        return [hidden]


def _coreml_dirs(tmp_path) -> None:
    fp32 = tmp_path / "kure-v1" / "fp32"
    fp32.mkdir(parents=True)
    (fp32 / "model.json").write_text('{"dim": 2, "normalize": false}')
    fp16 = tmp_path / "kure-v1" / "fp16"
    fp16.mkdir(parents=True)
    for f in ("model.onnx", "model.onnx_data", "tokenizer.json"):
        (fp16 / f).write_text(f)


def test_coreml_pads_each_text_to_its_bucket(tmp_path, monkeypatch) -> None:
    _coreml_dirs(tmp_path)
    monkeypatch.setattr(coreml_text, "coreml_provider_available", lambda: True)
    monkeypatch.setattr(coreml_text, "load_tokenizer", lambda path, max_len: (_Tok(), 1))
    sessions: list[_FakeSession] = []
    import onnxruntime

    def session(*a, **k) -> _FakeSession:
        sessions.append(_FakeSession(*a, **k))
        return sessions[-1]

    monkeypatch.setattr(onnxruntime, "InferenceSession", session)
    enc = CoreMLTextEncoder(model_dir=str(tmp_path), buckets=(8, 64, 9999))
    assert enc.buckets == (8, 64, 512) and enc.batch_size_override == 1 and enc.available
    assert [enc.bucket(n) for n in (1, 8, 9, 64, 65, 600)] == [8, 8, 64, 64, 512, 512]
    root = tmp_path / "kure-v1" / "fp16" / "coreml"
    (root / "oldstamp").mkdir(parents=True)
    assert not enc.compiled(8)
    out = enc.encode_passages(["x" * n for n in (5, 40, 3, 70)], batch_size=16)
    np.testing.assert_array_equal(out, [[5, 8], [40, 64], [3, 8], [70, 512]])
    assert sorted(s.calls[0] for s in sessions) == [(1, 8), (1, 64), (1, 512)]  # warm-up runs
    assert sum(len(s.calls) for s in sessions) == 3 + 4
    assert not (root / "oldstamp").exists() and enc.compiled(8) and enc.compiled(64) and enc.compiled(600)
    opts = dict(sessions[0].providers[0][1])
    assert opts["MLComputeUnits"] == "CPUAndNeuralEngine" and opts["RequireStaticInputShapes"] == "1"
    assert opts["ModelCacheDirectory"].endswith("/s8") and sessions[0].providers[-1] == "CPUExecutionProvider"
    np.testing.assert_array_equal(enc.encode_query("abc"), [3, 8])

    enc2 = CoreMLTextEncoder(model_dir=str(tmp_path), buckets=(8,))
    stale = root / coreml_text.model_stamp(enc2.path, enc2.units) / "s512"
    (stale / "ready").unlink()
    (stale / "partial.bin").write_text("interrupted compile")
    enc2.preload()
    assert not (stale / "partial.bin").exists() and (stale / "ready").exists()


def test_coreml_unavailable_without_provider_or_model(tmp_path, monkeypatch) -> None:
    enc = CoreMLTextEncoder(model_dir=str(tmp_path))
    assert not enc.available and enc.dim == 1024 and enc.encode_passages([]).shape == (0, 1024)
    with pytest.raises((ModelFilesMissing, RuntimeError)):
        enc.encode_query("안녕하세요")
    with pytest.raises(ModelFilesMissing, match="export_kure.py"):
        coreml_text.prepare_fp16(model_dir=str(tmp_path))
    _coreml_dirs(tmp_path)
    monkeypatch.setattr(sys, "platform", "linux")
    assert not CoreMLTextEncoder(model_dir=str(tmp_path)).available


def test_model_stamp_follows_the_model_files(tmp_path) -> None:
    _coreml_dirs(tmp_path)
    path = tmp_path / "kure-v1" / "fp16"
    a = coreml_text.model_stamp(path, "CPUAndNeuralEngine")
    assert a == coreml_text.model_stamp(path, "CPUAndNeuralEngine") != coreml_text.model_stamp(path, "CPUAndGPU")
    (path / "model.onnx_data").write_text("new weights")
    assert coreml_text.model_stamp(path, "CPUAndNeuralEngine") != a


def _fake_availability(monkeypatch, torch_ok: bool, coreml_ok: bool, memory: int = 24 * 1024**3) -> None:
    monkeypatch.setattr(TorchTextEncoder, "available", property(lambda self: torch_ok))
    monkeypatch.setattr(CoreMLTextEncoder, "available", property(lambda self: coreml_ok))
    monkeypatch.setattr(backends, "physical_memory", lambda: memory)
    monkeypatch.setattr(backends.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(sys, "platform", "darwin")


def test_auto_backend_on_apple_silicon(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv(backends.ENV, raising=False)
    d = str(tmp_path)
    _fake_availability(monkeypatch, torch_ok=True, coreml_ok=True)
    enc = backends.passage_encoder(model_dir=d)
    assert isinstance(enc, TandemEncoder) and isinstance(enc.helper, CoreMLTextEncoder)
    assert isinstance(enc.primary, TorchTextEncoder) and enc.primary.device == "mps" and enc.available
    _fake_availability(monkeypatch, torch_ok=True, coreml_ok=True, memory=8 * 1024**3)
    assert isinstance(backends.passage_encoder(model_dir=d), TorchTextEncoder)
    _fake_availability(monkeypatch, torch_ok=False, coreml_ok=True)
    assert isinstance(backends.passage_encoder(model_dir=d), CoreMLTextEncoder)
    _fake_availability(monkeypatch, torch_ok=False, coreml_ok=False)
    assert isinstance(backends.passage_encoder(model_dir=d), TextEncoder)
    _fake_availability(monkeypatch, torch_ok=True, coreml_ok=False)
    enc = backends.passage_encoder(model_dir=d, backend="tandem")
    assert isinstance(enc, TandemEncoder) and enc.helper is None
    assert isinstance(backends.passage_encoder(model_dir=d, backend="coreml"), CoreMLTextEncoder)
    monkeypatch.setattr(backends.platform, "machine", lambda: "x86_64")
    assert isinstance(backends.passage_encoder(model_dir=d), TextEncoder)


def test_default_encoder_honours_backend_env(tmp_path, monkeypatch) -> None:
    from tidy_one.agent.run import default_encoder

    cfg = SimpleNamespace(model_dir=str(tmp_path))
    monkeypatch.delenv("TIDY_FAKE_ENCODER", raising=False)
    monkeypatch.setenv(backends.ENV, "onnx")
    enc = default_encoder(cfg)  # type: ignore[arg-type]
    assert isinstance(enc, TextEncoder) and enc.variant == "fp32" and enc.path == tmp_path / "kure-v1" / "fp32"
    monkeypatch.setenv("TIDY_FAKE_ENCODER", "1")
    assert isinstance(default_encoder(cfg), FakeEncoder)  # type: ignore[arg-type]


def test_coreml_matches_fp32_onnx_and_int8_queries(coreml_encoder: CoreMLTextEncoder) -> None:
    fp32, int8 = _encoder("fp32"), _encoder("int8")
    dev = coreml_encoder.encode_passages(PASSAGES)
    ref = fp32.encode_passages(PASSAGES)
    assert dev.shape == (8, 1024) and dev.dtype == np.float32
    np.testing.assert_allclose(np.linalg.norm(dev, axis=1), 1.0, atol=1e-5)
    assert float((dev * ref).sum(1).min()) > 0.999
    q = np.stack([int8.encode_query(t) for t in QUERIES])
    assert ((q @ dev.T).argmax(1) == (q @ ref.T).argmax(1)).all()
    assert ((q @ dev.T).argmax(1) == np.arange(len(QUERIES))).all()


def test_tandem_matches_fp32_onnx(mps_encoder: TorchTextEncoder, coreml_encoder: CoreMLTextEncoder) -> None:
    enc = TandemEncoder(mps_encoder, coreml_encoder, assist_after=0)
    enc.preload()
    texts = PASSAGES * 4
    dev = enc.encode_passages(texts)
    ref = _encoder("fp32").encode_passages(PASSAGES)
    assert float((dev * np.tile(ref, (4, 1))).sum(1).min()) > 0.999


def test_prepare_fp16_once_per_fp32_export(tmp_path, monkeypatch) -> None:
    onnx = pytest.importorskip("onnx")
    from onnx import TensorProto, helper

    fp32 = tmp_path / "kure-v1" / "fp32"
    fp32.mkdir(parents=True)

    dims: list[str | int] = ["batch_size", "sequence_length"]

    def export(scale: float) -> None:
        table = helper.make_tensor("table", TensorProto.FLOAT, [10, 4], [scale * i for i in range(40)])
        graph = helper.make_graph(
            [helper.make_node("Gather", ["table", "input_ids"], ["last_hidden_state"])], "toy",
            [helper.make_tensor_value_info("input_ids", TensorProto.INT64, dims)],
            [helper.make_tensor_value_info("last_hidden_state", TensorProto.FLOAT, dims + [4])],
            [table],
        )
        onnx.save(helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)]), str(fp32 / "model.onnx"))

    export(1.0)
    (fp32 / "tokenizer.json").write_text("{}")
    out = coreml_text.prepare_fp16(model_dir=str(tmp_path))
    assert out == tmp_path / "kure-v1" / "fp16" and (out / "tokenizer.json").read_text() == "{}"
    m = onnx.load(str(out / "model.onnx"))
    assert m.graph.initializer[0].data_type == TensorProto.FLOAT16
    assert m.graph.input[0].type.tensor_type.elem_type == TensorProto.INT64
    assert m.graph.output[0].type.tensor_type.elem_type == TensorProto.FLOAT  # fp32 at the edges
    assert coreml_text.model_meta("kure-v1", out)["input_dims"] == ["batch_size", "sequence_length"]
    first = (out / "model.onnx").stat().st_mtime_ns
    assert coreml_text.prepare_fp16(model_dir=str(tmp_path)) == out and (out / "model.onnx").stat().st_mtime_ns == first
    time.sleep(0.01)
    export(2.0)  # a new fp32 export makes a new fp16 copy
    coreml_text.prepare_fp16(model_dir=str(tmp_path))
    assert (out / "model.onnx").stat().st_mtime_ns != first and not list(out.parent.glob("fp16.tmp-*"))


def test_count_tokens_reports_untruncated_lengths() -> None:
    """The chunker asks the encoder how long a text is before truncation, to split chunks that do not fit."""
    enc = _LengthEncoder()
    assert enc.count_tokens(["abcd", "x"]) == [4, 1]
    overflow = SimpleNamespace(encode_batch=lambda texts: [
        SimpleNamespace(ids=[1] * 512, overflowing=[SimpleNamespace(ids=[1] * 90)]) for _ in texts
    ])
    enc._tokenizer = overflow
    assert enc.count_tokens(["long"]) == [602]
    tandem = TandemEncoder(_LengthEncoder(), None)  # type: ignore[arg-type]
    assert tandem.count_tokens(["abc"]) == [3] and tandem.max_len == 512


def test_real_tokenizer_counts_past_the_limit() -> None:
    enc = TextEncoder("kure-v1", "int8")
    if not enc.available:
        pytest.skip("int8 KURE-v1 export not found")
    n_short, n_long = enc.count_tokens(["짧은 글", "근로계약서 " * 400])
    assert 2 < n_short < 10 and n_long > enc.max_len
