"""RAG 런북 선택 — 원본 _classify_incident_type(모니터링 알림 키워드 규칙)의 대체.

원본은 사용자 질의를 보지 않고, 조사한 시스템의 알림 문구에서 키워드 하나를 찾아 런북
1개를 고른다. 여기서는 질의 문장을 임베딩해 런북 6개와 코사인 유사도로 순위를 매긴다.

- ranking: 상위 top_k 순위. Recall@k·MRR 계산 대상.
- fed: write 에 실제로 넣는 런북. 1위 점수에서 margin 이내인 것만 넣는다. 복합 장애면
  2개가 들어가고, 단일 장애면 대개 1개만 들어간다. margin 은 측정 결과를 보기 전에 정한 값이며
  평가셋으로 튜닝하지 않는다.
- min_score(v2): 1위 점수 자체가 이 값보다 낮으면 아무 런북도 넣지 않는다 (graph_ext 에서 적용).
  margin 과 달리 dev 24건만으로 eval/calibrate_rag.py 가 정했고, 임베더마다 점수 척도가 달라
  구성 파일마다 값이 다르다 (final.yaml · final_local*.yaml 의 rag.min_score 참고).

켜는 스위치: runbook_selection=rag (검색기 생성은 src/adapter.py, 노드는 graph_ext.replan_check_rag_node).
임베더: rag.embedding — text-embedding-3-small(OpenAI, 본 실측) · local(LocalNgram, 오프라인 테스트) ·
local-tfidf · ollama:<모델> (로컬 Ollama 데모). 모두 같은 embed(texts, persist) 인터페이스를 따른다.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from .meter import QueryCache, current_meter, post_with_retry, stage

EMBED_URL = "https://api.openai.com/v1/embeddings"


def _unit(v: list[float]) -> list[float]:
    """L2 정규화. 단위 벡터끼리의 내적 = 코사인 유사도라서, rank 는 내적만 계산한다."""
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class OpenAIEmbedder:
    """OpenAI 임베딩 API. 런북 색인 벡터만 .cache/emb_<모델>.json 에 남겨 재실행 비용을 없앤다."""

    def __init__(self, model: str, api_key: str, cache_dir: Path):
        self.model = model
        self.name = f"openai:{model}"
        self.api_key = api_key
        self.cache_path = cache_dir / f"emb_{model}.json"
        cache_dir.mkdir(parents=True, exist_ok=True)
        self._disk = json.loads(self.cache_path.read_text()) if self.cache_path.exists() else {}

    def embed(self, texts: list[str], persist: bool = False) -> list[list[float]]:
        """persist=True 는 런북 문서 색인용(1회성 비용). 질의는 디스크에 남기지 않는다."""
        keys = [hashlib.sha1(t.encode()).hexdigest() for t in texts]   # 본문 해시 → 런북이 바뀌면 다시 임베딩
        # 디스크 캐시는 persist(런북 색인)일 때만 본다. 질의 임베딩은 매번 API 로 — 질의 비용을 그대로 재기 위함
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


class LocalTfidfEmbedder:
    """API 없이 도는 글자 2·3-gram TF-IDF 임베딩 (rag.embedding: local-tfidf). 로컬 Ollama 데모용.

    LocalNgram 은 모든 런북에 흔한 어구(확인·상태·점검)가 점수를 좌우해 dev 정답 1위가 18건 중 11건뿐이었다.
    여기서는 런북 6개에서 문서 빈도(IDF)를 구해 흔한 어구의 무게를 낮추고, 런북에 없는 어구는 질의에서 뺀다.
    어휘·IDF 는 런북 본문에서만 만든다 (평가 질의는 보지 않는다).
    """

    name = "local-tfidf"

    def __init__(self, runbook_dir: Path, ns: tuple[int, ...] = (2, 3)):
        self.ns = ns
        docs = [self._grams(p.read_text(encoding="utf-8")) for p in sorted(runbook_dir.glob("*.md"))]
        df: dict[str, int] = {}
        for g in docs:
            for k in g:
                df[k] = df.get(k, 0) + 1
        self.vocab = {k: i for i, k in enumerate(sorted(df))}
        # 평활 IDF: log((N+1)/(df+1)). 6개 런북 모두에 있는 어구는 log(7/7)=0 → 점수에 기여하지 않는다
        self.idf = {k: math.log((len(docs) + 1) / (c + 1)) for k, c in df.items()}

    def _grams(self, t: str) -> dict[str, int]:
        """공백을 지운 소문자 문자열의 글자 n-gram 빈도."""
        s = "".join(t.lower().split())
        out: dict[str, int] = {}
        for n in self.ns:
            for i in range(len(s) - n + 1):
                out[s[i:i + n]] = out.get(s[i:i + n], 0) + 1
        return out

    def embed(self, texts: list[str], persist: bool = False) -> list[list[float]]:
        out = []
        for t in texts:
            v = [0.0] * len(self.vocab)
            for g, c in self._grams(t).items():
                if g in self.vocab:
                    v[self.vocab[g]] = (1 + math.log(c)) * self.idf[g]   # 로그 TF x IDF (긴 질의의 반복 어구 완화)
            out.append(_unit(v))
        return out


class OllamaEmbedder:
    """로컬 Ollama 임베딩 모델 (rag.embedding: "ollama:<모델>", 예: ollama:bge-m3). 로컬 Ollama 데모용.

    POST http://127.0.0.1:11434/api/embed {"model", "input": [...]} — API 키·외부 전송 없음, 비용 0.
    런북 색인(persist=True)만 .cache/emb_ollama_<모델>.json 에 남긴다 (OpenAI 캐시 파일과 이름이 다름).
    """

    def __init__(self, model: str, cache_dir: Path, url: str = "http://127.0.0.1:11434/api/embed",
                 timeout: float = 120.0):
        self.model = model
        self.name = f"ollama:{model}"
        self.url = url
        self.timeout = timeout
        self.cache_path = cache_dir / f"emb_ollama_{model.replace(':', '_').replace('/', '_')}.json"
        cache_dir.mkdir(parents=True, exist_ok=True)
        self._disk = json.loads(self.cache_path.read_text()) if self.cache_path.exists() else {}

    def embed(self, texts: list[str], persist: bool = False) -> list[list[float]]:
        import httpx
        keys = [hashlib.sha1(t.encode()).hexdigest() for t in texts]
        todo = [t for t, k in zip(texts, keys) if not (persist and k in self._disk)]
        fresh = {}
        if todo:
            with stage("embed"):
                resp = httpx.post(self.url, json={"model": self.model, "input": todo}, timeout=self.timeout)
            resp.raise_for_status()
            for t, vec in zip(todo, resp.json()["embeddings"]):
                fresh[hashlib.sha1(t.encode()).hexdigest()] = _unit(vec)
        if persist and fresh:
            self._disk.update(fresh)
            self.cache_path.write_text(json.dumps(self._disk))
        return [fresh.get(k) or self._disk[k] for k in keys]


_INDEX: dict[str, list[list[float]]] = {}   # 임베더 이름 → 런북 벡터 (프로세스당 1회)


class RunbookRetriever:
    """src/data/runbooks/*.md 를 색인하고 질의와의 코사인 유사도로 순위를 낸다.

    런북 id = 파일 이름(stem). 질의 임베딩은 cost.cache 가 켜져 있으면 QueryCache(kind="embed")로 재사용한다.
    """

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
        """Returns: [(런북 id, 코사인 유사도)] 점수 내림차순 상위 top_k."""
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
    """1위 점수 - margin 이상인 런북만 고른다 (1위는 항상 포함).

    상대 기준이라 1위가 엉뚱해도 1개는 들어간다. 그 경우는 min_score(절대 기준)가 거른다.
    margin 은 구성값(rag.margin), 본 실측 구성은 0.05 를 측정 전에 정해 두었다.
    """
    if not ranking:
        return []
    top = ranking[0][1]
    return [rid for rid, s in ranking if s >= top - margin]
