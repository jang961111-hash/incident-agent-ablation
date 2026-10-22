"""수치 코드 검증 (src/ext/factcheck.py) — 답변 수치가 근거에 있는지 대조."""
import pytest

from ext import factcheck as fc

CTX = "- 모니터링 log-service: 상태=critical, CPU 42.5%, 메모리 71%, 알림 2건 ['disk usage 95%']"


def test_numbers_in_collects_all_numbers_regardless_of_unit():
    assert fc.numbers_in("CPU 42.5%, 알림 2건, 95") == {42.5, 2.0, 95.0}
    assert fc.numbers_in("") == set() and fc.numbers_in(None) == set()


@pytest.mark.parametrize("text,expected", [
    ("디스크 사용률 95%", [95.0]),
    ("지연 2.4s 로 증가", [2.4]),
    ("지연 2.4초 로 증가", [2.4]),
    ("응답 300ms", [300.0]),
    ("알림 3건, 서버 2대", [3.0, 2.0]),
    ("로그 12GB 정리", [12.0]),
    ("95 %", [95.0]),                       # 숫자와 단위 사이 공백
])
def test_claimed_numbers_units(text, expected):
    assert fc.claimed_numbers(text) == expected


def test_claimed_numbers_ignores_step_numbers_and_bare_small_ints():
    answer = "1) 로그를 정리한다\n2. 서비스를 재시작한다\n③ 3 단계로 확인"
    assert fc.claimed_numbers(answer) == []


def test_claimed_numbers_counts_bare_decimals_once():
    # 단위 없는 소수도 측정값으로 본다. 단위 있는 같은 값과 중복 집계하지 않는다
    assert fc.claimed_numbers("부하 0.85, 사용률 0.85%") == [0.85]
    assert fc.claimed_numbers("버전 1.2.3 배포") == []   # 버전 문자열은 소수가 아님


def test_unsupported_flags_number_missing_from_context():
    assert fc.unsupported("CPU 사용률이 88%입니다", CTX) == [88.0]


def test_supported_numbers_pass_including_rounding_tolerance():
    assert fc.unsupported("CPU 42.5%, 메모리 71%, 디스크 95%", CTX) == []
    assert fc.unsupported("CPU 약 43%", CTX) == []          # 42.5 의 반올림 (±0.5)
    assert fc.unsupported("CPU 약 44%", CTX) == [44.0]      # 허용 범위 밖


def test_unit_mismatch_still_matches_by_value():
    assert fc.unsupported("p95 지연 2.4초", "p95 latency 2.4s") == []


def test_check_summary_shape():
    bad = fc.check("1) CPU 88% 확인\n2) 디스크 95% 정리", CTX)
    assert bad == {"n_claims": 2, "unsupported": [88.0], "ok": False}
    good = fc.check("1) 디스크를 정리한다", CTX)
    assert good == {"n_claims": 0, "unsupported": [], "ok": True}


def test_empty_context_flags_every_claim():
    assert fc.check("CPU 88%, 메모리 70%", "")["unsupported"] == [88.0, 70.0]
