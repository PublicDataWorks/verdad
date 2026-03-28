# Prompt Rewriter Agent: Implementation Roadmap

## Overview

This document breaks down the Prompt Rewriter Agent into concrete implementation tasks. Each task is sized for ~1-3 days of work and can be assigned as a Linear issue.

---

## Phase 1: Foundation

### 1.1 Database Schema Deployment
**Priority: Critical | Estimate: 1 day**

- [ ] Review migration file: `supabase/migrations/20260124000000_prompt_rewriter_agent_schema.sql`
- [ ] Test migration in local Supabase instance
- [ ] Deploy to staging environment
- [ ] Verify all tables, indexes, and functions created correctly
- [ ] Document any schema adjustments needed

**Files:**
- `supabase/migrations/20260124000000_prompt_rewriter_agent_schema.sql`

---

### 1.2 Feedback Event Capture - Thumbs Down
**Priority: Critical | Estimate: 2 days**

Add thumbs down button to snippet UI and capture events.

- [ ] Add `thumbs_down` column to snippets table (or use feedback_events)
- [ ] Create API endpoint: `POST /api/snippets/:id/feedback`
- [ ] Add thumbs down button to snippet card component
- [ ] Wire button to API endpoint
- [ ] Insert record into `user_feedback_events` table
- [ ] Test end-to-end flow

**Files to modify:**
- `web/src/components/SnippetCard.tsx` (or equivalent)
- `server/src/api/routes.ts`
- `server/src/services/feedbackService.ts` (new)

---

### 1.3 Feedback Event Capture - Comments
**Priority: High | Estimate: 1 day**

Extend existing Liveblocks webhook to capture comment events for processing.

- [ ] Modify `handleCommentCreated` to insert into `user_feedback_events`
- [ ] Extract snippet_id from Liveblocks room_id
- [ ] Classify comment sentiment (positive/negative/neutral)
- [ ] Test with sample comments

**Files to modify:**
- `server/src/api/webhooks.ts`
- `server/src/services/commentService.ts`

---

### 1.4 Basic Orchestrator Prefect Flow
**Priority: Critical | Estimate: 2 days**

Create the main Prefect flow that orchestrates the agent pipeline.

```python
@flow(name="Prompt Rewriter Agent")
async def prompt_rewriter_flow(proposal_id: UUID):
    # 1. Load proposal from database
    # 2. Run feedback intake agent
    # 3. Run research agent
    # 4. Run proposal writer agent
    # 5. Run experiment runner
    # 6. Run evaluation agent
    # 7. Deploy or refine
```

- [ ] Create `src/prompt_rewriter/main.py` with orchestrator flow
- [ ] Create `src/prompt_rewriter/__init__.py`
- [ ] Add Prefect deployment configuration
- [ ] Create manual trigger endpoint for testing
- [ ] Test with mock data

**Files to create:**
- `src/prompt_rewriter/main.py`
- `src/prompt_rewriter/config.py`
- `src/prompt_rewriter/models.py` (Pydantic models)

---

### 1.5 Database Utilities
**Priority: High | Estimate: 1 day**

Create database utility functions for the rewriter system.

- [ ] Add `prompt_rewriter_utils.py` with CRUD operations
- [ ] `create_proposal()` - insert new proposal
- [ ] `update_proposal_status()` - status transitions
- [ ] `get_pending_proposals()` - fetch proposals to process
- [ ] `log_agent_execution()` - insert agent logs
- [ ] Unit tests for all functions

**Files to create:**
- `src/prompt_rewriter/db_utils.py`
- `tests/prompt_rewriter/test_db_utils.py`

---

## Phase 2: Core Agents

### 2.1 Feedback Intake Agent
**Priority: Critical | Estimate: 3 days**

Analyzes user feedback to classify intent and extract actionable information.

**Input:** Raw feedback event (thumbs down, comment, etc.)
**Output:** Classified intent, extracted claim, affected prompts

- [ ] Create `src/prompt_rewriter/agents/feedback_intake.py`
- [ ] Design prompt for feedback classification
- [ ] Implement intent classification (factual_error, missing_context, etc.)
- [ ] Implement claim extraction from free-form text
- [ ] Determine which pipeline stages are affected
- [ ] Add confidence scoring
- [ ] Unit tests with sample feedback

