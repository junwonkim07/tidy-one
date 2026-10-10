import unicodedata
from concurrent.futures import ThreadPoolExecutor

from tidy_one.text import identifier_tokens, is_identifier, morph


def test_particles_dropped_nouns_kept():
    toks = morph("회의록을 정리했습니다").split()
    assert "회의록" in toks
    assert "정리" in toks
    assert "을" not in toks and "습니다" not in toks


def test_query_and_document_share_terms():
    doc = set(morph("지난주 주간 회의록을 공유드립니다").split())
    assert set(morph("회의록").split()) <= doc
    assert set(morph("회의록을").split()) <= doc


def test_verb_stems_and_stopwords():
    toks = morph("점심을 먹었다 그리고 할 수 있다").split()
    assert "먹" in toks
    assert "하" not in toks and "있" not in toks and "수" not in toks


def test_latin_lowercased_and_identifiers_kept():
    toks = morph("KURE 모델 IMG_1234.HEIC를 tidy_one에서 열었다").split()
    assert "kure" in toks
    assert "img_1234.heic" in toks
    assert "tidy_one" in toks
    assert all(t == t.lower() for t in toks)


def test_numbers_kept():
    toks = morph("2024년 3분기 매출").split()
    assert "2024" in toks and "매출" in toks and "3분기" in toks


def test_nfd_input_matches_nfc():
    s = "회의록을 정리"
    assert morph(unicodedata.normalize("NFD", s)) == morph(s)


def test_empty():
    assert morph("") == ""
    assert morph("   ") == ""


def test_identifier_helpers():
    assert is_identifier("IMG_1234")
    assert is_identifier("v0.1.9")
    assert is_identifier("kure-v1")
    assert not is_identifier("hello")
    assert not is_identifier("2024")
    assert not is_identifier("회의록")
    assert identifier_tokens("(see IMG_0001.jpg) and tidy_one을") == ["img_0001.jpg", "tidy_one"]


def test_thread_safe():
    texts = [f"{i}번째 회의록을 서울에서 정리했습니다 report_{i}.pdf" for i in range(40)]
    expected = [morph(t) for t in texts]
    with ThreadPoolExecutor(8) as pool:
        assert list(pool.map(morph, texts)) == expected


def test_english_stopwords_dropped():
    toks = morph("How do I install the craft apps from the DMG files").split()
    assert {"install", "craft", "apps", "dmg", "files"} <= set(toks)
    assert not {"how", "do", "i", "the", "from"} & set(toks)


def test_acronyms_survive_the_english_stoplist():
    assert "it" in morph("IT 부서 예산").split()
    assert "who" in morph("WHO 보고서").split()
    assert "us" in morph("US 법인 설립").split()
    assert "as" in morph("AS 센터 접수").split()
    assert morph("IT") == "it"
    assert not {"it", "us", "i"} & set(morph("I think it is for us").split())  # lowercase words stay stopwords


def test_prefixed_nouns_keep_the_prefix():
    assert morph("비공개 문서").split() == ["비공개", "공개", "문서"]
    assert {"불가능", "가능"} <= set(morph("불가능").split())
    assert {"재발급", "발급"} <= set(morph("재발급 신청").split())
    assert "비공개" not in morph("공개 문서").split()


def test_word_stem_drops_particles_and_endings():
    from tidy_one.text import word_stem

    assert word_stem("회의를") == "회의"
    assert word_stem("근로계약서를") == "근로계약서"
    assert word_stem("계약했다") == "계약"
    assert word_stem("온보딩자료") == "온보딩자료"  # odd analysis inside the word keeps the surface text
    assert word_stem("IMG_1234를") == "IMG_1234"
    assert word_stem("") == ""
