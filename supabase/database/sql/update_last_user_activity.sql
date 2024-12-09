UPDATE snippets s
SET user_last_activity = (
    SELECT MAX(activity_time)
    FROM (
        -- Get label upvotes timestamps
        SELECT created_at as activity_time
        FROM label_upvotes
        WHERE snippet_label IN (
            SELECT id 
            FROM snippet_labels 
            WHERE snippet = s.id
        )
        
        UNION ALL
        
        -- Get likes timestamps
        SELECT created_at as activity_time
        FROM user_like_snippets
        WHERE snippet = s.id
        AND (value = 1 OR value = -1)
        
        UNION ALL

        SELECT created_at as activity_time
        FROM comments 
        WHERE room_id = s.id
        AND deleted_at is null
        
    ) all_activities
);