**Prompt design considerations:**
```
Given this user feedback on a misinformation analysis:
- Snippet title: {title}
- Original analysis: {summary}
- User feedback: {feedback_content}

Classify the intent and extract any claims mentioned.
```

---

### 2.2 Research Agent
**Priority: Critical | Estimate: 4 days**

Conducts web research to verify or debunk claims.

**Key requirements:**
- Multi-source verification (minimum 3 sources)
- Source credibility scoring
- Retry logic with exponential backoff
- Fail noisily with detailed errors

- [ ] Create `src/prompt_rewriter/agents/research.py`
- [ ] Implement search query generation (multiple query variants)
- [ ] Integrate with existing Google Search grounding (from Stage 3)
- [ ] Add SearXNG integration as backup search
- [ ] Implement source credibility scoring
- [ ] Implement retry logic (max 5 attempts per search)
- [ ] Aggregate and synthesize results
- [ ] Return structured research output
- [ ] Integration tests with real searches

**Search strategy:**
```python
search_queries = [
    f"{claim} fact check",
    f"{claim} evidence",
    f"{claim} site:gov OR site:edu",
]
```

---

### 2.3 Proposal Writer Agent
**Priority: Critical | Estimate: 3 days**

Generates structured prompt modification proposals.

**Input:** Research results, feedback analysis
**Output:** Structured proposal with specific changes

- [ ] Create `src/prompt_rewriter/agents/proposal_writer.py`
- [ ] Design proposal output schema (JSON)
- [ ] Implement factual addition proposals
- [ ] Implement heuristic update proposals
- [ ] Generate clear rationale and expected impact
- [ ] Select test snippets from database
- [ ] Unit tests with sample research results

**Proposal schema:**
```json
{
  "type": "factual_addition",
  "target_prompts": ["Stage_1_heuristics.md"],
  "changes": [{
    "section": "## COVID-19 / Vaccines",
    "action": "append",
    "content": "- **Claim**: ...\n  **Fact**: ..."
  }],
  "expected_impact": "..."
}
```

---

### 2.4 Experiment Runner Agent
**Priority: High | Estimate: 4 days**

Tests proposals against real snippets with statistical rigor.

- [ ] Create `src/prompt_rewriter/agents/experiment_runner.py`
- [ ] Implement baseline run (current prompt, N times)
- [ ] Implement proposal run (modified prompt, N times)
- [ ] Create temporary prompt modification system
- [ ] Capture and store all LLM outputs
- [ ] Calculate accuracy metrics
- [ ] Implement consistency scoring
- [ ] Integration tests with real LLM calls

**Methodology:**
1. Run current prompt against test snippet (5 times)
2. Run modified prompt against test snippet (5 times)
3. Compare outputs, calculate improvement metrics

---

### 2.5 Evaluation Agent
**Priority: High | Estimate: 2 days**

Determines whether to accept, refine, or reject a proposal.

**Acceptance criteria:**
- Resolves originally reported issue
- No regressions on control snippets
- Improvement is statistically significant
- Consistency > 80%

- [ ] Create `src/prompt_rewriter/agents/evaluator.py`
- [ ] Implement acceptance criteria checks
- [ ] Implement regression detection
- [ ] Generate refinement suggestions if needed
- [ ] Flag for human review when uncertain
- [ ] Unit tests with sample experiment results

---

## Phase 3: Experimentation & Refinement

### 3.1 Semantic Search Agent
**Priority: High | Estimate: 2 days**

Finds similar snippets for broader testing and reprocessing.

- [ ] Create `src/prompt_rewriter/agents/semantic_search.py`
- [ ] Use existing Stage 5 embeddings
- [ ] Implement cosine similarity search via pgvector
- [ ] Filter by relevant disinformation categories
- [ ] Return ranked list of similar snippets
- [ ] Integration tests

**Query:**
```sql
SELECT id, title, 1 - (embedding <=> $1) as similarity
FROM snippets
WHERE status = 'Processed'
ORDER BY embedding <=> $1
LIMIT 50;
```

