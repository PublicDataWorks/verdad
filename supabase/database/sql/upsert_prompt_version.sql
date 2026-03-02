DROP FUNCTION IF EXISTS upsert_prompt_version;

CREATE OR REPLACE FUNCTION upsert_prompt_version(
    p_stage TEXT,
    p_version TEXT,
    p_description TEXT,
    p_created_by TEXT,
    p_system_instruction TEXT DEFAULT NULL,
    p_user_prompt TEXT DEFAULT NULL,
    p_output_schema JSONB DEFAULT NULL,
    p_set_active BOOLEAN DEFAULT TRUE,
    p_sub_stage TEXT DEFAULT NULL
) RETURNS jsonb SECURITY INVOKER AS $$
DECLARE
    new_version_id UUID;
    result jsonb;
BEGIN
    -- Insert new version (always as inactive first)
    INSERT INTO public.prompt_versions (
        stage, sub_stage, version, description, created_by,
        system_instruction, user_prompt, output_schema, is_active
    ) VALUES (
        p_stage, p_sub_stage, p_version, p_description, p_created_by,
        p_system_instruction, p_user_prompt, p_output_schema, FALSE
    )
    RETURNING id INTO new_version_id;

    -- If set_active, atomically deactivate others and activate this one
    IF p_set_active THEN
        UPDATE public.prompt_versions
        SET is_active = FALSE
        WHERE stage = p_stage
          AND sub_stage IS NOT DISTINCT FROM p_sub_stage
          AND id != new_version_id
          AND is_active = TRUE;

        UPDATE public.prompt_versions
        SET is_active = TRUE
        WHERE id = new_version_id;
    END IF;

    -- Return the new version info
    SELECT jsonb_build_object(
        'id', id,
        'stage', stage,
        'sub_stage', sub_stage,
        'version', version,
        'is_active', is_active
    ) INTO result
    FROM public.prompt_versions
    WHERE id = new_version_id;

    RETURN result;
END;
$$ LANGUAGE plpgsql;
