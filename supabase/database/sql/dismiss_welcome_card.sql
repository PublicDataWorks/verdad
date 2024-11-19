CREATE
OR REPLACE FUNCTION dismiss_welcome_card () RETURNS jsonb SECURITY DEFINER AS $$ 
DECLARE
    current_user_id UUID;
    metadata jsonb;
BEGIN
    -- Check if the user is authenticated
    current_user_id := auth.uid();
    IF current_user_id IS NULL THEN
        RAISE EXCEPTION 'Only logged-in users can call this function';
    END IF;

    -- Get existing metadata and create new object
    SELECT COALESCE(raw_user_meta_data, '{}'::jsonb) || 
           jsonb_build_object('dismiss_welcome_card', true)
    INTO metadata
    FROM auth.users
    WHERE id = current_user_id;

    -- Update the user's profile in the auth.users table
    UPDATE auth.users
    SET
        raw_user_meta_data = metadata,
        updated_at = now() AT TIME ZONE 'utc'
    WHERE id = current_user_id;

    RETURN metadata;
END;
$$ LANGUAGE plpgsql;
