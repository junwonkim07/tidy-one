import os
import random
import stat
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pytest

from tidy_one.catalog import Catalog, make_excerpt, quantize, rrf_fuse
from tidy_one.catalog.catalog import day_number
from tidy_one.embed.fake import FakeEncoder
from tidy_one.model import SENS_SECRET, Chunk, Document, Record, finalize_chunks

ENC = FakeEncoder()


@pytest.fixture
def cat(tmp_path):
    c = Catalog(str(tmp_path / "catalog.sqlite"))
    yield c
    c.close()


def make_record(
    doc_id: str, texts: list[str], *, vectors: bool = True, source_id: str = "file:mba", modality: str = "text", **kw
) -> Record:
    doc = Document(
        doc_id=doc_id,
        source_id=source_id,
        native_id=doc_id,
        modality=modality,
        title=kw.pop("title", doc_id),
        uri=f"file:///{doc_id}",
        **kw,
    )
    chunks = finalize_chunks(doc_id, [Chunk(i, t) for i, t in enumerate(texts)])
    vecs = {}
    if vectors and chunks:
        vecs = {"kure-v1": dict(zip([c.chunk_id for c in chunks], ENC.encode_passages(texts)))}
    return Record(doc, chunks, vecs)


def ids(hits: list[dict]) -> list[str]:
    return [h["doc_id"] for h in hits]


def search(cat: Catalog, q: str, vec: bool = True, **kw) -> list[dict]:
    return cat.search(q, ENC.encode_query(q) if vec else None, None, **kw)


def test_apply_is_idempotent(cat):
    rec = make_record("a", ["주간 회의록을 정리했다", "다음 분기 예산"], updated_at="2024-05-01T00:00:00Z")
    cat.apply(rec)
    first = (cat.stats(), search(cat, "회의록"))
    cat.apply(rec)
    second = (cat.stats(), search(cat, "회의록"))
    for key in ("documents", "chunks", "vec_text"):
        assert first[0][key] == second[0][key]
    assert first[0]["chunks"] == 2 and first[0]["vec_text"] == 2
    assert [(h["doc_id"], h["excerpt"], h["signals"]) for h in first[1]] == [
        (h["doc_id"], h["excerpt"], h["signals"]) for h in second[1]
    ]


def test_chunks_replaced_atomically(cat):
    cat.apply(make_record("a", ["사과 농장 방문기", "배 수확 일정", "포도 가격"]))
    cat.apply(make_record("a", ["귤 상자 주문"]))
    s = cat.stats()
    assert s["chunks"] == 1 and s["vec_text"] == 1
    assert search(cat, "포도", vec=False) == []
    assert search(cat, "농장", vec=False) == []
    assert ids(search(cat, "귤", vec=False)) == ["a"]
    assert cat.get_document("a")["n_chunks"] == 1


def test_failed_apply_rolls_back(cat):
    cat.apply(make_record("a", ["원래 내용"]))
    bad = make_record("a", ["하나", "둘"])
    bad.chunks[1].chunk_id = bad.chunks[0].chunk_id
    with pytest.raises(ValueError):
        cat.apply(bad)
    assert ids(search(cat, "원래 내용", vec=False)) == ["a"]


def test_tombstone_and_revive(cat):
    cat.apply(make_record("a", ["삭제될 회의록"]))
    cat.apply(make_record("b", ["남을 회의록"]))
    cat.delete("a", "2024-06-01T00:00:00Z")
    assert ids(search(cat, "회의록")) == ["b"]
    assert cat.get_document("a") is None
    assert cat.fetch("a")["error"] == "not found"
    s = cat.stats()
    assert s["documents"] == 1 and s["deleted"] == 1 and s["chunks"] == 1 and s["vec_text"] == 1
    cat.delete("missing", "2024-06-01T00:00:00Z")
    cat.apply(make_record("a", ["다시 살아난 회의록"]))
    assert cat.get_document("a") is not None
    assert set(ids(search(cat, "회의록"))) == {"a", "b"}
    assert cat.stats()["deleted"] == 0


