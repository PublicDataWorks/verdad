-- VER-445: hide the still-visible verdicts that deny the US capture of Maduro (WRITES).
-- EXECUTED 2026-11-02 ~23:40 UTC (Rajiv asked for the cleanup in-session): 50 rows in batch hide-2026-11-02-maduro.
-- Prepared 2026-11-02 from a read-only probe: 71 visible (not hidden), Processed, 95+ snippets recorded since
-- 2026-01-03 whose titles call a Maduro capture / removal / imprisonment claim false. Each explanation was read by
-- hand. The 49 below deny that the capture (2026-01-03), his imprisonment in New York, or the 32 Cuban deaths
-- happened; most were judged while pipeline KB entries called the capture a "viral hoax" (deactivated in cleanup 12
-- and VER-413) or while SearXNG was down (VER-390). Plus de8e8301, the landing-page snippet that calls Asfura's
-- 2025 Honduras win false using 2021 results.
-- Same mechanism as cleanup_2026_09/13: NULL-user rows in user_hide_snippets, one snippet_quarantine_log row each
-- (batch 'hide-2026-11-02-maduro'), snippets.status untouched. Reversible with the statement at the bottom.
--
-- NOT hidden (accept the capture, dispute timing / framing / a detail; re-review only, see
-- reports/2026-11-02_landing_page_false_positives.md): 16 snippets.
-- Left alone (correct verdicts): 7b58b881 (speaker denies the capture), b86d8ef7, d682c960, 368a05a2 (Cilia Flores
-- "interim president"), 17e515c3, 400948f2.
--
-- After Gemini quota returns (VER-438): requeue this batch for Stage 4 with
--   python src/scripts/reprocess_snippets.py --quarantine-batch hide-2026-11-02-maduro --stage 4 --execute
-- and restore (rollback statement, with ids set to those snippets) the ones whose new verdict is correct.

BEGIN;

