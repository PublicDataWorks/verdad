CREATE
OR REPLACE FUNCTION reset_password (new_password TEXT) RETURNS jsonb SECURITY DEFINER AS $$
DECLARE 
    current_user_id UUID;
BEGIN 
    -- Check if the user is authenticated 
    current_user_id := auth.uid(); 
    IF current_user_id IS NULL THEN 
        RAISE EXCEPTION 'Only logged-in users can call this function'; 
    END IF;

    -- Check minimum password length
    IF LENGTH(new_password) < 6 THEN
        RAISE EXCEPTION 'Password must be at least 6 characters long';
    END IF;

    -- Update the user's password in the auth.users table
    UPDATE auth.users 
    SET
        encrypted_password = crypt(new_password, gen_salt('bf')), 
        updated_at = now() AT TIME ZONE 'utc'
    WHERE id = current_user_id;

    RETURN jsonb_build_object('status', 'success', 'message', 'Password reset successfully'); 
END; 
$$ LANGUAGE plpgsql;
