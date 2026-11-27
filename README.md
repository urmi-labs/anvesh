# Anvesh

A free radar for newly funded tech startups and the roles they are hiring for, with alerts on Telegram.

Anvesh watches funding news, startup lists and public job APIs, finds companies that just raised money, checks them for roles that match your profile, and sends you a short alert. It runs entirely on the GitHub Actions free tier, with no paid APIs.

> **Status:** early development. The plumbing works; sources and filters are being added.

## Planned features

- Funding signals from public RSS feeds, Google News, SEC Form D and the YC company list
- Open roles from public ATS job APIs (Greenhouse, Lever, Ashby, Workable and more)
- Your roles, skills, locations and experience level set in one config file; nothing is hardcoded
- Strict filters: only roles posted in the last 24 hours, seniority limits you choose, and a two-gate exclusion filter for off-target roles
- Visa sponsorship and relocation detection
- Scored alerts and an evening digest on Telegram

## How it runs

Anvesh uses two repositories:

- **This repo (public):** the code and example configs.
- **Your private data repo:** your profile, secrets, the scheduled workflow and the run state. It installs this package with pip.

Your profile and any contact details the radar finds never go into a public repository.

## Local development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
anvesh --help
anvesh check-sources --config config   # after copying config/sources.example.yaml to config/sources.yaml
```

## License

MIT
