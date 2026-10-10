"""Export nlpai-lab/KURE-v1 to ONNX fp32 (device passages) and int8 dynamic-quantised (hub queries).

Writes `$TIDY_MODEL_DIR/kure-v1/{fp32,int8}/`: `model.onnx` + its external weights file, `tokenizer.json`,
`model.json`; copy whole directories. Prints file sizes and checks agreement: sentence-transformers vs
ONNX fp32, and fp32 vs int8.
Idempotent: existing outputs are kept unless --force. Needs the `export` extra (torch, optimum):

    uv run --extra export python scripts/export_kure.py [--force] [--no-verify]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import numpy as np

from tidy_one.embed.text import TextEncoder, models_root

REPO = "nlpai-lab/KURE-v1"
MODEL_ID = "kure-v1"
MAX_LEN = 512
DOWNLOAD_PATTERNS = ["*.json", "model.safetensors", "1_Pooling/*"]

VERIFY_TEXTS = [
    "오늘 회의에서 다음 분기 마케팅 예산을 20% 늘리기로 결정했다.",
    "서울 강남역 근처에서 점심으로 냉면을 먹었다.",
    "The quarterly revenue report is due next Friday.",
    "주민등록등본 발급은 정부24에서 온라인으로 할 수 있습니다.",
    "How do I reset my router password?",
    "딥러닝 모델의 양자화는 추론 속도를 높이고 메모리를 줄인다.",
    "제주도 여행 일정: 성산일출봉, 우도, 한라산 등반",
    "Kubernetes 클러스터에 배포할 때 리소스 limit을 꼭 설정하세요.",
    "아이의 예방접종 기록을 확인하고 싶어요.",
    "계약서 3조 2항에 따라 위약금은 계약금의 10%로 한다.",
    " ".join(["개인 통합 인덱스는 파일, 메모, 사진과 클라우드 문서를 한곳에서 검색하게 해 준다."] * 40),
]


def human(n: int) -> str:
    return f"{n / 1e6:,.1f} MB"


def download() -> Path:
    from huggingface_hub import snapshot_download
    from huggingface_hub.errors import LocalEntryNotFoundError

    try:
        src = Path(snapshot_download(REPO, allow_patterns=DOWNLOAD_PATTERNS, local_files_only=True))
        if (src / "model.safetensors").exists() and (src / "tokenizer.json").exists():
            return src
    except LocalEntryNotFoundError:
        pass
    return Path(snapshot_download(REPO, allow_patterns=DOWNLOAD_PATTERNS))


def model_meta(src: Path) -> dict:
    """dim / pooling / normalize from the sentence-transformers config (modules.json + Pooling config)."""
    modules = json.loads((src / "modules.json").read_text())
    pooling, dim, st_normalize = None, None, False
    for m in modules:
        kind = m["type"].rsplit(".", 1)[-1]
        if kind == "Pooling":
            cfg = json.loads((src / m["path"] / "config.json").read_text())
            dim = cfg["word_embedding_dimension"]
            modes = [k for k, v in cfg.items() if k.startswith("pooling_mode_") and v]
            names = {"pooling_mode_cls_token": "cls", "pooling_mode_mean_tokens": "mean"}
            if len(modes) != 1 or modes[0] not in names:
                raise SystemExit(f"unsupported pooling config {modes}")
            pooling = names[modes[0]]
        elif kind == "Normalize":
            st_normalize = True
    if pooling is None:
        raise SystemExit("no Pooling module in modules.json")
    dim = dim or json.loads((src / "config.json").read_text())["hidden_size"]
    print(f"pooling={pooling} dim={dim} sentence-transformers Normalize module={st_normalize}")
    return {"model_id": MODEL_ID, "source": REPO, "dim": dim, "pooling": pooling, "max_len": MAX_LEN, "normalize": True}


def export_fp32(src: Path, dst: Path) -> None:
    from optimum.exporters.onnx import main_export

    tmp = dst.with_name(dst.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    main_export(
        str(src),
        output=tmp,
        task="feature-extraction",
        library_name="transformers",
        opset=18,
        device="cpu",
        do_validation=False,
    )
    move_model_files(tmp, dst)


def quantize_int8(fp32: Path, dst: Path, per_channel: bool, weight_type: str) -> None:
    from onnxruntime.quantization import QuantType, quantize_dynamic

    tmp = dst.with_name(dst.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    quantize_dynamic(
        fp32 / "model.onnx",
        tmp / "model.onnx",
        per_channel=per_channel,
        weight_type=QuantType.QInt8 if weight_type == "qint8" else QuantType.QUInt8,
        use_external_data_format=True,  # onnxruntime memory-maps external weights: ~0.9GB less RSS on the hub
        extra_options={"MatMulConstBOnly": True},
    )
    move_model_files(tmp, dst)


def move_model_files(tmp: Path, dst: Path) -> None:
    """Moves model.onnx and its external weight file(s) into dst, replacing older ones."""
    dst.mkdir(parents=True, exist_ok=True)
    for f in dst.glob("model.onnx*"):
        f.unlink()
    for f in tmp.glob("model.onnx*"):
        shutil.move(str(f), dst / f.name)
    shutil.rmtree(tmp)


def finish_dir(src: Path, dst: Path, meta: dict, variant: str) -> None:
    shutil.copyfile(src / "tokenizer.json", dst / "tokenizer.json")
    (dst / "model.json").write_text(json.dumps({**meta, "variant": variant}, indent=2) + "\n")


def print_sizes(root: Path) -> None:
    for variant in ("fp32", "int8"):
        d = root / variant
        files = sorted(d.iterdir()) if d.exists() else []
        total = sum(f.stat().st_size for f in files)
        print(f"{d}  total {human(total)}")
        for f in files:
            print(f"  {f.name:<18} {human(f.stat().st_size)}")


def cosines(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    a = a / np.linalg.norm(a, axis=1, keepdims=True)
    b = b / np.linalg.norm(b, axis=1, keepdims=True)
    return (a * b).sum(1)


def verify(src: Path, model_dir: str) -> bool:
    from sentence_transformers import SentenceTransformer

    st = SentenceTransformer(str(src), device="cpu")
    st.max_seq_length = MAX_LEN
    ref = st.encode(VERIFY_TEXTS, batch_size=4, normalize_embeddings=True, convert_to_numpy=True)
    fp32 = TextEncoder(MODEL_ID, "fp32", model_dir).encode_passages(VERIFY_TEXTS, batch_size=4)
    int8 = TextEncoder(MODEL_ID, "int8", model_dir).encode_passages(VERIFY_TEXTS, batch_size=4)
    c1, c2 = cosines(ref, fp32), cosines(fp32, int8)
    print(f"cosine(sentence-transformers, onnx fp32): min {c1.min():.6f} mean {c1.mean():.6f}")
    print(f"cosine(onnx fp32, onnx int8):            min {c2.min():.6f} mean {c2.mean():.6f}")
    for text, x, y in zip(VERIFY_TEXTS, c1, c2):
        print(f"  {x:.6f} {y:.6f}  {text[:40]}")
    ok = bool(c1.min() > 0.999 and c2.min() > 0.98)
    print("verify:", "OK" if ok else "FAILED (expected st/fp32 > 0.999, fp32/int8 > 0.98)")
    return ok


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model-dir", help="default $TIDY_MODEL_DIR or ~/.cache/tidy-one/models")
    ap.add_argument("--force", action="store_true", help="re-export even if outputs exist")
    ap.add_argument("--no-verify", action="store_true", help="skip the sentence-transformers / int8 agreement check")
    ap.add_argument("--per-channel", action=argparse.BooleanOptionalAction, default=True)
    # u8 weights: on x86 hubs without VNNI, u8s8 MatMulInteger can saturate; quality on ARM is the same
    ap.add_argument("--weight-type", choices=["qint8", "quint8"], default="quint8")
    args = ap.parse_args(argv)

    root = models_root(args.model_dir) / MODEL_ID
    fp32, int8 = root / "fp32", root / "int8"
    src = download()
    meta = model_meta(src)

    if args.force or not (fp32 / "model.onnx").exists():
        print(f"exporting fp32 ONNX -> {fp32}")
        export_fp32(src, fp32)
    else:
        print(f"fp32 exists, skipping export: {fp32}")
    finish_dir(src, fp32, meta, "fp32")

    quant = {"per_channel": args.per_channel, "weight_type": args.weight_type}
    if args.force or not (int8 / "model.onnx").exists():
        print(f"quantising int8 ({quant}) -> {int8}")
        quantize_int8(fp32, int8, args.per_channel, args.weight_type)
    else:
        print(f"int8 exists, skipping quantisation: {int8}")
        old = int8 / "model.json"
        if old.exists():
            quant = {k: v for k, v in json.loads(old.read_text()).items() if k in quant}
    finish_dir(src, int8, {**meta, **quant}, "int8")

    print_sizes(root)
    if args.no_verify:
        return 0
    return 0 if verify(src, str(models_root(args.model_dir))) else 1


if __name__ == "__main__":
    sys.exit(main())
