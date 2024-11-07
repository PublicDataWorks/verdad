CREATE
OR REPLACE FUNCTION get_users_by_emails (emails TEXT[]) RETURNS jsonb SECURITY DEFINER AS $$
DECLARE
    current_user_id UUID;
    result jsonb;
BEGIN
    -- Check if the user is authenticated
    current_user_id := auth.uid();
    IF current_user_id IS NULL THEN
        RAISE EXCEPTION 'Only logged-in users can call this function';
    END IF;

    -- Return specified fields of users from the auth schema based on provided emails
    SELECT jsonb_agg(jsonb_build_object(
        'id', u.id,
        'email', u.email,
        'raw_user_meta_data', u.raw_user_meta_data - 'iss' - 'sub' - 'email_verified' - 'phone_verified' - 'provider_id' - 'custom_claims'
    ))
    INTO result
    FROM auth.users u
    WHERE u.email = ANY(emails);

    RETURN COALESCE(result, '[]'::jsonb);
END;
$$ LANGUAGE plpgsql;
