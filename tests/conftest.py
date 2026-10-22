"""테스트 공통 설정 — API 비용 0 보장.

1. 다른 모듈을 import 하기 전에 트레이싱을 끄고 가짜 키를 넣는다.
   src/adapter.py 의 load_dotenv 는 override=False 라서, 여기서 먼저 넣은 값을 .env 가 덮지 않는다.
2. 소켓 수준에서 외부 연결을 막는다 (루프백만 허용). httpx, requests, urllib 모두 이 아래를 지나므로
   목(mock)을 빠뜨린 테스트가 있어도 OpenAI, LangSmith, Ollama 로 요청이 나가지 않고 바로 실패한다.
   MCP 서버는 stdio 서브프로세스라 영향이 없고, 모의 HTTP 서버(127.0.0.1)는 허용된다.
"""
import os
import socket
import sys
from pathlib import Path

import pytest

os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_API_KEY"] = ""
os.environ["LANGSMITH_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = "test-dummy-key-not-real"

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

_LOOPBACK = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "", None}


class ExternalNetworkBlocked(RuntimeError):
    pass


def _host_of(address):
    if isinstance(address, tuple) and address:
        return address[0]
    return None   # AF_UNIX 경로 등


def _check(host):
    if host not in _LOOPBACK and not str(host).startswith("127."):
        raise ExternalNetworkBlocked(f"테스트 중 외부 네트워크 접속 차단: {host!r}")


_orig_connect = socket.socket.connect
_orig_connect_ex = socket.socket.connect_ex
_orig_getaddrinfo = socket.getaddrinfo


def _guard_connect(self, address):
    if self.family in (socket.AF_INET, socket.AF_INET6):
        _check(_host_of(address))
    return _orig_connect(self, address)


def _guard_connect_ex(self, address):
    if self.family in (socket.AF_INET, socket.AF_INET6):
        _check(_host_of(address))
    return _orig_connect_ex(self, address)


def _guard_getaddrinfo(host, *args, **kwargs):
    _check(host.decode() if isinstance(host, bytes) else host)
    return _orig_getaddrinfo(host, *args, **kwargs)


socket.socket.connect = _guard_connect
socket.socket.connect_ex = _guard_connect_ex
socket.getaddrinfo = _guard_getaddrinfo


@pytest.fixture(autouse=True)
def _reset_meter():
    """Meter 는 contextvar 라 같은 스레드의 다음 테스트로 넘어간다. 테스트마다 비운다."""
    from ext import meter
    token = meter._meter.set(None)
    yield
    meter._meter.reset(token)
