-- cleanup_2026_09 / step 11: seed dated, analyst-verified knowledge-base facts (WRITES).
-- EXECUTED 2026-09-17 ~20:25 UTC: 14 rows; embeddings backfilled the same evening with a paged one-off (VER-377).
--
-- VER-326 / VER-338. Fourteen post-cutoff facts that Stage 3 keeps labelling 'fabricated' (Tamoa's Feedback #5-#7,
-- the 45 still-visible Colombia/Peru/Brazil snippets, the Syria and Colombia-earthquake clusters). Each fact was
-- verified on 2026-09-17 against at least two sources; every URL below came back from a live web search, none was
-- typed from memory. Sources of type 'other' (Wikipedia, think tanks, official PDFs) are kept for the record but a
-- non-'other' source is listed first so kb_context.is_trustworthy_entry accepts the entry.
--
-- created_by_model = 'analyst-seed-2026-09-17' (not a gemini-* value) so the pipeline treats these as curated,
-- and every source has a publication_date, so Stage 1 and the Stage 4 KB researcher can use them.
-- Idempotent: re-running skips facts already present (matched on created_by_model + fact).
--
-- AFTER RUNNING: the entries have no embedding yet, so search_kb_entries cannot find them until
--   PYTHONPATH=.:src python src/scripts/backfill_kb_embeddings.py
-- runs from a machine with OPENAI_API_KEY and the production Supabase key (Thien; see docs/OPERATIONS.md).
--
-- ROLLBACK: DELETE FROM kb_entry_embeddings WHERE kb_entry IN (SELECT id FROM kb_entries WHERE created_by_model = 'analyst-seed-2026-09-17');
--           DELETE FROM kb_entry_sources    WHERE kb_entry IN (SELECT id FROM kb_entries WHERE created_by_model = 'analyst-seed-2026-09-17');
--           DELETE FROM kb_entries WHERE created_by_model = 'analyst-seed-2026-09-17';

BEGIN;

-- fact 1 (confirmed; event 2026-08-07)
WITH e AS (
    INSERT INTO public.kb_entries (fact, related_claim, confidence_score, disinformation_categories, keywords, is_time_sensitive, valid_from, status, created_by_model)
    SELECT 'Abelardo de la Espriella won Colombia''s presidential runoff on 2026-06-21 and was inaugurated President of Colombia on 2026-08-07 in Cali, succeeding Gustavo Petro, whose term ended 2026-08-07.', 'Abelardo de la Espriella is not the president of Colombia / Gustavo Petro is still president in 2026', 95, ARRAY['Political Figures and Movements','Election Integrity and Voting Processes'], ARRAY['Abelardo de la Espriella','Colombia','president','inauguration','Petro','2026 election'], false, '2026-08-07'::timestamptz, 'active', 'analyst-seed-2026-09-17'
    WHERE NOT EXISTS (SELECT 1 FROM public.kb_entries WHERE created_by_model = 'analyst-seed-2026-09-17' AND fact = 'Abelardo de la Espriella won Colombia''s presidential runoff on 2026-06-21 and was inaugurated President of Colombia on 2026-08-07 in Cali, succeeding Gustavo Petro, whose term ended 2026-08-07.')
    RETURNING id
)
INSERT INTO public.kb_entry_sources (kb_entry, url, source_name, source_type, title, publication_date, relevance_to_claim)
    SELECT e.id, 'https://www.vanguardia.com/colombia/2026/08/07/abelardo-de-la-espriella-tomo-posesion-como-nuevo-presidente-de-colombia-2026-2030/', 'Vanguardia', 'tier3_regional_news', 'Abelardo de la Espriella tomó posesión como nuevo presidente de Colombia 2026-2030', '2026-08-07'::date, 'contradicts_claim' FROM e
UNION ALL
    SELECT e.id, 'https://www.eltiempo.com/politica/abelardo-de-la-espriella/posesion-de-abelardo-de-la-espriella-como-presidente-61-de-colombia-retos-analisis-y-balance-con-el-que-comienza-el-nuevo-gobierno-2026-3576887', 'El Tiempo', 'tier2_major_news', 'Posesión de Abelardo De La Espriella como presidente 61 de Colombia', '2026-08-07'::date, 'contradicts_claim' FROM e
UNION ALL
    SELECT e.id, 'https://cnnespanol.cnn.com/2026/08/07/colombia/live-news/abelardo-espriella-posesion-investidura-presidencial-orix', 'CNN en Español', 'tier2_major_news', 'Resumen de la investidura presidencial de Abelardo de la Espriella, 7 de agosto', '2026-08-07'::date, 'contradicts_claim' FROM e;

