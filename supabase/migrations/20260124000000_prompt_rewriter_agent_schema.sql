-- Prompt Rewriter Agent Schema
-- Migration for the autonomous prompt improvement system

-- Create enum for proposal status tracking
CREATE TYPE prompt_rewrite_status AS ENUM (
    'pending',
    'analyzing_feedback',
    'researching',
    'writing_proposal',
    'experimenting',
    'evaluating',
    'refining',
    'awaiting_review',
    'deploying',
    'deployed',
    'rejected',
    'failed'
);

-- Create enum for feedback intent classification
CREATE TYPE feedback_intent AS ENUM (
    'factual_error',
    'missing_context',
    'wrong_category',
    'false_positive',
    'false_negative',
    'unclear_explanation',
    'translation_error',
    'other'
);

-- Create enum for proposal types
CREATE TYPE proposal_type AS ENUM (
    'factual_addition',
    'heuristic_update',
    'instruction_clarification',
    'category_addition',
    'category_removal',
    'prompt_rewrite'
);

-- Main table to track prompt rewrite proposals
CREATE TABLE prompt_rewrite_proposals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Trigger information
    triggered_by_feedback_type TEXT NOT NULL, -- 'thumbs_down', 'comment', 'label_dispute', 'manual'
    triggered_by_snippet_id UUID REFERENCES snippets(id),
    triggered_by_user_id UUID REFERENCES auth.users(id),
    triggered_by_comment_id TEXT, -- Liveblocks comment ID if applicable
    trigger_content TEXT, -- The actual comment/feedback text

    -- Feedback analysis results
    intent_classification feedback_intent,
    intent_confidence FLOAT,
    extracted_claim TEXT,
    user_correction TEXT,
    affected_prompt_stages INTEGER[], -- e.g., [1, 3] for Stage 1 and Stage 3
    priority TEXT DEFAULT 'medium', -- 'low', 'medium', 'high', 'critical'

    -- Research results
    research_started_at TIMESTAMPTZ,
    research_completed_at TIMESTAMPTZ,
    research_attempts INTEGER DEFAULT 0,
    research_summary TEXT,
    research_verdict TEXT, -- 'confirmed', 'debunked', 'inconclusive'
    research_confidence FLOAT,
    research_sources JSONB, -- Array of {url, title, credibility_score, excerpt, date}

    -- Proposal details
    proposal_type proposal_type,
    proposal_changes JSONB, -- Structured changes to apply
    expected_impact TEXT,

    -- Experiment configuration and results
    test_snippet_ids UUID[], -- Snippets used for testing
    control_snippet_ids UUID[], -- Control snippets for regression testing
    experiment_runs INTEGER DEFAULT 5,
    experiment_results JSONB,
    baseline_accuracy FLOAT,
    proposal_accuracy FLOAT,
    improvement_score FLOAT,
    consistency_score FLOAT,

    -- Evaluation
    evaluation_decision TEXT, -- 'accept', 'refine', 'reject'
    evaluation_confidence FLOAT,
    refinement_count INTEGER DEFAULT 0,
    max_refinements INTEGER DEFAULT 3,
    regression_detected BOOLEAN DEFAULT false,
    human_review_required BOOLEAN DEFAULT false,
    human_review_notes TEXT,
    reviewed_by UUID REFERENCES auth.users(id),
    reviewed_at TIMESTAMPTZ,

    -- Deployment
    deployed_at TIMESTAMPTZ,
    deployed_prompt_version_id UUID, -- Reference to prompt_versions if it exists
    rollback_at TIMESTAMPTZ,
    rollback_reason TEXT,

    -- Reprocessing tracking
    reprocess_snippet_count INTEGER DEFAULT 0,
    reprocess_completed_count INTEGER DEFAULT 0,

    -- Status and errors
    status prompt_rewrite_status DEFAULT 'pending',
    current_agent TEXT, -- Which agent is currently processing
    error_message TEXT,
    error_details JSONB,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for finding proposals by status
CREATE INDEX idx_prompt_rewrite_proposals_status ON prompt_rewrite_proposals(status);

