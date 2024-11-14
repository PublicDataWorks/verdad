CREATE
OR REPLACE FUNCTION get_roles () RETURNS TEXT[] SECURITY DEFINER AS $$
DECLARE
    current_user_id UUID;
    user_roles text[];
BEGIN
    -- Check if the user is authenticated
    current_user_id := auth.uid();
    IF current_user_id IS NULL THEN
        RAISE EXCEPTION 'Only logged-in users can call this function';
    END IF;

    -- Get the role names from the roles table by joining with user_roles
    SELECT array_agg(r.name) INTO user_roles
    FROM public.user_roles ur
    JOIN public.roles r ON ur.role = r.id
    WHERE ur."user" = current_user_id;

    RETURN COALESCE(user_roles, '{}');
END;
$$ LANGUAGE plpgsql;
