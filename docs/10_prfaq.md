# 10. PRFAQ — BRD → Engineering

*Capstone Week 1, Exercise 1. Working-backwards narrative: written as if the product has launched internally.*

## Press release

**Engineering Managers turn a requirements document into a decision-ready engineering plan in minutes, not days**

*Internal launch, Engineering Productivity*

Today we are launching **BRD → Engineering**, a multi-agent assistant for Engineering Managers. An EM uploads a Business Requirements Document and, in under five minutes, receives an engineering pack: a phased plan, a schedule with p50/p80 estimates, a solution architecture, a scoped proof of concept and two to three scored tech-stack options.

Today, turning a BRD into a plan takes an EM and a tech lead two to five days of reading, estimating and drawing, and the result depends on who writes it. Contradictions, missing non-functional requirements and unrealistic deadlines are usually found weeks later, in sprint planning or in production.

BRD → Engineering grounds every claim in our own history: past BRDs, plan templates, architecture patterns, project timelines, engineering standards and the tech decision log. Seven specialist agents each do one job; a Critic agent scores their work against a rubric, checks that the schedule matches the architecture's complexity, and sends specific feedback back for up to two revision rounds. Every artifact carries a GREEN / AMBER / RED badge. Nothing is exported to Jira or shared as final until the EM approves it.

"On the fraud-alerts platform, the first draft said 23 weeks and fit our 24-week deadline. The Critic caught that the plan was sized for a simpler system than the architecture; the revised schedule was 36.5 weeks and the system opened an escalation ticket. It told me the date was wrong before my team did." — *pilot Engineering Manager (illustrative quote from the evaluation run E3)*

To get started, run `python run_pipeline.py <your_brd.md>` (offline by default, OpenAI or Anthropic when approved), or open the sample pack in `outputs/sample_run_E2/`.

## Customer FAQ (Engineering Managers)

**What do I get?** An engineering pack (Markdown + PDF), an HTML dashboard with scores per revision, Jira epics and stories (after approval) and an escalation ticket for anything the BRD gets wrong.

**Can I trust it?** Every claim cites the BRD requirement it serves and the knowledge-base source that supports it. Unsupported claims are marked as assumptions. The Critic's scores and issues are visible, and you approve or reject at the end.

**What if my BRD is vague or contradictory?** The system never guesses silently. Vague terms become flagged assumptions with a conservative default; contradictions and infeasible deadlines are escalated to you.

**Does it replace my tech lead?** No. It produces a reviewed first draft and surfaces risks early; the team still owns the decisions.

**Is my data safe?** Offline mode never leaves your machine. LLM mode only runs after you confirm the provider is approved for the data; PII and secrets are redacted first, and logs store hashes only.

## Internal FAQ (stakeholders, leadership)

**Why now?** LLMs plus retrieval over our own history make consistent first drafts feasible; the cost per BRD is roughly a dollar (see `11_strategy_and_plan.md`), against two to five EM/tech-lead days.

**How do we know it works?** 8-input eval set (5 BRDs from simple to complex, 3 guardrail attacks), 5 evaluation methods, 44/44 expected-outcome checks, Critic calibrated against a human reviewer (MAE 0.44 / 5; precision 1.0, recall 0.71 on "needs revision" verdicts). See `04_evaluation_report.md`.

**What are the risks?** Over-trust in AI plans (mitigated by badges, citations and the approval gate), BRD confidentiality with external LLMs (opt-in data boundary, redaction), and knowledge-base staleness (versioned index, owner per source type).

**Build or buy?** Build on open frameworks (LangGraph, LangChain) and a bought model API. Our differentiator is our own knowledge base and rubric, not the model. See `07_decision_justification.md`.

**What do you need from us?** A small pilot team, an LLM budget and three pilot EMs. See the leadership asks in `11_strategy_and_plan.md`.
