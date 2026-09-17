-- cleanup_2026_09 / step 12: deactivate active knowledge-base "facts" that deny post-cutoff events (WRITES; needs Rajiv's go).
--
-- Found 2026-09-17 (VER-341, Feedback #6/#7). All pipeline-authored (created_by_model gemini-2.5-pro), all wrong as
-- of today, all still 'active' and therefore fed to Stage 1 as "Verified Facts" and to the Stage 4 KB researcher.
-- Explicit ids, reviewed one by one (a regex over `fact` matched "petrodollar" and true historical facts):
--   bbc2a8a5  "Tomás Uribe was inaugurated as the President of Colombia on August 7, 2026" (written 2026-09-17; a fifth invented winner)
--   65d14916  "Gustavo Petro is the President of Colombia, having taken office on August 7, 2022"
--   77623aa6  "As of September 2026, the President of Colombia was Gustavo Petro"
--   b39af239  "Gustavo Petro was the President of Colombia as of August 2026"
--   0950b357  "Gustavo Petro was the President of Colombia in August 2026, as confirmed by ... the August 10th earthquake"
--   7cc23404  "Dina Boluarte was the President of Peru as of September 2026 ... Claims that Keiko Fujimori assumed ..."
--   9b73e82e  "Claims that Keiko Fujimori assumed the presidency of Peru in June 2026 are false ..."
--   5dfda8e1  "Following the Peruvian general election in April 2026, Keiko Fujimori ... was not the winner"
--   eb92f04c  "The claim that ... Maduro and his wife Cilia Flores were 'kidnapped' by U.S. forces in January 2026 is a viral hoax"
--   e27854d8  "Viktor Orbán has continuously served as the Prime Minister of Hungary since 2010 and was still in office as of September 2026"
-- Reality: de la Espriella inaugurated 2026-08-07; Fujimori sworn in 2026-07-28; Maduro captured 2026-01-03;
-- Orbán lost on 2026-04-12 (sources in 11_seed_dated_facts.sql).
-- Same audit mechanism as 07/08: kb_deactivation_log rows, batch 'cleanup-2026-09-17-postcutoff', embeddings set
-- 'Deactivated' (not deleted); rollback = 08 with this batch name. Idempotent.

BEGIN;

WITH picked AS (
    SELECT e.id, e.status
    FROM public.kb_entries e
    WHERE e.status = 'active'
      AND e.id IN (
        'bbc2a8a5-1908-4edb-92ef-6426714b0467',
        '65d14916-dc3d-4cae-8389-f612092a025f',
        '77623aa6-6748-4f73-a89b-0cf011cb2e25',
        'b39af239-ddbf-4466-b161-fb0e8e553512',
        '0950b357-80bb-4f51-8817-a57217811b36',
        '7cc23404-1c4b-4ac0-89db-b8fbf1efa69d',
        '9b73e82e-90d8-4734-936e-2e1a07b84fb6',
        '5dfda8e1-6f83-4e5e-9bfa-e04610857540',
        'eb92f04c-ca70-4758-9931-b6ffd7694cd9',
        'e27854d8-5e16-4a0b-90a9-a1d3024d53be'
      )
      AND NOT EXISTS (SELECT 1 FROM public.kb_deactivation_log l WHERE l.kb_entry = e.id AND l.batch = 'cleanup-2026-09-17-postcutoff')
),
logged AS (
    INSERT INTO public.kb_deactivation_log (kb_entry, previous_status, reason, batch)
    SELECT id, status, 'denies_post_cutoff_event', 'cleanup-2026-09-17-postcutoff' FROM picked
    RETURNING kb_entry
),
deactivated AS (
    UPDATE public.kb_entries e
    SET status = 'deactivated',
        deactivation_reason = 'cleanup-2026-09: denies_post_cutoff_event (VER-341, 2026-09-17)',
        updated_at = now()
    FROM logged l WHERE e.id = l.kb_entry
    RETURNING e.id
)
UPDATE public.kb_entry_embeddings kee
SET status = 'Deactivated', updated_at = now()
FROM deactivated d WHERE kee.kb_entry = d.id AND kee.status = 'Processed';

COMMIT;

-- Verify: SELECT count(*) FROM public.kb_deactivation_log WHERE batch = 'cleanup-2026-09-17-postcutoff' AND restored_at IS NULL;  -- expect 10
