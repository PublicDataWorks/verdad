# Prompt Rewriter Agent: Technical Proposal

## Executive Summary

VERDAD's current fact-checking relies primarily on web search during analysis. This approach has proven insufficient for reliably correcting misinformation—search results are inconsistent, may not surface authoritative sources, and leave critical knowledge gaps.

We propose a **Prompt Rewriter Agent** system that:
1. Dynamically augments prompts with verified factual information
2. Automatically triggers on user feedback (thumbs down, comments)
3. Researches, proposes, tests, and deploys prompt improvements
4. Reprocesses historical snippets affected by new knowledge

This system is designed to be **extensible** for future applications (Contextualizer/Docs-AI).

---

## Problem Statement

### Current Limitations

1. **Search Unreliability**: Stage 3's Google Search grounding returns inconsistent results. The same query may yield different sources at different times, leading to varying analysis quality.

2. **Knowledge Gaps**: The model lacks domain-specific knowledge about recurring misinformation narratives (e.g., specific election fraud claims, COVID vaccine myths with precise statistics).

3. **No Learning Loop**: User feedback (labels, comments, reactions) is captured but never feeds back into prompt improvements. The system doesn't learn from corrections.

4. **Manual Prompt Updates**: Currently, prompt changes require developer intervention—reading the prompt file, making edits, deploying. No systematic testing of changes.

---

## Proposed Solution

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          USER FEEDBACK TRIGGERS                              │
│         👎 Thumbs Down  │  💬 Comment  │  🏷️ Label Dispute  │  📝 Report   │
└─────────────────────────────┬───────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      PROMPT REWRITER AGENT ORCHESTRATOR                      │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  Feedback Intake Agent                                                │   │
│  │  • Parse feedback type and content                                    │   │
│  │  • Extract snippet context                                            │   │
│  │  • Classify intent (factual error, missing context, wrong category)  │   │
│  └───────────────────────────────────┬──────────────────────────────────┘   │
│                                      ▼                                       │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  Research Agent                                                       │   │
│  │  • Multi-source web research with retry logic                         │   │
│  │  • Source credibility scoring                                         │   │
│  │  • Fact extraction and verification                                   │   │
│  │  • Fail noisily with detailed error context                          │   │
│  └───────────────────────────────────┬──────────────────────────────────┘   │
│                                      ▼                                       │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  Proposal Writer Agent                                                │   │
│  │  • Generate structured prompt modification proposals                  │   │
│  │  • Specify: target prompt, section, addition type, content            │   │
│  │  • Include rationale and expected impact                             │   │
│  └───────────────────────────────────┬──────────────────────────────────┘   │
│                                      ▼                                       │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  Experiment Runner Agent                                              │   │
│  │  • Run proposal against original snippet (N times)                    │   │
│  │  • Compare outputs: before vs after                                   │   │
│  │  • Statistical significance testing                                   │   │
│  └───────────────────────────────────┬──────────────────────────────────┘   │
│                                      ▼                                       │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  Evaluation Agent                                                     │   │
│  │  • Assess if proposal resolves reported issue                         │   │
│  │  • Check for regressions on control snippets                          │   │
│  │  • Score improvement confidence                                       │   │
│  └───────────────────────────────────┬──────────────────────────────────┘   │
│                                      ▼                                       │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  Refinement Loop (if needed)                                          │   │
│  │  • Adjust proposal based on experiment results                        │   │
│  │  • Re-run experiments                                                 │   │
│  │  • Max 3 refinement iterations                                        │   │
│  └───────────────────────────────────┬──────────────────────────────────┘   │
│                                      ▼                                       │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  Semantic Search Agent                                                │   │
│  │  • Find historically similar snippets via embedding similarity        │   │
│  │  • Test proposal against similar snippets                             │   │
│  │  • Identify snippets for reprocessing                                 │   │
│  └───────────────────────────────────┬──────────────────────────────────┘   │
│                                      ▼                                       │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  Deployment Agent                                                     │   │
│  │  • Update prompt_versions table with new version                      │   │
│  │  • Set is_active=true for new prompt                                  │   │
│  │  • Queue historical snippets for reprocessing                         │   │
│  │  • Notify team via Slack                                              │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Knowledge Base Design

### Structure

The knowledge base is a **structured addition to existing prompts**, not a separate retrieval system. For now, we inject the entire knowledge base into prompts. If it grows large enough to warrant sharding, we can add RAG later.

