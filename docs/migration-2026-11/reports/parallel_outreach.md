# Parallel outreach for VERDAD (research and draft only, nothing sent)

## Contacts, ranked by likelihood of a fast approval

1. **Travers Nisbet, co-founder.** Leads product, go-to-market and operations, so he can approve credits and also owns Decisions-style product questions. Evidence: https://tickets.raisesummit.com/2026/speaker/2102380/travers-nisbet (bio); https://en.wikipedia.org/wiki/Parallel_Web_Systems (co-founder). No public email found. Reach via LinkedIn or X cold message, or a warm intro (Khosla, Index and First Round are investors).
2. **Graham Moreno, Head of GTM.** Evidence: https://parallel.ai/press (lists him as Head of GTM, First Round video, May 21 2026). A search also surfaced Parallel's LinkedIn company post and a Turing Tree listing naming him, but I did not open those, so treat the title as one verified source plus two unverified. No public email found.
3. **support@parallel.ai.** Documented route for requesting higher limits: https://docs.parallel.ai/getting-started/rate-limits ("email support@parallel.ai with your use case and requirements"). Best official channel for the allocation request, probably slower than a named person but the one they tell you to use.
4. **hello@parallel.ai.** General address shown on https://contact.parallel.ai/ (fallback link). The contact form there (name, title, email, website, needs) is the sales/demo route and has no nonprofit or startup option.
5. Long shot: **Parag Agrawal, CEO** (LinkedIn https://www.linkedin.com/in/paragagr/). Use only through a warm intro.

Suggested sequence: email Travers (or Graham) directly if you can find an address or a LinkedIn route, and send the same text to support@parallel.ai with hello@parallel.ai on cc the same day, so it lands in a queue someone is obliged to read.

## Official channels
- Startup credits form (up to $250): https://form.fillout.com/t/cNxJPKmh7eus (linked from https://parallel.ai/pricing). Could not read the form's fields or eligibility. $250 would cover about 250,000 Decisions calls at list price, so it may cover the Decisions ask by itself if VERDAD qualifies as a startup. Your call whether to submit it; I did not.
- Contact/demo form: https://contact.parallel.ai/
- Developer platform: https://platform.parallel.ai; docs https://docs.parallel.ai; cookbook https://github.com/parallel-web/parallel-cookbook
- No Discord or Slack community, no X handle and no DevRel person found on any Parallel page I could read. Parallel's own Slack agent exists (https://parallel.ai/blog/parallel-slack-agent) but is a product, not a community. A DevRel Engineer and a Developer Partnerships role were posted earlier in 2026 (https://inferencejobs.com/companies/parallel-web-systems/jobs/devrel-engineer returned 404; Developer Partnerships posting at https://jobs.khoslaventures.com/companies/parallel-web-systems/jobs/55981447-developer-partnerships, closed, names nobody). The careers page (https://parallel.ai/careers) no longer lists DevRel roles.

## Published policy
- Free tier: $5 in free credits per month per organization with a card on file, plus 5,000 free Decisions requests to start (https://parallel.ai/blog/free-tier-parallel.md, https://parallel.ai/blog/decisions-api). The pricing page also says "up to $80 at signup" (https://parallel.ai/pricing).
- Startup program: "qualified startups can receive up to $250 in free credits" (pricing page).
- Nonprofit, research, journalism or academic program: none found anywhere. So this is a discretionary ask, and the pitch (public write-up, eval numbers, reference call) is the thing that makes it approvable.
- Case studies they promote: Macroscope, Starbridge, Lindy, Day AI, Gumloop (search result, not opened); Decisions post cites a KYB engine (426 companies, 98% of flags held up) and GTM lead routing (500 leads, 97% routed correctly) at https://parallel.ai/blog/decisions-api. TechCrunch names Clay, Harvey, Notion and Opendoor as customers (https://techcrunch.com/2026/04/29/parallel-web-systems-hits-2b-valuation-five-months-after-its-last-big-raise/). Nothing in civic tech or journalism, so VERDAD would be a new kind of reference.

## Facts that shape the ask
- Decisions pricing: $1 per 1,000 calls; a call can carry up to 100 questions for the same price (https://parallel.ai/blog/decisions-api). So 30,000 calls is about $30 a month and 100,000 about $100 at list price. The credits themselves are small for them; the technical contact is worth more than the money. Task API runs from $5 per 1,000 (Lite) to $2,400 per 1,000 (Ultra8x).
- Rate limit: Decisions 600 per minute, Tasks 2,000 per minute (https://docs.parallel.ai/getting-started/rate-limits). 1,000 clips a day is nowhere near the limit.
- Docs gap that justifies the "technical contact" ask: the Decisions quickstart and best-practices pages say nothing on supported languages or include/exclude domain source control. The only grounding control documented is `advanced_settings.location` (country code). Citations are per call, not mapped to each answer, and refusals come back as a normal 200 answer of type "refusal". Worth testing both against your 38 labeled clips.
- Caveat: one search result says a Hacker News report described insufficient-balance errors inside the free allowance; unverified.

## Email

**Subject:** VERDAD: testing the Decisions API on 1,000 radio fact-checks a day

**Alternative subject:** Non-profit election misinformation pilot for the Decisions API

(Greeting assumes Travers. Swap the name if you write to Graham, or use "Hi Parallel team," for support@.)

Hi Travers,

I'm Rajiv Sinclair at Public Data Works. We build VERDAD (verdad.app), a non-profit, public-interest project with City Bureau and Outlier Media. It records 54 Spanish- and Arabic-language US radio stations around the clock and flags suspected mis/disinformation for hundreds of journalists and researchers. It is in heavy use ahead of the November 3 midterms.

Our pipeline fact-checks about 1,000 flagged clips a day with an LLM tool loop over web search: roughly 4 to 7 search and read turns per clip, 170k to 550k input tokens, $0.29 to $0.46 a clip. We built it that way after native search grounding failed silently and the model hallucinated fact-checks, so a cited, auditable web-grounded answer matters a lot to us.

We would like to test the Decisions API as a cited pre-check and evidence supplier for that loop, and possibly for our review stage. We start this week with 38 production clips that have human labels. If it holds up, we run a daily shadow pass over about 1,000 clips, around 30,000 calls a month, which is above the 5,000 free tier.

Would you consider a boosted free or credited allocation for two to three months, roughly 30,000 to 100,000 Decisions calls a month plus a small Task API allowance for deeper checks? We would also value a technical contact for questions about Spanish and Arabic claims and source control.

In return, if it works we will publish a write-up with the eval numbers on how it changed our pipeline's reliability, throughput and cost, and I am glad to do a reference call. I did a similar collaboration with the Google Gemini team.

Thank you for considering it. I'm happy to share the 38-clip results either way.

Rajiv Sinclair
Public Data Works
rajiv@publicdata.works

(Body is 293 words including the signature.)