-- fact 2 (confirmed; event 2026-07-28)
WITH e AS (
    INSERT INTO public.kb_entries (fact, related_claim, confidence_score, disinformation_categories, keywords, is_time_sensitive, valid_from, status, created_by_model)
    SELECT 'Keiko Fujimori won Peru''s presidential runoff on 2026-06-07 (50.13% to Roberto Sánchez''s 49.87%) and was sworn in as President of Peru on 2026-07-28; Dina Boluarte''s mandate ended that day. Pedro Castillo was removed in December 2022 and sentenced on 2025-11-27 to 11.5 years in prison; he was not a 2026 candidate.', 'Keiko Fujimori did not become president of Peru in 2026 / Dina Boluarte is still president / Pedro Castillo won in 2026', 95, ARRAY['Political Figures and Movements','Election Integrity and Voting Processes'], ARRAY['Keiko Fujimori','Peru','president','2026 election','Boluarte','Castillo'], false, '2026-07-28'::timestamptz, 'active', 'analyst-seed-2026-09-17'
    WHERE NOT EXISTS (SELECT 1 FROM public.kb_entries WHERE created_by_model = 'analyst-seed-2026-09-17' AND fact = 'Keiko Fujimori won Peru''s presidential runoff on 2026-06-07 (50.13% to Roberto Sánchez''s 49.87%) and was sworn in as President of Peru on 2026-07-28; Dina Boluarte''s mandate ended that day. Pedro Castillo was removed in December 2022 and sentenced on 2025-11-27 to 11.5 years in prison; he was not a 2026 candidate.')
    RETURNING id
)
INSERT INTO public.kb_entry_sources (kb_entry, url, source_name, source_type, title, publication_date, relevance_to_claim)
    SELECT e.id, 'https://cnnespanol.cnn.com/2026/07/28/latinoamerica/peru-keiko-fujimori-jura-presidenta-orix', 'CNN en Español', 'tier2_major_news', 'Fujimori jura como presidenta de Perú', '2026-07-28'::date, 'contradicts_claim' FROM e
UNION ALL
    SELECT e.id, 'https://www.infobae.com/peru/2026/07/28/keiko-fujimori-en-vivo-juramentacion-toma-de-mando-y-la-agenda-completa-de-su-primer-dia-como-presidenta-del-peru/', 'Infobae', 'tier2_major_news', 'Así fue el primer día de Keiko Fujimori como presidenta del Perú', '2026-07-28'::date, 'contradicts_claim' FROM e
UNION ALL
    SELECT e.id, 'https://www.aljazeera.com/news/2025/11/27/former-peru-president-pedro-castillo-sentenced-to-11-5-years-in-prison', 'Al Jazeera', 'tier2_major_news', 'Former Peru President Pedro Castillo sentenced to 11.5 years in prison', '2025-11-27'::date, 'contradicts_claim' FROM e;

-- fact 3 (confirmed; event 2026-01-03)
WITH e AS (
    INSERT INTO public.kb_entries (fact, related_claim, confidence_score, disinformation_categories, keywords, is_time_sensitive, valid_from, status, created_by_model)
    SELECT 'Nicolás Maduro was captured by United States forces in Caracas on 2026-01-03, flown to the United States and charged in the Southern District of New York; Delcy Rodríguez was sworn in as Venezuela''s interim president on 2026-01-05.', 'The capture of Maduro by US forces in January 2026 is a hoax or fabrication', 95, ARRAY['Geopolitical Issues','Foreign Policy and International Relations'], ARRAY['Maduro','Venezuela','capture','Operation Absolute Resolve','Delcy Rodríguez','SDNY'], false, '2026-01-03'::timestamptz, 'active', 'analyst-seed-2026-09-17'
    WHERE NOT EXISTS (SELECT 1 FROM public.kb_entries WHERE created_by_model = 'analyst-seed-2026-09-17' AND fact = 'Nicolás Maduro was captured by United States forces in Caracas on 2026-01-03, flown to the United States and charged in the Southern District of New York; Delcy Rodríguez was sworn in as Venezuela''s interim president on 2026-01-05.')
    RETURNING id
)
INSERT INTO public.kb_entry_sources (kb_entry, url, source_name, source_type, title, publication_date, relevance_to_claim)
    SELECT e.id, 'https://www.aljazeera.com/news/2026/1/4/how-the-us-attack-on-venezuela-abduction-of-maduro-unfolded', 'Al Jazeera', 'tier2_major_news', 'How the US attack on Venezuela, abduction of Maduro unfolded', '2026-01-04'::date, 'contradicts_claim' FROM e