def test_secret_documents_never_returned(cat):
    cat.apply(make_record("s", ["api key 회의록"], sensitivity=SENS_SECRET))
    cat.apply(make_record("ok", ["평범한 회의록"]))
    assert ids(search(cat, "회의록")) == ["ok"]
    assert cat.get_document("s") is None
    assert cat.stats()["chunks"] == 1


def test_korean_fts_matches_inflected_query(cat):
    cat.apply(make_record("m", ["3월 회의록 초안입니다. 참석자는 다섯 명."], vectors=False))
    cat.apply(make_record("x", ["점심 메뉴 추천"], vectors=False))
    hits = search(cat, "회의록을", vec=False)
    assert ids(hits) == ["m"]
    # the particle changes nothing: 회의록을 gets the same signals as 회의록 (morphemes, and the stem as a substring)
    assert hits[0]["signals"] == ["fts", "trigram"]
    assert [h["signals"] for h in search(cat, "회의록", vec=False)] == [hits[0]["signals"]]
    assert "회의록" in hits[0]["excerpt"]


def test_fts_prefix_matches_compound_noun(cat):
    cat.apply(make_record("m", ["주간회의록 공유"], vectors=False))
    assert "m" in ids(search(cat, "회의", vec=False))


def test_trigram_for_two_syllable_query(cat):
    cat.apply(make_record("seoul", ["서울특별시 강남구 사무실 이전"], vectors=False))
    cat.apply(make_record("busan", ["부산 해운대 출장"], vectors=False))
    hits = search(cat, "특별", vec=False)
    assert ids(hits) == ["seoul"]
    assert hits[0]["signals"] == ["trigram"]


def test_trigram_for_identifier_fragment(cat):
    cat.apply(make_record("img", ["IMG_1234.HEIC 제주 바다"], vectors=False))
    cat.apply(make_record("other", ["IMG_9999.HEIC 서울 야경"], vectors=False))
    hits = search(cat, "G_123", vec=False)
    assert ids(hits) == ["img"]
    assert hits[0]["signals"] == ["trigram"]
    assert ids(search(cat, "IMG_1234", vec=False))[0] == "img"


def test_vector_ranking(cat):
    docs = {
        "sea": "제주 바다 여행 사진과 해변 산책",
        "budget": "다음 분기 마케팅 예산 계획",
        "hire": "신규 채용 면접 일정 정리",
    }
    for d, t in docs.items():
        cat.apply(make_record(d, [t]))
    hits = cat.search("", ENC.encode_query("마케팅 예산 계획"), None)
    assert ids(hits)[0] == "budget"
    assert hits[0]["signals"] == ["vec"]
    assert [h["score"] for h in hits] == sorted([h["score"] for h in hits], reverse=True)


def test_rrf_fusion_math():
    fused = dict(rrf_fuse({"fts": ["a", "b", "a"], "vec": ["b", "c"], "trigram": ["c"]}))
    assert fused["a"] == pytest.approx(1.0 / 61)
    assert fused["b"] == pytest.approx(1.0 / 62 + 1.0 / 61)
    assert fused["c"] == pytest.approx(1.0 / 62 + 0.5 / 61)
    order = [k for k, _ in rrf_fuse({"fts": ["a", "b", "a"], "vec": ["b", "c"], "trigram": ["c"]})]
    assert order == ["b", "c", "a"]
    assert rrf_fuse({"x": ["a"]}, {"x": 2.0}, k=1) == [("a", 1.0)]


def test_fusion_prefers_agreeing_signals(cat):
    cat.apply(make_record("both", ["분기 예산 회의록"]))
    cat.apply(make_record("lex", ["예산"], vectors=False))
    cat.apply(make_record("sem", ["분기 예산 회의 정리 메모"]))
    hits = search(cat, "예산 회의록")
    assert ids(hits)[0] == "both"
    assert hits[0]["signals"] == ["fts", "trigram", "vec"]  # 회의록 (3 syllables) is also a substring term


