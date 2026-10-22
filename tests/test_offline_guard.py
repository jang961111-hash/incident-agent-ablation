"""테스트 환경 자체 점검 — 트레이싱 꺼짐, 가짜 키, 외부 네트워크 차단 (conftest.py)."""
import os

import httpx
import pytest

from conftest import ExternalNetworkBlocked


def test_tracing_disabled_and_dummy_key():
    from langsmith import utils
    assert os.environ["LANGCHAIN_TRACING_V2"] == "false" and os.environ["LANGSMITH_TRACING"] == "false"
    assert not utils.tracing_is_enabled()
    # conftest 의 가짜 키, 또는 eval/mock_llm_bench import 시 덮어쓰는 모의 키 — 실제 키가 아니어야 한다
    assert os.environ["OPENAI_API_KEY"] in {"test-dummy-key-not-real", "mock-key-not-real"}


@pytest.mark.parametrize("url", ["https://api.openai.com/v1/chat/completions",
                                 "https://api.smith.langchain.com/runs/multipart"])
def test_external_network_is_blocked(url):
    with pytest.raises(ExternalNetworkBlocked):
        httpx.post(url, json={}, timeout=1)