---

### 3.2 Refinement Loop
**Priority: Medium | Estimate: 2 days**

Iteratively improves proposals based on experiment feedback.

- [ ] Implement refinement iteration in orchestrator
- [ ] Cap at 3 refinement attempts
- [ ] Create refinement prompt for Proposal Writer
- [ ] Track refinement history in proposal record
- [ ] Escalate to human review after max refinements

---

### 3.3 Control Snippet Selection
**Priority: Medium | Estimate: 1 day**

Select control snippets to detect regressions.

- [ ] Implement control snippet selection logic
- [ ] Select snippets from different categories than the test snippet
- [ ] Store control snippet IDs in proposal
- [ ] Run experiments against control snippets
- [ ] Flag if control snippet outputs degrade

---

## Phase 4: Deployment & Reprocessing

### 4.1 Deployment Agent
**Priority: High | Estimate: 3 days**

Applies approved changes to production prompts.

- [ ] Create `src/prompt_rewriter/agents/deployer.py`
- [ ] Create new prompt version in `prompt_versions` table
- [ ] Update prompt files on disk (if using file-based storage)
- [ ] Set new version as active
- [ ] Add facts to `knowledge_facts` table
- [ ] Send Slack notification
- [ ] Create rollback capability

**Slack notification:**
```
New prompt improvement deployed!
- Type: Factual addition
- Category: COVID-19 / Vaccines
- Claim addressed: "Vaccines cause autism"
- Triggered by: user@example.com
- Snippets to reprocess: 23
```

---

### 4.2 Knowledge Base Injection
**Priority: High | Estimate: 2 days**

Inject knowledge base into prompts at runtime.

- [ ] Modify `constants.py` to load knowledge base
- [ ] Query active facts from `knowledge_facts` table
- [ ] Format facts for injection into prompts
- [ ] Add to Stage 1 and Stage 3 prompts
- [ ] Monitor prompt token count
- [ ] Add logging for knowledge base size

**Implementation:**
```python
def get_knowledge_base_section():
    facts = supabase.table('knowledge_facts').select('*').eq('is_active', True).execute()
    return format_facts_as_markdown(facts.data)
```

---

### 4.3 Reprocessing Queue Worker
**Priority: High | Estimate: 3 days**

Process snippets affected by prompt improvements.

- [ ] Create `src/prompt_rewriter/reprocess_worker.py`
- [ ] Create Prefect flow for reprocessing
- [ ] Fetch from `snippet_reprocess_queue`
- [ ] Run Stage 3 analysis with new prompts
- [ ] Compare before/after outputs
- [ ] Update snippet record
- [ ] Mark queue item complete
- [ ] Rate limiting to avoid overload

---

### 4.4 Reprocessing Queue Population
**Priority: Medium | Estimate: 1 day**

Populate the reprocessing queue after deployment.

- [ ] Query similar snippets via Semantic Search Agent
- [ ] Insert into `snippet_reprocess_queue` with priority
- [ ] Skip already-processed snippets
- [ ] Estimate and log total snippets to reprocess

---

## Phase 5: Monitoring & Polish

### 5.1 Admin Dashboard - Proposal Status
**Priority: Medium | Estimate: 3 days**

Dashboard to monitor proposal status and history.

- [ ] Create `/admin/proposals` page
- [ ] List all proposals with status
- [ ] Show proposal details (research, changes, experiments)
- [ ] Allow manual approval/rejection
- [ ] Show agent execution logs
- [ ] Filter by status, date, user

---

### 5.2 Human Review Interface
**Priority: Medium | Estimate: 2 days**

Interface for reviewing proposals flagged for human review.

- [ ] Create `/admin/proposals/:id/review` page
- [ ] Show full proposal context
- [ ] Show experiment results comparison
- [ ] Allow approve/reject with notes
- [ ] Allow editing proposed changes
- [ ] Trigger deployment on approval

---

### 5.3 Metrics & Monitoring
**Priority: Medium | Estimate: 2 days**

Track system health and effectiveness.