-- Index for finding proposals by snippet
CREATE INDEX idx_prompt_rewrite_proposals_snippet ON prompt_rewrite_proposals(triggered_by_snippet_id);

-- Index for finding proposals by user
CREATE INDEX idx_prompt_rewrite_proposals_user ON prompt_rewrite_proposals(triggered_by_user_id);

-- Track individual experiment runs
CREATE TABLE prompt_experiment_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    proposal_id UUID NOT NULL REFERENCES prompt_rewrite_proposals(id) ON DELETE CASCADE,
    snippet_id UUID NOT NULL REFERENCES snippets(id),
    run_type TEXT NOT NULL, -- 'baseline' or 'proposal'
    run_number INTEGER NOT NULL,

    -- Input
    prompt_version TEXT, -- 'current' or 'proposed'
    prompt_content_hash TEXT, -- Hash of prompt used

    -- Output
    llm_output JSONB,
    llm_model TEXT,
    llm_tokens_used INTEGER,

    -- Evaluation
    is_correct BOOLEAN,
    correctness_confidence FLOAT,
    evaluation_notes TEXT,

    -- Timing
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    duration_ms INTEGER
);

CREATE INDEX idx_experiment_runs_proposal ON prompt_experiment_runs(proposal_id);

-- Track snippets queued for reprocessing
CREATE TABLE snippet_reprocess_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snippet_id UUID NOT NULL REFERENCES snippets(id),
    proposal_id UUID NOT NULL REFERENCES prompt_rewrite_proposals(id) ON DELETE CASCADE,

    -- Why this snippet was queued
    reason TEXT NOT NULL, -- 'semantic_similarity', 'same_category', 'manual'
    similarity_score FLOAT, -- If queued due to semantic similarity

    -- Processing
    priority INTEGER DEFAULT 0, -- Higher = process first
    status TEXT DEFAULT 'queued', -- 'queued', 'processing', 'completed', 'failed', 'skipped'

    -- Results
    original_output JSONB, -- Store original analysis for comparison
    reprocessed_output JSONB,
    output_changed BOOLEAN,
    improvement_detected BOOLEAN,

    -- Timestamps
    queued_at TIMESTAMPTZ DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,

    -- Errors
    error_message TEXT,
    retry_count INTEGER DEFAULT 0
);

CREATE INDEX idx_reprocess_queue_status ON snippet_reprocess_queue(status);
CREATE INDEX idx_reprocess_queue_proposal ON snippet_reprocess_queue(proposal_id);
CREATE INDEX idx_reprocess_queue_priority ON snippet_reprocess_queue(priority DESC, queued_at ASC);

-- Knowledge base for verified facts
-- This enables future RAG-based retrieval when the knowledge base grows large
CREATE TABLE knowledge_facts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Classification
    category TEXT NOT NULL, -- 'election', 'covid', 'immigration', 'climate', etc.
    subcategory TEXT,

    -- The fact itself
    claim TEXT NOT NULL, -- The misinformation claim
    fact TEXT NOT NULL, -- The verified truth
    fact_summary TEXT, -- One-line summary for quick injection

    -- Supporting evidence
    sources JSONB, -- Array of source objects
    confidence_score FLOAT DEFAULT 0.9,

    -- Provenance
    added_by_proposal_id UUID REFERENCES prompt_rewrite_proposals(id),
    added_by_user_id UUID REFERENCES auth.users(id),

    -- Version control
    version INTEGER DEFAULT 1,
    previous_version_id UUID REFERENCES knowledge_facts(id),

    -- Usage tracking
    times_used INTEGER DEFAULT 0,
    last_used_at TIMESTAMPTZ,
    effectiveness_score FLOAT, -- How often this fact leads to correct analysis

    -- Status
    is_active BOOLEAN DEFAULT true,
    reviewed_by UUID REFERENCES auth.users(id),
    reviewed_at TIMESTAMPTZ,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_knowledge_facts_category ON knowledge_facts(category);
CREATE INDEX idx_knowledge_facts_active ON knowledge_facts(is_active) WHERE is_active = true;