def test_filters_apply_to_every_signal(cat):
    cat.apply(
        make_record(
            "f1",
            ["제주 회의록"],
            source_id="file:mba",
            updated_at="2024-01-15T09:00:00Z",
            place_ko="제주시",
            place_en="Jeju",
        )
    )
    cat.apply(make_record("n1", ["제주 회의록"], source_id="notion:acme", updated_at="2024-03-31T23:00:00Z"))
    cat.apply(
        make_record(
            "p1",
            ["제주 회의록"],
            source_id="photos:mba",
            modality="image",
            taken_at="2023-07-01T00:00:00Z",
            updated_at="2024-09-01T00:00:00Z",
            place_en="Jeju-si",
        )
    )
    for vec in (True, False):
        assert ids(search(cat, "회의록", vec=vec, source="notion")) == ["n1"]
        assert set(ids(search(cat, "회의록", vec=vec, source="file:"))) == {"f1"}
        assert ids(search(cat, "회의록", vec=vec, kind="image")) == ["p1"]
        assert set(ids(search(cat, "회의록", vec=vec, date_from="2024-01-01", date_to="2024-03-31"))) == {"f1", "n1"}
        assert ids(search(cat, "회의록", vec=vec, date_to="2023-12-31")) == ["p1"]
        assert set(ids(search(cat, "회의록", vec=vec, place="jeju"))) == {"f1", "p1"}
        assert ids(search(cat, "회의록", vec=vec, place="제주")) == ["f1"]
    vec_only = cat.search("", ENC.encode_query("제주 회의록"), None, source="photos", date_from="2023-01")
    assert ids(vec_only) == ["p1"] and vec_only[0]["signals"] == ["vec"]
    tri = search(cat, "제주", vec=False, kind="text", source="notion")
    assert ids(tri) == ["n1"] and "trigram" in tri[0]["signals"]


def test_vector_filters_are_pushed_into_knn(cat):
    for i in range(80):
        cat.apply(make_record(f"near{i}", [f"분기 예산 회의록 {i}"], updated_at="2024-05-01T00:00:00Z"))
    cat.apply(make_record("far", ["고양이 사료 주문"], source_id="notion:acme", updated_at="2022-02-02T00:00:00Z"))
    qv = ENC.encode_query("분기 예산 회의록")
    assert ids(cat.search("", qv, None, k=5, source="notion")) == ["far"]
    assert ids(cat.search("", qv, None, k=5, date_to="2023")) == ["far"]
    assert ids(cat.search("", qv, None, k=5, date_from="2022-02", date_to="2022-02")) == ["far"]
    assert cat.search("", qv, None, source="gmail") == []
    assert len(cat.search("", qv, None, k=5, date_from="2024-05-01", date_to="2024-05-01")) == 5


def test_day_number():
    assert day_number("2024-03-05T10:00:00Z") == 20240305
    assert day_number("2024-03") == 20240301
    assert day_number("2024-03", upper=True) == 20240331
    assert day_number("2024", upper=True) == 20241231
    assert day_number("") is None and day_number("yesterday") is None


def test_empty_query_lists_recent_with_filters(cat):
    cat.apply(make_record("old", ["가"], updated_at="2023-01-01T00:00:00Z"))
    cat.apply(make_record("new", ["나"], updated_at="2024-01-01T00:00:00Z"))
    assert ids(cat.search("", None, None)) == ["new", "old"]
    assert ids(cat.search("", None, None, date_to="2023-06")) == ["old"]


def test_visual_signal(cat):
    cat.register_model("siglip2-b16", "visual", 768)
    rng = np.random.default_rng(0)
    base = {d: rng.normal(size=768).astype(np.float32) for d in ("beach", "office")}
    for d, v in base.items():
        rec = make_record(d, [f"{d} 사진"], modality="video", vectors=False)
        frames = [
            (f"{d}#f{i}", float(i * 10) if i else None, (v + rng.normal(scale=0.3, size=768)).astype(np.float32))
            for i in range(3)
        ]
        rec.vec_visual = {"siglip2-b16": [(fid, t, x / np.linalg.norm(x)) for fid, t, x in frames]}
        cat.apply(rec)
    assert cat.stats()["vec_visual"] == 6
    q = base["beach"] / np.linalg.norm(base["beach"])
    hits = cat.search("", None, q)
    assert ids(hits)[0] == "beach"
    assert hits[0]["signals"] == ["visual"] and hits[0]["t_start"] is not None
    assert hits[0]["excerpt"] == "beach 사진"
    assert cat.search("", None, q, kind="text") == []
    rec = make_record("beach", ["beach 사진"], modality="video", vectors=False)
    rec.vec_visual = {"siglip2-b16": [("beach#f0", 0.0, q)]}
    cat.apply(rec)
    assert cat.stats()["vec_visual"] == 4
    cat.delete("office", "2024-01-01T00:00:00Z")
    assert cat.stats()["vec_visual"] == 1


