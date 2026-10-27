"""Mock Jira REST client (external integration with mock data).

Mirrors the shape of Jira Cloud's POST /rest/api/3/issue: returns {"id", "key",
"self"}. Issues are persisted as JSON under <run>/jira_mock/. Set
BRD2ENG_SIMULATE_TOOL_FAILURE=1 to make the first call fail with a transient
error, which demonstrates the tool-retry path in the logs.

To use real Jira, implement `create_issue` with requests against your site and
an API token from a secret store; the exporter interface stays the same.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .registry import TransientToolError


class MockJiraClient:
    def __init__(self, out_dir: Path, project_key: str = "BRD"):
        self.dir = out_dir / "jira_mock"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.project = project_key
        self.counter = 0
        self._fail_once = os.getenv("BRD2ENG_SIMULATE_TOOL_FAILURE") == "1"

    def create_issue(self, issue_type: str, summary: str, description: str, labels: list[str] | None = None,
                     parent: str | None = None, priority: str = "Medium") -> dict:
        if self._fail_once:
            self._fail_once = False
            raise TransientToolError("503 Service Unavailable (simulated)")
        self.counter += 1
        key = f"{self.project}-{self.counter}"
        payload = {"fields": {"project": {"key": self.project}, "issuetype": {"name": issue_type}, "summary": summary[:250],
                              "description": description, "labels": labels or [], "priority": {"name": priority},
                              **({"parent": {"key": parent}} if parent else {})}}
        resp = {"id": str(10000 + self.counter), "key": key, "self": f"https://mock.atlassian.net/rest/api/3/issue/{key}"}
        (self.dir / f"{key}.json").write_text(json.dumps({"request": payload, "response": resp}, indent=2))
        return resp