```markdown
## Verified Facts Knowledge Base

### Election Claims
- **Claim**: "2020 election had millions of illegal votes"
  **Fact**: Multiple audits, court cases (60+), and election officials from both
  parties confirmed the 2020 election results. No evidence of widespread fraud
  was found. Source: CISA, state election officials, court records.

- **Claim**: "Dominion voting machines switched votes"
  **Fact**: Hand recounts in Georgia matched machine counts. Dominion machines
  produce paper ballots for verification. Multiple audits found no manipulation.
  Source: Georgia Secretary of State audit, CISA.

### COVID-19 / Vaccines
- **Claim**: "mRNA vaccines alter your DNA"
  **Fact**: mRNA cannot enter the cell nucleus where DNA is stored. mRNA is
  processed in the cytoplasm and degrades within days. Source: CDC, peer-reviewed
  studies in Nature.

### Immigration
- **Claim**: "Immigrants commit more crimes than citizens"
  **Fact**: Studies consistently show immigrants (including undocumented) commit
  crimes at lower rates than native-born citizens. Source: Cato Institute,
  multiple peer-reviewed criminology studies.
```

### Storage Options

**Option A: Inline in Prompt Files (Recommended for MVP)**
- Add `## Verified Facts Knowledge Base` section to `Stage_1_heuristics.md` and `Stage_3_heuristics.md`
- Simple to implement, version-controlled with git
- Easy to audit and review changes

**Option B: Separate Knowledge Base File**
- Create `prompts/knowledge_base.md`
- Imported into prompts via `constants.py`
- Better separation of concerns

**Option C: Database-Stored (Future)**
- Store facts in `knowledge_facts` table
- Query and inject at runtime
- Enables RAG when knowledge base grows large

---

## Detailed Agent Specifications

### 1. Feedback Intake Agent

**Purpose**: Parse and classify user feedback to determine appropriate action.

**Input**:
```json
{
  "feedback_type": "thumbs_down" | "comment" | "label_dispute",
  "snippet_id": "uuid",
  "user_id": "uuid",
  "content": "The analysis says this is false but it's actually true...",
  "metadata": { "label_id": "uuid", "thread_id": "string" }
}
```

**Output**:
```json
{
  "intent": "factual_error" | "missing_context" | "wrong_category" | "unclear",
  "confidence": 0.85,
  "extracted_claim": "Vaccine causes autism",
  "user_correction": "Multiple studies disprove this",
  "affected_prompts": ["stage_1", "stage_3"],
  "priority": "high" | "medium" | "low"
}
```

**Implementation Notes**:
- Uses LLM to parse free-form comments
- Maps label disputes to specific claim types
- Determines which pipeline stages need modification

---

### 2. Research Agent

**Purpose**: Conduct thorough, reliable web research on the disputed claim.

**Key Requirements**:
- **Multi-source verification**: Minimum 3 independent sources
- **Source credibility scoring**: Prioritize .gov, .edu, peer-reviewed
- **Retry logic**: Exponential backoff, max 5 retries per search
- **Fail noisily**: If research cannot be completed, halt pipeline with detailed error

**Search Strategy**:
```python
search_queries = [
    f"{claim} fact check",
    f"{claim} evidence",
    f"{claim} debunked OR confirmed",
    f"{claim} site:gov OR site:edu",
    f"{claim} peer reviewed study"
]
```

**Output**:
```json
{
  "claim": "Vaccine causes autism",
  "verdict": "false",
  "confidence": 0.95,
  "sources": [
    {
      "url": "https://www.cdc.gov/...",
      "title": "Vaccines Do Not Cause Autism",
      "credibility_score": 0.95,
      "relevant_excerpt": "...",
      "publication_date": "2023-01-15"
    }
  ],
  "summary": "Multiple large-scale studies...",
  "research_complete": true,
  "research_attempts": 2
}
```

---

### 3. Proposal Writer Agent

**Purpose**: Generate structured, testable prompt modification proposals.

**Proposal Types**:
1. **Factual Addition**: Add verified fact to knowledge base
2. **Heuristic Update**: Modify detection heuristics
3. **Instruction Clarification**: Improve analysis instructions
4. **Category Addition**: Add new disinformation category

**Output Schema**:
```json
{
  "proposal_id": "uuid",
  "type": "factual_addition",
  "target_prompts": ["Stage_1_heuristics.md", "Stage_3_heuristics.md"],
  "changes": [
    {
      "file": "Stage_1_heuristics.md",
      "section": "## COVID-19 / Vaccines",
      "action": "append",
      "content": "- **Claim**: \"Vaccines cause autism\"\n  **Fact**: ...",
      "rationale": "User reported incorrect analysis of autism-vaccine claim"
    }
  ],
  "expected_impact": "Snippets mentioning vaccine-autism link will correctly identify this as debunked misinformation",
  "test_snippet_ids": ["uuid1", "uuid2"]
}
```

