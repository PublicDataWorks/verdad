CREATE
OR REPLACE FUNCTION track_user_signups (origin TEXT) RETURNS jsonb SECURITY DEFINER AS $$
DECLARE
    current_user_id UUID;
    sign_up_date TIMESTAMP WITH TIME ZONE;
BEGIN
    -- Check if the user is authenticated
    current_user_id := auth.uid();
    IF current_user_id IS NULL THEN
        RAISE EXCEPTION 'Only logged-in users can call this function';
    END IF;

    -- Retrieve the sign_up_date from the auth.users table
    SELECT created_at INTO sign_up_date
    FROM auth.users
    WHERE id = current_user_id;

    -- Check if the sign_up_date is more than 1 hour ago
    IF sign_up_date < (NOW() - INTERVAL '1 hour') THEN
        RETURN jsonb_build_object(
            'status', 'failed',
            'message', 'Sign-up date is more than 1 hour ago'
        );
    END IF;

    -- Check if the record already exists
    IF EXISTS (SELECT 1 FROM profiles.user_signups WHERE id = current_user_id) THEN
        RETURN jsonb_build_object(
            'status', 'failed',
            'message', 'User has already signed up'
        );
    END IF;

    -- Insert into table profiles.user_signups
    INSERT INTO profiles.user_signups (id, origin)
    VALUES (current_user_id, origin);

    RETURN jsonb_build_object(
        'status', 'success',
        'message', 'Success'
    );
END;
$$ LANGUAGE plpgsql;
