"""
Prompt Rewriter Agent System

An autonomous system for improving prompts based on user feedback.
This module provides agents that analyze feedback, research claims,
propose prompt modifications, test changes, and deploy improvements.

Usage:
    from prompt_rewriter import PromptRewriterOrchestrator

    orchestrator = PromptRewriterOrchestrator()
    result = await orchestrator.process_feedback(feedback_event)
"""

from .models import (
    FeedbackEvent,
    FeedbackIntent,
    ProposalType,
    ProposalStatus,
    ResearchResult,
    PromptProposal,
    ExperimentResult,
    EvaluationResult,
)

__all__ = [
    "FeedbackEvent",
    "FeedbackIntent",
    "ProposalType",
    "ProposalStatus",
    "ResearchResult",
    "PromptProposal",
    "ExperimentResult",
    "EvaluationResult",
]

__version__ = "0.1.0"
