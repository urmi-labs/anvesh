# Anvesh — project guide for Claude Code

Free, open-source radar for newly funded tech startups and the roles they hire for, with Telegram alerts.
Runs on GitHub Actions free tier. No paid APIs.

## Two repos
- This repo (public, urmi-labs/anvesh): code, tests, example configs. Never put personal data here.
- Private data repo (../anvesh-data): real sources.yaml, profile.yaml (later), secrets, the scheduled
  workflow (.github/workflows/radar.yml), the `state` branch, and the design docs in docs/.
  It installs this package with `pip install git+https://github.com/urmi-labs/anvesh@main`.
- Design spec: ../anvesh-data/docs/anvesh-job-board.pdf (main design) and Source_catalogue.pdf.
  Read them before planning a new phase. Deviations already agreed are listed below.

## Rules
- Nothing user-specific is hardcoded. Roles, locations, seniority, thresholds, scores, sources, limits,
  wording and retention live in YAML config with sensible defaults. Only fixed external facts
  (e.g. Telegram's 4096-char limit) stay in code. Every config gets a documented `config/*.example.yaml`
  and a test that the example is valid.
- Every module gets tests that run offline (httpx.MockTransport, tmp_path, fake clocks). `pytest -q` must pass before commit.
- All network access goes through anvesh/http.py (per-host rate limit, retries, ETag cache, User-Agent).
- Never fake a browser User-Agent or bypass bot protection. If a feed 403s, use a google_news `site:` query or disable it.
- Times are UTC ISO strings via state.to_iso / from_iso.
- Secrets only from environment variables; never print or log tokens or URLs containing them.
- `dry-run` never sends to Telegram and never writes state.

## How to work with me (the maintainer)
- I build this in ~30-minute sessions. Work one small step at a time and stop at a checkpoint
  (tests pass / command output looks right) before moving on.
- Explain briefly what each new piece of code does and why, so I understand and can extend it.
- Ask before committing or pushing. Commit messages: short, imperative, describe the change.
- Prefer exact commands and complete files over partial snippets when showing me something.
- At the end of each session, update the Status and Next sections of this file.

## Agreed deviations from the design doc
- Python package is `anvesh` (CLI `anvesh ...`), not `radar`.
- sources.yaml is one flat list of sources with an `adapter` field (rss | json_api | google_news), not per-type sections.
- Action versions: actions/checkout@v7, actions/setup-python@v7.
- finsmes, devops_com and eu_startups read via Google News (direct feeds 403; eu_startups only from
  GitHub Actions IPs, so always test a new direct feed with a workflow run, not just from home). SEC Form D disabled until Phase 4 (403 with our User-Agent).
- Added sources: hn_jobs, hn_launches.

## Agreed product design (2026-11-28, decided with the maintainer; overrides the design doc where different)
Profile (profile.yaml, filled by `anvesh init`, editable later):
- Users answer questions, never write regex. Required: roles (built-in role FAMILIES: devops, sre, platform,
  cloud, security, backend, frontend, fullstack, mobile, data, ml, mlops, qa, design, product, sales, support),
  experience_years, based_in (country), locations (countries and/or "remote"), visa (bool).
  Optional (`init --detailed`, Enter skips): stack (tools), work_mode, company_stage, avoid_industries,
  avoid_companies, min_salary. Optional `advanced:` keep/exclude words for power users (e.g. mlops keep).
- Role families: a title matching a family the user did NOT pick is dropped (no exclude list to write).
  Seniority derives from experience_years (1 -> drop Senior/Staff/Lead/Principal/II/III and >2 years asked).
- `anvesh explain "<title>"` says why a title is kept or dropped. Typos: "did you mean devops?".
anvesh init (terminal, no LLM): 5 essentials (roles, experience, country, where to work, visa), then optional
  details (stack, work mode, company stage, industries/companies to avoid, salary), then Telegram setup
  (hidden token input, find chat id, test message, `gh secret set`, commit+push profile). Each answer echoes
  its effect (✓ ...). Re-run uses current answers as defaults; `anvesh profile` / `anvesh profile set k v`.
  Later options: Telegram interview with buttons (needs the Worker), free-text via user's own free LLM key.
Salary: min_salary is a LIST of {currency, amount, period(year|month)}; user picks the currency, no FX
  conversion, no margins. Compare only jobs in a currency the user set (top of the job's range, same period;
  month x12, hour x2080). Other currency -> pass, show salary as stated "(no USD minimum set)". Not stated ->
  pass, "Salary: not stated". init offers a minimum for a new currency when a country is added.
Location: countries + "remote" only, NO cities. Remote jobs restricted elsewhere ("Remote (US only)",
  "must reside in EU") are dropped for users based elsewhere; worldwide/APAC/own-country remote passes;
  unclear location passes and is shown as written. Abroad onsite only if visa allows and the job sponsors.
Company enrichment (after jobs reach Telegram): per funded startup show name, what it does, website, careers
  page + open roles (ATS detection, matches marked), and 2-3 people (founder, hiring/talent lead, technical)
  each with title, email + label, LinkedIn button. "Find before guess": company site team/about/contact,
  company GitHub commit emails, the article, personal site/HN/X; then pattern guess (learn the pattern from
  any found email; check the domain has MX). LinkedIn = search link by default (never scrape LinkedIn);
  exact profile URL only via a search API free quota if one exists at build time. Optional user-provided
  key for a paid provider (e.g. Hunter) / free verifier quota, off by default.
HARD RULE, emails: every email is shown with how it was found and is never presented as more than it is:
  "found on <exact page>" | "verified by <service>" (only with the user's key) | "⚠️ guessed, not verified"
  (fixed text, not configurable) | "LinkedIn only" when no email. Guessed addresses are never sent to
  automatically; Phase 3b drafts to a guessed address require explicit confirmation with the warning shown.
  A test fails the build if any email renders without its label. README states Anvesh has no contact
  database. (Antijob shows "Checked" emails from paid data; we cannot match that for free and must not pretend.)
Freshness stays the differentiator: Antijob listed matches posted 5-47 days ago; Anvesh keeps the 24h rule
  for jobs (funding news window is 36h in the maintainer's private filters.yaml).

## Status
Phase 0 done (2026-11-27): telegram.py, state.py, http.py, config.py, check.py, CLI with run / dry-run /
check-sources / report. 28 sources, 0 failing. Private workflow runs manually and saves state.
Session 10 done (2026-11-27): settings.yaml (http timeout/retries/backoff/Retry-After cap/per-host gap,
project_url, contact; state.retention_days; google_news.language). Optional file, all defaults in
config.py Settings; CLI loads it and passes it down. 45 tests.
Session 11 done (2026-11-27): anvesh/signals.py (frozen Signal dataclass), anvesh/adapters/ (fetch()
dispatcher, base.py SourceError + clean_text, rss.py for rss and google_news via feedparser, ETag 304 -> []).
Live-checked on inc42, entrackr, finsmes. json_api adapter not built yet. 54 tests.
Session 12 done (2026-11-28): filters.yaml (optional; defaults in config.py FiltersConfig): window.hours 24
+ source.lag_hours, window.undated keep|drop (keep = counts as published when first seen; dedupe stops
repeats), funding.match_fields (title by default), include/exclude regex lists (user list replaces default;
exclude wins). anvesh/filters.py (in_window, FundingMatcher, apply_filters with drop counts by reason).
Excludes IPO/listing, M&A, stake sales/block deals, layoffs/shutdowns, VC fund closes, weekly roundups.
Live-checked on 6 sources: 0 misses, roundup false positive fixed. anvesh/pipeline.py (collect: broken
source never stops the run, missing `needs` env = skipped; run_pass; summary_line). run / dry-run now
fetch all enabled sources with the ETag cache, filter, print kept signals; run sends only a status line
to Telegram until the digest exists. Sources whose adapter is not built (json_api) are reported as skipped,
not failed. Full dry-run on private config: 468 fetched, 120 kept, but only ~35 distinct stories
(gnews_funding repeats each link per region; same raise also via finsmes/eu_startups/inc42). Non-tech raises
(pet food, beverages) pass the regex on purpose; the later classification step drops them. 90 tests.
Session 13 done (2026-11-28): anvesh/dedupe.py. Layer 1: normalise_link (lowercase host, no utm_/fbclid/
gclid/ref, no #fragment, no trailing /), repeats dropped. Layer 2: name_words = title words minus
dedupe.ignore_words (amounts and 's removed); amounts() parses $9 Mn / $9M / €9.48 million / ₹2.5 Crore /
Rs / USD / $490K / A$ into (currency, whole units). Same story = share >=1 name word AND (overlap >=
title_similarity 0.6 OR same amount+currency). Currencies never converted (converting merged M with
nextesy in testing). Story keeps the direct publisher link over news.google.com, sources, also_in().
SeenStories reads state table seen_stories (links + fingerprints); pipeline.run_pass returns Pass
(collected, filtered, stories, new, already_seen). run does NOT call remember() yet: stories are marked
seen only after the digest really delivers them. Live dry-run: 115 kept -> 32 stories, 0 wrong merges
(nextesy 3x by design). tests/fixtures/funding_titles_2026-11-28.txt pins 46 titles -> 33. 112 tests.
Session 14 done (2026-11-28): anvesh/digest.py. story_line: headline is the <a href> (HTML mode, only
& < > escaped), "· source +N". build_messages: header (settings digest.header with {new} {stories}
{fetched} {sources}; bad placeholder = config error), grouped by region in digest.region_order, packed by
visible_length() (Telegram counts visible text in UTF-16 units; hidden hrefs free), region heading repeated
on a continued message; max_stories holds the rest back; send_when_empty. deliver(): send each message
with split=False, remember its stories only after it went out; stops at first failure (none lost, none
twice). run: missing Telegram secrets = exit 1 without saving state; saves runs.delivered/held_back.
LIVE 2026-11-28 via private workflow: 31 stories in 1 Telegram message; second run 0 new / 30 seen, nothing
sent. eu_startups 403 from Actions -> google_news. 128 tests.
Session 15 (2026-11-28): Collected.ok lists sources that answered (304 counts); all_sources_failed() ->
run / dry-run exit 1 (a blind run must not look like a quiet day). Private radar.yml: schedule
"17 2,7,11,15 * * *" (07:47/12:47/16:47/20:47 IST) + workflow_dispatch with a test_alert input that fails
on purpose; existing concurrency group radar (cancel-in-progress false) stops overlapping runs on the
state branch; last step "Alert on failure" (if: failure(), plain curl, works even if install broke) sends
one Telegram line with the run URL. 130 tests.
Session 16 (2026-11-28): anvesh/sector.py, filters.yaml `sector:` (enabled, match_fields title+summary,
tech / non_tech regex lists, unknown keep|drop). Classified from ALL merged headlines (Story.signals):
tech wins over non_tech; only non_tech is dropped; unknown kept by default. Pass.sector holds kept/dropped;
dry-run lists "not tech, dropped" lines; summary shows "N stories, M not tech". Funding exclude now also
drops government grants. On the 2026-11-28 fixture: drops exactly pet food, protein water, period products;
0 tech misclassified. 144 tests.
Session 17 (2026-11-28): Source.kind funding|job|launch (default funding); Signal.kind + Signal.company.
anvesh/adapters/json_api.py: generic, driven by sources.yaml `items` (dotted path, "" = top-level list) and
`fields` (title, link or link_template, company, published, summary; published must be the POSTED date).
parse_date: ISO / RFC 2822 / epoch s or ms, naive = UTC, unreadable or >1h in the future = missing.
Enabled json_api without fields = config error. Mappings for remoteok, jobicy, arbeitnow(_uk), hn_jobs,
hn_launches; yc_hiring (needs a daily diff) and hn_whoishiring (jobs are comments) disabled. wwr_devops is
kind job. Pipeline: only kind funding goes to filters/dedupe/sector/digest; job + launch go to Pass.held,
counted in the summary ("held (no role filter yet): job=N launch=N"); dry-run prints 3 samples per held
source to check mappings. Nothing from jobs is sent yet. 165 tests.

## Next
Session 18a: profile.yaml per "Agreed product design" (all fields; only roles + experience_years used yet),
built-in role families catalogue, title filter (family match, user's families kept, others dropped,
advanced keep/exclude, senior title words incl. II/III/SDE 2 derived from experience_years), `anvesh explain`,
dry-run shows how many held jobs pass and why others dropped. Example profile is role-neutral.
Session 18b: hard rules: years parsed from title+summary ("3+ years", "3-5 yrs", "at least three years";
number within 6 words of experience/exp), 24h date rule (posted, else first seen; no date and not first seen
in window = drop), tests/test_hard_rules.py with the design doc's recorded cases, every drop recorded with
gate + matched word (excluded table).
Session 19: jobs into the digest (own section), first-run-of-a-source stays silent, repost check.
Session 20: `anvesh init` / `anvesh profile`. Then company enrichment, then salary + location sessions.
Watch: first scheduled runs; check held job samples in dry-run look right (field mappings untested live).
Later: region per story (Indian raises via gnews_funding show as GLOBAL); yc_hiring diff; hn_whoishiring.