-- Full-text search on claims and facts
CREATE INDEX idx_knowledge_facts_claim_fts ON knowledge_facts USING GIN (to_tsvector('english', claim));
CREATE INDEX idx_knowledge_facts_fact_fts ON knowledge_facts USING GIN (to_tsvector('english', fact));

-- Track feedback that triggers the rewriter
-- This provides a unified view of all feedback types
CREATE TABLE user_feedback_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- What type of feedback
    feedback_type TEXT NOT NULL, -- 'thumbs_down', 'thumbs_up', 'comment', 'label_applied', 'label_removed', 'label_upvote'

    -- Context
    snippet_id UUID REFERENCES snippets(id),
    user_id UUID REFERENCES auth.users(id),

    -- Related entities
    comment_id TEXT, -- Liveblocks comment ID
    label_id UUID REFERENCES labels(id),
    snippet_label_id UUID REFERENCES snippet_labels(id),

    -- Content
    content TEXT, -- Comment text, label text, etc.
    sentiment TEXT, -- 'positive', 'negative', 'neutral'

    -- Processing
    processed BOOLEAN DEFAULT false,
    processed_at TIMESTAMPTZ,
    proposal_id UUID REFERENCES prompt_rewrite_proposals(id),

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_feedback_events_snippet ON user_feedback_events(snippet_id);
CREATE INDEX idx_feedback_events_unprocessed ON user_feedback_events(processed) WHERE processed = false;
CREATE INDEX idx_feedback_events_type ON user_feedback_events(feedback_type);

-- Agent execution logs for debugging and monitoring
CREATE TABLE prompt_rewriter_agent_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    proposal_id UUID REFERENCES prompt_rewrite_proposals(id) ON DELETE CASCADE,

    -- Which agent
    agent_name TEXT NOT NULL, -- 'feedback_intake', 'research', 'proposal_writer', etc.

    -- Execution details
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    duration_ms INTEGER,

    -- Input/Output
    input_data JSONB,
    output_data JSONB,

    -- LLM details if applicable
    llm_model TEXT,
    llm_prompt_tokens INTEGER,
    llm_completion_tokens INTEGER,
    llm_total_tokens INTEGER,
    llm_cost_usd FLOAT,

    -- Status
    status TEXT DEFAULT 'running', -- 'running', 'completed', 'failed', 'retrying'
    error_message TEXT,
    retry_count INTEGER DEFAULT 0
);

CREATE INDEX idx_agent_logs_proposal ON prompt_rewriter_agent_logs(proposal_id);
CREATE INDEX idx_agent_logs_agent ON prompt_rewriter_agent_logs(agent_name);

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_prompt_rewriter_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply timestamp triggers
CREATE TRIGGER prompt_rewrite_proposals_update_timestamp
    BEFORE UPDATE ON prompt_rewrite_proposals
    FOR EACH ROW EXECUTE FUNCTION update_prompt_rewriter_timestamp();

CREATE TRIGGER knowledge_facts_update_timestamp
    BEFORE UPDATE ON knowledge_facts
    FOR EACH ROW EXECUTE FUNCTION update_prompt_rewriter_timestamp();

-- Function to get next proposal to process
CREATE OR REPLACE FUNCTION get_next_pending_proposal()
RETURNS UUID AS $$
DECLARE
    proposal_id UUID;
BEGIN
    SELECT id INTO proposal_id
    FROM prompt_rewrite_proposals
    WHERE status = 'pending'
    ORDER BY
        CASE priority
            WHEN 'critical' THEN 1
            WHEN 'high' THEN 2
            WHEN 'medium' THEN 3
            WHEN 'low' THEN 4
        END,
        created_at ASC
    LIMIT 1
    FOR UPDATE SKIP LOCKED;

    IF proposal_id IS NOT NULL THEN
        UPDATE prompt_rewrite_proposals
        SET status = 'analyzing_feedback', updated_at = NOW()
        WHERE id = proposal_id;
    END IF;

    RETURN proposal_id;
END;
$$ LANGUAGE plpgsql;

