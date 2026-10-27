"""LangGraph orchestration of the 7-agent pipeline.

The same stages as the classic `Pipeline.run` loop, expressed as a LangGraph
`StateGraph`:

    START → ingest ─┬─(rejected)→ END
                    └→ route → plan_generator → schedule_estimator
                         → solution_architect → poc_planner → tech_stack_recommender
                         → critic ─┬─(decision == "revise")→ revise → critic   (≤ MAX_REVISIONS)
                                   └→ escalate → hitl → export → END
    any agent node ─(failed after retries)→ END

LangGraph owns the control flow and the routing state (status, Critic round,
decision, revision targets, HITL outcome). The HITL gate is a real
`interrupt()`: the graph pauses with a checkpoint (InMemorySaver, thread_id =
run_id) and resumes with `Command(resume=<EM decision>)`. Heavy run objects
(parsed BRD, artifacts, retriever, logger) live in the per-run context held by
the node closures, exactly as in the classic driver, so both engines write the
same outputs.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from .agents.base import RunContext
from .agents.critic import Critic
from .agents.orchestrator import WORKFLOWS, Pipeline, PipelineState

AGENT_SEQUENCE = WORKFLOWS["planning"] + WORKFLOWS["design"]


class GraphState(TypedDict, total=False):
    status: str             # started | parsed | routed | ok | rejected | failed:<agent> | approved... | completed
    round: int              # Critic revision round
    decision: str           # latest Critic decision: pass | revise | escalate
    to_revise: list[str]    # agents re-run in the next revise step (flagged + dependents)
    hitl: dict              # EM decision record


class GraphPipeline(Pipeline):
    engine = "langgraph"

    def build_graph(self, state: Optional[PipelineState] = None, ctx: Optional[RunContext] = None,
                    checkpointer=None):
        """Compile the graph for one run (state/ctx may be None when only drawing the graph)."""
        critic = Critic(ctx) if ctx else None
        jira = {}

        def ingest(s: GraphState) -> GraphState:
            return {"status": "parsed" if self.ingest(state, ctx) else "rejected"}

        def route(s: GraphState) -> GraphState:
            self.route(state, ctx)
            return {"status": "routed"}

        def agent_node(name: str):
            def node(s: GraphState) -> GraphState:
                return {"status": "ok" if self.run_stage_agent(state, ctx, name, 0) else f"failed:{name}"}
            return node

        def critic_node(s: GraphState) -> GraphState:
            rnd = s.get("round", 0)
            report = self.critic_round(state, critic, rnd)
            to_revise = self.revision_targets(state, report) if report.decision == "revise" else []
            return {"decision": report.decision, "to_revise": to_revise}

        def revise(s: GraphState) -> GraphState:
            rnd = s.get("round", 0) + 1
            for name in s["to_revise"]:
                if not self.run_stage_agent(state, ctx, name, rnd):
                    return {"status": f"failed:{name}", "round": rnd}
            return {"status": "ok", "round": rnd}

        def escalate(s: GraphState) -> GraphState:
            jira["client"] = self.escalate(state, ctx)
            self.write_draft(state)
            return {}

        def hitl(s: GraphState) -> GraphState:
            # Re-executed from the top on resume, so nothing before interrupt() may have side effects.
            d = self.hitl_auto(state) if self.opt.auto_approve else interrupt(self.hitl_payload(state))
            state.hitl = d
            self.logger.log("hitl", **d)
            return {"hitl": d, "status": d["decision"]}

        def export(s: GraphState) -> GraphState:
            self.complete(state, jira["client"])
            return {"status": "completed"}

        def after(next_node: str):
            return lambda s: END if s.get("status", "").startswith(("failed", "rejected")) else next_node

        g = StateGraph(GraphState)
        g.add_node("ingest", ingest)
        g.add_node("route", route)
        for name in AGENT_SEQUENCE:
            g.add_node(name, agent_node(name))
        g.add_node("critic", critic_node)
        g.add_node("revise", revise)
        g.add_node("escalate", escalate)
        g.add_node("hitl", hitl)
        g.add_node("export", export)

        g.add_edge(START, "ingest")
        g.add_conditional_edges("ingest", after("route"), ["route", END])
        g.add_edge("route", AGENT_SEQUENCE[0])
        for name, nxt in zip(AGENT_SEQUENCE, AGENT_SEQUENCE[1:] + ["critic"]):
            g.add_conditional_edges(name, after(nxt), [nxt, END])
        g.add_conditional_edges("critic", lambda s: "revise" if s["decision"] == "revise" else "escalate",
                                ["revise", "escalate"])
        g.add_conditional_edges("revise", after("critic"), ["critic", END])
        g.add_edge("escalate", "hitl")
        g.add_edge("hitl", "export")
        g.add_edge("export", END)
        return g.compile(checkpointer=checkpointer)

    def run(self, brd_path: Path) -> PipelineState:
        state, ctx = self.start(brd_path)
        graph = self.build_graph(state, ctx, checkpointer=InMemorySaver())
        # run_name / tags / metadata label the LangSmith trace when tracing is on (ids only, no BRD text)
        config = {"configurable": {"thread_id": state.run_id}, "run_name": f"brd2eng {state.run_id}",
                  "tags": [self.engine, self.llm.provider, self.opt.profile],
                  "metadata": {"run_id": state.run_id, "provider": self.llm.provider, "profile": self.opt.profile}}
        out = graph.invoke({"status": "started", "round": 0}, config)
        while out.get("__interrupt__"):          # HITL gate: ask the EM, then resume the paused graph
            payload = out["__interrupt__"][0].value
            out = graph.invoke(Command(resume=self.hitl_prompt(payload)), config)
        return state

    def mermaid(self) -> str:
        return self.build_graph().get_graph().draw_mermaid()
