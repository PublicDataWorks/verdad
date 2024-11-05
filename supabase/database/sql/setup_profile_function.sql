CREATE
OR REPLACE FUNCTION setup_profile (
  first_name TEXT,
  last_name TEXT,
  avatar_url TEXT
) RETURNS jsonb SECURITY DEFINER AS $$
DECLARE
    current_user_id UUID;
    metadata jsonb;
    result jsonb;
BEGIN
    -- Check if the user is authenticated
    current_user_id := auth.uid();
    IF current_user_id IS NULL THEN
        RAISE EXCEPTION 'Only logged-in users can call this function';
    END IF;

    -- Create the metadata JSON object
    metadata := jsonb_build_object(
        'first_name', first_name,
        'last_name', last_name,
        'name', CONCAT(first_name, ' ', last_name),
        'full_name', CONCAT(first_name, ' ', last_name),
        'email', (SELECT email FROM auth.users WHERE id = current_user_id),
        'picture', avatar_url,
        'avatar_url', avatar_url
    );

    -- Update the user's profile in the auth.users table
    UPDATE auth.users
    SET
        raw_user_meta_data = metadata,
        updated_at = now() AT TIME ZONE 'utc'
    WHERE id = current_user_id;

    RETURN jsonb_build_object(
        'status', 'success',
        'message', 'Profile updated successfully'
    );
END;
$$ LANGUAGE plpgsql;
