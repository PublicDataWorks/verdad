"""
Pydantic models for the Prompt Rewriter Agent system.

These models define the data structures passed between agents
and stored in the database.
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class FeedbackIntent(str, Enum):
    """Classification of user feedback intent."""

    FACTUAL_ERROR = "factual_error"
    MISSING_CONTEXT = "missing_context"
    WRONG_CATEGORY = "wrong_category"
    FALSE_POSITIVE = "false_positive"
    FALSE_NEGATIVE = "false_negative"
    UNCLEAR_EXPLANATION = "unclear_explanation"
    TRANSLATION_ERROR = "translation_error"
    OTHER = "other"


class ProposalType(str, Enum):
    """Type of prompt modification proposal."""

    FACTUAL_ADDITION = "factual_addition"
    HEURISTIC_UPDATE = "heuristic_update"
    INSTRUCTION_CLARIFICATION = "instruction_clarification"
    CATEGORY_ADDITION = "category_addition"
    CATEGORY_REMOVAL = "category_removal"
    PROMPT_REWRITE = "prompt_rewrite"


class ProposalStatus(str, Enum):
    """Status of a prompt rewrite proposal."""

    PENDING = "pending"
    ANALYZING_FEEDBACK = "analyzing_feedback"
    RESEARCHING = "researching"
    WRITING_PROPOSAL = "writing_proposal"
    EXPERIMENTING = "experimenting"
    EVALUATING = "evaluating"
    REFINING = "refining"
    AWAITING_REVIEW = "awaiting_review"
    DEPLOYING = "deploying"
    DEPLOYED = "deployed"
    REJECTED = "rejected"
    FAILED = "failed"


class EvaluationDecision(str, Enum):
    """Decision from the evaluation agent."""

    ACCEPT = "accept"
    REFINE = "refine"
    REJECT = "reject"


class FeedbackEvent(BaseModel):
    """A user feedback event that may trigger the rewriter."""

    id: Optional[UUID] = None
    feedback_type: str  # 'thumbs_down', 'comment', 'label_dispute', 'manual'
    snippet_id: UUID
    user_id: Optional[UUID] = None
    content: Optional[str] = None  # Comment text or feedback details
    comment_id: Optional[str] = None  # Liveblocks comment ID
    label_id: Optional[UUID] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class FeedbackAnalysis(BaseModel):
    """Output from the Feedback Intake Agent."""

    intent: FeedbackIntent
    intent_confidence: float = Field(ge=0, le=1)
    extracted_claim: Optional[str] = None
    user_correction: Optional[str] = None
    affected_prompt_stages: list[int] = Field(default_factory=lambda: [1, 3])
    priority: str = "medium"  # 'low', 'medium', 'high', 'critical'
    reasoning: Optional[str] = None


class ResearchSource(BaseModel):
    """A source found during research."""

    url: str
    title: str
    credibility_score: float = Field(ge=0, le=1)
    excerpt: Optional[str] = None
    publication_date: Optional[str] = None
    source_type: Optional[str] = None  # 'gov', 'edu', 'news', 'factcheck', etc.


class ResearchResult(BaseModel):
    """Output from the Research Agent."""

    claim: str
    verdict: str  # 'confirmed', 'debunked', 'inconclusive'
    confidence: float = Field(ge=0, le=1)
    sources: list[ResearchSource] = Field(default_factory=list)
    summary: str
    research_complete: bool = True
    research_attempts: int = 1
    error_message: Optional[str] = None


class ProposalChange(BaseModel):
    """A single change to apply to a prompt file."""

    file: str  # e.g., 'Stage_1_heuristics.md'
    section: Optional[str] = None  # e.g., '## COVID-19 / Vaccines'
    action: str  # 'append', 'replace', 'insert_before', 'insert_after'
    content: str
    rationale: str


class PromptProposal(BaseModel):
    """Output from the Proposal Writer Agent."""

    proposal_id: Optional[UUID] = None
    proposal_type: ProposalType
    target_prompts: list[str]  # List of prompt files to modify
    changes: list[ProposalChange]
    expected_impact: str
    test_snippet_ids: list[UUID] = Field(default_factory=list)
    control_snippet_ids: list[UUID] = Field(default_factory=list)


class ExperimentRun(BaseModel):
    """A single experiment run result."""

    run_id: int
    run_type: str  # 'baseline' or 'proposal'
    snippet_id: UUID
    llm_output: dict
    is_correct: bool
    correctness_confidence: float = Field(ge=0, le=1)
    duration_ms: int


class ExperimentResult(BaseModel):
    """Output from the Experiment Runner Agent."""

    experiment_id: Optional[UUID] = None
    proposal_id: UUID
    snippet_id: UUID
    baseline_runs: list[ExperimentRun] = Field(default_factory=list)
    proposal_runs: list[ExperimentRun] = Field(default_factory=list)
    baseline_accuracy: float = Field(ge=0, le=1)
    proposal_accuracy: float = Field(ge=0, le=1)
    improvement: float  # Can be negative if regression
    consistency_score: float = Field(ge=0, le=1)


class EvaluationResult(BaseModel):
    """Output from the Evaluation Agent."""

    decision: EvaluationDecision
    confidence: float = Field(ge=0, le=1)
    issues_resolved: bool
    regressions_detected: bool = False
    refinement_suggestions: Optional[str] = None
    human_review_required: bool = False
    reasoning: str


class SemanticSearchResult(BaseModel):
    """Output from the Semantic Search Agent."""

    query_snippet_id: UUID
    similar_snippets: list[dict]  # [{id, similarity, title}, ...]
    reprocess_candidates: list[UUID]
    estimated_impact: int


class DeploymentResult(BaseModel):
    """Output from the Deployment Agent."""

    success: bool
    prompt_version_id: Optional[UUID] = None
    knowledge_fact_ids: list[UUID] = Field(default_factory=list)
    snippets_queued_for_reprocess: int = 0
    error_message: Optional[str] = None


class AgentLogEntry(BaseModel):
    """Log entry for agent execution."""

    agent_name: str
    proposal_id: UUID
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    status: str = "running"  # 'running', 'completed', 'failed', 'retrying'
    input_summary: Optional[str] = None
    output_summary: Optional[str] = None
    llm_tokens_used: Optional[int] = None
    error_message: Optional[str] = None
