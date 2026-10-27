"""Structured JSONL logging for every agent execution.

Confidentiality: raw BRD text and generated artifact text are NEVER written to
the log. Inputs/outputs are logged as SHA-256 hashes plus non-sensitive
summaries (counts, ids, scores). Artifacts themselves live only in the local
run folder, which is treated as confidential.
"""
from __future__ import annotations

import hashlib
import json
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def sha(text: str | bytes, n: int = 16) -> str:
    if isinstance(text, str):
        text = text.encode("utf-8")
    return hashlib.sha256(text).hexdigest()[:n]


class RunLogger:
    def __init__(self, run_dir: Path, run_id: str):
        self.run_dir = run_dir
        self.run_id = run_id
        self.path = run_dir / "run_log.jsonl"
        run_dir.mkdir(parents=True, exist_ok=True)
        self.events: list[dict] = []

    def log(self, event: str, **fields: Any) -> dict:
        rec = {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
               "run_id": self.run_id, "event": event, **fields}
        self.events.append(rec)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, default=str) + "\n")
        return rec

    @contextmanager
    def agent_span(self, agent: str, step: str, input_obj: Any, revision: int = 0):
        """Times an agent execution and logs the required fields."""
        t0 = time.perf_counter()
        span: dict[str, Any] = {
            "agent": agent, "step": step, "revision": revision,
            "input_hash": sha(json.dumps(input_obj, default=str, sort_keys=True)),
            "rag_chunks": [], "guardrail_triggers": [], "status": "ok",
            "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "model": None,
        }
        try:
            yield span
        except Exception as exc:  # logged then re-raised to the orchestrator's retry logic
            span["status"] = "error"
            span["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
            raise
        finally:
            span["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            out = span.pop("output_obj", None)
            if out is not None:
                span["output_hash"] = sha(json.dumps(out, default=str, sort_keys=True))
            self.log("agent_execution", **span)

    def summary(self) -> dict:
        ex = [e for e in self.events if e["event"] == "agent_execution"]
        by_agent: dict[str, dict] = {}
        for e in ex:
            a = by_agent.setdefault(e["agent"], {"executions": 0, "errors": 0, "latency_ms": 0.0,
                                                 "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0})
            a["executions"] += 1
            a["errors"] += e["status"] != "ok"
            a["latency_ms"] += e.get("latency_ms", 0)
            a["tokens_in"] += e.get("tokens_in", 0)
            a["tokens_out"] += e.get("tokens_out", 0)
            a["cost_usd"] += e.get("cost_usd", 0.0)
        tool_calls = [e for e in self.events if e["event"] == "tool_call"]
        return {
            "agent_executions": len(ex),
            "agent_errors": sum(e["status"] != "ok" for e in ex),
            "tool_calls": len(tool_calls),
            "tool_call_success_rate": round(sum(t.get("ok", False) for t in tool_calls) / len(tool_calls), 3) if tool_calls else None,
            "guardrail_triggers": sum(1 for e in self.events if e["event"] == "guardrail"),
            "contract_violations": sum(1 for e in self.events if e["event"] == "contract_violation"),
            "by_agent": {k: {kk: round(vv, 4) if isinstance(vv, float) else vv for kk, vv in v.items()}
                         for k, v in by_agent.items()},
        }
