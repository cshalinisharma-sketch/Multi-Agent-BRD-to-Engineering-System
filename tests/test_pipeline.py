"""Smoke + guardrail + contract tests.  Run: python -m pytest -q  (or python tests/test_pipeline.py)"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agents.orchestrator import Pipeline  # noqa: E402
from src.config import RunOptions  # noqa: E402
from src.contracts import EngineeringPlan  # noqa: E402
from src.guardrails import ContractViolation, quarantine_injections, redact, validate_handoff  # noqa: E402
from src.llm import ALLOW_EXTERNAL_ENV, ExternalContentNotAllowed, LLMClient, LLMResult  # noqa: E402

BRDS = ROOT / "eval_dataset" / "brds"
OUT = ROOT / "outputs" / "tests"


def _offline():
    """Tests never call a live provider, even when an API key is set in the shell."""
    return LLMClient(provider="offline")


def _pipe(**kw):
    return Pipeline(RunOptions(auto_approve=True, extra={"quiet": True}, **kw), llm=_offline(), output_dir=OUT)


def _env(**values):
    """Set env vars (None = unset); returns the previous values for _restore."""
    old = {k: os.environ.get(k) for k in values}
    for k, v in values.items():
        os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    return old


def test_end_to_end_demo_brd():
    st = _pipe().run(BRDS / "E2_merchant_dispute_portal.md")
    assert st.status == "completed"
    assert st.critic_reports[-1].overall_badge in ("GREEN", "AMBER")
    assert len(st.critic_reports) >= 2, "revision loop should have run at least once"
    assert (st.run_dir / "engineering_pack.md").exists() and (st.run_dir / "jira_export.json").exists()
    log = [json.loads(l) for l in (st.run_dir / "run_log.jsonl").read_text().splitlines()]
    raw = (BRDS / "E2_merchant_dispute_portal.md").read_text()
    blob = json.dumps(log)
    assert "Merchants sign in" not in blob and raw[:200] not in blob, "raw BRD content must never be logged"
    assert all("input_hash" in e for e in log if e["event"] == "agent_execution")


def test_malformed_and_wrong_type_rejected():
    assert _pipe().run(BRDS / "G1_malformed_meeting_notes.txt").status == "rejected"
    assert _pipe().run(BRDS / "G3_wrong_file_type.json").status == "rejected"


def test_injection_and_pii():
    text = (BRDS / "G2_prompt_injection_pii.md").read_text()
    clean, counts = redact(text)
    assert counts.get("EMAIL") == 1 and counts.get("API_KEY") == 1 and "priya" not in clean
    clean, refs, terms = quarantine_injections(clean)
    assert refs == ["FR-04"] and "cryptocurrency" in terms and "Ignore all previous" not in clean
    st = _pipe().run(BRDS / "G2_prompt_injection_pii.md")
    blob = json.dumps({k: v.model_dump() for k, v in st.artifacts.items()}).lower()
    assert "crypto" not in blob and st.brd.req("FR-04") is None


def test_contract_violation_detected():
    try:
        validate_handoff(EngineeringPlan, {"template_used": "T1", "phases": [], "milestones": [], "risks": [], "team": []},
                         "plan_generator", "schedule_estimator")
    except ContractViolation as e:
        assert "phases" in e.errors
    else:
        raise AssertionError("empty plan must violate the contract")


def test_llm_retry_then_fallback(monkeypatch=None):
    """Online path: first response is malformed JSON, second violates the schema, third is valid -> accepted.
    A client that never returns valid JSON falls back to the heuristic and flags it."""
    calls = {"n": 0}
    pipe = _pipe()
    good = {}

    def fake_call(self, agent, system, user, max_tokens=4000):
        if agent != "plan_generator":
            return LLMResult(None, 10, 10, "fake")  # everything else falls back
        calls["n"] += 1
        if calls["n"] == 1:
            return LLMResult(None, 10, 10, "fake", "not json")
        if calls["n"] == 2:
            return LLMResult({"template_used": "T1"}, 10, 10, "fake")
        return LLMResult(good["plan"], 10, 10, "fake")

    # capture a valid plan from an offline run to serve as the "LLM" answer
    st0 = pipe.run(BRDS / "E1_leave_request_tracker.md")
    good["plan"] = st0.artifacts["plan_generator"].model_dump()
    orig = LLMClient._call
    LLMClient._call = fake_call
    old_env = _env(ANTHROPIC_API_KEY="test-key", **{ALLOW_EXTERNAL_ENV: "1"})
    try:
        llm = LLMClient(provider="anthropic")
        p2 = Pipeline(RunOptions(auto_approve=True, extra={"quiet": True}), llm=llm, output_dir=OUT)
        st = p2.run(BRDS / "E1_leave_request_tracker.md")
    finally:
        LLMClient._call = orig
        _env(**old_env)
    assert st.status == "completed"
    log = [json.loads(l) for l in (st.run_dir / "run_log.jsonl").read_text().splitlines()]
    plan_ev = next(e for e in log if e["event"] == "agent_execution" and e["agent"] == "plan_generator")
    assert plan_ev["mode"].startswith("llm(attempt=3)"), plan_ev["mode"]
    assert "malformed_json" in plan_ev["guardrail_triggers"] and "schema_violation" in plan_ev["guardrail_triggers"]
    other = next(e for e in log if e["event"] == "agent_execution" and e["agent"] == "solution_architect")
    assert other["mode"] == "fallback-heuristic" and "llm_fallback_to_heuristic" in other["guardrail_triggers"]


def _summary_core(st):
    s = json.loads((st.run_dir / "summary.json").read_text())
    return {k: s[k] for k in ("status", "final_badge", "final_score", "revision_rounds", "critic_history", "hitl")}


def test_langgraph_engine_matches_classic():
    from src.graph import GraphPipeline
    brd = BRDS / "E3_realtime_fraud_alerts.md"
    classic = _pipe().run(brd)
    graph = GraphPipeline(RunOptions(auto_approve=True, extra={"quiet": True}), llm=_offline(), output_dir=OUT).run(brd)
    assert _summary_core(graph) == _summary_core(classic)
    assert graph.exports.keys() == classic.exports.keys()
    assert GraphPipeline(RunOptions(extra={"quiet": True}), llm=_offline(), output_dir=OUT).run(BRDS / "G3_wrong_file_type.json").status == "rejected"


def test_langgraph_hitl_interrupt_resume():
    """Without --auto-approve the graph pauses at the HITL node and resumes with the EM decision."""
    from src.graph import GraphPipeline
    seen = []

    class EM(GraphPipeline):
        @staticmethod
        def hitl_prompt(payload):
            seen.append(payload)
            return {"decision": "rejected", "by": "EM (test)"}

    st = EM(RunOptions(extra={"quiet": True}), llm=_offline(), output_dir=OUT).run(BRDS / "E1_leave_request_tracker.md")
    assert len(seen) == 1 and seen[0]["badge"] in ("GREEN", "AMBER", "RED") and seen[0]["artifacts"]
    assert st.status == "completed" and st.hitl["decision"] == "rejected"
    assert "jira" not in st.exports and "pdf" not in st.exports, "rejected pack must not be pushed to Jira"


def test_external_provider_requires_opt_in():
    """BRD text may only leave the machine with an API key AND the explicit data-boundary opt-in."""
    old = _env(OPENAI_API_KEY=None, **{ALLOW_EXTERNAL_ENV: None})
    try:
        for env in ({}, {"OPENAI_API_KEY": "test-key"}):
            _env(**env)
            try:
                LLMClient(provider="openai")
            except ExternalContentNotAllowed:
                pass
            else:
                raise AssertionError(f"openai must be refused with env {env}")
        _env(**{ALLOW_EXTERNAL_ENV: "1"})
        llm = LLMClient(provider="openai")
        assert llm.backend == "langchain" and type(llm._chat_model("gpt-4.1", 100)).__name__ == "_ChatModelBinding"
    finally:
        _env(**old)


def test_llm_cache_and_tracing_gate():
    """Opt-in response cache: the second identical call is served from disk with zero tokens.
    LangSmith tracing is switched off unless the data-boundary opt-in is set."""
    import shutil
    import tempfile
    from src import llm as llm_mod
    calls = {"n": 0}

    def fake_call(self, agent, system, user, max_tokens=4000):
        calls["n"] += 1
        return LLMResult({"ok": True}, 100, 20, "fake", '{"ok": true}')

    tmp = Path(tempfile.mkdtemp())
    orig_call, orig_dir = LLMClient._call, llm_mod.CACHE_DIR
    old = _env(OPENAI_API_KEY="test-key", BRD2ENG_LLM_CACHE="1", **{ALLOW_EXTERNAL_ENV: "1"})
    LLMClient._call, llm_mod.CACHE_DIR = fake_call, tmp
    try:
        c = LLMClient(provider="openai")
        first, second = c._cached_call("critic", "sys", "user"), c._cached_call("critic", "sys", "user")
        assert calls["n"] == 1 and not first.cached and second.cached and second.tokens_in == 0
        assert second.data == {"ok": True}
        _env(LANGSMITH_TRACING="true")
        assert llm_mod.gate_tracing() == "on"
        _env(**{ALLOW_EXTERNAL_ENV: None})
        assert llm_mod.gate_tracing() == "blocked" and os.environ["LANGSMITH_TRACING"] == "false"
    finally:
        LLMClient._call, llm_mod.CACHE_DIR = orig_call, orig_dir
        _env(**old, LANGSMITH_TRACING=None)
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("PASS", name)
