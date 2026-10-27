#!/usr/bin/env python3
"""Run the BRD-to-Engineering multi-agent pipeline on one BRD.

Examples
  python run_pipeline.py eval_dataset/brds/E2_merchant_dispute_portal.md            # interactive HITL gate
  python run_pipeline.py eval_dataset/brds/E2_merchant_dispute_portal.md --auto-approve
  python run_pipeline.py my_brd.docx --profile baseline --auto-approve
  OPENAI_API_KEY=... python run_pipeline.py my_brd.md --provider openai --allow-external
  python run_pipeline.py my_brd.md --engine classic        # plain-Python loop instead of LangGraph
  python run_pipeline.py --show-graph                       # print the LangGraph as Mermaid
"""
import argparse
import json
import os
import sys
from pathlib import Path

from src.agents.orchestrator import Pipeline
from src.config import RunOptions
from src.llm import ALLOW_EXTERNAL_ENV, ExternalContentNotAllowed, LLMClient
from src.rag.retriever import build_index

ENGINES = {"classic": Pipeline}
try:
    from src.graph import GraphPipeline
    ENGINES["langgraph"] = GraphPipeline
except ImportError:  # langgraph not installed -> classic engine only
    pass


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("brd", nargs="?", help="path to BRD (.md, .txt, .docx)")
    ap.add_argument("--profile", default="tuned", choices=["baseline", "tuned"], help="retrieval profile")
    ap.add_argument("--auto-approve", action="store_true", help="non-interactive HITL (RED is auto-rejected)")
    ap.add_argument("--no-export", action="store_true")
    ap.add_argument("--rebuild-index", action="store_true", help="re-chunk and re-embed the knowledge base")
    ap.add_argument("--label", default="", help="prefix for the run folder")
    ap.add_argument("--engine", default="langgraph" if "langgraph" in ENGINES else "classic", choices=sorted(ENGINES),
                    help="orchestration engine (default: langgraph when installed)")
    ap.add_argument("--show-graph", action="store_true", help="print the LangGraph workflow as Mermaid and exit")
    ap.add_argument("--provider", choices=["openai", "anthropic", "offline"],
                    help="LLM provider (default: BRD2ENG_LLM_PROVIDER, else detected from the API key, else offline)")
    ap.add_argument("--allow-external", action="store_true",
                    help=f"confirm the provider endpoint is approved for this BRD (same as {ALLOW_EXTERNAL_ENV}=1)")
    a = ap.parse_args()
    if a.show_graph:
        print(ENGINES["langgraph"](llm=LLMClient(provider="offline")).mermaid())
        return
    if a.rebuild_index or not a.brd:
        s = build_index()
        print(f"index built: {len(s.chunks)} chunks")
        if not a.brd:
            return
    if a.allow_external:
        os.environ[ALLOW_EXTERNAL_ENV] = "1"
    try:
        llm = LLMClient(provider=a.provider)
    except ExternalContentNotAllowed as e:
        sys.exit(f"✖ {e}")
    st = ENGINES[a.engine](RunOptions(profile=a.profile, auto_approve=a.auto_approve, export=not a.no_export, run_label=a.label), llm=llm).run(Path(a.brd))
    print(json.dumps({"status": st.status, "engine": a.engine, "provider": llm.provider, "backend": llm.backend,
                      "run_dir": str(st.run_dir),
                      "badge": st.critic_reports[-1].overall_badge if st.critic_reports else None,
                      "score": st.critic_reports[-1].overall_score if st.critic_reports else None,
                      "exports": st.exports, "errors": st.errors}, indent=2))


if __name__ == "__main__":
    main()
