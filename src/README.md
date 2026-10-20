# src — 베이스 에이전트

여기에 교수님 제공 베이스 AI 에이전트 코드를 넣는다.

## 넣은 뒤 할 일

1. `base` 구성으로 평가셋을 돌려 원래 동작이 재현되는지 확인한다.
   이게 안 되면 Ablation 전체가 성립하지 않는다.

2. `adapter.py` 를 만들어 평가 하네스가 부르는 단일 진입점을 노출한다.

```python
# src/adapter.py
def run_once(query: str, config: dict) -> dict:
    """평가 하네스가 질의 1건에 대해 호출하는 진입점.

    Returns:
        {
          "answer":    str,          # 최종 답변
          "context":   str,          # 수집된 근거 (Judge의 completeness 판정 대상)
          "retrieved": [str],        # 선택된 런북 id, 순위 순서 (Recall@k 대상)
          "rewrites":  int,          # 재작성 횟수
          "tokens":    {"prompt": int, "completion": int},
          "latency_ms": float,
          "trace_url": str | None,   # LangSmith
        }
    """
```

3. 개선은 전부 `config` 플래그로 분기시킨다. 코드를 지우고 덮어쓰지 않는다.

```python
if config["runbook_selection"] == "rag":
    runbooks = rag_select(query, top_k=config["rag"]["top_k"])
else:
    runbooks = keyword_select(query)      # 베이스 원본 유지
```

## 베이스 파이프라인 (수업 기준)

```
route → plan → validate(plan) → research(MCP tools) → replan_check
      → analysis(gate) → write → validate(quality)
```

개선이 들어가는 지점:

| 노드 | 개선 |
|---|---|
| `research` 앞 런북 선택 | 키워드 규칙 → RAG |
| `validate(quality)` | 규칙 기반 → LLM-as-a-Judge 4지표 |
| 전체 모델 호출 | 단일 모델 → fast/quality 분리 |
| `research` 진입 | 질의 정규화 캐싱 |
