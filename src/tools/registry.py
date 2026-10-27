"""Tool registry: every external action goes through `call_tool`, which logs the
call (no payload content), retries transient failures with backoff, and
returns a structured result. Used for: BRD parsing, Jira (mock) issue creation,
Markdown/PDF/Jira/HTML exports.
"""
from __future__ import annotations

import time
from typing import Any, Callable


class TransientToolError(RuntimeError):
    pass


def call_tool(logger, name: str, fn: Callable[..., Any], *args, retries: int = 2, agent: str = "orchestrator", **kwargs) -> Any:
    attempt = 0
    while True:
        attempt += 1
        t0 = time.perf_counter()
        try:
            out = fn(*args, **kwargs)
            logger.log("tool_call", tool=name, agent=agent, ok=True, attempt=attempt,
                       latency_ms=round((time.perf_counter() - t0) * 1000, 1))
            return out
        except TransientToolError as exc:
            logger.log("tool_call", tool=name, agent=agent, ok=False, attempt=attempt, error=str(exc)[:200],
                       latency_ms=round((time.perf_counter() - t0) * 1000, 1))
            if attempt > retries:
                raise
            time.sleep(0.05 * 2 ** attempt)