def test_one_vector_per_chunk_prefers_serving_model(cat):
    cat.register_model("kure-v2", "text", 1024)
    rec = make_record("a", ["회의록"])
    other = {cid: -v for cid, v in rec.vec_text["kure-v1"].items()}
    rec.vec_text = {"kure-v2": other, "kure-v1": rec.vec_text["kure-v1"]}
    cat.apply(rec)
    assert cat.stats()["vec_text"] == 1
    assert ids(cat.search("", ENC.encode_query("회의록"), None)) == ["a"]


def test_unknown_model_vectors_skipped_but_registered(cat):
    rec = make_record("a", ["회의록"])
    rec.vec_text["other-model"] = rec.vec_text.pop("kure-v1")
    cat.apply(rec)
    s = cat.stats()
    assert s["vec_text"] == 0
    seen = {m["model_id"]: m for m in s["models"]}
    assert seen["other-model"]["active"] == 0 and seen["other-model"]["dim"] == 1024
    assert seen["kure-v1"]["active"] == 1


def test_quantize():
    v = np.array([1.5, -2.0, 0.5, -0.003, 0.0], dtype=np.float32)
    assert np.frombuffer(quantize(v), dtype=np.int8).tolist() == [127, -127, 64, 0, 0]


def test_fetch_slicing_and_overlap(cat):
    body = "".join(f"{i:03d} 문장입니다. " for i in range(120))
    c1, c2 = body[:900], body[900 - 120 : 1800]
    rec = make_record("long", [c1, c2], vectors=False)
    rec.chunks.append(Chunk(0, "long 제목 메타", field="meta", chunk_id="long#meta:0"))
    cat.apply(rec)
    full = cat.fetch("long", 0, 100_000)
    assert full["text"] == body[:1800] + "\n\nlong 제목 메타"
    assert full["total_chars"] == len(full["text"]) and full["next_offset"] is None
    part = cat.fetch("long", 100, 50)
    assert part["text"] == body[100:150] and part["length"] == 50 and part["next_offset"] == 150
    assert part["title"] == "long" and part["uri"] == "file:///long"
    assert cat.fetch("long", 10_000, 10)["text"] == ""


def test_excerpt_centered_and_bounded():
    text = "가" * 1000 + " 회의록 " + "나" * 1000
    ex = make_excerpt(text, ["회의록"])
    assert len(ex) <= 300 and "회의록" in ex and ex.startswith("…") and ex.endswith("…")
    assert make_excerpt("짧은 글", ["없음"]) == "짧은 글"
    assert len(make_excerpt("다" * 500, ["없음"])) == 300


def test_search_hit_shape(cat):
    cat.apply(make_record("a", ["회의록 본문"], updated_at="2024-01-01T00:00:00Z"))
    hit = search(cat, "회의록")[0]
    assert set(hit) == {
        "doc_id",
        "title",
        "uri",
        "modality",
        "source_id",
        "updated_at",
        "taken_at",
        "score",
        "excerpt",
        "field",
        "page",
        "t_start",
        "signals",
    }
    assert hit["field"] == "body"


def test_list_sources_and_stats(cat):
    cat.apply(make_record("a", ["하나"], source_id="file:mba", updated_at="2024-01-01T00:00:00Z"))
    cat.apply(make_record("b", ["둘"], source_id="file:mba", updated_at="2024-02-01T00:00:00Z"))
    cat.apply(make_record("c", ["셋"], source_id="notion:acme"))
    cat.delete("c", "2024-03-01T00:00:00Z")
    src = {s["source_id"]: s for s in cat.list_sources()}
    assert src["file:mba"]["documents"] == 2 and src["file:mba"]["last_updated"] == "2024-02-01T00:00:00Z"
    assert src["file:mba"]["kind"] == "file"
    assert src["notion:acme"]["documents"] == 0
    s = cat.stats()
    assert s["documents"] == 2 and s["deleted"] == 1 and s["by_modality"] == {"text": 2}
    assert s["db_bytes"] > 0 and s["sqlite_vec"].startswith("v")