UNION ALL
    SELECT e.id, 'https://www.cnn.com/world/live-news/venezuela-explosions-caracas-intl-hnk-01-03-26', 'CNN', 'tier2_major_news', 'January 3, 2026 — Maduro in US custody', '2026-01-03'::date, 'contradicts_claim' FROM e
UNION ALL
    SELECT e.id, 'https://www.cbsnews.com/news/nicolas-maduro-replaced-venezuela-president-delcy-rodriguez-who-is-she/', 'CBS News', 'tier2_major_news', 'As Delcy Rodríguez is sworn in as Venezuela''s interim president, who is Maduro''s former No. 2?', '2026-01-05'::date, 'contradicts_claim' FROM e;

-- fact 4 (partially_confirmed; event 2026-08-28)
WITH e AS (
    INSERT INTO public.kb_entries (fact, related_claim, confidence_score, disinformation_categories, keywords, is_time_sensitive, valid_from, status, created_by_model)
    SELECT 'On 2026-08-28 President Trump announced an agreement giving US-aligned interests majority control of more than 65 billion barrels of Venezuelan oil reserves.', 'There is no US-Venezuela oil agreement in 2026', 95, ARRAY['Foreign Policy and International Relations','Economic Policies and Inflation'], ARRAY['Venezuela','oil','65 billion barrels','Trump','agreement'], false, '2026-08-28'::timestamptz, 'active', 'analyst-seed-2026-09-17'
    WHERE NOT EXISTS (SELECT 1 FROM public.kb_entries WHERE created_by_model = 'analyst-seed-2026-09-17' AND fact = 'On 2026-08-28 President Trump announced an agreement giving US-aligned interests majority control of more than 65 billion barrels of Venezuelan oil reserves.')
    RETURNING id
)
INSERT INTO public.kb_entry_sources (kb_entry, url, source_name, source_type, title, publication_date, relevance_to_claim)
    SELECT e.id, 'https://www.npr.org/2026/08/28/nx-s1-5948229/trump-says-u-s-has-entered-deal-with-venezuela-to-take-control-of-65-billion-barrels-of-oil-reserves', 'NPR', 'tier2_major_news', 'Trump says U.S. has entered deal with Venezuela to take control of 65 billion barrels of oil reserves', '2026-08-28'::date, 'contradicts_claim' FROM e
UNION ALL
    SELECT e.id, 'https://www.aljazeera.com/news/2026/8/29/trump-announces-biggest-oil-deal-in-world-history-with-venezuela', 'Al Jazeera', 'tier2_major_news', 'Trump announces ''biggest oil deal in world history'' with Venezuela', '2026-08-29'::date, 'contradicts_claim' FROM e
UNION ALL
    SELECT e.id, 'https://www.cnbc.com/2026/08/28/trump-announces-deal-with-venezuela-to-secure-more-than-65-billion-barrels-of-oil-reserves.html', 'CNBC', 'tier2_major_news', 'Trump announces deal with Venezuela to secure more than 65 billion barrels of oil reserves', '2026-08-28'::date, 'contradicts_claim' FROM e;

-- fact 5 (confirmed; event 2026-09-09)
WITH e AS (
    INSERT INTO public.kb_entries (fact, related_claim, confidence_score, disinformation_categories, keywords, is_time_sensitive, valid_from, status, created_by_model)
    SELECT 'At the Republican convention in Dallas on 2026-09-09, President Trump promised a $5,000 ''Trump dividend'' payment to every adult US citizen if Republicans keep the House and Senate in the November 2026 midterms.', 'Trump never promised a $5,000 dividend', 95, ARRAY['Economic Policies and Inflation','Political Figures and Movements'], ARRAY['Trump dividend','$5,000','midterms','Dallas','Republican convention'], false, '2026-09-09'::timestamptz, 'active', 'analyst-seed-2026-09-17'
    WHERE NOT EXISTS (SELECT 1 FROM public.kb_entries WHERE created_by_model = 'analyst-seed-2026-09-17' AND fact = 'At the Republican convention in Dallas on 2026-09-09, President Trump promised a $5,000 ''Trump dividend'' payment to every adult US citizen if Republicans keep the House and Senate in the November 2026 midterms.')
    RETURNING id
)
INSERT INTO public.kb_entry_sources (kb_entry, url, source_name, source_type, title, publication_date, relevance_to_claim)
    SELECT e.id, 'https://www.npr.org/2026/09/09/nx-s1-5961045/republican-midterm-convention-dallas-trump-vance', 'NPR', 'tier2_major_news', 'Trump promises $5,000 dividend in convention speech, but only if Republicans win', '2026-09-09'::date, 'contradicts_claim' FROM e
