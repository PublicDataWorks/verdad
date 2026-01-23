-- Load initial prompt versions from the prompts directory
-- This migration should be run after 01_local_schema.sql

-- Stage 1 Prompts
INSERT INTO prompt_versions (
    stage,
    version_number,
    llm_model,
    prompt_text,
    system_instruction,
    output_schema,
    is_active,
    change_explanation
) VALUES (
    'stage_1',
    1,
    'gemini-2.5-flash',
    -- prompt_text will need to be loaded from Stage_1_detection_prompt.md
    'This is a placeholder - prompts need to be loaded via script',
    'This is a placeholder - system instructions need to be loaded via script',
    '{"type": "object"}'::jsonb,
    TRUE,
    'Initial version from migration'
);

-- Gemini Timestamped Transcription Prompts
INSERT INTO prompt_versions (
    stage,
    version_number,
    llm_model,
    prompt_text,
    system_instruction,
    output_schema,
    is_active,
    change_explanation
) VALUES (
    'gemini_timestamped_transcription',
    1,
    'gemini-2.5-flash',
    -- prompt_text will need to be loaded from Gemini_timestamped_transcription_generation_prompt.md
    'This is a placeholder - prompts need to be loaded via script',
    NULL,
    '{"type": "object"}'::jsonb,
    TRUE,
    'Initial version from migration'
);

-- Stage 3 Prompts
INSERT INTO prompt_versions (
    stage,
    version_number,
    llm_model,
    prompt_text,
    system_instruction,
    output_schema,
    is_active,
    change_explanation
) VALUES (
    'stage_3',
    1,
    'gemini-2.5-flash',
    -- prompt_text will need to be loaded from Stage_3_analysis_prompt.md
    'This is a placeholder - prompts need to be loaded via script',
    'This is a placeholder - system instructions need to be loaded via script',
    '{"type": "object"}'::jsonb,
    TRUE,
    'Initial version from migration'
);

-- Stage 1 Heuristics
INSERT INTO heuristics (
    stage,
    version_number,
    content,
    is_active,
    change_explanation
) VALUES (
    'stage_1',
    1,
    'This is a placeholder - heuristics need to be loaded via script',
    TRUE,
    'Initial version from migration'
);

-- Stage 3 Heuristics
INSERT INTO heuristics (
    stage,
    version_number,
    content,
    is_active,
    change_explanation
) VALUES (
    'stage_3',
    1,
    'This is a placeholder - heuristics need to be loaded via script',
    TRUE,
    'Initial version from migration'
);
