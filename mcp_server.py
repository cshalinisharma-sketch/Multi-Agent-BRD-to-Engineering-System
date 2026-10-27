#!/usr/bin/env python3
"""Stretch: MCP-style tool server (JSON-RPC 2.0 over stdio).

Exposes the BRD parser and knowledge-base retrieval as MCP tools so any MCP
client (Claude Desktop, an n8n MCP node, another agent) can call them:

  tools/list
  tools/call  {"name": "parse_brd", "arguments": {"path": "..."}}
  tools/call  {"name": "search_knowledge_base", "arguments": {"query": "...", "top_k": 4, "source_types": [...]}}

Implements the minimal MCP lifecycle (initialize, tools/list, tools/call) without
external dependencies. Register in an MCP client config as:
  {"command": "python", "args": ["/path/to/brd2eng/mcp_server.py"]}
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.config import PROFILES  # noqa: E402
from src.guardrails import quarantine_injections, redact, validate_file, validate_text  # noqa: E402
from src.parsing.brd_parser import parse_brd, read_text  # noqa: E402
from src.rag.retriever import Retriever, load_or_build  # noqa: E402

TOOLS = [
    {"name": "parse_brd", "description": "Validate, sanitise (PII redaction, injection quarantine) and parse a BRD file "
                                         "into structured requirements, constraints and flags.",
     "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "search_knowledge_base", "description": "Hybrid retrieval over past BRDs, plan templates, architecture "
                                                     "patterns, project timelines, standards and the tech decision log.",
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string"}, "top_k": {"type": "integer", "default": 4},
         "source_types": {"type": "array", "items": {"type": "string"}}}, "required": ["query"]}},
]

_retriever = None


def call(name, args):
    global _retriever
    if name == "parse_brd":
        p = Path(args["path"])
        validate_file(p)
        raw = read_text(p)
        validate_text(raw)
        clean, _ = redact(raw)
        clean, _, _ = quarantine_injections(clean)
        return parse_brd(p, clean).model_dump()
    if name == "search_knowledge_base":
        _retriever = _retriever or Retriever(load_or_build(), PROFILES["tuned"])
        hits = _retriever.search("mcp_client", args["query"], top_k=args.get("top_k", 4), source_types=args.get("source_types"))
        return [{"chunk_id": h.chunk_id, "score": h.score, "source_type": h.metadata.get("source_type"), "text": h.text}
                for h in hits]
    raise ValueError(f"unknown tool {name}")


def handle(msg):
    m, i = msg.get("method"), msg.get("id")
    if m == "initialize":
        return {"jsonrpc": "2.0", "id": i, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                                                       "serverInfo": {"name": "brd2eng", "version": "1.0"}}}
    if m == "tools/list":
        return {"jsonrpc": "2.0", "id": i, "result": {"tools": TOOLS}}
    if m == "tools/call":
        try:
            res = call(msg["params"]["name"], msg["params"].get("arguments", {}))
            return {"jsonrpc": "2.0", "id": i, "result": {"content": [{"type": "text", "text": json.dumps(res, default=str)}]}}
        except Exception as e:  # tool errors are returned, not raised (MCP convention)
            return {"jsonrpc": "2.0", "id": i, "result": {"isError": True, "content": [{"type": "text", "text": str(e)}]}}
    if i is None:  # notification (e.g. notifications/initialized)
        return None
    return {"jsonrpc": "2.0", "id": i, "error": {"code": -32601, "message": f"method not found: {m}"}}


def main():
    for line in sys.stdin:
        if not line.strip():
            continue
        out = handle(json.loads(line))
        if out is not None:
            sys.stdout.write(json.dumps(out) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