UNION ALL
    SELECT e.id, 'https://time.com/article/2026/09/10/trump-dividend-five-thousand-dollars-midterms-republican-convention/', 'TIME', 'tier2_major_news', 'Trump Announces $5,000 Dividend if Republicans Win Midterms', '2026-09-10'::date, 'contradicts_claim' FROM e
UNION ALL
    SELECT e.id, 'https://www.pbs.org/newshour/politics/trump-promised-5000-checks-if-republicans-win-the-midterms-how-would-that-work', 'PBS News', 'tier2_major_news', 'Trump promised $5,000 checks if Republicans win the midterms. How would that work?', '2026-09-10'::date, 'contradicts_claim' FROM e;

-- fact 6 (partially_confirmed; event 2026-09-14)
WITH e AS (
    INSERT INTO public.kb_entries (fact, related_claim, confidence_score, disinformation_categories, keywords, is_time_sensitive, valid_from, status, created_by_model)
    SELECT 'On 2026-09-14 the US Supreme Court denied the Trump administration''s emergency application in United States Postal Service v. California, leaving in place the injunction that blocks the USPS mail-ballot rule for the November 2026 elections (per curiam order, No. 26A305).', 'The Supreme Court did not rule on mail-in voting in September 2026', 95, ARRAY['Election Integrity and Voting Processes'], ARRAY['Supreme Court','USPS','mail-in ballots','California','2026 election','injunction'], false, '2026-09-14'::timestamptz, 'active', 'analyst-seed-2026-09-17'
    WHERE NOT EXISTS (SELECT 1 FROM public.kb_entries WHERE created_by_model = 'analyst-seed-2026-09-17' AND fact = 'On 2026-09-14 the US Supreme Court denied the Trump administration''s emergency application in United States Postal Service v. California, leaving in place the injunction that blocks the USPS mail-ballot rule for the November 2026 elections (per curiam order, No. 26A305).')
    RETURNING id
)
INSERT INTO public.kb_entry_sources (kb_entry, url, source_name, source_type, title, publication_date, relevance_to_claim)
    SELECT e.id, 'https://abc7news.com/post/2026-election-california-mail-voting-unchanged-supreme-court-blocks-president-donald-trump-restrictions/19837294/', 'ABC7 San Francisco', 'tier3_regional_news', '2026 Election: California mail-in voting unchanged after Supreme Court blocks Trump restrictions', '2026-09-14'::date, 'contradicts_claim' FROM e
UNION ALL
    SELECT e.id, 'https://www.supremecourt.gov/opinions/25pdf/26a305_4g15.pdf', 'Supreme Court of the United States (official)', 'official_source', '26A305 Postal Service v. California', '2026-09-14'::date, 'contradicts_claim' FROM e
UNION ALL
    SELECT e.id, 'https://www.jurist.org/news/2026/09/us-supreme-court-rejects-doj-bid-to-stay-injunction-blocking-usps-mail-in-ballot-rule/', 'JURIST', 'other', 'US Supreme Court rejects DOJ bid to stay injunction blocking USPS mail-in ballot rule', '2026-09-14'::date, 'contradicts_claim' FROM e;

-- fact 7 (confirmed; event 2026-09-02)
WITH e AS (
    INSERT INTO public.kb_entries (fact, related_claim, confidence_score, disinformation_categories, keywords, is_time_sensitive, valid_from, status, created_by_model)
    SELECT 'Nicaragua''s National Assembly approved in first reading on 2026-09-01 a constitutional reform extending elective terms, including the presidency, from five to seven years; the text was published in La Gaceta No. 163 on 2026-09-02. A second-reading vote is still required.', 'Nicaragua did not change presidential term lengths in 2026', 95, ARRAY['Geopolitical Issues','Election Integrity and Voting Processes'], ARRAY['Nicaragua','Ortega','constitutional reform','seven-year term','La Gaceta','2026'], false, '2026-09-02'::timestamptz, 'active', 'analyst-seed-2026-09-17'
    WHERE NOT EXISTS (SELECT 1 FROM public.kb_entries WHERE created_by_model = 'analyst-seed-2026-09-17' AND fact = 'Nicaragua''s National Assembly approved in first reading on 2026-09-01 a constitutional reform extending elective terms, including the presidency, from five to seven years; the text was published in La Gaceta No. 163 on 2026-09-02. A second-reading vote is still required.')
    RETURNING id
)
INSERT INTO public.kb_entry_sources (kb_entry, url, source_name, source_type, title, publication_date, relevance_to_claim)
    SELECT e.id, 'https://www.infobae.com/nicaragua/2026/09/02/el-regimen-de-nicaragua-publico-oficialmente-la-reforma-que-pone-fin-a-las-elecciones-con-oposicion/', 'Infobae', 'tier2_major_news', 'El régimen de Nicaragua publicó oficialmente la reforma que pone fin a las elecciones con oposición', '2026-09-02'::date, 'contradicts_claim' FROM e
