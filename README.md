# Anvesh

A free radar for newly funded tech startups and their DevOps, SRE and platform roles, with alerts on Telegram.

Anvesh watches funding news, filings and public job APIs, finds startups that just raised, checks their careers pages for matching roles, and sends you a short alert. It runs entirely on GitHub Actions free tier, with no paid APIs.

> **Status:** early development. The plumbing works; sources and filters are being added.

## Planned features

- Funding signals from public RSS feeds, Google News, SEC Form D and the YC company list
- Open roles from public ATS job APIs (Greenhouse, Lever, Ashby, Workable and more)
- Strict filters: roles posted in the last 24 hours only, no senior roles for early-career users, and a two-gate exclusion filter for off-target roles
- Visa sponsorship and relocation detection
- Scored alerts and an evening digest on Telegram

## How it runs

Anvesh uses two repositories:

- **This repo (public):** the code.
- **Your private data repo:** your profile, secrets, the scheduled workflow and the run state. It installs this package with pip.

Your profile and the people found by the radar never go into a public repository.

## Local development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
anvesh --help
```

## License

MIT
