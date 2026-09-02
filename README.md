# Nudge

Free, self-hosted sales follow-up agent for small business owners. Add leads, generate a three-step email sequence, then copy, export, or optionally send it through your own SMTP server.

No signup. No license server. One Docker Compose service and a SQLite file. Aimed at a cheap 1GB VPS (or similar Amazon Linux / Ubuntu host) and about 15 minutes to install.

## What it does

- Web UI plus CSV import for leads (name, email, company, last touch date, notes)
- Generate a 3-step follow-up sequence (subject + body) per lead, spaced Day 0 / Day 3 / Day 7 from last touch (or today if last touch is empty)
- Copy each step, copy all, or export as `.txt` — SMTP is not required
- Optional SMTP send for one step or all unsent steps
- Mark leads contacted, skipped, or replied
- `GET /health` returns HTTP 200 JSON `{"status":"ok"}` even when SMTP is unset

Sequences are filled from templates (no LLM). Sign-off uses `FROM_NAME` / `FROM_EMAIL` when set, otherwise `Your name`.

## 15-minute Ubuntu VPS install

### 1. Install Docker Engine and the Compose plugin

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo ${UBUNTU_CODENAME:-$VERSION_CODENAME}) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo usermod -aG docker "$USER"
```

Log out and back in (or run `newgrp docker`) so `docker` works without `sudo`.

### 2. Clone, configure, start

```bash
git clone https://github.com/aidendify/nudge-followup.git
cd nudge-followup
cp .env.example .env
# optional: set FROM_NAME, FROM_EMAIL, SMTP_*, MARKETING_URL
docker compose up --build -d
```

The app binds `0.0.0.0:8080` in the container. Compose maps host `8080:8080`. SQLite lives on the `nudge-data` volume at `/data/nudge.db`.

### 3. Smoke test

1. Healthcheck:

   ```bash
   curl -sf http://localhost:8080/health
   ```

   Expected: `{"smtp_configured":false,"status":"ok"}` (key order may vary) and HTTP 200.

2. Open http://localhost:8080, use **Import CSV**, and choose `sample-leads.csv` from this repo.

3. Open a lead, click **Generate sequence**, then copy a step or **Export as .txt**. SMTP is not required.

## Configuration

Copy `.env.example` to `.env` before `docker compose up`. Variables:

| Variable | Purpose |
| --- | --- |
| `PORT` | Documented as 8080. The container always binds gunicorn to `0.0.0.0:8080`. |
| `DATABASE_PATH` | SQLite file. Compose overrides this to `/data/nudge.db`. |
| `SECRET_KEY` | Flask session key for flash messages. Change it on a public VPS. |
| `FROM_NAME`, `FROM_EMAIL` | Used in sequence sign-off and as the SMTP From header. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_TLS` | Optional send. If `SMTP_HOST` is unset, send buttons are hidden. |
| `MARKETING_URL` | If set, footer link **Powered by Nudge** points here. If unset, there is no footer. |

Do not commit `.env`. SMTP passwords are never written to application logs.

## CSV import

Header row required. Columns recognized (case-insensitive):

- `name` (required)
- `email` (required)
- `company`
- `last_touch` or `last touch date`
- `notes`

Rows missing a name or a valid email are skipped. Unparseable dates are skipped. The import flash reports how many rows were imported vs skipped.

## Sequence templates

| Step | Send on | Subject |
| --- | --- | --- |
| 1 | Day 0 | `Quick follow-up, {first_name}` |
| 2 | Day 3 | `Checking in with {company_or_you}` |
| 3 | Day 7 | `Last note from me, {first_name}` |

Generate is idempotent-ish: if a sequence already exists, it is shown and regenerate replaces it (including clearing send timestamps).

## Healthcheck

`GET /health` → HTTP 200:

```json
{"status":"ok","smtp_configured":false}
```

`smtp_configured` is `true` only when `SMTP_HOST` is set. Health succeeds even when SMTP is unset.

## Local development (optional)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_PATH=./nudge.db
python app.py
```

Then open http://localhost:8080. This path is for hacking on the code; the supported install is Docker Compose.

## What this is not

Nudge does not scrape inboxes, host a license server, take payments, or run as multi-tenant SaaS. It is a single Compose service you run yourself.