UNION ALL
    SELECT e.id, 'https://www.articulo66.com/2026/09/02/reforma-constitucional-nicaragua-siete-anos-periodo-presidencial-proscribe-opositores/', 'Artículo 66', 'tier3_regional_news', 'Ortega y Murillo se recetan un año más y proscriben a opositores con nueva reforma constitucional', '2026-09-02'::date, 'contradicts_claim' FROM e
UNION ALL
    SELECT e.id, 'https://www.abc.com.py/internacionales/2026/09/01/nicaragua-avanza-hacia-una-reforma-constitucional-que-excluye-de-elecciones-a-traidores/', 'ABC Color', 'tier3_regional_news', 'Nicaragua avanza hacia una reforma constitucional que excluye de elecciones a ''traidores''', '2026-09-01'::date, 'contradicts_claim' FROM e;

-- fact 8 (partially_confirmed; event 2026-08-05)
WITH e AS (
    INSERT INTO public.kb_entries (fact, related_claim, confidence_score, disinformation_categories, keywords, is_time_sensitive, valid_from, status, created_by_model)
    SELECT 'Flávio Bolsonaro is a candidate in Brazil''s 2026-10-04 presidential election and on 2026-08-05 named federal deputy Alfredo Gaspar as his running mate; Luiz Inácio Lula da Silva is the incumbent president. Lula met President Trump at the White House in the week of 2026-05-07.', 'Flávio Bolsonaro is not a presidential candidate / Trump never met Lula', 95, ARRAY['Political Figures and Movements','Election Integrity and Voting Processes'], ARRAY['Flávio Bolsonaro','Brazil','2026 election','Lula','Alfredo Gaspar','Trump'], false, '2026-08-05'::timestamptz, 'active', 'analyst-seed-2026-09-17'
    WHERE NOT EXISTS (SELECT 1 FROM public.kb_entries WHERE created_by_model = 'analyst-seed-2026-09-17' AND fact = 'Flávio Bolsonaro is a candidate in Brazil''s 2026-10-04 presidential election and on 2026-08-05 named federal deputy Alfredo Gaspar as his running mate; Luiz Inácio Lula da Silva is the incumbent president. Lula met President Trump at the White House in the week of 2026-05-07.')
    RETURNING id
)
INSERT INTO public.kb_entry_sources (kb_entry, url, source_name, source_type, title, publication_date, relevance_to_claim)
    SELECT e.id, 'https://www.pbs.org/newshour/politics/watch-live-trump-meets-with-brazils-lula-at-the-white-house', 'PBS News', 'tier2_major_news', 'Trump meets with Brazil''s Lula at the White House', '2026-05-07'::date, 'contradicts_claim' FROM e
UNION ALL
    SELECT e.id, 'https://es-us.noticias.yahoo.com/fl%C3%A1vio-bolsonaro-anuncia-compa%C3%B1ero-f%C3%B3rmula-174848696.html', 'Yahoo Noticias (citing wire reporting)', 'other', 'Flávio Bolsonaro anuncia su compañero de fórmula', '2026-08-05'::date, 'contradicts_claim' FROM e
UNION ALL
    SELECT e.id, 'https://en.wikipedia.org/wiki/Fl%C3%A1vio_Bolsonaro_2026_presidential_campaign', 'Wikipedia', 'other', 'Flávio Bolsonaro 2026 presidential campaign', '2026-01-01'::date, 'contradicts_claim' FROM e;

