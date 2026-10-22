"""도구 부분 실패 허용 (research_tolerant_node) + 장애 주입 (FaultyMCP). LLM, 네트워크 없음."""
import asyncio
from pathlib import Path

import pytest
import yaml

from ext.faults import FaultyMCP
from ext.graph_ext import research_tolerant_node

ROOT = Path(__file__).resolve().parent.parent


class FakeMCP:
    def __init__(self, fail_targets=(), fail_runbooks=(), timeouts_first=()):
        self.fail_targets, self.fail_runbooks = set(fail_targets), set(fail_runbooks)
        self.timeouts = set(timeouts_first)
        self.template_lookups = 0

    async def call_tool(self, name, arguments, server="ops"):
        target = arguments["system_name"]
        if target in self.timeouts:
            self.timeouts.discard(target)
            raise asyncio.TimeoutError()
        if target in self.fail_targets:
            raise ConnectionError(f"down: {target}")
        return {"system_name": target, "status": "ok", "cpu_percent": 10, "memory_percent": 20, "alerts": []}

    async def find_resource_template(self, name):
        self.template_lookups += 1
        return "ops", "runbook://{incident_type}"

    async def read_resource(self, uri, server="ops"):
        if uri.split("//")[1] in self.fail_runbooks:
            raise FileNotFoundError(uri)
        return f"본문 {uri}"


def task(i, kind, target, status="pending"):
    return {"id": f"t{i}", "agent": "research", "kind": kind, "target": target, "status": status}


def research(mcp, tasks, **extra):
    from types import SimpleNamespace
    state = {"tasks": tasks, "events": [], "collected": [], **extra}
    return asyncio.run(research_tolerant_node(state, deps=SimpleNamespace(mcp=mcp)))


def test_one_tool_failure_keeps_other_results():
    out = research(FakeMCP(fail_targets={"web-01"}),
                   [task(0, "monitoring", "auth-service"), task(1, "monitoring", "web-01"),
                    task(2, "runbook", "db-down")])
    status = {t["target"]: t["status"] for t in out["tasks"]}
    assert status == {"auth-service": "done", "web-01": "failed", "db-down": "done"}
    assert out["tool_failures"] == 1
    sources = [c["source"] for c in out["collected"]]
    assert sources.count("monitoring") == 1 and sources.count("runbook") == 1
    note = [c["data"] for c in out["collected"] if c["source"] == "analysis"][0]
    assert "web-01 monitoring 조회 실패" in note and "추측하지 말 것" in note
    failed = [e for e in out["events"] if e["type"] == "TaskFailed"]
    assert failed[0]["target"] == "web-01" and failed[0]["error"].startswith("ConnectionError")


def test_runbook_read_failure_is_tolerated():
    out = research(FakeMCP(fail_runbooks={"disk-full"}), [task(0, "runbook", "disk-full")])
    assert out["tasks"][0]["status"] == "failed" and out["tool_failures"] == 1
    assert out["events"][-1]["error"].startswith("FileNotFoundError")


def test_all_tools_fail_pipeline_still_returns():
    out = research(FakeMCP(fail_targets={"a", "b"}),
                   [task(0, "monitoring", "a"), task(1, "monitoring", "b")], tool_failures=1)
    assert out["tool_failures"] == 3          # 이전 누적 1 + 이번 2
    assert all(t["status"] == "failed" for t in out["tasks"])


def test_success_path_has_no_failures_and_input_not_mutated():
    tasks = [task(0, "monitoring", "auth-service")]
    out = research(FakeMCP(), tasks)
    assert out["tool_failures"] == 0 and out["tasks"][0]["status"] == "done"
    assert tasks[0]["status"] == "pending"               # 원본 state 의 태스크는 그대로


def test_monitoring_only_does_not_lookup_runbook_template():
    mcp = FakeMCP()
    research(mcp, [task(0, "monitoring", "auth-service")])
    assert mcp.template_lookups == 0


def test_transient_timeout_is_retried_and_counted():
    out = research(FakeMCP(timeouts_first={"auth-service"}), [task(0, "monitoring", "auth-service")])
    assert out["tasks"][0]["status"] == "done" and out["retry_count"] == 1 and out["tool_failures"] == 0


def test_no_pending_research_is_skipped():
    out = research(FakeMCP(), [task(0, "monitoring", "a", status="done")])
    assert out["events"][-1]["type"] == "ResearchSkipped" and "tasks" not in out


# --- FaultyMCP ------------------------------------------------------------------

class Inner:
    def __init__(self):
        self.calls = []
        self.marker = "inner"

    async def call_tool(self, name, arguments, server="ops"):
        self.calls.append(name)
        return {"ok": name}


def _hits(f, n=50):
    out = []
    for i in range(n):
        try:
            asyncio.run(f.call_tool("get_monitoring_status", {"system_name": f"s{i}"}))
            out.append(False)
        except ConnectionError:
            out.append(True)
    return out


def test_faulty_rate_zero_and_one():
    assert not any(_hits(FaultyMCP(Inner(), "get_monitoring_status", 0.0, 7, "q")))
    f = FaultyMCP(Inner(), "get_monitoring_status", 1.0, 7, "q")
    assert all(_hits(f)) and f.injected == 50


def test_faulty_is_deterministic_per_seed_and_query():
    a = _hits(FaultyMCP(Inner(), "get_monitoring_status", 0.3, 7, "q"))
    b = _hits(FaultyMCP(Inner(), "get_monitoring_status", 0.3, 7, "q"))
    c = _hits(FaultyMCP(Inner(), "get_monitoring_status", 0.3, 11, "q"))
    assert a == b and a != c
    assert 0 < sum(a) < 50


def test_faulty_only_targets_named_tool_and_delegates_attrs():
    inner = Inner()
    f = FaultyMCP(inner, "get_monitoring_status", 1.0, 7, "q")
    assert asyncio.run(f.call_tool("other_tool", {"x": 1})) == {"ok": "other_tool"}
    assert f.marker == "inner" and f.injected == 0


# --- 통합: fake 백엔드 final 구성에서 도구 100% 실패해도 답을 낸다 ------------------

def test_final_config_completes_under_total_tool_failure():
    from src.adapter import run_once
    cfg = yaml.safe_load((ROOT / "eval/configs/final.yaml").read_text())
    cfg.update(backend="fake", fake_force_incident=True,
               fault_injection={"tool": "get_monitoring_status", "rate": 1.0, "seed": 7})
    cfg["cost"]["cache"] = False
    out = run_once("log-service 디스크 공간 부족 장애 진단해줘", cfg)
    assert out["answer"] and out["faults_injected"] >= 1 and out["tool_failures"] >= 1
    assert "조회 실패" in out["context"]
