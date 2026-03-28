"""
Configuration for the Prompt Rewriter Agent system.
"""

import os
from dataclasses import dataclass, field


@dataclass
class ResearchConfig:
    """Configuration for the Research Agent."""

    max_search_attempts: int = 5
    min_sources_required: int = 3
    retry_delay_seconds: float = 2.0
    retry_backoff_multiplier: float = 2.0
    credibility_threshold: float = 0.6
    timeout_seconds: int = 30

    # Source credibility weights
    source_weights: dict = field(
        default_factory=lambda: {
            "gov": 0.95,
            "edu": 0.90,
            "factcheck": 0.85,
            "peer_reviewed": 0.90,
            "major_news": 0.75,
            "other": 0.50,
        }
    )


@dataclass
class ExperimentConfig:
    """Configuration for the Experiment Runner Agent."""

    runs_per_variant: int = 5
    timeout_per_run_seconds: int = 120
    min_consistency_threshold: float = 0.80
    min_improvement_threshold: float = 0.10


@dataclass
class EvaluationConfig:
    """Configuration for the Evaluation Agent."""

    min_accuracy_improvement: float = 0.10
    max_regression_tolerance: float = 0.05
    confidence_threshold_for_auto_deploy: float = 0.90
    max_refinement_iterations: int = 3


@dataclass
class DeploymentConfig:
    """Configuration for the Deployment Agent."""

    max_snippets_to_reprocess: int = 1000
    reprocess_similarity_threshold: float = 0.75
    slack_webhook_url: str = ""
    notify_on_deploy: bool = True
    require_human_review_for_high_impact: bool = True
    high_impact_snippet_threshold: int = 100


@dataclass
class PromptRewriterConfig:
    """Main configuration for the Prompt Rewriter system."""

    # Sub-agent configs
    research: ResearchConfig = field(default_factory=ResearchConfig)
    experiment: ExperimentConfig = field(default_factory=ExperimentConfig)
    evaluation: EvaluationConfig = field(default_factory=EvaluationConfig)
    deployment: DeploymentConfig = field(default_factory=DeploymentConfig)

    # LLM settings
    default_llm_model: str = "gemini-2.5-pro"
    feedback_intake_model: str = "gemini-2.5-flash"
    research_model: str = "gemini-2.5-pro"
    proposal_writer_model: str = "gemini-2.5-pro"
    evaluator_model: str = "gemini-2.5-pro"

    # Prompt file paths (relative to project root)
    prompts_dir: str = "prompts"
    stage_1_heuristics_file: str = "Stage_1_heuristics.md"
    stage_3_heuristics_file: str = "Stage_3_heuristics.md"

    # Database
    supabase_url: str = ""
    supabase_key: str = ""

    # Feature flags
    auto_deploy_enabled: bool = False  # Require human review by default
    reprocess_on_deploy: bool = True
    log_all_llm_calls: bool = True

    @classmethod
    def from_env(cls) -> "PromptRewriterConfig":
        """Create config from environment variables."""
        config = cls()

        # Override with environment variables if set
        if url := os.getenv("SUPABASE_URL"):
            config.supabase_url = url
        if key := os.getenv("SUPABASE_SERVICE_ROLE_KEY"):
            config.supabase_key = key
        if slack := os.getenv("SLACK_WEBHOOK_URL"):
            config.deployment.slack_webhook_url = slack
        if model := os.getenv("PROMPT_REWRITER_LLM_MODEL"):
            config.default_llm_model = model

        # Feature flags from env
        if os.getenv("PROMPT_REWRITER_AUTO_DEPLOY", "").lower() == "true":
            config.auto_deploy_enabled = True

        return config


# Default configuration instance
default_config = PromptRewriterConfig.from_env()