-- fact 9 (confirmed; event 2026-09-08)
WITH e AS (
    INSERT INTO public.kb_entries (fact, related_claim, confidence_score, disinformation_categories, keywords, is_time_sensitive, valid_from, status, created_by_model)
    SELECT 'US Secretary of State Marco Rubio toured Ecuador, Colombia and Peru from 2026-09-08 to 2026-09-11, meeting the newly elected right-leaning governments including President Abelardo de la Espriella and President Keiko Fujimori.', 'Rubio''s September 2026 visit to Colombia and Peru is fictitious', 95, ARRAY['Foreign Policy and International Relations'], ARRAY['Marco Rubio','Secretary of State','Colombia','Peru','Ecuador','tour','September 2026'], false, '2026-09-08'::timestamptz, 'active', 'analyst-seed-2026-09-17'
    WHERE NOT EXISTS (SELECT 1 FROM public.kb_entries WHERE created_by_model = 'analyst-seed-2026-09-17' AND fact = 'US Secretary of State Marco Rubio toured Ecuador, Colombia and Peru from 2026-09-08 to 2026-09-11, meeting the newly elected right-leaning governments including President Abelardo de la Espriella and President Keiko Fujimori.')
    RETURNING id
)
INSERT INTO public.kb_entry_sources (kb_entry, url, source_name, source_type, title, publication_date, relevance_to_claim)
    SELECT e.id, 'https://www.aljazeera.com/news/2026/9/7/rubio-heads-to-ecuador-colombia-peru-after-right-wing-victories-in-region', 'Al Jazeera', 'tier2_major_news', 'Rubio heads to Ecuador, Colombia, Peru after right-wing victories in region', '2026-09-07'::date, 'contradicts_claim' FROM e
UNION ALL
    SELECT e.id, 'https://colombiaone.com/2026/09/11/marco-rubio-ends-colombia-ecuador-and-peru-tour-by-forging-new-alliances/', 'Colombia One', 'tier3_regional_news', 'Marco Rubio Ends Colombia, Ecuador, and Peru Tour by Forging New Alliances', '2026-09-11'::date, 'contradicts_claim' FROM e
UNION ALL
    SELECT e.id, 'https://www.atlanticcouncil.org/dispatches/what-rubios-tour-means-for-colombia-ecuador-and-peru/', 'Atlantic Council', 'other', 'What Rubio''s Latin America tour means for Colombia, Ecuador, and Peru', '2026-09-01'::date, 'contradicts_claim' FROM e;

-- fact 10 (confirmed; event 2026-08-10)
WITH e AS (
    INSERT INTO public.kb_entries (fact, related_claim, confidence_score, disinformation_categories, keywords, is_time_sensitive, valid_from, status, created_by_model)
    SELECT 'A magnitude 7.4 earthquake struck western Colombia on 2026-08-10 with its epicenter near San José del Palmar, Chocó; the death toll rose to at least 132, with heavy damage in the Cali and Pereira regions.', 'There was no earthquake in Colombia in August 2026', 95, ARRAY['Conspiracy Theories','Public Safety and Law Enforcement'], ARRAY['Colombia','earthquake','Chocó','San José del Palmar','Cali','August 2026','7.4'], false, '2026-08-10'::timestamptz, 'active', 'analyst-seed-2026-09-17'
    WHERE NOT EXISTS (SELECT 1 FROM public.kb_entries WHERE created_by_model = 'analyst-seed-2026-09-17' AND fact = 'A magnitude 7.4 earthquake struck western Colombia on 2026-08-10 with its epicenter near San José del Palmar, Chocó; the death toll rose to at least 132, with heavy damage in the Cali and Pereira regions.')
    RETURNING id
)
INSERT INTO public.kb_entry_sources (kb_entry, url, source_name, source_type, title, publication_date, relevance_to_claim)
    SELECT e.id, 'https://www.cnn.com/2026/08/10/world/live-news/colombia-earthquake-san-jose-del-palmar', 'CNN', 'tier2_major_news', 'August 10, 2026: Death toll rises to 132 following 7.4 magnitude earthquake in Colombia', '2026-08-10'::date, 'contradicts_claim' FROM e
UNION ALL
    SELECT e.id, 'https://www.cbsnews.com/news/colombia-earthquake-western-region-evacuations/', 'CBS News', 'tier2_major_news', 'Strong earthquake strikes western Colombia, killing at least 111 people', '2026-08-10'::date, 'contradicts_claim' FROM e
UNION ALL
    SELECT e.id, 'https://time.com/article/2026/08/10/colombia-earthquake-death-toll-damage/', 'TIME', 'tier2_major_news', 'What to Know About the Earthquake in Colombia', '2026-08-10'::date, 'contradicts_claim' FROM e;

