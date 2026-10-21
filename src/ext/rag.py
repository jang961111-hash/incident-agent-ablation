"""RAG 런북 선택 — 원본 _classify_incident_type(모니터링 알림 키워드 규칙)의 대체.

원본은 사용자 질의를 보지 않고, 조사한 시스템의 알림 문구에서 키워드 하나를 찾아 런북
1개를 고른다. 여기서는 질의 문장을 임베딩해 런북 6개와 코사인 유사도로 순위를 매긴다.

- ranking: 상위 top_k 순위. Recall@k·MRR 계산 대상.
- fed: write 에 실제로 넣는 런북. 1위 점수에서 margin 이내인 것만 넣는다. 복합 장애면
  2개가 들어가고, 단일 장애면 대개 1개만 들어간다. margin 은 측정 결과를 보기 전에 정한 값이며
  평가셋으로 튜닝하지 않는다.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from .meter import QueryCache, current_meter, post_with_retry, stage

EMBED_URL = "https://api.openai.com/v1/embeddings"


def _unit(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class OpenAIEmbedder:
    def __init__(self, model: str, api_key: str, cache_dir: Path):
        self.model = model
        self.name = f"openai:{model}"
        self.api_key = api_key
        self.cache_path = cache_dir / f"emb_{model}.json"
        cache_dir.mkdir(parents=True, exist_ok=True)
        self._disk = json.loads(self.cache_path.read_text()) if self.cache_path.exists() else {}

    def embed(self, texts: list[str], persist: bool = False) -> list[list[float]]:
        """persist=True 는 런북 문서 색인용(1회성 비용). 질의는 디스크에 남기지 않는다."""
        keys = [hashlib.sha1(t.encode()).hexdigest() for t in texts]
        todo = [t for t, k in zip(texts, keys) if not (persist and k in self._disk)]
        fresh = {}
        if todo:
            if not self.api_key:
                raise RuntimeError("OPENAI_API_KEY가 없습니다 — scripts/set_keys.sh")
            with stage("embed"):
                data = post_with_retry(EMBED_URL, {"model": self.model, "input": todo},
                                       self.api_key)
            meter = current_meter()
            if meter is not None:
                meter.add(self.model, data.get("usage", {}).get("prompt_tokens", 0), 0, "embed")
            for t, item in zip(todo, data["data"]):
                fresh[hashlib.sha1(t.encode()).hexdigest()] = _unit(item["embedding"])
        if persist and fresh:
            self._disk.update(fresh)
            self.cache_path.write_text(json.dumps(self._disk))
        return [fresh.get(k) or self._disk[k] for k in keys]


class LocalNgramEmbedder:
    """API 없이 도는 글자 2·3-gram 해시 임베딩. 오프라인 테스트 전용 — 실측에는 쓰지 않는다."""

    name = "local-ngram"

    def __init__(self, dim: int = 1024):
        self.dim = dim

    def embed(self, texts: list[str], persist: bool = False) -> list[list[float]]:
        out = []
        for t in texts:
            v = [0.0] * self.dim
            s = "".join(t.lower().split())
            for n in (2, 3):
                for i in range(len(s) - n + 1):
                    h = int(hashlib.md5(s[i:i + n].encode()).hexdigest(), 16)
                    v[h % self.dim] += 1.0
            out.append(_unit(v))
        return out


_INDEX: dict[str, list[list[float]]] = {}   # 임베더 이름 → 런북 벡터 (프로세스당 1회)


class RunbookRetriever:
    def __init__(self, runbook_dir: Path, embedder, cache: QueryCache | None = None):
        self.embedder = embedder
        self.cache = cache
        self.docs = {p.stem: p.read_text(encoding="utf-8")
                     for p in sorted(runbook_dir.glob("*.md"))}
        self.ids = list(self.docs)
        self._vecs = None

    def _index(self) -> list[list[float]]:
        """색인 비용은 질의별 비용이 아니므로 adapter 가 Meter 시작 전에 미리 부른다."""
        if self._vecs is None:
            key = self.embedder.name
            if key not in _INDEX:
                _INDEX[key] = self.embedder.embed([self.docs[i] for i in self.ids], persist=True)
            self._vecs = _INDEX[key]
        return self._vecs

    def rank(self, query: str, top_k: int) -> list[tuple[str, float]]:
        qv = self.cache.get("embed", query) if self.cache else None
        if qv is None:
            qv = self.embedder.embed([query])[0]
            if self.cache:
                self.cache.put("embed", query, qv)
        scores = [(rid, sum(a * b for a, b in zip(qv, dv)))
                  for rid, dv in zip(self.ids, self._index())]
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]


def select_feed(ranking: list[tuple[str, float]], margin: float) -> list[str]:
    if not ranking:
        return []
    top = ranking[0][1]
    return [rid for rid, s in ranking if s >= top - margin]
