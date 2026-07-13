"""
Prompt Rewriter Agent Orchestrator

This module contains the main Prefect flow that orchestrates the prompt
rewriting pipeline. It coordinates the execution of all agents in sequence
and handles state transitions.

Usage:
    # Trigger manually
    await prompt_rewriter_flow(proposal_id=uuid)

    # Or via the continuous worker
    prefect deployment run "Prompt Rewriter Agent/default"
"""

import logging
from uuid import UUID

from prefect import flow, task
from prefect.task_runners import ConcurrentTaskRunner

from .agents.feedback_intake import FeedbackIntakeAgent
from .config import PromptRewriterConfig, default_config
from .models import (
    EvaluationDecision,
    FeedbackAnalysis,
    FeedbackEvent,
    ProposalStatus,
    PromptProposal,
    ResearchResult,
)

logger = logging.getLogger(__name__)


@task(name="Load Proposal", retries=2, retry_delay_seconds=5)
async def load_proposal(proposal_id: UUID, config: PromptRewriterConfig) -> dict:
    """Load a proposal from the database."""
    from supabase import create_client

    client = create_client(config.supabase_url, config.supabase_key)

    result = (
        client.table("prompt_rewrite_proposals")
        .select("*")
        .eq("id", str(proposal_id))
        .single()
        .execute()
    )

    return result.data


@task(name="Update Proposal Status")
async def update_proposal_status(
    proposal_id: UUID,
    status: ProposalStatus,
    config: PromptRewriterConfig,
    additional_data: dict | None = None,
) -> None:
    """Update the status of a proposal in the database."""
    from supabase import create_client

    client = create_client(config.supabase_url, config.supabase_key)

    update_data = {"status": status.value}
    if additional_data:
        update_data.update(additional_data)

    client.table("prompt_rewrite_proposals").update(update_data).eq(
        "id", str(proposal_id)
    ).execute()


@task(name="Analyze Feedback")
async def analyze_feedback(
    proposal_data: dict,
    config: PromptRewriterConfig,
) -> FeedbackAnalysis:
    """Run the Feedback Intake Agent."""
    agent = FeedbackIntakeAgent(config)

    feedback = FeedbackEvent(
        id=UUID(proposal_data["id"]),
        feedback_type=proposal_data["triggered_by_feedback_type"],
        snippet_id=UUID(proposal_data["triggered_by_snippet_id"]),
        user_id=(
            UUID(proposal_data["triggered_by_user_id"])
            if proposal_data.get("triggered_by_user_id")
            else None
        ),
        content=proposal_data.get("trigger_content"),
        comment_id=proposal_data.get("triggered_by_comment_id"),
    )

    return await agent.execute(feedback, proposal_id=UUID(proposal_data["id"]))


@task(name="Research Claim")
async def research_claim(
    analysis: FeedbackAnalysis,
    proposal_id: UUID,
    config: PromptRewriterConfig,
) -> ResearchResult:
    """Run the Research Agent."""
    # TODO: Implement ResearchAgent
    # For now, return a placeholder
    logger.info(f"Research agent would research: {analysis.extracted_claim}")

    return ResearchResult(
        claim=analysis.extracted_claim or "Unknown claim",
        verdict="inconclusive",
        confidence=0.5,
        sources=[],
        summary="Research agent not yet implemented",
        research_complete=False,
    )


@task(name="Write Proposal")
async def write_proposal(
    analysis: FeedbackAnalysis,
    research: ResearchResult,
    proposal_id: UUID,
    config: PromptRewriterConfig,
) -> PromptProposal:
    """Run the Proposal Writer Agent."""
    # TODO: Implement ProposalWriterAgent
    # For now, return a placeholder
    logger.info("Proposal writer would generate prompt modifications")

    from .models import ProposalChange, ProposalType

    return PromptProposal(
        proposal_id=proposal_id,
        proposal_type=ProposalType.FACTUAL_ADDITION,
        target_prompts=["Stage_1_heuristics.md"],
        changes=[
            ProposalChange(
                file="Stage_1_heuristics.md",
                section="## Verified Facts",
                action="append",
                content=f"- Claim: {research.claim}\n  Fact: {research.summary}",
                rationale="Based on user feedback and research",
            )
        ],
        expected_impact="Improve detection accuracy for this claim type",
    )