---

### 4. Experiment Runner Agent

**Purpose**: Test proposals against real snippets with statistical rigor.

**Methodology**:
1. Run original prompt against test snippet (5 times)
2. Run modified prompt against test snippet (5 times)
3. Compare outputs for consistency and correctness
4. Calculate improvement metrics

**Output**:
```json
{
  "experiment_id": "uuid",
  "proposal_id": "uuid",
  "snippet_id": "uuid",
  "runs": {
    "baseline": [
      { "run_id": 1, "output": {...}, "correct": false },
      { "run_id": 2, "output": {...}, "correct": false }
    ],
    "proposal": [
      { "run_id": 1, "output": {...}, "correct": true },
      { "run_id": 2, "output": {...}, "correct": true }
    ]
  },
  "metrics": {
    "baseline_accuracy": 0.0,
    "proposal_accuracy": 1.0,
    "improvement": 1.0,
    "consistency": 0.95
  }
}
```

---

### 5. Evaluation Agent

**Purpose**: Determine if proposal should be accepted, refined, or rejected.

**Acceptance Criteria**:
- Resolves the originally reported issue
- No regressions on control snippets (unrelated topics)
- Improvement is statistically significant (p < 0.05)
- Consistency across runs > 80%

**Output**:
```json
{
  "decision": "accept" | "refine" | "reject",
  "confidence": 0.92,
  "issues_resolved": true,
  "regressions_detected": false,
  "refinement_suggestions": null,
  "human_review_required": false
}
```

---

### 6. Semantic Search Agent

**Purpose**: Find similar historical snippets that may benefit from the improvement.

**Implementation**:
- Use existing Stage 5 embeddings
- Cosine similarity search against snippet collection
- Filter by disinformation categories mentioned in proposal

**Output**:
```json
{
  "query_snippet_id": "uuid",
  "similar_snippets": [
    { "id": "uuid", "similarity": 0.92, "title": "..." },
    { "id": "uuid", "similarity": 0.87, "title": "..." }
  ],
  "reprocess_candidates": ["uuid1", "uuid2", "uuid3"],
  "estimated_impact": 47
}
```

---

### 7. Deployment Agent

**Purpose**: Apply approved changes and trigger reprocessing.

**Actions**:
1. Create new prompt version in `prompt_versions` table
2. Update prompt files (if using file-based storage)
3. Set new version as active
4. Queue similar snippets for Stage 3 reprocessing
5. Send Slack notification to team

---

## Database Schema Extensions