def test_document_roundtrip(cat):
    rec = make_record("a", ["본문"], participants=["김", "이"], labels=["beach"], extra={"pages": 3})
    cat.apply(rec)
    d = cat.get_document("a")
    assert d["participants"] == ["김", "이"] and d["labels"] == ["beach"] and d["extra"] == {"pages": 3}
    assert d["persons"] is None


def test_concurrent_searches(cat):
    for i in range(20):
        cat.apply(make_record(f"d{i}", [f"{i}번 회의록 내용"]))
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda q: search(cat, q), ["회의록"] * 16))
    assert all(len(r) == 10 for r in results)


_WORDS = (
    "회의록 예산 마케팅 채용 면접 일정 보고서 계약서 견적 프로젝트 고객 제안서 디자인 서버 배포 데이터 분석 "
    "매출 비용 회계 세금 영수증 출장 제주 서울 부산 사진 영상 녹음 전사 요약 노션 메일 캘린더 학교 과제 논문 "
    "실험 결과 모델 학습 평가 지표 검색 색인 형태소 벡터 임베딩 문서 파일 폴더 백업 동기화 보안 권한 계정"
).split()


def test_performance_smoke(tmp_path, capsys):
    cat = Catalog(str(tmp_path / "perf.sqlite"))
    rnd = random.Random(7)
    rng = np.random.default_rng(7)
    t0 = time.perf_counter()
    for i in range(2000):
        texts = [" ".join(rnd.choices(_WORDS, k=40)) + f" 문서{i}번 IMG_{i:04d}" for _ in range(3)]
        rec = make_record(f"file:mba:{i:05d}", texts, vectors=False, updated_at=f"2024-{1 + i % 12:02d}-01T00:00:00Z")
        v = rng.normal(size=(3, 1024)).astype(np.float32)
        rec.vec_text = {"kure-v1": {c.chunk_id: x / np.linalg.norm(x) for c, x in zip(rec.chunks, v)}}
        cat.apply(rec)
    t_apply = time.perf_counter() - t0
    queries = ["회의록을", "마케팅 예산", "제주 사진", "형태소", "IMG_0042", "서버 배포 보안 권한", "특별"]
    for q in queries:
        search(cat, q)
    times = []
    for q in queries * 3:
        qv = ENC.encode_query(q)
        t = time.perf_counter()
        hits = cat.search(q, qv, None)
        times.append((time.perf_counter() - t) * 1000)
        assert hits
    filtered = []
    for q in queries:
        qv = ENC.encode_query(q)
        t = time.perf_counter()
        cat.search(q, qv, None, source="file", date_from="2024-03", date_to="2024-06")
        filtered.append((time.perf_counter() - t) * 1000)
    with capsys.disabled():
        print(
            f"\n[perf] apply 2000 docs x 3 chunks: {t_apply:.1f}s; search ms median {statistics.median(times):.1f} "
            f"max {max(times):.1f}; filtered median {statistics.median(filtered):.1f} max {max(filtered):.1f}"
        )
    assert max(times) < 300 and max(filtered) < 300
    cat.close()


def test_reopen_keeps_data(tmp_path):
    path = str(tmp_path / "sub" / "c.sqlite")
    with Catalog(path) as c:
        c.apply(make_record("a", ["회의록 원본"]))
    with Catalog(path) as c:
        assert ids(search(c, "회의록")) == ["a"]
        assert c.stats()["vec_text"] == 1