-- fact 11 (confirmed; event 2026-09-25)
WITH e AS (
    INSERT INTO public.kb_entries (fact, related_claim, confidence_score, disinformation_categories, keywords, is_time_sensitive, valid_from, status, created_by_model)
    SELECT 'Pope Leo XIV (Robert Prevost, elected 2025-05-08) is scheduled to make an apostolic journey to France, including UNESCO headquarters in Paris, from 2026-09-25 to 2026-09-28, as announced by the Holy See.', 'Pope Leo XIV''s 2026 trip to France is fabricated', 95, ARRAY['Political Figures and Movements'], ARRAY['Pope Leo XIV','France','apostolic journey','UNESCO','September 2026'], false, '2026-05-16'::timestamptz, 'active', 'analyst-seed-2026-09-17'
    WHERE NOT EXISTS (SELECT 1 FROM public.kb_entries WHERE created_by_model = 'analyst-seed-2026-09-17' AND fact = 'Pope Leo XIV (Robert Prevost, elected 2025-05-08) is scheduled to make an apostolic journey to France, including UNESCO headquarters in Paris, from 2026-09-25 to 2026-09-28, as announced by the Holy See.')
    RETURNING id
)
INSERT INTO public.kb_entry_sources (kb_entry, url, source_name, source_type, title, publication_date, relevance_to_claim)
    SELECT e.id, 'https://www.vatican.va/content/leo-xiv/en/travels/2026/documents/francia-25-28settembre2026.html', 'Vatican (official)', 'official_source', 'Apostolic Journey of the Holy Father to France and Visit to UNESCO (25-28 September 2026)', '2026-05-16'::date, 'contradicts_claim' FROM e
UNION ALL
    SELECT e.id, 'https://www.vaticannews.va/en/pope/news/2026-08/pope-leos-packed-schedule-4-day-apostolic-journey-to-france.html', 'Vatican News', 'official_source', 'Pope Leo''s schedule for his four-day Apostolic Journey to France', '2026-08-01'::date, 'contradicts_claim' FROM e;

-- fact 12 (confirmed; event 2025-09-10)
WITH e AS (
    INSERT INTO public.kb_entries (fact, related_claim, confidence_score, disinformation_categories, keywords, is_time_sensitive, valid_from, status, created_by_model)
    SELECT 'Charlie Kirk was shot and killed on 2025-09-10 at an event at Utah Valley University in Orem, Utah; Tyler Robinson was charged with the murder.', 'Charlie Kirk is alive / his assassination is a hoax', 95, ARRAY['Political Figures and Movements','Conspiracy Theories'], ARRAY['Charlie Kirk','assassination','Utah Valley University','Tyler Robinson','2025-09-10'], false, '2025-09-10'::timestamptz, 'active', 'analyst-seed-2026-09-17'
    WHERE NOT EXISTS (SELECT 1 FROM public.kb_entries WHERE created_by_model = 'analyst-seed-2026-09-17' AND fact = 'Charlie Kirk was shot and killed on 2025-09-10 at an event at Utah Valley University in Orem, Utah; Tyler Robinson was charged with the murder.')
    RETURNING id
)
INSERT INTO public.kb_entry_sources (kb_entry, url, source_name, source_type, title, publication_date, relevance_to_claim)
    SELECT e.id, 'https://utahnewsdispatch.com/2025/09/10/charlie-kirk-shot-during-event-at-utah-valley-university/', 'Utah News Dispatch', 'tier3_regional_news', 'Charlie Kirk killed at Utah Valley University, search for shooter continues', '2025-09-10'::date, 'contradicts_claim' FROM e
UNION ALL
    SELECT e.id, 'https://www.fbi.gov/news/press-releases/utah-valley-shooting-updates', 'FBI (official)', 'official_source', 'Utah Valley Shooting Updates', '2025-09-10'::date, 'contradicts_claim' FROM e
UNION ALL
    SELECT e.id, 'https://en.wikipedia.org/wiki/Assassination_of_Charlie_Kirk', 'Wikipedia', 'other', 'Assassination of Charlie Kirk', '2025-01-01'::date, 'contradicts_claim' FROM e;

