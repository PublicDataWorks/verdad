"""
Prompt Rewriter Agents

Each agent is responsible for a specific step in the prompt rewriting pipeline:

1. FeedbackIntakeAgent - Analyzes user feedback to classify intent
2. ResearchAgent - Conducts web research on disputed claims
3. ProposalWriterAgent - Generates structured prompt modification proposals
4. ExperimentRunnerAgent - Tests proposals against real snippets
5. EvaluationAgent - Decides whether to accept, refine, or reject proposals
6. SemanticSearchAgent - Finds similar snippets for broader testing
7. DeploymentAgent - Applies approved changes to production
"""

from .base import BaseAgent

__all__ = ["BaseAgent"]