def test_meta_chunk_labels_not_indexed(cat):
    """Labels of the extractor's meta chunk (파일:, 폴더:, ...) must not make every meta chunk match."""
    meta = "제목: 휴가 사진\n폴더: Pictures(사진)\n파일: beach.jpg\n수정: 2026년 10월 3일 (2026-10-03)"
    doc = Document(doc_id="m1", source_id="file:mba", native_id="m1", modality="image", title="휴가 사진", uri="file:///m1")
    cat.apply(Record(doc, finalize_chunks("m1", [Chunk(0, meta, field="meta")]), {}))
    cat.apply(make_record("d1", ["설치 파일 목록을 정리한 문서"], vectors=False))
    assert ids(search(cat, "설치 파일", vec=False)) == ["d1"]
    assert ids(search(cat, "beach", vec=False)) == ["m1"]
    assert cat.fetch("m1")["text"].startswith("제목: 휴가 사진")


def test_long_document_cannot_fill_a_signal(cat):
    """One file with many matching chunks must not crowd every other document out of the top k."""
    cat.apply(make_record("long", [f"학교생활 안내 일정 {i}쪽: 기숙사와 수업 일정 안내" for i in range(120)]))
    for i in range(4):
        cat.apply(make_record(f"short{i}", [f"학교 행사 일정 안내 {i}"]))
    for vec in (False, True):
        got = ids(search(cat, "학교 일정 안내", vec=vec, k=5))
        assert got[0] == "long" or "long" in got
        assert len(got) == 5, (vec, got)


# -- regressions --------------------------------------------------------------


def _chunked(doc_id: str, text: str, **kw) -> Record:
    """A record cut by the real chunker (overlapping body chunks + meta chunk)."""
    from tidy_one.extract.chunk import chunk_blocks
    from tidy_one.extract.extract import TextBlock

    doc = Document(doc_id=doc_id, source_id="file:mba", native_id=doc_id, modality="text", title=doc_id,
                   uri=f"file:///{doc_id}", **kw)
    return Record(doc, chunk_blocks([TextBlock(text)], title=doc_id, doc_id=doc_id), {})


def test_fetch_keeps_every_row_of_repetitive_text(cat):
    """The overlap merge must not swallow identical rows or sentences that follow the real overlap."""
    rows = "출근,09:00,18:00,정상\n" * 200
    sentences = "오늘도 주간 회의를 진행했다. " * 120
    numbered = "".join(f"{i:03d},출근,정상\n" for i in range(300))
    for doc_id, text in (("rows", rows), ("sent", sentences), ("num", numbered)):
        rec = _chunked(doc_id, text)
        assert len([c for c in rec.chunks if c.field == "body"]) > 2
        cat.apply(rec)
        body = cat.fetch(doc_id, 0, 100_000)["text"].split("\n\n제목:")[0]
        assert body == text.strip(), doc_id
    assert cat.fetch("rows", 0, 100_000)["text"].count("출근,09:00,18:00,정상") == 200
    assert cat.fetch("sent", 0, 100_000)["text"].count("회의를 진행했다") == 120


def test_fetch_merges_chunks_from_other_chunkers_without_loss(cat):
    """Chunks another chunker cut with a longer overlap (15 identical rows): an ambiguous overlap may
    duplicate a few rows, but never drops one (60 distinct rows in all)."""
    row = "합계,0,0,0,0\n"
    a, b = row * 30, row * 45  # b repeats the last 15 rows of a, then has 30 new ones
    cat.apply(make_record("other", [a.strip(), b.strip()], vectors=False))
    assert cat.fetch("other", 0, 100_000)["text"].count("합계") >= 60


def test_meta_labels_do_not_match_short_queries(cat):
    """수정/생성/제목/폴더/파일 are meta-chunk labels: they must not match every document via trigram or scan."""
    for i in range(30):
        meta = f"제목: 사진목록{i}\n폴더: Pictures(사진)\n파일: list{i}.txt\n수정: 2026년 10월 3일 (2026-10-03)\n" \
               f"생성: 2026년 10월 1일 (2026-10-01)"
        doc = Document(f"p{i}", "file:mba", f"p{i}", "text", f"사진목록{i}", f"file:///p{i}")
        cat.apply(Record(doc, finalize_chunks(f"p{i}", [Chunk(0, f"사진 {i}장 정리"), Chunk(1, meta, field="meta")])))
    cat.apply(make_record("contract", ["계약서 초안을 수정했다. 다음 주에 서명한다."], vectors=False))
    hits = search(cat, "수정", vec=False, k=5)
    assert ids(hits) == ["contract"]
    for label in ("생성", "제목", "폴더", "파일"):
        assert search(cat, label, vec=False) == [], label
    assert ids(search(cat, "사진목록7", vec=False))[0] == "p7"  # the values after the labels still match


