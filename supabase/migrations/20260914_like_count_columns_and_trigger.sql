-- Repo drift: production already has snippets.like_count / dislike_count, the
-- update_snippet_like_count() trigger function and the update_like_count trigger on
-- user_like_snippets (see supabase/database/sql/like_count_migration.sql and
-- like_count_trigger.sql), but no migration file records them. This file is idempotent and
-- matches the live definitions captured 2026-09-14 (columns: integer NULL DEFAULT 0).
-- Safe to run on production (no-op there) and needed on fresh environments before
-- 20260914_get_snippets_include_count.sql, which reads like_count / dislike_count.

ALTER TABLE public.snippets ADD COLUMN IF NOT EXISTS like_count integer DEFAULT 0;
ALTER TABLE public.snippets ADD COLUMN IF NOT EXISTS dislike_count integer DEFAULT 0;

CREATE OR REPLACE FUNCTION public.update_snippet_like_count()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
BEGIN
    UPDATE snippets
    SET
        like_count = (
            SELECT COUNT(*)
            FROM user_like_snippets
            WHERE snippet = COALESCE(NEW.snippet, OLD.snippet)
            AND value = 1
        ),
        dislike_count = (
            SELECT COUNT(*)
            FROM user_like_snippets
            WHERE snippet = COALESCE(NEW.snippet, OLD.snippet)
            AND value = -1
        ),
        user_last_activity = NOW()
    WHERE id = COALESCE(NEW.snippet, OLD.snippet);

    RETURN NULL;
END;
$function$;

DROP TRIGGER IF EXISTS update_like_count ON public.user_like_snippets;
CREATE TRIGGER update_like_count
    AFTER INSERT OR DELETE OR UPDATE ON public.user_like_snippets
    FOR EACH ROW EXECUTE FUNCTION public.update_snippet_like_count();

-- Guarded backfill: only touches snippets whose counters disagree with user_like_snippets
-- (no-op on production, where the trigger has been maintaining them).
UPDATE public.snippets s
SET like_count = c.likes,
    dislike_count = c.dislikes
FROM (
    SELECT s2.id,
           COUNT(*) FILTER (WHERE uls.value = 1)  AS likes,
           COUNT(*) FILTER (WHERE uls.value = -1) AS dislikes
    FROM public.snippets s2
    LEFT JOIN public.user_like_snippets uls ON uls.snippet = s2.id
    GROUP BY s2.id
) c
WHERE c.id = s.id
  AND (COALESCE(s.like_count, 0) <> c.likes OR COALESCE(s.dislike_count, 0) <> c.dislikes);
