"""Central configuration: thresholds, retrieval profiles, model routing."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KB_DIR = ROOT / "knowledge_base"
INDEX_DIR = ROOT / ".index"
OUTPUT_DIR = ROOT / "outputs"
EVAL_DIR = ROOT / "eval_dataset"

# ---------------------------------------------------------------- thresholds
GROUNDEDNESS_MIN = 0.75     # >= 75% of claims carry a citation
COMPLETENESS_MIN = 1.00     # 100% of routed requirements addressed
CONSISTENCY_MAX = 0         # 0 contradictions
ACTIONABILITY_MIN = 4.0     # judge score >= 4/5
MAX_REVISIONS = 2           # Critic revision cap
AGENT_MAX_RETRIES = 2       # per-agent retry on exception / contract violation

ALLOWED_EXTENSIONS = {".md", ".txt", ".docx"}
MAX_FILE_BYTES = 2_000_000
MIN_BRD_CHARS = 300


@dataclass(frozen=True)
class RetrievalProfile:
    """Two profiles let us measure the effect of RAG tuning (eval report §7D)."""
    name: str
    top_k: int
    use_metadata_filters: bool
    hybrid: bool              # dense (LSA) + sparse (TF-IDF) fusion
    sim_threshold: float      # minimum fused similarity to keep a chunk
    cite_threshold: float     # minimum item<->chunk similarity to attach a citation


PROFILES = {
    "baseline": RetrievalProfile("baseline", top_k=2, use_metadata_filters=False, hybrid=False,
                                 sim_threshold=0.05, cite_threshold=0.20),
    "tuned": RetrievalProfile("tuned", top_k=5, use_metadata_filters=True, hybrid=True,
                              sim_threshold=0.08, cite_threshold=0.12),
}

# Metadata filters per agent (source_type allow-list). Used when profile.use_metadata_filters.
AGENT_SOURCE_FILTERS = {
    "plan_generator": ["plan_template", "past_brd", "project_timeline", "standards"],
    "schedule_estimator": ["project_timeline", "plan_template", "past_brd"],
    "solution_architect": ["architecture_pattern", "standards", "past_brd", "tech_decision"],
    "poc_planner": ["past_brd", "plan_template", "architecture_pattern", "standards"],
    "tech_stack_recommender": ["tech_decision", "standards", "past_brd"],
}

# ---------------------------------------------------------------- model routing
# Small model for parsing/classification/judging, larger for reasoning-heavy design.
MODEL_ROUTING = {
    "anthropic": {
        "small": os.getenv("BRD2ENG_SMALL_MODEL", "claude-haiku-5-5"),
        "large": os.getenv("BRD2ENG_LARGE_MODEL", "claude-sonnet-5-5"),
    },
    "openai": {
        "small": os.getenv("BRD2ENG_SMALL_MODEL", "gpt-4.1-mini"),
        "large": os.getenv("BRD2ENG_LARGE_MODEL", "gpt-4.1"),
    },
}
AGENT_MODEL_TIER = {
    "orchestrator": "small",
    "plan_generator": "large",
    "schedule_estimator": "small",
    "solution_architect": "large",
    "poc_planner": "small",
    "tech_stack_recommender": "large",
    "critic": "small",
    "judge": "large",
}

# Indicative prices (USD per 1M tokens) for cost tracking; edit for your contract.
PRICE_PER_MTOK = {"small": (1.0, 5.0), "large": (3.0, 15.0), "offline": (0.0, 0.0)}


@dataclass
class RunOptions:
    profile: str = "tuned"
    auto_approve: bool = False
    export: bool = True
    run_label: str = ""
    extra: dict = field(default_factory=dict)