```sql
-- Track prompt rewrite proposals
CREATE TABLE prompt_rewrite_proposals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    triggered_by_feedback_type TEXT NOT NULL, -- 'thumbs_down', 'comment', 'label_dispute'
    triggered_by_snippet_id UUID REFERENCES snippets(id),
    triggered_by_user_id UUID REFERENCES auth.users(id),

    -- Feedback analysis
    intent_classification TEXT, -- 'factual_error', 'missing_context', etc.
    extracted_claim TEXT,
    user_correction TEXT,

    -- Research results
    research_summary JSONB,
    sources JSONB,
    research_completed_at TIMESTAMPTZ,

    -- Proposal details
    proposal_type TEXT, -- 'factual_addition', 'heuristic_update', etc.
    proposal_changes JSONB,
    expected_impact TEXT,

    -- Experiment results
    experiment_results JSONB,
    baseline_accuracy FLOAT,
    proposal_accuracy FLOAT,

    -- Evaluation
    evaluation_decision TEXT, -- 'accept', 'refine', 'reject'
    refinement_count INT DEFAULT 0,
    human_review_required BOOLEAN DEFAULT false,

    -- Deployment
    deployed_at TIMESTAMPTZ,
    prompt_version_id UUID REFERENCES prompt_versions(id),

    -- Status tracking
    status TEXT DEFAULT 'pending', -- 'pending', 'researching', 'proposing', 'experimenting', 'evaluating', 'deployed', 'rejected', 'failed'
    error_message TEXT,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Track reprocessing jobs spawned by proposals
CREATE TABLE snippet_reprocess_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snippet_id UUID REFERENCES snippets(id),
    proposal_id UUID REFERENCES prompt_rewrite_proposals(id),
    reason TEXT,
    priority INT DEFAULT 0,
    status TEXT DEFAULT 'queued', -- 'queued', 'processing', 'completed', 'failed'
    queued_at TIMESTAMPTZ DEFAULT NOW(),
    processed_at TIMESTAMPTZ
);

-- Knowledge base entries (for future RAG)
CREATE TABLE knowledge_facts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category TEXT NOT NULL, -- 'election', 'covid', 'immigration', etc.
    claim TEXT NOT NULL,
    fact TEXT NOT NULL,
    sources JSONB,
    added_by_proposal_id UUID REFERENCES prompt_rewrite_proposals(id),
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## Implementation Phases

### Phase 1: Foundation (Week 1-2)
- Database schema extensions
- Basic feedback intake pipeline (webhook → database)
- Manual trigger for rewriter agent (admin API endpoint)

### Phase 2: Core Agents (Week 3-4)
- Feedback Intake Agent
- Research Agent with retry logic
- Proposal Writer Agent
- Basic experiment runner (single snippet, single run)

### Phase 3: Experimentation & Evaluation (Week 5-6)
- Full Experiment Runner with statistical testing
- Evaluation Agent with acceptance criteria
- Refinement loop implementation

### Phase 4: Deployment & Reprocessing (Week 7-8)
- Semantic Search Agent integration
- Deployment Agent with prompt versioning
- Reprocessing queue and workers
- Slack notifications

### Phase 5: Polish & Monitoring (Week 9-10)
- Dashboard for proposal status tracking
- Metrics and monitoring
- Documentation and runbooks

---

## Extensibility for Future Projects

The Prompt Rewriter Agent is designed as a **reusable module**:

```python
class PromptRewriterAgent:
    """Base class for prompt rewriting workflows."""

    def __init__(self, config: RewriterConfig):
        self.feedback_intake = FeedbackIntakeAgent(config)
        self.research = ResearchAgent(config)
        self.proposal_writer = ProposalWriterAgent(config)
        self.experiment_runner = ExperimentRunnerAgent(config)
        self.evaluator = EvaluationAgent(config)
        self.deployer = DeploymentAgent(config)

    async def process_feedback(self, feedback: Feedback) -> ProposalResult:
        """Override in subclasses for custom workflows."""
        pass

class VerdadPromptRewriter(PromptRewriterAgent):
    """VERDAD-specific implementation."""

    async def process_feedback(self, feedback: Feedback) -> ProposalResult:
        # VERDAD-specific logic
        pass

class ContextualizerPromptRewriter(PromptRewriterAgent):
    """Contextualizer/Docs-AI implementation."""

    async def process_feedback(self, feedback: Feedback) -> ProposalResult:
        # Contextualizer-specific logic
        pass
```

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Bad proposals deployed | Require human review for high-impact changes |
| Research returns incorrect info | Multi-source verification, credibility scoring |
| Infinite refinement loops | Max 3 refinement iterations, then human escalation |
| Prompt bloat from too many facts | Monitor prompt token count, implement RAG when >8k tokens |
| Reprocessing overwhelms system | Priority queue, rate limiting, off-peak scheduling |

---

## Success Metrics

1. **Feedback Resolution Rate**: % of user feedback that results in deployed improvements
2. **Time to Resolution**: Hours from feedback to deployed fix
3. **Accuracy Improvement**: % improvement in correctness for affected claim types
4. **Regression Rate**: % of deployments that cause regressions (target: <5%)
5. **Knowledge Base Growth**: Facts added per week

---

## Conclusion

The Prompt Rewriter Agent transforms VERDAD from a static analysis system into a **continuously learning platform**. User feedback directly improves the system, creating a virtuous cycle where corrections make future analysis more accurate.

The architecture is intentionally modular and extensible, serving as the foundation for similar systems in Contextualizer/Docs-AI and other future projects.

---

## Appendix: Example Workflow

**Scenario**: User clicks thumbs down on a snippet about "vaccine microchips"

1. **Trigger**: Thumbs down webhook fires
2. **Feedback Intake**: Classifies as "factual_error", extracts claim "vaccines contain microchips"
3. **Research**: Finds CDC, FDA, Reuters fact-checks confirming this is false
4. **Proposal**: Suggests adding to knowledge base: "Claim: Vaccines contain microchips. Fact: Vaccines do not contain microchips. The largest component in vaccines is too small to be a tracking device."
5. **Experiment**: Runs modified prompt 5x against original snippet, achieves 100% correct detection
6. **Evaluation**: Accepts proposal (no regressions, statistically significant improvement)
7. **Deployment**: Updates prompt_versions, queues 23 similar snippets for reprocessing
8. **Notification**: Slack message: "New fact added to knowledge base: vaccine microchips claim"