def test_title_scan_keeps_every_chunkless_document(cat):
    """Documents with no chunks (visual-only photos) must not collapse into one title hit."""
    for i in range(3):
        cat.apply(make_record(f"photos:{i}", [], modality="image", title=f"제주 바다 {i}", vectors=False))
    assert sorted(ids(search(cat, "제주", vec=False, k=10))) == ["photos:0", "photos:1", "photos:2"]


def test_substring_scan_caps_hits_per_document(cat):
    from tidy_one.catalog.catalog import PER_DOC, _Filters

    cat.apply(make_record("long", [f"학교생활 안내 {i}쪽" for i in range(120)], vectors=False))
    for i in range(4):
        cat.apply(make_record(f"short{i}", [f"우리 학교 행사 {i}"], vectors=False))
    hits = cat._search_trigram("학교", _Filters(), 50)
    docs = [h[0] for h in hits]
    assert docs.count("long") <= PER_DOC and {f"short{i}" for i in range(4)} <= set(docs)


def test_visual_signal_caps_frames_per_document(cat):
    """One long video's near-identical frames must not take every visual candidate slot."""
    cat.register_model("siglip2-b16", "visual", 768)
    rng = np.random.default_rng(1)
    q = rng.normal(size=768).astype(np.float32)
    q /= np.linalg.norm(q)

    def near(scale: float) -> np.ndarray:
        x = q + rng.normal(scale=scale, size=768).astype(np.float32)
        return x / np.linalg.norm(x)

    video = make_record("video", ["바다 영상"], modality="video", vectors=False)
    video.vec_visual = {"siglip2-b16": [(f"v#{i}", float(i), near(0.01)) for i in range(600)]}
    cat.apply(video)
    for i in range(50):
        photo = make_record(f"photo{i}", [f"사진 {i}"], modality="image", vectors=False)
        photo.vec_visual = {"siglip2-b16": [(f"p{i}#0", None, near(0.05))]}
        cat.apply(photo)
    got = ids(cat.search("", None, q, k=10))
    assert got[0] == "video" and len(got) == 10 and all(d.startswith("photo") for d in got[1:])


def test_compound_noun_alone_matches_split_compound(cat):
    """Kiwi keeps 근로계약서 whole in a short query but splits it inside sentences."""
    for i, s in enumerate(["근로계약서를 다시 작성했다.", "근로계약서는 매년 갱신한다.", "근로계약서에 서명했다."]):
        cat.apply(make_record(f"c{i}", [s], vectors=False))
    cat.apply(make_record("other", ["임대차 계약 갱신 안내"], vectors=False))
    assert sorted(ids(search(cat, "근로계약서", vec=False))) == ["c0", "c1", "c2"]
    assert sorted(ids(search(cat, "근로계약서를", vec=False))) == ["c0", "c1", "c2"]


def test_trigram_terms_strip_particles_and_skip_counters():
    from tidy_one.catalog.catalog import _trigram_terms

    assert _trigram_terms("v1.2에서") == ["v1.2"]
    assert _trigram_terms("IMG_1234를") == ["IMG_1234"]
    assert _trigram_terms("회의를") == ["회의"]
    assert _trigram_terms("3월 회의 자료") == []  # 3월 is a number + counter, not an identifier
    # no 1-2 character term (those need a full substring scan) in a multi-word query
    assert all(len(t) >= 3 for t in _trigram_terms("2층 10시 회의 3월 5일"))
    assert _trigram_terms("2024-03-05에 회의") == ["2024-03-05"]
    assert _trigram_terms("근로계약서 양식") == ["근로계약서"]


def test_identifier_with_particle_matches_by_trigram(cat):
    cat.apply(make_record("rel", ["tidy v1.2 릴리스 노트"], vectors=False))
    cat.apply(make_record("x", ["v2.0 계획"], vectors=False))
    hits = search(cat, "v1.2에서", vec=False)
    assert ids(hits)[0] == "rel" and "trigram" in hits[0]["signals"]