@task(name="Run Experiments")
async def run_experiments(
    proposal: PromptProposal,
    config: PromptRewriterConfig,
) -> dict:
    """Run the Experiment Runner Agent."""
    # TODO: Implement ExperimentRunnerAgent
    logger.info("Experiment runner would test the proposal")

    return {
        "baseline_accuracy": 0.0,
        "proposal_accuracy": 0.8,
        "improvement": 0.8,
        "consistency_score": 0.9,
    }


@task(name="Evaluate Results")
async def evaluate_results(
    experiment_results: dict,
    config: PromptRewriterConfig,
) -> dict:
    """Run the Evaluation Agent."""
    # TODO: Implement EvaluationAgent
    improvement = experiment_results.get("improvement", 0)
    consistency = experiment_results.get("consistency_score", 0)

    if improvement >= config.evaluation.min_accuracy_improvement and consistency >= 0.8:
        decision = EvaluationDecision.ACCEPT
    elif improvement > 0:
        decision = EvaluationDecision.REFINE
    else:
        decision = EvaluationDecision.REJECT

    return {
        "decision": decision.value,
        "confidence": 0.8,
        "issues_resolved": improvement > 0,
        "regressions_detected": False,
        "human_review_required": not config.auto_deploy_enabled,
    }


@task(name="Deploy Changes")
async def deploy_changes(
    proposal: PromptProposal,
    config: PromptRewriterConfig,
) -> dict:
    """Run the Deployment Agent."""
    # TODO: Implement DeploymentAgent
    logger.info("Deployment agent would apply changes")

    return {
        "success": True,
        "prompt_version_id": None,
        "snippets_queued_for_reprocess": 0,
    }


