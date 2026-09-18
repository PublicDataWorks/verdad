-- cleanup_2026_09 / step 13: hide the still-visible post-cutoff false positives (WRITES; needs Rajiv's go).
--
-- Prepared 2026-09-17 from a read-only probe (VER-338, Tamoa's Feedback #6/#7). 73 snippets scored 95+,
-- verified_false, publicly visible, whose verdict denies an event that did happen: de la Espriella and Fujimori
-- as presidents, Flávio Bolsonaro's candidacy, Maduro's capture and Delcy Rodríguez, Charlie Kirk's death, Rubio's
-- Sep 2026 tour, Orbán's April defeat, the 2026-08-10 Colombia earthquake, al-Sharaa's White House visit.
-- Same mechanism as the 09-15 batches: NULL-user rows in user_hide_snippets, one snippet_quarantine_log row each
-- (batch 'hide-2026-09-17-postcutoff', reason = topic cluster), snippets.status untouched. Reversible with the
-- statement at the bottom. 04b_snapshot_analyses.sql must run for this batch before any reprocessing.
--
-- NOT included (need an analyst look, may be real catches): the Colombia-earthquake benefit-concert scam ads,
-- the "distorted timeline of real post-Assad events" Syria reports.

BEGIN;

WITH picked(snippet, reason) AS (VALUES
    ('02735077-6723-4e9b-8457-6c9089165a1e'::uuid, 'latam_presidents'),
    ('02b33e98-445d-4ae1-9f10-68e037c4df8c'::uuid, 'latam_presidents'),
    ('039190c0-836e-4867-9bce-b2e05d25b250'::uuid, 'latam_presidents'),
    ('0857990d-c3ca-4af0-aba0-9155cddcf907'::uuid, 'latam_presidents'),
    ('0b751385-96d2-4578-9439-ed79d0d28084'::uuid, 'latam_presidents'),
    ('0b96c0c8-07f2-4f50-b7da-ffa8722e10f6'::uuid, 'kirk'),
    ('0c91142e-3253-4595-a13d-3a107e826870'::uuid, 'sharaa'),
    ('0ed4aa9a-720f-43d2-ac9b-9b3320e16d45'::uuid, 'latam_presidents'),
    ('10a2c210-918c-4a73-b5c5-c6d77e54e934'::uuid, 'latam_presidents'),
    ('15d30396-1227-46c8-8e32-e052f8f01968'::uuid, 'orban'),
    ('1c6b06df-618f-4b47-8951-c3c135820df3'::uuid, 'latam_presidents'),
    ('1ca79347-60e6-4d39-8ac9-2e579037c24f'::uuid, 'latam_presidents'),
    ('1d23aeca-d00a-4ba4-8f35-f67654e48146'::uuid, 'kirk'),
    ('258c447b-48b0-4ed5-84e5-a3d07983f9f7'::uuid, 'sharaa'),
    ('274e6cf0-1b37-4d82-ae57-f3b40eec804a'::uuid, 'sharaa'),
    ('2bb4119f-a5d9-4ac6-a7ab-1a368a1563f6'::uuid, 'maduro_capture'),
    ('2cd32339-b68e-4d85-b606-89f0bbe2099e'::uuid, 'latam_presidents'),
    ('2dfaa786-8a97-4cc4-8ecf-5599473450b6'::uuid, 'latam_presidents'),
    ('3298224d-555e-47d3-9fe4-21ebb3dbad5d'::uuid, 'latam_presidents'),
    ('351456dd-7975-44e3-9179-e538bb00ece8'::uuid, 'latam_presidents'),
    ('3b100305-1cee-4794-ace3-c0402fd64e27'::uuid, 'kirk'),
    ('3c4696b1-f48a-4b64-b4d6-a4e3466a7e0d'::uuid, 'latam_presidents'),
    ('3def66b1-2031-4ead-982f-e7bf834aa112'::uuid, 'maduro_capture'),
    ('411269b2-c908-4a1c-b415-1ea294e75da7'::uuid, 'latam_presidents'),
    ('4ff34835-73fe-42b3-be8c-d561754e45c8'::uuid, 'rubio_tour'),
    ('5040b57d-79fe-4bba-9f6e-8fdc214cd491'::uuid, 'latam_presidents'),
    ('50a1cea7-23a1-4a4d-bf65-fca7f6f8bdc9'::uuid, 'kirk'),
    ('57915a11-0846-415c-87d9-ee88d06d93e5'::uuid, 'kirk'),
    ('57ac943f-9886-48e5-bc82-89e03a4b5225'::uuid, 'latam_presidents'),
    ('59708e0d-8a74-4483-91d5-1db5628417cf'::uuid, 'latam_presidents'),
    ('5bcf1eaa-d54d-4dc5-b7e8-0d2eba3906b3'::uuid, 'latam_presidents'),
    ('5f591597-7e2f-4aca-8f61-ed697b66b98d'::uuid, 'sharaa'),
    ('616d511e-6430-4813-ad55-e64add111df8'::uuid, 'latam_presidents'),
    ('61f7f8e7-edf1-46df-a4c9-ebb715ddb59e'::uuid, 'latam_presidents'),
    ('66f4b51f-45d3-4c53-9eb8-afa130fb015d'::uuid, 'latam_presidents'),
    ('6dddb89d-37e2-474a-8bb0-6c75ae45fc2a'::uuid, 'latam_presidents'),
    ('6e3f5172-6867-45b9-8690-dc38782092fe'::uuid, 'latam_presidents'),
    ('7685b992-e72c-4aaa-98f9-7f875af7190d'::uuid, 'colombia_quake'),
    ('76df4b6a-c3ac-4c70-9082-bdca67e0190d'::uuid, 'maduro_capture'),
    ('773ffeb8-d206-4f87-8ec2-d5bf255d0af5'::uuid, 'latam_presidents'),
    ('777333c3-dc77-4c10-a45c-6df72222ea35'::uuid, 'maduro_capture'),
    ('799de49d-7b4c-4003-a4a0-071ef661e7bc'::uuid, 'delcy'),
    ('8463960c-eac6-4fb4-b543-35f84db8a859'::uuid, 'maduro_capture'),
    ('886dbc68-d31a-4a1b-a7ea-9ee1068119ce'::uuid, 'latam_presidents'),
    ('89495e6b-8934-429d-ab4c-7fe434d6fafb'::uuid, 'latam_presidents'),
    ('8ca183d7-16ab-4dc5-9a7b-9b53f780fcde'::uuid, 'colombia_quake'),
    ('8e70d0ff-7f36-4c9b-993c-af276650cdaa'::uuid, 'maduro_capture'),
    ('8e8cc01c-2139-4d70-bd2f-5db33564cadf'::uuid, 'latam_presidents'),
    ('909f007e-e844-48e3-af82-ff72a7d10b8a'::uuid, 'latam_presidents'),
    ('988da769-e793-4f43-9b4d-ccd34479dc39'::uuid, 'latam_presidents'),
    ('9a91e4a3-4d3e-4721-b59e-3e6e5a0c1e12'::uuid, 'delcy'),
    ('9c2dceaf-fc2b-4107-a290-824a46367de8'::uuid, 'maduro_capture'),
    ('a53bed06-2a2b-47ea-87d2-5c59688e95ae'::uuid, 'maduro_capture'),
    ('a6ee9e9d-c5c4-486b-84fe-602d6d8e5ab3'::uuid, 'rubio_tour'),
    ('ad7cf011-c875-4c9a-8ce7-f8771c857097'::uuid, 'latam_presidents'),
    ('af375229-5c60-4dba-8771-28ae725dc458'::uuid, 'latam_presidents'),
    ('ba8536d2-c78b-4209-9122-4e9852064c3c'::uuid, 'latam_presidents'),
    ('bd495514-1436-4580-9d78-55e2df6b6205'::uuid, 'latam_presidents'),
    ('c1de69b2-2903-480e-b1d0-e1b3e0f1c75f'::uuid, 'latam_presidents'),
    ('c313a7cd-52aa-47c6-9c1d-2fe92ac485fb'::uuid, 'delcy'),
    ('c4c694df-3749-46e4-876d-cb9aea446a01'::uuid, 'latam_presidents'),
    ('c5cfa455-c79c-4e35-ade6-e05321ac4315'::uuid, 'maduro_capture'),
    ('c6f2a770-c3b4-4d5a-bf77-af6cab6acb65'::uuid, 'latam_presidents'),
    ('cf1817af-cf4b-4b09-9295-5425cd82c519'::uuid, 'latam_presidents'),
    ('d1b94add-dd13-406c-a53d-3c32c1250452'::uuid, 'latam_presidents'),
    ('e04f5edc-4782-468a-bf26-a83dcb5827af'::uuid, 'latam_presidents'),
    ('e4b4ca1a-f79d-4ddc-a20c-68733ff416ef'::uuid, 'latam_presidents'),
    ('e4cf6bb5-b570-44ab-a15e-ac79470e6afe'::uuid, 'latam_presidents'),
    ('e4e373e6-448d-4c3c-ac7c-7c3f69a30e74'::uuid, 'latam_presidents'),
    ('eb5c5a6d-5c70-434c-8f8f-9afe044c1a77'::uuid, 'maduro_capture'),
    ('ee989aae-30a8-4c1f-9e79-d2ec5dbd166a'::uuid, 'sharaa'),
    ('f280ca46-061a-4f6f-bc6b-8313153f7efd'::uuid, 'latam_presidents'),
    ('fbd0b1a4-8e04-4dc4-8142-a5a88a938f1c'::uuid, 'latam_presidents')
),
todo AS (
    SELECT p.snippet, p.reason
    FROM picked p
    JOIN public.snippets s ON s.id = p.snippet AND s.status = 'Processed'
    WHERE NOT EXISTS (SELECT 1 FROM public.user_hide_snippets h WHERE h.snippet = p.snippet AND h."user" IS NULL)
      -- Only an active log row blocks a re-hide; a rolled-back row (restored_at set) is reactivated below.
      AND NOT EXISTS (
          SELECT 1 FROM public.snippet_quarantine_log l
          WHERE l.snippet = p.snippet AND l.batch = 'hide-2026-09-17-postcutoff' AND l.restored_at IS NULL
      )
),
logged AS (
    INSERT INTO public.snippet_quarantine_log (snippet, previous_status, reason, batch)
    SELECT snippet, 'Processed', reason, 'hide-2026-09-17-postcutoff' FROM todo
    ON CONFLICT (snippet, batch) DO UPDATE
        SET previous_status = EXCLUDED.previous_status,
            reason = EXCLUDED.reason,
            quarantined_at = now(),
            restored_at = NULL
    RETURNING snippet
)
INSERT INTO public.user_hide_snippets (snippet, "user")
SELECT snippet, NULL FROM logged;

COMMIT;

-- Verify:
-- SELECT reason, count(*) FROM public.snippet_quarantine_log WHERE batch = 'hide-2026-09-17-postcutoff' AND restored_at IS NULL GROUP BY 1;

-- Rollback (not run):
-- WITH r AS (
--   DELETE FROM public.user_hide_snippets h USING public.snippet_quarantine_log l
--   WHERE l.snippet = h.snippet AND l.batch = 'hide-2026-09-17-postcutoff' AND l.restored_at IS NULL AND h."user" IS NULL
--   RETURNING h.snippet)
-- UPDATE public.snippet_quarantine_log l SET restored_at = now() FROM r WHERE l.snippet = r.snippet AND l.batch = 'hide-2026-09-17-postcutoff';