WITH picked(snippet, reason) AS (VALUES
    ('b885c1f5-795f-4bb1-9bec-0970438b076e'::uuid, 'maduro_capture_denied'),
    ('7eb3407c-e60c-4d3a-8fff-ff0c7b122103'::uuid, 'maduro_capture_denied'),
    ('d30ad5f1-8d8f-4d95-b1d1-633c768a39bc'::uuid, 'maduro_capture_denied'),
    ('f0e73da5-7843-46bc-af6a-e70df2665a99'::uuid, 'maduro_capture_denied'),
    ('2b6bd41c-68fb-4a01-b983-dd6df7cc7d60'::uuid, 'maduro_capture_denied'),
    ('317628ea-de0c-4080-a5a2-fbecb792e513'::uuid, 'maduro_capture_denied'),
    ('0ac85f2b-2ed2-436f-a22c-ce01eec34c8b'::uuid, 'maduro_capture_denied'),
    ('2ac68ca0-c201-474e-bec3-604618cc2e24'::uuid, 'maduro_capture_denied'),
    ('dfb2a445-f958-47fa-9cca-fa0ffa3f7e7d'::uuid, 'maduro_capture_denied'),
    ('1018ab29-89f8-4a9d-a4c0-df0573932422'::uuid, 'maduro_capture_denied'),
    ('39df57c1-2853-4004-be07-93ae32b79bd2'::uuid, 'maduro_capture_denied'),
    ('e3a97cc1-6a4e-4a00-b761-f44ad5016d4f'::uuid, 'maduro_capture_denied'),
    ('ab402816-8943-4682-b660-aac502df9764'::uuid, 'maduro_capture_denied'),
    ('20f73033-ed05-487d-a6a8-e1fef10404d1'::uuid, 'maduro_capture_denied'),
    ('799a5e81-000c-4eb8-9145-97d21f3462af'::uuid, 'maduro_capture_denied'),
    ('4ef0c321-4d7b-471d-b652-7f528278414d'::uuid, 'maduro_capture_denied'),
    ('3fe3b28a-e5df-42c3-8f1e-ecd419d3b28a'::uuid, 'maduro_capture_denied'),
    ('91b07cf7-f353-4ffa-8538-f273d7d8076c'::uuid, 'maduro_capture_denied'),
    ('a6427fec-0571-4996-95ab-1ca8d191b849'::uuid, 'maduro_capture_denied'),
    ('bfb2aab9-6c18-47be-82ba-fecbe13b8036'::uuid, 'maduro_capture_denied'),
    ('7840f690-42a8-4228-bbe3-1197cdb6b437'::uuid, 'maduro_capture_denied'),
    ('b132c966-58e8-4d9f-b024-2e9bbb12f31e'::uuid, 'maduro_capture_denied'),
    ('c118214d-90dc-4593-aa5f-a586b867118f'::uuid, 'maduro_capture_denied'),
    ('9e4c9eff-e99b-4bc9-b9e6-db7955cbcd80'::uuid, 'maduro_capture_denied'),
    ('86b53afd-8df7-4c7c-ac2b-58c4c87a210c'::uuid, 'maduro_capture_denied'),
    ('0dc318ef-50d3-4ef6-96b2-276c63ed8664'::uuid, 'maduro_capture_denied'),
    ('e5e34b37-b89e-48a3-b1a3-6dd1eac4f4a9'::uuid, 'maduro_capture_denied'),
    ('366ec6af-2589-4f5c-8e50-5b47c33705af'::uuid, 'maduro_capture_denied'),
    ('3a6cc72b-af10-4f6f-bcc9-00dd1ca268c7'::uuid, 'maduro_capture_denied'),
    ('633202f0-6b20-44d4-b3f7-3586c0adb574'::uuid, 'maduro_capture_denied'),
    ('c6247f8b-ae29-4c63-a586-18a56084f0ae'::uuid, 'maduro_capture_denied'),
    ('ca7570bd-499b-452a-aeef-67f9661c4552'::uuid, 'maduro_capture_denied'),
    ('02facc9c-8856-4270-bf80-0ff359e712ff'::uuid, 'maduro_capture_denied'),
    ('4cc124e5-72c1-4342-91cb-05966fadd96e'::uuid, 'maduro_capture_denied'),
    ('e6861de7-c798-4e9e-9f1d-21d0644fc045'::uuid, 'maduro_capture_denied'),
    ('ca2a3638-735f-4020-a267-a4fa520d1643'::uuid, 'maduro_capture_denied'),
    ('745c5b9a-cfab-4090-ba76-8fb681452bdf'::uuid, 'maduro_capture_denied'),
    ('416bf516-2616-4b9f-97fa-c41933ffee8a'::uuid, 'maduro_capture_denied'),
    ('d4fcf654-563d-48b3-88af-3e870451cc1b'::uuid, 'maduro_capture_denied'),
    ('b2e27230-e826-45f0-9f83-2c21e18fa2ac'::uuid, 'maduro_capture_denied'),
    ('9e99893e-e8a2-47c3-94a9-4837bb048178'::uuid, 'maduro_capture_denied'),
    ('29516219-374d-4633-add3-51315a699421'::uuid, 'maduro_capture_denied'),
    ('4d6b2cea-cd9f-4d12-aae3-fc95b9dcc276'::uuid, 'maduro_capture_denied'),
    ('0f13ed70-7907-48d7-bf74-6239a4250fb7'::uuid, 'maduro_capture_denied'),
    ('0962b3f8-3906-44d6-8153-9b2791125488'::uuid, 'maduro_capture_denied'),
    ('b02e777e-c0a9-4b3a-b1c3-d0d00e14f1b7'::uuid, 'maduro_capture_denied'),
    ('74fadaae-9ec5-4c43-bfdd-6a626d1cce2d'::uuid, 'maduro_capture_denied'),
    ('7df35c8d-db39-43b2-87ea-c4e70147884f'::uuid, 'maduro_capture_denied'),
    ('889ebd49-ffd6-4a72-976e-f0dfdb5fd315'::uuid, 'maduro_capture_denied'),
    ('de8e8301-0aba-4e98-90f6-71cf15e430a1'::uuid, 'honduras_asfura')
),
todo AS (
    SELECT p.snippet, p.reason
    FROM picked p
    JOIN public.snippets s ON s.id = p.snippet AND s.status = 'Processed'
    WHERE NOT EXISTS (SELECT 1 FROM public.user_hide_snippets h WHERE h.snippet = p.snippet)
      AND NOT EXISTS (
          SELECT 1 FROM public.snippet_quarantine_log l
          WHERE l.snippet = p.snippet AND l.batch = 'hide-2026-11-02-maduro' AND l.restored_at IS NULL
      )
),
logged AS (
    INSERT INTO public.snippet_quarantine_log (snippet, previous_status, reason, batch)
    SELECT snippet, 'Processed', reason, 'hide-2026-11-02-maduro' FROM todo
    ON CONFLICT (snippet, batch) DO UPDATE
        SET previous_status = EXCLUDED.previous_status,
            reason = EXCLUDED.reason,
            quarantined_at = now(),
            restored_at = NULL
    RETURNING snippet
)
INSERT INTO public.user_hide_snippets (snippet, "user")
SELECT snippet, NULL FROM logged
ON CONFLICT (snippet) DO NOTHING;

COMMIT;

-- Verify:
-- SELECT reason, count(*) FROM public.snippet_quarantine_log WHERE batch = 'hide-2026-11-02-maduro' AND restored_at IS NULL GROUP BY 1;

-- Rollback. Set ids to the snippets to restore (one, several, or NULL for the whole batch):
-- WITH ids(snippet) AS (VALUES ('00000000-0000-0000-0000-000000000000'::uuid)),
-- r AS (
--   DELETE FROM public.user_hide_snippets h USING public.snippet_quarantine_log l
--   WHERE l.snippet = h.snippet AND l.batch = 'hide-2026-11-02-maduro' AND l.restored_at IS NULL AND h."user" IS NULL
--     AND (h.snippet IN (SELECT snippet FROM ids) OR EXISTS (SELECT 1 FROM ids WHERE snippet IS NULL))
--   RETURNING h.snippet)
-- UPDATE public.snippet_quarantine_log l SET restored_at = now() FROM r WHERE l.snippet = r.snippet AND l.batch = 'hide-2026-11-02-maduro';