@flow(
    name="Prompt Rewriter Agent",
    task_runner=ConcurrentTaskRunner(),
    description="Orchestrates the prompt rewriting pipeline from feedback to deployment",
)
async def prompt_rewriter_flow(
    proposal_id: UUID,
    config: PromptRewriterConfig | None = None,
) -> dict:
    """
    Main orchestrator flow for the Prompt Rewriter Agent system.

    This flow coordinates the execution of all agents:
    1. Load proposal from database
    2. Analyze feedback (Feedback Intake Agent)
    3. Research the disputed claim (Research Agent)
    4. Generate proposal (Proposal Writer Agent)
    5. Run experiments (Experiment Runner Agent)
    6. Evaluate results (Evaluation Agent)
    7. Deploy if approved (Deployment Agent)

    Args:
        proposal_id: UUID of the proposal to process
        config: Optional configuration override

    Returns:
        Dictionary with final status and results
    """
    config = config or default_config

    logger.info(f"Starting prompt rewriter flow for proposal {proposal_id}")

    # 1. Load proposal
    proposal_data = await load_proposal(proposal_id, config)

    if not proposal_data:
        logger.error(f"Proposal {proposal_id} not found")
        return {"status": "failed", "error": "Proposal not found"}

    # 2. Analyze feedback
    await update_proposal_status(
        proposal_id, ProposalStatus.ANALYZING_FEEDBACK, config
    )
    analysis = await analyze_feedback(proposal_data, config)

    await update_proposal_status(
        proposal_id,
        ProposalStatus.RESEARCHING,
        config,
        {
            "intent_classification": analysis.intent.value,
            "intent_confidence": analysis.intent_confidence,
            "extracted_claim": analysis.extracted_claim,
            "user_correction": analysis.user_correction,
            "priority": analysis.priority,
        },
    )

    # 3. Research the claim
    research = await research_claim(analysis, proposal_id, config)

    await update_proposal_status(
        proposal_id,
        ProposalStatus.WRITING_PROPOSAL,
        config,
        {
            "research_summary": research.summary,
            "research_sources": [s.model_dump() for s in research.sources],
        },
    )

    # 4. Generate proposal
    proposal = await write_proposal(analysis, research, proposal_id, config)

    await update_proposal_status(
        proposal_id,
        ProposalStatus.EXPERIMENTING,
        config,
        {
            "proposal_type": proposal.proposal_type.value,
            "proposal_changes": [c.model_dump() for c in proposal.changes],
            "expected_impact": proposal.expected_impact,
        },
    )

    # 5. Run experiments
    experiment_results = await run_experiments(proposal, config)

    await update_proposal_status(
        proposal_id,
        ProposalStatus.EVALUATING,
        config,
        {
            "experiment_results": experiment_results,
            "baseline_accuracy": experiment_results.get("baseline_accuracy"),
            "proposal_accuracy": experiment_results.get("proposal_accuracy"),
        },
    )

    # 6. Evaluate results
    evaluation = await evaluate_results(experiment_results, config)

    # 7. Handle evaluation decision
    if evaluation["decision"] == EvaluationDecision.ACCEPT.value:
        if evaluation["human_review_required"]:
            await update_proposal_status(
                proposal_id,
                ProposalStatus.AWAITING_REVIEW,
                config,
                {"evaluation_decision": evaluation["decision"]},
            )
            logger.info(f"Proposal {proposal_id} awaiting human review")
            return {"status": "awaiting_review", "evaluation": evaluation}
        else:
            # Auto-deploy
            await update_proposal_status(
                proposal_id, ProposalStatus.DEPLOYING, config
            )
            deployment = await deploy_changes(proposal, config)

            if deployment["success"]:
                await update_proposal_status(
                    proposal_id, ProposalStatus.DEPLOYED, config
                )
                logger.info(f"Proposal {proposal_id} deployed successfully")
                return {"status": "deployed", "deployment": deployment}
            else:
                await update_proposal_status(
                    proposal_id,
                    ProposalStatus.FAILED,
                    config,
                    {"error_message": "Deployment failed"},
                )
                return {"status": "failed", "error": "Deployment failed"}

    elif evaluation["decision"] == EvaluationDecision.REFINE.value:
        # TODO: Implement refinement loop
        await update_proposal_status(
            proposal_id,
            ProposalStatus.AWAITING_REVIEW,
            config,
            {
                "evaluation_decision": evaluation["decision"],
                "human_review_required": True,
            },
        )
        logger.info(f"Proposal {proposal_id} needs refinement, escalating to review")
        return {"status": "awaiting_review", "evaluation": evaluation}

    else:  # REJECT
        await update_proposal_status(
            proposal_id,
            ProposalStatus.REJECTED,
            config,
            {"evaluation_decision": evaluation["decision"]},
        )
        logger.info(f"Proposal {proposal_id} rejected")
        return {"status": "rejected", "evaluation": evaluation}


@flow(name="Process Pending Proposals")
async def process_pending_proposals(config: PromptRewriterConfig | None = None):
    """
    Continuous worker flow that processes pending proposals.

    This flow fetches the next pending proposal and processes it.
    It should be deployed as a continuous worker.
    """
    config = config or default_config

    from supabase import create_client

    client = create_client(config.supabase_url, config.supabase_key)

    # Get next pending proposal using the database function
    result = client.rpc("get_next_pending_proposal").execute()

    if not result.data:
        logger.info("No pending proposals to process")
        return {"status": "no_work"}

    proposal_id = UUID(result.data)
    logger.info(f"Processing proposal {proposal_id}")

    return await prompt_rewriter_flow(proposal_id, config)


# Entry point for manual testing
if __name__ == "__main__":
    import asyncio
    import sys

    if len(sys.argv) > 1:
        proposal_id = UUID(sys.argv[1])
        result = asyncio.run(prompt_rewriter_flow(proposal_id))
        print(f"Result: {result}")
    else:
        print("Usage: python -m prompt_rewriter.main <proposal_id>")