-- fact 13 (partially_confirmed; event 2025-11-10)
WITH e AS (
    INSERT INTO public.kb_entries (fact, related_claim, confidence_score, disinformation_categories, keywords, is_time_sensitive, valid_from, status, created_by_model)
    SELECT 'Ahmed al-Sharaa has led Syria since the fall of Bashar al-Assad on 2024-12-08 and was formally installed as president on 2025-01-29; he met President Trump at the White House on 2025-11-10, the first visit by a Syrian president.', 'Assad is still president of Syria / al-Sharaa never visited the White House', 95, ARRAY['Geopolitical Issues','Foreign Policy and International Relations'], ARRAY['Ahmed al-Sharaa','Syria','Assad','White House','2025-11-10','president'], false, '2025-11-10'::timestamptz, 'active', 'analyst-seed-2026-09-17'
    WHERE NOT EXISTS (SELECT 1 FROM public.kb_entries WHERE created_by_model = 'analyst-seed-2026-09-17' AND fact = 'Ahmed al-Sharaa has led Syria since the fall of Bashar al-Assad on 2024-12-08 and was formally installed as president on 2025-01-29; he met President Trump at the White House on 2025-11-10, the first visit by a Syrian president.')
    RETURNING id
)
INSERT INTO public.kb_entry_sources (kb_entry, url, source_name, source_type, title, publication_date, relevance_to_claim)
    SELECT e.id, 'https://www.cnn.com/2025/11/10/middleeast/syrias-postwar-pivot-reaches-washington-intl', 'CNN', 'tier2_major_news', 'Ahmed Al-Sharaa: Syria''s jihadist-turned-president caps extraordinary transformation with White House visit', '2025-11-10'::date, 'contradicts_claim' FROM e
UNION ALL
    SELECT e.id, 'https://www.pbs.org/newshour/show/al-sharaa-meets-with-trump-at-white-house-as-syria-seeks-closer-ties-with-the-west', 'PBS News', 'tier2_major_news', 'Al-Sharaa meets with Trump at White House as Syria seeks closer ties with the West', '2025-11-10'::date, 'contradicts_claim' FROM e
UNION ALL
    SELECT e.id, 'https://en.wikipedia.org/wiki/November_2025_visit_by_Ahmed_al-Sharaa_to_the_United_States', 'Wikipedia', 'other', 'November 2025 visit by Ahmed al-Sharaa to the United States', '2025-01-01'::date, 'contradicts_claim' FROM e;

-- fact 14 (confirmed; event 2026-04-12)
WITH e AS (
    INSERT INTO public.kb_entries (fact, related_claim, confidence_score, disinformation_categories, keywords, is_time_sensitive, valid_from, status, created_by_model)
    SELECT 'Viktor Orbán lost Hungary''s parliamentary election on 2026-04-12 to Péter Magyar''s Tisza party and conceded defeat, ending his premiership after 16 years.', 'Viktor Orbán is still Prime Minister of Hungary in late 2026', 95, ARRAY['Political Figures and Movements','Geopolitical Issues'], ARRAY['Viktor Orbán','Hungary','election','Péter Magyar','Tisza','2026-04-12'], false, '2026-04-12'::timestamptz, 'active', 'analyst-seed-2026-09-17'
    WHERE NOT EXISTS (SELECT 1 FROM public.kb_entries WHERE created_by_model = 'analyst-seed-2026-09-17' AND fact = 'Viktor Orbán lost Hungary''s parliamentary election on 2026-04-12 to Péter Magyar''s Tisza party and conceded defeat, ending his premiership after 16 years.')
    RETURNING id
)
INSERT INTO public.kb_entry_sources (kb_entry, url, source_name, source_type, title, publication_date, relevance_to_claim)
    SELECT e.id, 'https://edition.cnn.com/2026/04/12/world/live-news/hungary-election-orban-magyar', 'CNN', 'tier2_major_news', 'Hungary election 2026 results: Petér Magyar wins, Trump ally Viktor Orbán concedes landmark defeat', '2026-04-12'::date, 'contradicts_claim' FROM e
UNION ALL
    SELECT e.id, 'https://www.aljazeera.com/news/2026/4/12/hungary-election-early-results-show-magyars-tisza-ahead-of-orbans-fidesz', 'Al Jazeera', 'tier2_major_news', 'Peter Magyar wins Hungary election, unseating Viktor Orban after 16 years', '2026-04-12'::date, 'contradicts_claim' FROM e
UNION ALL
    SELECT e.id, 'https://en.wikipedia.org/wiki/2026_Hungarian_parliamentary_election', 'Wikipedia', 'other', '2026 Hungarian parliamentary election', '2026-01-01'::date, 'contradicts_claim' FROM e;

COMMIT;
