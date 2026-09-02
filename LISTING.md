# Nudge — marketplace listing

**Price:** Free (lead magnet). Self-hosted. No signup, no license server.

**One-liner:** A small sales follow-up app you run on your own VPS. Add leads, generate a 3-step email sequence, copy/export it, or send it through your own SMTP.

**Who it's for:** Small business owners who want a follow-up cadence without a SaaS inbox tool.

**Install:** About 15 minutes. Documented on Ubuntu 22.04/24.04 (Docker Engine + Compose plugin). Debian 13 uses `docker.io` + `docker-compose`. Amazon Linux notes are not published yet.

**Smoke test:** `curl -sf http://localhost:8080/health` returns HTTP 200 and `{"smtp_configured":false,"status":"ok"}` when SMTP is unset. In the browser, Import CSV (`sample-leads.csv`), generate a sequence, copy or export. Do not `curl -L` the CSV import.

**Repo:** https://github.com/aidendify/nudge-followup

**Config:** Copy `.env.example` to `.env`. Leave `MARKETING_URL` empty (no footer). SMTP is optional.
