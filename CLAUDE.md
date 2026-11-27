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
- finsmes and devops_com read via Google News (direct feeds 403). SEC Form D disabled until Phase 4 (403 with our User-Agent).
- Added sources: hn_jobs, hn_launches.

## Status
Phase 0 done (2026-11-27): telegram.py, state.py, http.py, config.py, check.py, CLI with run / dry-run /
check-sources / report. 36 tests. 28 sources, 0 failing. Private workflow runs manually and saves state.

## Next
Session 10: add settings.yaml (HTTP timeout/retries/per-host interval, User-Agent project URL, state
retention days, Google News language) with today's values as defaults, and wire it in. Then Phase 1:
RSS adapter -> Signal records, regex funding pre-filter, cross-source dedupe, Telegram digest,
cron schedule "17 2,7,11,15 * * *". Goal: schedule live before 2026-12-28.