def test_place_filter_is_applied_before_vector_ranking(cat):
    """Many closer chunks from other places must not crowd out every place-matching candidate."""
    rng = np.random.default_rng(3)
    q = np.zeros(1024, dtype=np.float32)
    q[0] = 1.0

    def at(cos: float) -> np.ndarray:
        x = rng.normal(size=1024).astype(np.float32)
        x[0] = 0.0
        x /= np.linalg.norm(x)
        return (cos * q + np.sqrt(1 - cos * cos) * x).astype(np.float32)

    for i in range(1200):
        rec = make_record(f"t{i}", [f"문서 {i}"], vectors=False)
        rec.vec_text = {"kure-v1": {rec.chunks[0].chunk_id: at(0.6)}}
        cat.apply(rec)
    for i in range(3):
        rec = make_record(f"jeju{i}", [f"사진 {i}"], modality="image", place_ko="제주 서귀포", vectors=False)
        rec.vec_text = {"kure-v1": {rec.chunks[0].chunk_id: at(0.45)}}
        cat.apply(rec)
    assert sorted(ids(cat.search("", q, None, place="제주"))) == ["jeju0", "jeju1", "jeju2"]
    assert sorted(ids(cat.search("", q, None, kind="image"))) == ["jeju0", "jeju1", "jeju2"]
    assert ids(cat.search("", q, None, place="부산")) == []


def test_place_filter_scores_visual_frames_exactly(cat):
    cat.register_model("siglip2-b16", "visual", 768)
    rng = np.random.default_rng(4)
    q = rng.normal(size=768).astype(np.float32)
    q /= np.linalg.norm(q)
    for i in range(3):
        rec = make_record(f"v{i}", [f"영상 {i}"], modality="video", place_ko="서울" if i else "제주", vectors=False)
        x = q + rng.normal(scale=0.2 * (i + 1), size=768).astype(np.float32)
        rec.vec_visual = {"siglip2-b16": [(f"v{i}#0", 1.5, x / np.linalg.norm(x))]}
        cat.apply(rec)
    hits = cat.search("", None, q, place="제주")
    assert ids(hits) == ["v0"] and hits[0]["t_start"] == 1.5
    assert ids(cat.search("", None, q, place="서울")) == ["v1", "v2"]


def test_durable_catalog_uses_full_sync(tmp_path):
    with Catalog(str(tmp_path / "a.sqlite"), durable=True) as c:
        assert c._db.execute("PRAGMA synchronous").fetchone()[0] == 2  # FULL
    with Catalog(str(tmp_path / "b.sqlite")) as c:
        assert c._db.execute("PRAGMA synchronous").fetchone()[0] == 1  # NORMAL


def test_catalog_files_are_owner_only(tmp_path):
    old = os.umask(0o022)
    try:
        path = tmp_path / "new" / "catalog.sqlite"
        with Catalog(str(path)) as c:
            c.apply(make_record("a", ["비공개 본문"]))
            for p in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm")):
                assert stat.S_IMODE(p.stat().st_mode) == 0o600, p
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
        loose = tmp_path / "loose.sqlite"
        Catalog(str(loose)).close()
        loose.chmod(0o644)
        Catalog(str(loose)).close()  # an existing world-readable catalog is tightened
        assert stat.S_IMODE(loose.stat().st_mode) == 0o600
    finally:
        os.umask(old)


def test_prefixed_noun_ranks_exact_word_first(cat):
    cat.apply(make_record("open", ["공개 문서 목록"], vectors=False))
    cat.apply(make_record("closed", ["비공개 문서 목록"], vectors=False))
    assert ids(search(cat, "비공개 문서", vec=False))[0] == "closed"
    assert set(ids(search(cat, "공개 문서", vec=False))) == {"open", "closed"}


def test_acronym_is_searchable(cat):
    cat.apply(make_record("it", ["IT 부서 예산 계획"], vectors=False))
    cat.apply(make_record("hr", ["인사 부서 예산 계획"], vectors=False))
    assert ids(search(cat, "IT", vec=False)) == ["it"]
    assert ids(search(cat, "IT 예산", vec=False))[0] == "it"