-- Function to get next snippet to reprocess
CREATE OR REPLACE FUNCTION get_next_reprocess_snippet()
RETURNS TABLE(queue_id UUID, snippet_id UUID, proposal_id UUID) AS $$
BEGIN
    RETURN QUERY
    WITH selected AS (
        SELECT q.id, q.snippet_id, q.proposal_id
        FROM snippet_reprocess_queue q
        WHERE q.status = 'queued'
        ORDER BY q.priority DESC, q.queued_at ASC
        LIMIT 1
        FOR UPDATE SKIP LOCKED
    )
    UPDATE snippet_reprocess_queue q
    SET status = 'processing', started_at = NOW()
    FROM selected s
    WHERE q.id = s.id
    RETURNING q.id, q.snippet_id, q.proposal_id;
END;
$$ LANGUAGE plpgsql;

-- Grant permissions
GRANT ALL ON prompt_rewrite_proposals TO authenticated;
GRANT ALL ON prompt_rewrite_proposals TO service_role;
GRANT ALL ON prompt_experiment_runs TO authenticated;
GRANT ALL ON prompt_experiment_runs TO service_role;
GRANT ALL ON snippet_reprocess_queue TO authenticated;
GRANT ALL ON snippet_reprocess_queue TO service_role;
GRANT ALL ON knowledge_facts TO authenticated;
GRANT ALL ON knowledge_facts TO service_role;
GRANT ALL ON user_feedback_events TO authenticated;
GRANT ALL ON user_feedback_events TO service_role;
GRANT ALL ON prompt_rewriter_agent_logs TO authenticated;
GRANT ALL ON prompt_rewriter_agent_logs TO service_role;

-- Enable RLS
ALTER TABLE prompt_rewrite_proposals ENABLE ROW LEVEL SECURITY;
ALTER TABLE prompt_experiment_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE snippet_reprocess_queue ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_facts ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_feedback_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE prompt_rewriter_agent_logs ENABLE ROW LEVEL SECURITY;

-- RLS Policies - allow authenticated users to read, service_role for write
CREATE POLICY "Allow authenticated read on proposals" ON prompt_rewrite_proposals
    FOR SELECT TO authenticated USING (true);
CREATE POLICY "Allow service_role all on proposals" ON prompt_rewrite_proposals
    FOR ALL TO service_role USING (true);

CREATE POLICY "Allow authenticated read on experiment_runs" ON prompt_experiment_runs
    FOR SELECT TO authenticated USING (true);
CREATE POLICY "Allow service_role all on experiment_runs" ON prompt_experiment_runs
    FOR ALL TO service_role USING (true);

CREATE POLICY "Allow authenticated read on reprocess_queue" ON snippet_reprocess_queue
    FOR SELECT TO authenticated USING (true);
CREATE POLICY "Allow service_role all on reprocess_queue" ON snippet_reprocess_queue
    FOR ALL TO service_role USING (true);

CREATE POLICY "Allow authenticated read on knowledge_facts" ON knowledge_facts
    FOR SELECT TO authenticated USING (true);
CREATE POLICY "Allow service_role all on knowledge_facts" ON knowledge_facts
    FOR ALL TO service_role USING (true);

CREATE POLICY "Allow authenticated read on feedback_events" ON user_feedback_events
    FOR SELECT TO authenticated USING (true);
CREATE POLICY "Allow service_role all on feedback_events" ON user_feedback_events
    FOR ALL TO service_role USING (true);

CREATE POLICY "Allow authenticated read on agent_logs" ON prompt_rewriter_agent_logs
    FOR SELECT TO authenticated USING (true);
CREATE POLICY "Allow service_role all on agent_logs" ON prompt_rewriter_agent_logs
    FOR ALL TO service_role USING (true);

COMMENT ON TABLE prompt_rewrite_proposals IS 'Tracks autonomous prompt improvement proposals from user feedback';
COMMENT ON TABLE knowledge_facts IS 'Verified facts knowledge base for prompt augmentation';
COMMENT ON TABLE user_feedback_events IS 'Unified tracking of all user feedback that may trigger prompt rewrites';