- [ ] Add Prometheus/Datadog metrics
- [ ] Track: proposals created, accepted, rejected
- [ ] Track: average time to resolution
- [ ] Track: reprocessing queue depth
- [ ] Track: knowledge base size
- [ ] Create alerts for failures

---

### 5.4 Slack Notifications
**Priority: Low | Estimate: 1 day**

Notify team of key events.

- [ ] Notification on new proposal created
- [ ] Notification on proposal awaiting human review
- [ ] Notification on proposal deployed
- [ ] Notification on proposal rejected/failed
- [ ] Daily summary of proposals

---

## Task Summary for Linear

| Issue Title | Priority | Estimate | Phase |
|------------|----------|----------|-------|
| Deploy prompt rewriter database schema | Critical | 1 day | 1 |
| Implement thumbs down feedback capture | Critical | 2 days | 1 |
| Extend comment webhook for feedback events | High | 1 day | 1 |
| Create orchestrator Prefect flow | Critical | 2 days | 1 |
| Create database utility functions | High | 1 day | 1 |
| Implement Feedback Intake Agent | Critical | 3 days | 2 |
| Implement Research Agent | Critical | 4 days | 2 |
| Implement Proposal Writer Agent | Critical | 3 days | 2 |
| Implement Experiment Runner Agent | High | 4 days | 2 |
| Implement Evaluation Agent | High | 2 days | 2 |
| Implement Semantic Search Agent | High | 2 days | 3 |
| Implement refinement loop | Medium | 2 days | 3 |
| Implement control snippet selection | Medium | 1 day | 3 |
| Implement Deployment Agent | High | 3 days | 4 |
| Implement knowledge base injection | High | 2 days | 4 |
| Create reprocessing queue worker | High | 3 days | 4 |
| Implement reprocess queue population | Medium | 1 day | 4 |
| Build admin proposals dashboard | Medium | 3 days | 5 |
| Build human review interface | Medium | 2 days | 5 |
| Add metrics and monitoring | Medium | 2 days | 5 |
| Add Slack notifications | Low | 1 day | 5 |

**Total estimated effort: ~42 days**

---

## Dependencies

```
Phase 1 (Foundation)
├── 1.1 Database Schema ─────────────────────────────────────────┐
├── 1.2 Thumbs Down Capture ──────────────────────────────────┐  │
├── 1.3 Comment Capture ──────────────────────────────────────┤  │
├── 1.4 Orchestrator Flow ◄───────────────────────────────────┤  │
└── 1.5 DB Utilities ◄────────────────────────────────────────┘  │
                                                                  │
Phase 2 (Core Agents)                                             │
├── 2.1 Feedback Intake Agent ◄───────────────────────────────────┤
├── 2.2 Research Agent ◄──────────────────────────────────────────┤
├── 2.3 Proposal Writer Agent ◄───────────────────────────────────┤
├── 2.4 Experiment Runner Agent ◄─────────────────────────────────┤
└── 2.5 Evaluation Agent ◄────────────────────────────────────────┘

Phase 3 (Experimentation)
├── 3.1 Semantic Search Agent
├── 3.2 Refinement Loop
└── 3.3 Control Snippet Selection

Phase 4 (Deployment)
├── 4.1 Deployment Agent
├── 4.2 Knowledge Base Injection
├── 4.3 Reprocessing Worker
└── 4.4 Queue Population

Phase 5 (Polish)
├── 5.1 Admin Dashboard
├── 5.2 Human Review Interface
├── 5.3 Metrics
└── 5.4 Slack Notifications
```

---

## Quick Start for Development

1. **Run migration locally:**
   ```bash
   supabase db reset
   # or
   supabase migration up
   ```

2. **Create agent module structure:**
   ```bash
   mkdir -p src/prompt_rewriter/agents
   touch src/prompt_rewriter/__init__.py
   touch src/prompt_rewriter/agents/__init__.py
   ```

3. **Start with orchestrator and one agent:**
   - Implement `main.py` orchestrator
   - Implement `feedback_intake.py` agent
   - Test end-to-end with mock data

4. **Iterate:**
   - Add agents one at a time
   - Test each integration point
   - Monitor logs and metrics
